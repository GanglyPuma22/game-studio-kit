"""glTF TRS skin samples: LINEAR/slerp, STEP and tangent-scaled CUBICSPLINE."""
import numpy as np
from pygltflib import GLTF2

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}

def acc(g, i):
    a = g.accessors[i]
    if a.sparse:
        raise ValueError("Sparse measured accessors are unsupported")
    bv = g.bufferViews[a.bufferView]
    data = g.binary_blob()
    dt = np.dtype(CT[a.componentType]); n = NC[a.type]
    off = (bv.byteOffset or 0) + (a.byteOffset or 0)
    stride = bv.byteStride or dt.itemsize * n
    raw = np.frombuffer(data, dtype=np.uint8, count=stride * (a.count - 1) + dt.itemsize * n, offset=off)
    out = np.lib.stride_tricks.as_strided(raw, shape=(a.count, dt.itemsize * n), strides=(stride, 1)).copy()
    arr = out.view(dt).reshape(a.count, n)
    if a.normalized:
        arr = np.maximum(arr.astype(np.float64) / np.iinfo(dt).max, -1.0)
    return arr

def qmat(q):
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def slerp(a, b, t):
    if np.dot(a, b) < 0: b = -b
    d = np.clip(np.dot(a, b), -1, 1)
    if d > 0.9995: r = a + t*(b-a); return r/np.linalg.norm(r)
    th = np.arccos(d); return (np.sin((1-t)*th)*a + np.sin(t*th)*b)/np.sin(th)

class Model:
    def __init__(self, path, gltf=None):
        g = self.g = gltf if gltf is not None else GLTF2().load(path)
        # every primitive of every mesh node bound to skin 0, concatenated (hide, eyes, plates ...)
        pos, jn, wt, idx = [], [], [], []
        base = 0
        for node in g.nodes:
            if node.mesh is None or node.skin != 0:
                continue
            for p in g.meshes[node.mesh].primitives:
                v = acc(g, p.attributes.POSITION)
                pos.append(v); jn.append(acc(g, p.attributes.JOINTS_0).astype(int))
                wt.append(acc(g, p.attributes.WEIGHTS_0).astype(np.float64))
                idx.append(acc(g, p.indices).reshape(-1, 3).astype(np.int64) + base)
                base += len(v)
        self.pos, self.jn, self.wt, self.idx = np.concatenate(pos), np.concatenate(jn), np.concatenate(wt), np.concatenate(idx)
        sk = g.skins[0]
        self.joints = sk.joints
        self.ibm = acc(g, sk.inverseBindMatrices).reshape(-1, 4, 4).transpose(0, 2, 1)
        self.parent = {}
        for i, n in enumerate(g.nodes):
            for c in (n.children or []): self.parent[c] = i
        self.anims = {a.name: a for a in g.animations}
        self.sampler_data = {}
        for name, animation in self.anims.items():
            for i, sampler in enumerate(animation.samplers):
                # Morph weights are intentionally not measured.
                if not any(c.sampler == i and c.target.path != 'weights' for c in animation.channels):
                    continue
                ts = acc(g, sampler.input)[:, 0]
                values = acc(g, sampler.output)
                mode = sampler.interpolation or 'LINEAR'
                if not len(ts) or not np.isfinite(ts).all() or np.any(np.diff(ts) <= 0) or not np.isfinite(values).all():
                    raise ValueError("Animation needs finite values and strictly increasing times")
                if len(values) != len(ts) * (3 if mode == 'CUBICSPLINE' else 1):
                    raise ValueError("Animation output count does not match interpolation")
                if mode == 'CUBICSPLINE' and len(ts) < 2:
                    raise ValueError("CUBICSPLINE needs at least two keys")
                self.sampler_data[name, i] = (ts, values)

    def local(self, i, over):
        n = self.g.nodes[i]
        t = np.array(over.get((i, 'translation'), n.translation or [0, 0, 0]), float)
        r = np.array(over.get((i, 'rotation'), n.rotation or [0, 0, 0, 1]), float)
        s = np.array(over.get((i, 'scale'), n.scale or [1, 1, 1]), float)
        M = np.eye(4); M[:3, :3] = qmat(r) * s; M[:3, 3] = t
        return M

    def sample(self, clip, t):
        over = {}
        if clip is None: return over
        a = self.anims[clip]
        for ch in a.channels:
            if ch.target.path == 'weights':
                continue
            smp = a.samplers[ch.sampler]
            ts, vs = self.sampler_data[clip, ch.sampler]
            mode = smp.interpolation or 'LINEAR'
            t2 = np.clip(t, ts[0], ts[-1])
            left = max(0, int(np.searchsorted(ts, t2, side='right')) - 1)
            if mode == 'STEP' or left == len(ts)-1 or len(ts) == 1:
                v = vs[3*left+1] if mode == 'CUBICSPLINE' else vs[left]
            else:
                right = left+1; dt = ts[right]-ts[left]; u = (t2-ts[left])/dt
                if mode == 'CUBICSPLINE':
                    v = ((2*u**3-3*u**2+1)*vs[3*left+1] + dt*(u**3-2*u**2+u)*vs[3*left+2]
                         + (-2*u**3+3*u**2)*vs[3*right+1] + dt*(u**3-u**2)*vs[3*right])
                elif ch.target.path == 'rotation': v = slerp(vs[left], vs[right], u)
                else: v = vs[left] + u*(vs[right]-vs[left])
            if ch.target.path == 'rotation':
                norm = np.linalg.norm(v)
                if not np.isfinite(norm) or norm < 1e-12:
                    raise ValueError("Invalid sampled quaternion")
                v = v / norm
            over[(ch.target.node, ch.target.path)] = v
        return over

    def duration(self, clip):
        a = self.anims[clip]
        return max(acc(self.g, s.input)[-1, 0] for s in a.samplers)

    def posed(self, clip=None, t=0.0):
        over = self.sample(clip, t); cache = {}
        def glob(i):
            if i in cache: return cache[i]
            M = self.local(i, over)
            if i in self.parent: M = glob(self.parent[i]) @ M
            cache[i] = M; return M
        J = np.stack([glob(j) @ self.ibm[k] for k, j in enumerate(self.joints)])
        v4 = np.c_[self.pos, np.ones(len(self.pos))]
        out = np.zeros((len(v4), 3))
        for c in range(4):
            out += self.wt[:, c:c+1] * np.einsum('nij,nj->ni', J[self.jn[:, c]], v4)[:, :3]
        return out
