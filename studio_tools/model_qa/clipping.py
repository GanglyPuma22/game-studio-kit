"""Measured crossings with seating, occlusion, junction and ground exceptions.

The calibrated defaults are 2 mm hidden tolerance, 2.5 mm junction tolerance,
10 mm major span, and at most two minor clips per hundred connected parts.
Bodies participating in a visible crossing always make that crossing major.
"""
import numpy as np
import trimesh
from trimesh.proximity import ProximityQuery
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_ray_tri
from rtree import index as rindex


def check(tm, parts, *, tol_mm=2.0, junction_mm=2.5, major_mm=10.0, max_minor_per_100=2.0):
    """Inspect geometry in glTF metres, Y up. Does not modify the input parts."""
    n = len(parts)
    tol = tol_mm / 1000
    def boundary_share(p):
        e = np.sort(p.edges, axis=1)
        _, cnt = np.unique(e, axis=0, return_counts=True)
        return float((cnt == 1).sum()) / max(len(cnt), 1)

    body = [boundary_share(p) < 0.2 for p in parts]   # mostly closed: tubes, domes, grains
    # The ground: a wide open sheet at the bottom that spans most of the model's footprint (a terrain patch).
    # A plant sitting in the soil crosses it by design, so crossings with the ground are allowed.
    foot = (tm.bounds[1] - tm.bounds[0])[[0, 2]]
    ground = {i for i, p in enumerate(parts)
              if p.bounds[0][1] <= tm.bounds[0][1] + 0.05 and (p.bounds[1] - p.bounds[0])[1] < 0.5
              and ((p.bounds[1] - p.bounds[0])[[0, 2]] >= 0.6 * foot).all() and (foot >= 0.8).all() and len(p.faces) >= 32}
    for i in ground:
        body[i] = False
    bvh = [BVHTree.FromPolygons([Vector(v) for v in p.vertices], [tuple(f) for f in p.faces], all_triangles=True) for p in parts]
    lo = np.array([p.bounds[0] for p in parts]); hi = np.array([p.bounds[1] for p in parts])
    prop = rindex.Property(); prop.dimension = 3
    idx = rindex.Index(properties=prop)
    for i in range(n):
        idx.insert(i, (*lo[i], *hi[i]))
    pq = {}
    def q(j):
        if j not in pq: pq[j] = ProximityQuery(parts[j])
        return pq[j]

    def crossings(i, j, pairs):
        """Points where triangles of parts i and j cross (edges of one through faces of the other)."""
        pts = []
        Pi, Pj = parts[i], parts[j]
        for fa, fb in pairs:
            for (A, B, fA, fB) in ((Pi, Pj, fa, fb), (Pj, Pi, fb, fa)):
                ta = [Vector(A.vertices[k]) for k in A.faces[fA]]
                tb = [Vector(B.vertices[k]) for k in B.faces[fB]]
                for s in range(3):
                    p0, p1 = ta[s], ta[(s + 1) % 3]
                    d = p1 - p0
                    L = d.length
                    if L < 1e-9: continue
                    hit = intersect_ray_tri(tb[0], tb[1], tb[2], d / L, p0, True)
                    if hit is None:
                        hit = intersect_ray_tri(tb[0], tb[2], tb[1], d / L, p0, True)
                    if hit is not None and (hit - p0).length <= L:
                        pts.append(tuple(hit))
        return np.array(pts) if pts else np.zeros((0, 3))

    def seated(i, j):
        """Part i enters body j and stays there at one end: its outside vertices form one connected piece."""
        if not body[j]: return False
        sd = q(j).signed_distance(parts[i].vertices)   # > 0 inside
        inside = sd > -1e-4
        if not inside.any() or inside.all(): return bool(inside.all())
        out = np.nonzero(~inside)[0]
        keep = set(out.tolist())
        g = trimesh.graph.nx.Graph(); g.add_nodes_from(out.tolist())
        g.add_edges_from([tuple(e) for e in parts[i].edges if e[0] in keep and e[1] in keep])
        return trimesh.graph.nx.number_connected_components(g) == 1

    def hidden(pt, i, j):
        """Crossing point inside (or within tol of) some body other than i and j."""
        for k in idx.intersection((*(pt - tol), *(pt + tol))):
            if k in (i, j) or not body[k]: continue
            if q(k).signed_distance(pt[None])[0] > -tol: return True
        # leaf bases meeting where they join a body that is i or j itself
        return False

    def samples(p):
        """A few of the part's own vertices, so a builder can tell which of its pieces this part is."""
        v = p.vertices
        return [[round(float(x), 5) for x in v[k]] for k in sorted({0, len(v) // 3, 2 * len(v) // 3, len(v) - 1})]

    clips, checked = [], 0
    for i in range(n):
        for j in idx.intersection((*lo[i], *hi[i])):
            if j <= i: continue
            ov = bvh[i].overlap(bvh[j])
            if not ov: continue
            checked += 1
            if i in ground or j in ground:
                continue
            if seated(i, j) or seated(j, i):
                continue
            pts = crossings(i, j, ov)
            if len(pts) == 0:
                continue
            vis = [p for p in pts if not hidden(p, i, j)]
            if not vis:
                continue
            # tiny touches between two parts' tips or edges: ignore crossings within tol of each other's boundary
            jn = junction_mm / 1000
            V = np.array(vis)
            if all(np.linalg.norm(parts[i].vertices - v, axis=1).min() < jn and np.linalg.norm(parts[j].vertices - v, axis=1).min() < jn for v in V):
                continue
            c = np.mean(vis, axis=0)
            span = float(np.ptp(np.array(vis), axis=0).max()) if len(vis) > 1 else 0.0
            if span < tol and len(vis) <= 2:
                continue
            clips.append(dict(a=i, b=j, a_kind='body' if body[i] else 'sheet', b_kind='body' if body[j] else 'sheet',
                              a_tris=len(parts[i].faces), b_tris=len(parts[j].faces), at=[round(float(x), 3) for x in c],
                              span_mm=round(span * 1000, 1),
                              a_pt=samples(parts[i]), b_pt=samples(parts[j]),
                              severity='major' if (body[i] or body[j] or span * 1000 >= major_mm) else 'minor'))
    major = [c for c in clips if c['severity'] == 'major']; minor = [c for c in clips if c['severity'] == 'minor']
    res = 'PASS' if not major and len(minor) <= max_minor_per_100 * n / 100 else 'FAIL'
    return dict(parts=n, major=len(major), minor=len(minor), clipping=clips,
                checked_pairs=checked, result=res, minor_limit=max_minor_per_100 * n / 100)
