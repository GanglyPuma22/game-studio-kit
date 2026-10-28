"""Surface checks a player sees, measured with Blender's BVH (no rendering).

- M14 self-intersection: triangles of one connected part that cross each other
  (a fold, a crease pushed through itself, a welded limb through its torso).
  M13 only looks between parts, so a part that cuts itself passes there.
- M15 see-through: rays from 26 directions around the model; a first hit on
  the back of a single-sided triangle means an inverted (inside-out) face or a
  hole that shows the inside of a shell. Engines cull those faces, so the
  player sees through the model there. glTF doubleSided materials and
  manifest double_sided names are exempt.
- M16 LOD screen error: how far, in screen pixels at the switch distance, the
  visible surface of the full-detail model is from the LOD drawn there. This
  measures a crumbled finger or a collapsed panel at the size the player sees
  it, which a pixel XOR of a far, tiny silhouette cannot.
- M17 mirror symmetry (only when the manifest declares it): parts whose
  surface is farther than the tolerance from the mirror image of the model.
"""
import math

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_ray_tri


def bvh_of(mesh):
    return BVHTree.FromPolygons([Vector(v) for v in mesh.vertices], [tuple(int(i) for i in f) for f in mesh.faces],
                                all_triangles=True)


def directions():
    """26 view directions: cube faces, edges and corners."""
    out = []
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            for z in (-1, 0, 1):
                if x or y or z:
                    v = np.array([x, y, z], float)
                    out.append(v / np.linalg.norm(v))
    return np.array(out)


def _crossings(A, fa, B, fb):
    """Points where an edge of one triangle passes through the other.

    Edges that touch a vertex the two triangles share are skipped: they meet
    there by construction. So neighbours across an edge never count, and
    neighbours around one vertex count only when a far edge pierces the other
    triangle (a low-poly corner pushed through its own side).
    """
    shared = set(A.faces[fa]) & set(B.faces[fb]) if A is B else set()
    pts = []
    for (P, Q, f, g) in ((A, B, fa, fb), (B, A, fb, fa)):
        ia = P.faces[f]
        ta = [Vector(P.vertices[k]) for k in ia]
        tb = [Vector(Q.vertices[k]) for k in Q.faces[g]]
        for s in range(3):
            if ia[s] in shared or ia[(s + 1) % 3] in shared:
                continue
            p0, p1 = ta[s], ta[(s + 1) % 3]
            d = p1 - p0
            L = d.length
            if L < 1e-9:
                continue
            hit = intersect_ray_tri(tb[0], tb[1], tb[2], d / L, p0, True)
            if hit is None:
                hit = intersect_ray_tri(tb[0], tb[2], tb[1], d / L, p0, True)
            if hit is not None and (hit - p0).length <= L:
                pts.append(tuple(hit))
    return pts


def _sites(groups, join_m=0.02):
    """Join crossing segments into sites.

    Each triangle pair's crossing points are one segment, however long (a
    low-poly crossing can be a single 10 cm segment). Segments with points
    closer than join_m chain into one site.
    """
    from scipy.spatial import cKDTree
    groups = [g for g in groups if g]
    if not groups:
        return []
    pts = np.array([p for g in groups for p in g])
    owner = np.repeat(np.arange(len(groups)), [len(g) for g in groups])
    root = list(range(len(groups)))
    def find(x):
        while root[x] != x:
            root[x] = root[root[x]]; x = root[x]
        return x
    for a, b in cKDTree(pts).query_pairs(join_m):
        ra, rb = find(owner[a]), find(owner[b])
        if ra != rb:
            root[ra] = rb
    sites = {}
    for k, g in enumerate(owner):
        sites.setdefault(find(int(g)), []).append(k)
    return [pts[v] for v in sites.values()]


def self_intersections(parts, names, *, tol_mm=2.0, major_mm=10.0, max_minor_per_100=2.0, max_pairs=200000,
                       face_joint=None, near=None, whole=None):
    """M14: crossing triangles inside each connected part (edge neighbours never count).

    On a skinned part, `face_joint[i]` gives each triangle's dominant joint and
    `near(a, b)` says whether two joints are neighbours in the skeleton. Where
    triangles of neighbouring joints cross (an elbow or armpit crease squeezed
    by linear blend skinning), the crossing is reported as a joint fold, not
    counted: that is a weighting matter the motion review owns. Triangles of
    one joint crossing each other (a hood through its own head) or of unrelated
    joints (a hand through a thigh) count.

    With `whole` (the full posed model), each site records whether any of its
    crossing points is the first surface seen from one of 26 directions. Only
    visible sites count; buried ones (inside a crotch, under a coat) stay
    listed with visible false.
    """
    rows, fold_sites, truncated = [], [], []
    whole_bvh = bvh_of(whole) if whole is not None else None
    for i, part in enumerate(parts):
        if len(part.faces) < 4:
            continue
        # Two separate trees: Blender's overlap of a tree with itself drops
        # every pair that shares a vertex, and a corner pushed through its own
        # side crosses exactly such neighbours.
        pairs = np.asarray(bvh_of(part).overlap(bvh_of(part.copy())), dtype=np.int64).reshape(-1, 2)
        if not len(pairs):
            continue
        faces = part.faces
        pairs = pairs[pairs[:, 0] < pairs[:, 1]]
        shared = (faces[pairs[:, 0]][:, :, None] == faces[pairs[:, 1]][:, None, :]).sum(axis=(1, 2))
        keep = pairs[shared < 2]
        if len(keep) > max_pairs:
            # Never pass a part that was only partly examined.
            truncated.append({"part": i, "name": names[i], "pairs": int(len(keep))})
            continue
        pts, folded = [], []
        fj = face_joint[i] if face_joint is not None else None
        for a, b in keep:
            hit = _crossings(part, a, part, b)
            if fj is not None and fj[a] != fj[b] and near(fj[a], fj[b]):
                folded.append(hit)
            else:
                pts.append(hit)
        for site in (_sites(folded) if folded else []):
            span = float(np.ptp(site, axis=0).max()) if len(site) > 1 else 0.0
            if span * 1000 >= major_mm:
                fold_sites.append({"part": i, "name": names[i], "at": [round(float(x), 3) for x in site.mean(axis=0)],
                                   "span_mm": round(span * 1000, 1)})
        if not any(pts):
            continue
        for site in _sites(pts):
            span = float(np.ptp(site, axis=0).max()) if len(site) > 1 else 0.0
            if span * 1000 < tol_mm and len(site) <= 2:
                continue
            seen = bool(visible_points(whole, whole_bvh, site).any()) if whole is not None else True
            rows.append({"part": i, "name": names[i], "at": [round(float(x), 3) for x in site.mean(axis=0)],
                         "span_mm": round(span * 1000, 1), "points": len(site), "visible": seen,
                         "severity": "major" if span * 1000 >= major_mm else "minor"})
    major = [r for r in rows if r["severity"] == "major" and r["visible"]]
    minor = [r for r in rows if r["severity"] == "minor" and r["visible"]]
    limit = max_minor_per_100 * len(parts) / 100
    return {"sites": rows, "major": len(major), "minor": len(minor), "minor_limit": limit,
            "hidden": sum(not r["visible"] for r in rows),
            "joint_folds": len(fold_sites), "joint_fold_sites": sorted(fold_sites, key=lambda r: -r["span_mm"])[:10],
            "truncated": truncated,
            "result": "FAIL" if major or len(minor) > limit else ("UNMEASURED" if truncated else "PASS")}


def _ray_grid(center, radius, d, res):
    """Orthographic rays covering the bounding sphere, looking along d."""
    up = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(d, up); u /= np.linalg.norm(u)
    v = np.cross(u, d)
    s = (np.arange(res) + 0.5) / res * 2 - 1
    gu, gv = np.meshgrid(s, s)
    keep = gu ** 2 + gv ** 2 <= 1
    origins = center - d * radius * 1.5 + radius * (gu[keep, None] * u + gv[keep, None] * v)
    return origins, radius * 2 / res


def _covered(bvh, loc, dv, gap):
    """A front face within `gap` behind a back-face hit. Engines cull the back
    face and draw that one, so coincident or near-coincident pairs (a blade
    built as two opposed sheets, a vertex-compressed copy of one) show no hole."""
    for _, normal, _, _ in bvh.find_nearest_range(loc, gap * 0.05):
        if normal.dot(dv) < 0:
            return True
    step = 1e-6
    o = loc + dv * step
    left = gap
    while left > 0:
        hit, normal, _, dist = bvh.ray_cast(o, dv, left)
        if hit is None:
            return False
        if normal.dot(dv) < 0:
            return True
        o = hit + dv * step
        left -= dist + step
    return False


def see_through(tm, face_part, names, double_faces, *, res=160, min_rays=12, min_share=0.002, gap_mm=2.0):
    """M15: first hits on the back of single-sided faces, per part."""
    bvh = bvh_of(tm)
    center = (tm.bounds[0] + tm.bounds[1]) / 2
    radius = float(np.linalg.norm(tm.bounds[1] - tm.bounds[0])) / 2 or 1.0
    n_parts = int(face_part.max()) + 1
    front = np.zeros(n_parts, int); back = np.zeros(n_parts, int)
    worst = [None] * n_parts
    pixel = 0.0
    gap = max(radius * 1e-3, gap_mm / 1000)
    for d in directions():
        origins, pixel = _ray_grid(center, radius, d, res)
        dv = Vector(d)
        for o in origins:
            loc, normal, face, _ = bvh.ray_cast(Vector(o), dv)
            if face is None:
                continue
            p = face_part[face]
            if normal.dot(dv) > 0 and not double_faces[face] and not _covered(bvh, loc, dv, gap):
                back[p] += 1
                if worst[p] is None:
                    worst[p] = {"at": [round(x, 3) for x in loc], "seen_along": [round(float(x), 3) for x in d]}
            else:
                front[p] += 1
    tri = tm.triangles
    signed = np.einsum('ij,ij->i', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6
    volume = np.bincount(face_part, weights=signed, minlength=n_parts)
    rows = []
    for p in range(n_parts):
        hits = front[p] + back[p]
        if back[p] >= min_rays and back[p] >= min_share * max(hits, 1):
            # A closed part with negative volume is inside out; otherwise the
            # back faces show through an opening or a few faces are flipped.
            kind = "inside-out" if volume[p] < 0 else "open or flipped faces"
            rows.append({"part": p, "name": names[p], "back_hits": int(back[p]), "front_hits": int(front[p]),
                         "back_share": round(back[p] / max(hits, 1), 4), "kind": kind, **(worst[p] or {})})
    rows.sort(key=lambda r: -r["back_hits"])
    return {"parts": rows, "flagged": len(rows), "rays_per_view": res, "ray_spacing_mm": round(pixel * 1000, 1),
            "back_hits": int(back.sum()), "hits": int(front.sum() + back.sum()),
            "result": "PASS" if not rows else "FAIL"}


def visible_points(tm, bvh, points, *, eps=None):
    """Which points are the first surface hit along at least one of the 26 directions."""
    radius = float(np.linalg.norm(tm.bounds[1] - tm.bounds[0])) / 2 or 1.0
    eps = eps if eps is not None else max(radius * 2e-3, 1e-4)
    seen = np.zeros(len(points), bool)
    for d in directions():
        dv = Vector(d)
        for k in np.flatnonzero(~seen):
            p = points[k]
            loc, _, _, dist = bvh.ray_cast(Vector(p - d * radius * 3), dv)
            if loc is not None and dist >= radius * 3 - eps:
                seen[k] = True
    return seen


def sample_surface(tm, count, seed=7):
    rng = np.random.default_rng(seed)
    areas = tm.area_faces
    if areas.sum() <= 0:
        return np.zeros((0, 3))
    face = rng.choice(len(areas), size=count, p=areas / areas.sum())
    r = rng.random((count, 2))
    flip = r.sum(axis=1) > 1
    r[flip] = 1 - r[flip]
    tri = tm.triangles[face]
    return tri[:, 0] + r[:, :1] * (tri[:, 1] - tri[:, 0]) + r[:, 1:] * (tri[:, 2] - tri[:, 0])


def pixel_size(distance, fov_deg, height_px):
    """Metres per screen pixel at `distance` for a vertical FOV and image height."""
    return 2 * distance * math.tan(math.radians(fov_deg) / 2) / height_px


def lod_screen_error(full, lod, distance, fov_deg, height_px, *, samples=12000, p99_px=1.0, vertex_px=3.0):
    """M16: visible full-detail surface distance to the LOD surface, in pixels at the switch distance.

    Both directions are measured: full -> LOD finds lost or collapsed detail
    (a crumbled finger), LOD -> full finds spikes and flipped shards the LOD
    adds. Area samples give the typical error (p99); every vertex is measured
    too, because a spike or a collapsed tip lives at a vertex and covers almost
    no area. Points hidden inside the model are left out, so simplifying
    buried surfaces costs nothing. The game's own LOD picker aims for about
    1 px, so the vertex limit leaves room above that.
    """
    px = pixel_size(distance, fov_deg, height_px)
    out = {"switch_distance_m": distance, "metres_per_pixel": round(px, 5)}
    bf, bl = bvh_of(full), bvh_of(lod)
    worst = {}
    for label, src, src_bvh, dst_bvh in (("lost", full, bf, bl), ("added", lod, bl, bf)):
        area = sample_surface(src, samples)
        area = area[visible_points(src, src_bvh, area)]
        verts = np.asarray(src.vertices, float)
        verts = verts[visible_points(src, src_bvh, verts)]
        if not len(area) and not len(verts):
            out[label] = {"visible_samples": 0, "visible_vertices": 0}
            continue
        ea = np.array([dst_bvh.find_nearest(Vector(p))[3] for p in area]) / px if len(area) else np.zeros(1)
        ev = np.array([dst_bvh.find_nearest(Vector(p))[3] for p in verts]) / px if len(verts) else np.zeros(1)
        k = int(np.argmax(ev))
        out[label] = {"visible_samples": int(len(area)), "visible_vertices": int(len(verts)),
                      "p99_px": round(float(np.percentile(ea, 99)), 3), "max_px": round(float(max(ea.max(), ev.max())), 3),
                      "vertices_over_limit": int((ev > vertex_px).sum()),
                      "worst_at": [round(float(x), 3) for x in verts[k]] if len(verts) else None}
        worst[label] = out[label]
    p99 = max((w["p99_px"] for w in worst.values()), default=0.0)
    mx = max((w["max_px"] for w in worst.values()), default=0.0)
    over = sum(w["vertices_over_limit"] for w in worst.values())
    out.update(p99_px=p99, max_px=mx, vertices_over_limit=over, limit_p99_px=p99_px, limit_vertex_px=vertex_px,
               result="PASS" if p99 <= p99_px and not over else "FAIL")
    return out


def symmetry(tm, face_part, names, *, axis="x", allow=(), tolerance_mm=10.0, samples=12000):
    """M17: distance from each part's visible surface to the model mirrored across its centre plane."""
    k = {"x": 0, "z": 2}[axis]
    mirror = tm.copy()
    c = (tm.bounds[0][k] + tm.bounds[1][k]) / 2
    mirror.vertices[:, k] = 2 * c - mirror.vertices[:, k]
    mirror.faces = mirror.faces[:, ::-1]
    bm, bt = bvh_of(mirror), bvh_of(tm)
    pts = sample_surface(tm, samples)
    vis = visible_points(tm, bt, pts)
    pts = pts[vis]
    d = np.array([bm.find_nearest(Vector(p))[3] for p in pts]) * 1000
    part = np.array([face_part[bt.find_nearest(Vector(p))[2]] for p in pts], int)
    rows = []
    for p in np.unique(part):
        e = d[part == p]
        p95 = float(np.percentile(e, 95))
        if p95 > tolerance_mm:
            declared = any(a and a in names[p] for a in allow)
            rows.append({"part": int(p), "name": names[p], "p95_mm": round(p95, 1), "max_mm": round(float(e.max()), 1),
                         "samples": int(len(e)), "status": "allowed (declared)" if declared else "ASYMMETRIC"})
    rows.sort(key=lambda r: -r["p95_mm"])
    bad = [r for r in rows if r["status"] == "ASYMMETRIC"]
    return {"axis": axis, "plane": round(float(c), 4), "tolerance_mm": tolerance_mm, "parts": rows,
            "asymmetric": len(bad), "result": "PASS" if not bad else "FAIL"}
