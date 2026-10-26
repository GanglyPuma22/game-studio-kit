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


def measure(parts, skin=None, *, structure="assembly", ground_y_m=0.0, samples=6):
    if structure == "assembly":
        return skinned(skin, samples=samples) if skin else static(parts)
    if not skin:
        return ground(parts, ground_y_m)
    labels = part_labels(skin)
    results = []
    for clip, t in [('rest', 0.0)] + [(c, float(t)) for c in skin.anims for t in np.linspace(0, skin.duration(c), samples)]:
        positions = skin.posed(None if clip == 'rest' else clip, t)
        # Bounds need faces too; retain the complete index space and trim unused vertices.
        pieces = [trimesh.Trimesh(positions, skin.idx[labels == i], process=False) for i in range(int(labels.max()) + 1)]
        for piece in pieces:
            piece.remove_unreferenced_vertices()
        results.append({"pose": clip, "time": t, **ground(pieces, ground_y_m)})
    worst = max(results, key=lambda r: r['floating'])
    return {**worst, "poses": len(results), "pose_results": results}


def static(parts, max_gap_mm=3.0):
    """The lowest Y part anchors static models; chains of touching parts count."""
    n = len(parts)
    anchor = int(np.argmin([p.bounds[0][1] for p in parts]))
    lo = np.array([p.bounds[0] for p in parts]); hi = np.array([p.bounds[1] for p in parts])
    lim = max_gap_mm / 1000
    from rtree import index as _rix
    _p = _rix.Property(); _p.dimension = 3
    idx = _rix.Index(properties=_p)
    for i in range(n): idx.insert(i, (lo[i][0] - lim, lo[i][1] - lim, lo[i][2] - lim, hi[i][0] + lim, hi[i][1] + lim, hi[i][2] + lim))
    G = {}
    _pq = {}
    def _q(j):
        if j not in _pq: _pq[j] = ProximityQuery(parts[j])
        return _pq[j]
    for i in range(n):
        for j in idx.intersection((lo[i][0] - lim, lo[i][1] - lim, lo[i][2] - lim, hi[i][0] + lim, hi[i][1] + lim, hi[i][2] + lim)):
            if i == j: continue
            d = _q(j).signed_distance(parts[i].vertices)
            G[(i, j)] = -float(d.max())   # min gap of part i's vertices to part j (negative = inside/seated)
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
        rows.append(dict(part=l, tris=len(parts[l].faces), gap_mm=round(g * 1000, 1) if np.isfinite(g) else 999.0, status='ok' if l in seen else 'FLOATING'))
    bad = [r for r in rows if r['status'] != 'ok']
    return dict(parts=rows, part_count=n, anchor=anchor, floating=len(bad),
                max_gap_mm=max_gap_mm, poses=1, result='PASS' if not bad else 'FAIL')


def part_labels(m):
    tm = trimesh.Trimesh(m.pos, m.idx, process=False)
    tm.merge_vertices(merge_tex=True, merge_norm=True)          # UV/normal seams are not separate parts
    return trimesh.graph.connected_component_labels(tm.face_adjacency, node_count=len(tm.faces))



def skinned(m, samples=6, max_gap_mm=3.0, free_names=()):
    lab = part_labels(m)
    n = int(lab.max()) + 1
    names = [m.g.nodes[j].name for j in m.joints]
    pverts = [np.unique(m.idx[lab == l]) for l in range(n)]
    pname = [names[np.bincount(m.jn[v, 0]).argmax()] for v in pverts]
    free = {s.strip() for s in free_names if s.strip()}
    poses = [('rest', 0.0)] + [(c, float(t)) for c in m.anims for t in np.linspace(0, m.duration(c), samples)]
    anchor = int(np.bincount(lab).argmax())            # the biggest part (hide/trunk) is the anchor
    lim = max_gap_mm / 1000.0
    worst = np.full(n, -1e9); where = [''] * n; best = np.full(n, 1e9)
    for clip, t in poses:
        P = m.posed(None if clip == 'rest' else clip, t)
        meshes = [trimesh.Trimesh(P, m.idx[lab == l], process=False) for l in range(n)]
        lo = np.array([P[v].min(0) for v in pverts]); hi = np.array([P[v].max(0) for v in pverts])
        G = np.full((n, n), np.inf)                    # G[i, j]: gap of part i to part j (signed, + = apart)
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                sep = np.maximum(0, np.maximum(lo[i] - hi[j], lo[j] - hi[i])).max()
                if sep > 0.25:                         # far apart: only an upper bound matters
                    G[i, j] = sep; continue
                G[i, j] = -float(ProximityQuery(meshes[j]).signed_distance(P[pverts[i]]).max())
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
        status = 'ok' if worst[l] <= max_gap_mm else ('free (declared)' if pname[l] in free else 'FLOATING')
        rows.append(dict(part=pname[l], part_id=l, tris=int((lab == l).sum()), gap_mm_worst=round(worst[l], 1),
                         gap_mm_best=round(best[l], 1), worst_pose=where[l], status=status))
    rows.sort(key=lambda r: -r['gap_mm_worst'])
    bad = [r for r in rows if r['status'] == 'FLOATING']
    return dict(parts=rows, part_count=n, anchor=anchor, floating=len(bad),
                max_gap_mm=max_gap_mm, poses=len(poses), result='PASS' if not bad else 'FAIL')
