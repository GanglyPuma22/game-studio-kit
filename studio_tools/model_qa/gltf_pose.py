"""Linear/slerp glTF skin sampling for the attachment check."""
import numpy as np
from pygltflib import GLTF2

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}

def acc(g, i):
    a = g.accessors[i]; bv = g.bufferViews[a.bufferView]
    data = g.binary_blob()
    dt = np.dtype(CT[a.componentType]); n = NC[a.type]
    off = (bv.byteOffset or 0) + (a.byteOffset or 0)
    stride = bv.byteStride or dt.itemsize * n
    raw = np.frombuffer(data, dtype=np.uint8, count=stride * (a.count - 1) + dt.itemsize * n, offset=off)
    out = np.lib.stride_tricks.as_strided(raw, shape=(a.count, dt.itemsize * n), strides=(stride, 1)).copy()
    arr = out.view(dt).reshape(a.count, n)
    if a.normalized:
        arr = arr.astype(np.float32) / np.iinfo(dt).max
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
    def __init__(self, path):
        g = self.g = GLTF2().load(path)
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
            smp = a.samplers[ch.sampler]
            ts = acc(self.g, smp.input)[:, 0]; vs = acc(self.g, smp.output)
            t2 = np.clip(t, ts[0], ts[-1]); k = np.searchsorted(ts, t2)
            k = min(max(k, 1), len(ts)-1); u = (t2-ts[k-1])/max(ts[k]-ts[k-1], 1e-9)
            u = np.clip(u, 0, 1)
            if ch.target.path == 'rotation': v = slerp(vs[k-1], vs[k], u)
            else: v = vs[k-1] + u*(vs[k]-vs[k-1])
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
