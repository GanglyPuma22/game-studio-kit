"""glTF TRS skin samples: LINEAR/slerp, STEP and tangent-scaled CUBICSPLINE."""
import re

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
    """Every mesh node of the active scene, posed per clip sample.

    Skinned primitives follow their skin (linear blend, the mesh node's own
    transform ignored, as glTF specifies). Unskinned primitives follow their
    node's world transform, so held props parented to a joint and rigid
    node-animated pieces move with the clip too. Positions concatenate in node
    index order; ``owner`` names each vertex's dominant joint (skinned) or its
    node (rigid), which is what reports call the part.
    """
    def __init__(self, path, gltf=None, exclude_meshes=(), exclude_clips=None):
        g = self.g = gltf if gltf is not None else GLTF2().load(path)
        self.parent = {}
        for i, n in enumerate(g.nodes):
            for c in (n.children or []): self.parent[c] = i
        scene = g.scenes[g.scene or 0] if g.scenes else None
        live = set()
        todo = list(scene.nodes) if scene else list(range(len(g.nodes)))
        while todo:
            k = todo.pop()
            if k not in live:
                live.add(k); todo.extend(g.nodes[k].children or [])
        drop = {str(x) for x in exclude_meshes}
        pos, jn, wt, idx, owner, label, groups, dbl, flips = [], [], [], [], [], [], [], [], []
        self.owner_names = []
        base = 0
        def owner_id(name):
            if name not in self.owner_names: self.owner_names.append(name)
            return self.owner_names.index(name)
        for ni, node in enumerate(g.nodes):
            if node.mesh is None or ni not in live:
                continue
            if node.name in drop or (g.meshes[node.mesh].name in drop):
                continue
            for p in g.meshes[node.mesh].primitives:
                v = acc(g, p.attributes.POSITION).astype(np.float64)
                f = (acc(g, p.indices).reshape(-1, 3).astype(np.int64) if p.indices is not None
                     else np.arange(len(v)).reshape(-1, 3))
                if node.skin is not None:
                    j = acc(g, p.attributes.JOINTS_0).astype(int)
                    w = acc(g, p.attributes.WEIGHTS_0).astype(np.float64)
                    joints = g.skins[node.skin].joints
                    # The joint with the largest weight owns the vertex, whatever its slot.
                    top = j[np.arange(len(j)), w.argmax(axis=1)]
                    owner.append(np.array([owner_id(g.nodes[joints[x]].name or 'joint') for x in top], int))
                    groups.append(("skin", node.skin, base, len(v)))
                else:
                    j = np.zeros((len(v), 4), int); w = np.zeros((len(v), 4)); w[:, 0] = 1
                    owner.append(np.full(len(v), owner_id(node.name or f'node-{ni}'), int))
                    groups.append(("node", ni, base, len(v)))
                    flips.append((sum(len(x) for x in idx), len(f), ni))
                pos.append(v); jn.append(j); wt.append(w); idx.append(f + base)
                mat = g.materials[p.material] if p.material is not None and g.materials else None
                dbl.append(np.full(len(f), bool(mat and mat.doubleSided)))
                base += len(v)
        if not pos:
            raise ValueError("No mesh instances in the active scene")
        self.pos, self.jn, self.wt, self.idx = np.concatenate(pos), np.concatenate(jn), np.concatenate(wt), np.concatenate(idx)
        self.owner = np.concatenate(owner)
        self.face_double = np.concatenate(dbl)
        self.groups = groups
        self.skinned = any(kind == "skin" for kind, *_ in groups)
        self.rigid = any(kind == "node" for kind, *_ in groups)
        # Single-skin compatibility for callers that read the joint list.
        sk = g.skins[0] if g.skins else None
        self.joints = sk.joints if sk else []
        self.ibms = [acc(g, s.inverseBindMatrices).reshape(-1, 4, 4).transpose(0, 2, 1) for s in g.skins]
        self.ibm = self.ibms[0] if self.ibms else None
        pattern = re.compile(exclude_clips) if exclude_clips else None
        self.anims = {a.name: a for a in g.animations if not (pattern and pattern.search(a.name or ''))}
        self.excluded_clips = sorted(a.name for a in g.animations if pattern and pattern.search(a.name or ''))
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
        # A mirroring node transform turns its triangles inside out unless the
        # winding flips with it (glTF requires renderers to flip it).
        if flips:
            world = self.world()
            for start, count, ni in flips:
                if np.linalg.det(world[ni][:3, :3]) < 0:
                    self.idx[start:start + count] = self.idx[start:start + count, ::-1]
        # Merge positions in each primitive's own frame (bind space for each
        # skin, rest world for rigid nodes), so a welded seam is one part.
        # Frames are kept apart: a vertex never welds to one from another
        # frame or motion group, even where their coordinates coincide.
        rest = self.posed()
        self.label_pos = self.pos.copy()
        # Rigid nodes weld only within one motion group: nodes that share their
        # nearest animated (or joint) ancestor-or-self move together.
        moving = {c.target.node for a in g.animations for c in a.channels if c.target.node is not None}
        moving |= {j for sk in g.skins for j in sk.joints}
        def motion(k):
            while k is not None and k not in moving:
                k = self.parent.get(k)
            return k
        frames = []
        for kind, ni, b, n in groups:
            if kind == "node":
                self.label_pos[b:b + n] = rest[b:b + n]
            frames.append((kind, ni if kind == "skin" else motion(ni)))
        keys = list(dict.fromkeys(frames))
        if len(keys) > 1:
            lo, hi = self.label_pos.min(axis=0), self.label_pos.max(axis=0)
            step = float((hi - lo).max()) * 4 + 1.0
            for (kind, ni, b, n), key in zip(groups, frames):
                self.label_pos[b:b + n, 0] += keys.index(key) * step

    def owner_neighbours(self, hops=2):
        """near(a, b): owners a and b (joint or node names) are within `hops` parent links of each other."""
        index = {n.name: i for i, n in enumerate(self.g.nodes) if n.name}
        def chain(name):
            out, k = [], index.get(name)
            while k is not None and len(out) <= hops:
                out.append(k); k = self.parent.get(k)
            return out
        chains = [chain(n) for n in self.owner_names]
        def near(a, b):
            ca, cb = chains[a], chains[b]
            for da, x in enumerate(ca):
                if x in cb and da + cb.index(x) <= hops:
                    return True
            return False
        return near

    def face_owner(self):
        """Each triangle's owner: the dominant joint shared by most of its corners."""
        o = self.owner[self.idx]
        return np.where(o[:, 1] == o[:, 2], o[:, 1], o[:, 0])

    def poses(self, samples, include_rest=True):
        out = [("rest", 0.0)] if include_rest or not self.anims else []
        return out + [(c, float(t)) for c in self.anims for t in np.linspace(0, self.duration(c), samples)]

    def local(self, i, over):
        n = self.g.nodes[i]
        if n.matrix and not any(k[0] == i for k in over):
            return np.array(n.matrix, dtype=float).reshape(4, 4).T
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

    def world(self, clip=None, t=0.0):
        """Every node's world matrix for one pose."""
        over = self.sample(clip, t); cache = {}
        def glob(i):
            if i in cache: return cache[i]
            M = self.local(i, over)
            if i in self.parent: M = glob(self.parent[i]) @ M
            cache[i] = M; return M
        return {i: glob(i) for i in range(len(self.g.nodes))}

    def posed(self, clip=None, t=0.0):
        over = self.sample(clip, t); cache = {}
        def glob(i):
            if i in cache: return cache[i]
            M = self.local(i, over)
            if i in self.parent: M = glob(self.parent[i]) @ M
            cache[i] = M; return M
        out = np.zeros((len(self.pos), 3))
        skins = {}
        for kind, ni, b, n in self.groups:
            v4 = np.c_[self.pos[b:b + n], np.ones(n)]
            if kind == "node":
                out[b:b + n] = (v4 @ glob(ni).T)[:, :3]
                continue
            if ni not in skins:
                sk = self.g.skins[ni]
                skins[ni] = np.stack([glob(j) @ self.ibms[ni][k] for k, j in enumerate(sk.joints)])
            J = skins[ni]
            jn, wt = self.jn[b:b + n], self.wt[b:b + n]
            for c in range(4):
                out[b:b + n] += wt[:, c:c+1] * np.einsum('nij,nj->ni', J[jn[:, c]], v4)[:, :3]
        return out
