"""Attachment to the connected set, preserving the calibrated 3 mm rule."""
import numpy as np
import trimesh
from trimesh.proximity import ProximityQuery


def ground(parts, ground_y_m=0.0, max_gap_mm=3.0):
    """Each connected piece must intersect or approach the declared Y-up plane."""
    rows = []
    for i, part in enumerate(parts):
        low, high = part.bounds[:, 1]
        gap = float(max(low - ground_y_m, ground_y_m - high, 0))
        rows.append(dict(part=i, tris=len(part.faces), gap_mm=gap * 1000,
                         status="ok" if gap <= max_gap_mm / 1000 else "FLOATING"))
    bad = sum(r['status'] != 'ok' for r in rows)
    return dict(parts=rows, part_count=len(parts), floating=bad, poses=1,
                ground_y_m=ground_y_m, max_gap_mm=max_gap_mm, result='FAIL' if bad else 'PASS')


def measure(parts, skin=None, *, structure="assembly", ground_y_m=0.0, samples=6, free_names=(), include_rest=True, names=None):
    if structure == "assembly":
        return skinned(skin, samples=samples, free_names=free_names, include_rest=include_rest) if skin else static(parts, free_names=free_names, names=names)
    if not skin:
        return ground(parts, ground_y_m)
    labels = part_labels(skin)
    results = []
    for clip, t in skin.poses(samples, include_rest):
        positions = skin.posed(None if clip == 'rest' else clip, t)
        # Bounds need faces too; retain the complete index space and trim unused vertices.
        pieces = [trimesh.Trimesh(positions, skin.idx[labels == i], process=False) for i in range(int(labels.max()) + 1)]
        for piece in pieces:
            piece.remove_unreferenced_vertices()
        results.append({"pose": clip, "time": t, **ground(pieces, ground_y_m)})
    worst = max(results, key=lambda r: r['floating'])
    return {**worst, "poses": len(results), "pose_results": results}


def is_free(name, free_names):
    """A declared free part: its name (or any '+'-joined node name) contains a declared entry."""
    return any(f and f in name for f in free_names)


def static(parts, max_gap_mm=3.0, free_names=(), names=None):
    """The lowest Y part anchors static models; chains of touching parts count."""
    n = len(parts)
    anchor = int(np.argmin([p.bounds[0][1] for p in parts]))
    lo = np.array([p.bounds[0] for p in parts]); hi = np.array([p.bounds[1] for p in parts])
    lim = max_gap_mm / 1000
    from rtree import index as _rix
    _p = _rix.Property(); _p.dimension = 3
    idx = _rix.Index(properties=_p)
    for i in range(n): idx.insert(i, (lo[i][0] - lim, lo[i][1] - lim, lo[i][2] - lim, hi[i][0] + lim, hi[i][1] + lim, hi[i][2] + lim))
    # Gaps come from Blender's BVH (overlap, nearest point, parity), like the
    # posed check. trimesh's signed distance guesses inside/outside for open
    # parts, and a wrong sign reads a loose part as seated.
    trees = {}
    def tree(k):
        if k not in trees:
            trees[k] = bvh_of(parts[k])
        return trees[k]
    closed = [_closed(p.faces) for p in parts]
    G = {}
    for i in range(n):
        for j in idx.intersection((lo[i][0] - lim, lo[i][1] - lim, lo[i][2] - lim, hi[i][0] + lim, hi[i][1] + lim, hi[i][2] + lim)):
            if i < j:
                G[(i, j)] = pair_gap(parts[i].vertices, parts[j].vertices, tree(i), tree(j), closed[i], closed[j])
    def gap(i, j): return min(G.get((i, j), np.inf), G.get((j, i), np.inf))
    nb = {i: [] for i in range(n)}
    best = {i: np.inf for i in range(n)}
    for (i, j) in G:
        g_ = gap(i, j)
        best[i] = min(best[i], g_); best[j] = min(best[j], g_)
        if g_ <= lim: nb[i].append(j); nb[j].append(i)
    seen = {anchor}; todo = [anchor]
    while todo:
        k = todo.pop()
        for j in nb[k]:
            if j not in seen: seen.add(j); todo.append(j)
    rows = []
    for l in range(n):
        if l == anchor: continue
        g = best[l]
        status = 'ok' if l in seen else ('free (declared)' if names and is_free(names[l], free_names) else 'FLOATING')
        rows.append(dict(part=l, tris=len(parts[l].faces), gap_mm=round(g * 1000, 1) if np.isfinite(g) else 999.0, status=status))
    bad = [r for r in rows if r['status'] == 'FLOATING']
    return dict(parts=rows, part_count=n, anchor=anchor, floating=len(bad),
                max_gap_mm=max_gap_mm, poses=1, result='PASS' if not bad else 'FAIL')


def _closed(faces):
    """Fewer than a fifth of the edges are open: treat the part as a shell with an inside."""
    f = np.asarray(faces)
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    return float((cnt == 1).sum()) / max(len(cnt), 1) < 0.2


def bvh_of(mesh):
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    return BVHTree.FromPolygons([Vector(v) for v in mesh.vertices], [tuple(int(i) for i in f) for f in mesh.faces],
                                all_triangles=True)


def inside(tree, point, closed):
    """Ray parity in a closed part; open sheets have no inside."""
    if not closed:
        return False
    from mathutils import Vector
    d = Vector((0.5773, 0.5774, 0.5772))
    o = Vector(point); hits = 0
    for _ in range(256):
        loc, _, _, _ = tree.ray_cast(o, d)
        if loc is None:
            break
        hits += 1
        o = loc + d * 1e-6
    return hits % 2 == 1


def pair_gap(Vi, Vj, ti, tj, closed_i, closed_j):
    """min(G[i, j], G[j, i]) of the vertex rule, with Blender's BVH.

    Crossing surfaces touch (gap 0). Otherwise each part's vertices are all
    outside or all inside the other, so one parity ray settles the sign and the
    nearest-vertex distance gives the size: the same value as the signed
    distance of every vertex, at C speed.
    """
    from mathutils import Vector
    if ti.overlap(tj):
        return 0.0
    gaps = []
    for V, t, closed in ((Vi, tj, closed_j), (Vj, ti, closed_i)):
        # A part with only zero-area triangles has an empty tree: nothing to measure against.
        found = [h[3] for h in (t.find_nearest(Vector(v)) for v in V) if h[3] is not None]
        if not found:
            continue
        dist = min(found)
        gaps.append(-dist if inside(t, V[0], closed) else dist)
    return float(min(gaps)) if gaps else float("inf")


def part_owners(m, labels):
    """Each part's name: the owner (joint or node) of most of its first-joint weights."""
    out = []
    for i in range(int(labels.max()) + 1):
        verts = np.unique(m.idx[labels == i])
        out.append(m.owner_names[int(np.bincount(m.owner[verts]).argmax())])
    return out


def welded(m):
    """The model's triangles with UV/normal seam duplicates merged (same face order as m.idx)."""
    tm = trimesh.Trimesh(getattr(m, 'label_pos', m.pos), m.idx, process=False)
    tm.merge_vertices(merge_tex=True, merge_norm=True)          # UV/normal seams are not separate parts
    return tm


def part_labels(m):
    tm = welded(m)
    return trimesh.graph.connected_component_labels(tm.face_adjacency, node_count=len(tm.faces))



def skinned(m, samples=6, max_gap_mm=3.0, free_names=(), include_rest=True):
    lab = part_labels(m)
    n = int(lab.max()) + 1
    pverts = [np.unique(m.idx[lab == l]) for l in range(n)]
    pname = part_owners(m, lab)
    free = {s.strip() for s in free_names if s.strip()}
    poses = m.poses(samples, include_rest)
    anchor = int(np.bincount(lab).argmax())            # the biggest part (hide/trunk) is the anchor
    lim = max_gap_mm / 1000.0
    worst = np.full(n, -1e9); where = [''] * n; best = np.full(n, 1e9)
    # Closure on the seam-welded topology: a closed box exported with split
    # UV/normal seams is still closed.
    wf = welded(m).faces
    closed = [_closed(wf[lab == v]) for v in range(n)]
    for clip, t in poses:
        P = m.posed(None if clip == 'rest' else clip, t)
        meshes = [trimesh.Trimesh(P, m.idx[lab == l], process=False) for l in range(n)]
        lo = np.array([P[v].min(0) for v in pverts]); hi = np.array([P[v].max(0) for v in pverts])
        G = np.full((n, n), np.inf)                    # G[i, j]: gap between parts i and j (+ = apart, - = sunk in)
        trees = {}
        def tree(k):
            if k not in trees:
                trees[k] = bvh_of(meshes[k])
            return trees[k]
        for i in range(n):
            for j in range(i + 1, n):
                sep = np.maximum(0, np.maximum(lo[i] - hi[j], lo[j] - hi[i])).max()
                if sep > 0.25:                         # far apart: only an upper bound matters
                    G[i, j] = G[j, i] = sep; continue
                G[i, j] = G[j, i] = pair_gap(P[pverts[i]], P[pverts[j]], tree(i), tree(j), closed[i], closed[j])
        A = np.minimum(G, G.T) <= lim                  # attached if within the limit either way
        comp = -np.ones(n, int); sizes = []
        for s0 in range(n):                            # connected groups of touching parts
            if comp[s0] >= 0:
                continue
            c = len(sizes); comp[s0] = c; todo = [s0]; tri = 0
            while todo:
                k = todo.pop(); tri += int((lab == k).sum())
                for j in np.nonzero(A[k])[0]:
                    if comp[j] < 0:
                        comp[j] = c; todo.append(int(j))
            sizes.append(tri)
        main = int(comp[anchor])                       # the body = the touching group holding the anchor (biggest part)
        Gs = np.minimum(G, G.T)
        for l in range(n):
            if l == anchor:
                continue
            # attached parts report their gap to the nearest neighbour; loose ones their gap to the body group
            if comp[l] == main:
                g_mm = float(min(Gs[l, j] for j in range(n) if j != l)) * 1000.0
            else:
                g_mm = float(min(Gs[l, j] for j in range(n) if comp[j] == main)) * 1000.0
            if g_mm > worst[l]:
                worst[l] = g_mm; where[l] = f'{clip} t={t:.2f}'
            best[l] = min(best[l], g_mm)
    rows = []
    for l in range(n):
        if l == anchor:
            continue
        status = 'ok' if worst[l] <= max_gap_mm else ('free (declared)' if is_free(pname[l], free) else 'FLOATING')
        rows.append(dict(part=pname[l], part_id=l, tris=int((lab == l).sum()), gap_mm_worst=round(worst[l], 1),
                         gap_mm_best=round(best[l], 1), worst_pose=where[l], status=status))
    rows.sort(key=lambda r: -r['gap_mm_worst'])
    bad = [r for r in rows if r['status'] == 'FLOATING']
    return dict(parts=rows, part_count=n, anchor=anchor, floating=len(bad),
                max_gap_mm=max_gap_mm, poses=len(poses), result='PASS' if not bad else 'FAIL')
