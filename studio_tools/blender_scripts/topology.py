"""Geometric mesh topology: count defects, never repair them.

The counts here answer one question a provider mesh cannot answer about itself:
is this surface closed, manifold and consistently wound, or does it only look
that way from outside? A remesh that drops 97% of the triangles can return a
silhouette that reads correctly in a viewport while leaving holes and edges
shared by three faces underneath, which is where rigging, collision generation
and baking start failing without saying why.

Duplicated texture-seam vertices are a normal, correct part of an exported mesh
and would otherwise be reported as thousands of boundary edges, so the audit
welds vertices *by position* before counting. That welding is arithmetic on a
copy of the index list: nothing here modifies a mesh, fills a hole or moves a
vertex. An intentional walk-through opening stays an opening, and it is counted
honestly as boundary edges, because only the person who modelled it knows
whether it is a defect.

Edge counts alone are not enough. Two closed shells that meet at a single
welded vertex have no boundary edge and no edge shared by three faces, so every
edge count calls them clean while the surface still cannot be rigged, unwrapped
or given collision at that point; `nonmanifold_vertices` is the connectivity
test that catches it. A zero-area triangle likewise passes every count while
having no normal to bake against or collide with, so `degenerate_faces` counts
those separately.

The module is plain Python so the arithmetic can be tested without Blender, and
every measurement has two implementations that are tested against each other:
a readable one for small meshes and hosts without numpy, and an array-based one
for the multi-million-triangle meshes this was written for. `numpy_module()`
lets a caller decide what to do when numpy is absent instead of discovering it
mid-audit.
"""

# The five defects that disqualify a mesh for rigging, collision or baking.
DEFECTS = (
    "boundary_edges",
    "nonmanifold_edges",
    "inconsistent_winding_edges",
    "nonmanifold_vertices",
    "degenerate_faces",
)

# A triangle counts as degenerate when twice its area is below this fraction of
# the squared bounding-box scale: relative, so it means the same thing on a
# mesh measured in metres and one measured in centimetres.
DEGENERATE_TOLERANCE = 1e-12

UNAVAILABLE = {
    "status": "unavailable",
    "reason": "numpy is not available to this Blender build; topology was not measured",
}


def numpy_module():
    """Return numpy, or None when this interpreter does not have it."""
    try:
        import numpy
    except ImportError:
        return None
    return numpy


# --------------------------------------------------------------------------
# Welding: duplicated positions become one index, on a copy, for counting only.
# --------------------------------------------------------------------------


def _numpy_welded(numpy, vertices, triangles):
    points = numpy.asarray(vertices, dtype=numpy.float32).reshape(-1, 3)
    faces = numpy.asarray(triangles, dtype=numpy.int64).reshape(-1, 3)
    if not len(faces):
        return numpy.zeros((0, 3), dtype=numpy.float32), faces
    unique, inverse = numpy.unique(points, axis=0, return_inverse=True)
    # numpy has returned this as (n,) and as (n, 1) across versions.
    return unique, numpy.asarray(inverse).reshape(-1)[faces]


def _python_welded(vertices, triangles):
    positions = {}
    remap = []
    for point in vertices:
        remap.append(positions.setdefault(tuple(point), len(positions)))
    unique = [None] * len(positions)
    for point, index in positions.items():
        unique[index] = point
    return unique, [tuple(remap[int(i)] for i in triangle) for triangle in triangles]


# --------------------------------------------------------------------------
# Edges: boundary, shared by more than two faces, wound inconsistently.
# --------------------------------------------------------------------------


def _numpy_edge_counts(numpy, welded, vertex_count):
    if not len(welded):
        return 0, 0, 0
    welded = welded.astype(numpy.uint64)
    count = numpy.uint64(vertex_count)
    edges = numpy.concatenate(
        (welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]])
    )
    # +1 and -1 for the two directions a shared edge can be traversed: two
    # faces that agree cancel to zero, two that disagree do not.
    sign = numpy.where(edges[:, 0] < edges[:, 1], 1, -1)
    edges = numpy.sort(edges, axis=1)
    keys = edges[:, 0] * count + edges[:, 1]
    _, index, shared = numpy.unique(keys, return_inverse=True, return_counts=True)
    winding = numpy.bincount(numpy.asarray(index).reshape(-1), weights=sign)
    return (
        int(numpy.sum(shared == 1)),
        int(numpy.sum(shared > 2)),
        int(numpy.sum((shared == 2) & (winding != 0))),
    )


def _python_edge_counts(welded):
    shared = {}
    winding = {}
    for first, second, third in welded:
        for start, end in ((first, second), (second, third), (third, first)):
            key = (start, end) if start < end else (end, start)
            shared[key] = shared.get(key, 0) + 1
            winding[key] = winding.get(key, 0) + (1 if start < end else -1)
    return (
        sum(1 for count in shared.values() if count == 1),
        sum(1 for count in shared.values() if count > 2),
        sum(1 for key, count in shared.items() if count == 2 and winding[key]),
    )


# --------------------------------------------------------------------------
# Vertices: the faces around one vertex must form a single edge-connected fan.
# --------------------------------------------------------------------------
#
# Both implementations work on *corners* -- one per (face, position in face),
# numbered 3 * face + position. Two corners of the same vertex are joined when
# their faces share an edge that vertex lies on. A vertex whose corners end up
# in more than one group is a bowtie, or two shells touching at a point: no
# boundary edge, no edge shared by three faces, and still unusable.


def _python_nonmanifold_vertices(welded):
    incident = {}
    shared = {}
    for face, triangle in enumerate(welded):
        first, second, third = triangle
        for position, vertex in enumerate(triangle):
            incident.setdefault(vertex, []).append(face * 3 + position)
        for position, (start, end) in enumerate(
            ((first, second), (second, third), (third, first))
        ):
            if start == end:
                # A degenerate edge joins nothing; it is counted elsewhere.
                continue
            key = (start, end) if start < end else (end, start)
            shared.setdefault((start, key), []).append(face * 3 + position)
            shared.setdefault((end, key), []).append(face * 3 + (position + 1) % 3)
    parent = {}

    def find(corner):
        root = corner
        while parent.setdefault(root, root) != root:
            root = parent[root]
        while parent[corner] != root:
            parent[corner], corner = root, parent[corner]
        return root

    for corners in shared.values():
        anchor = find(corners[0])
        for corner in corners[1:]:
            other = find(corner)
            if other != anchor:
                parent[other] = anchor
    return sum(
        1
        for corners in incident.values()
        if len({find(corner) for corner in corners}) > 1
    )


def _numpy_nonmanifold_vertices(numpy, welded, vertex_count):
    """Same count, without building a Python object per corner or per edge.

    The Python version above allocates dictionaries and sets proportional to
    the triangle count, which is not something to do to a mesh with millions of
    them. Here the incidence is three integer arrays, the grouping is one sort,
    and the union-find is label propagation over those arrays: assign every
    group its smallest label, pull each corner down to the smallest label any of
    its groups carries, then point every label at its own label until nothing
    moves. Labels only ever decrease, so the loop terminates, and it settles on
    the smallest corner index in each connected group.
    """
    faces = numpy.asarray(welded, dtype=numpy.int64).reshape(-1, 3)
    count = len(faces)
    if not count:
        return 0
    corners = numpy.arange(count * 3, dtype=numpy.int64).reshape(count, 3)
    vertex_of_corner = faces.reshape(-1)
    starts, ends = faces, faces[:, [1, 2, 0]]
    start_corner, end_corner = corners, corners[:, [1, 2, 0]]
    low = numpy.minimum(starts, ends).reshape(-1)
    high = numpy.maximum(starts, ends).reshape(-1)
    real = low != high
    key = low * numpy.int64(vertex_count) + high
    # One record per (endpoint, edge): the group of corners that edge joins at
    # that endpoint. The side bit keeps the two endpoints of an edge apart.
    side = (starts.reshape(-1) > ends.reshape(-1)).astype(numpy.int64)
    groups = numpy.concatenate(
        (key[real] * 2 + side[real], key[real] * 2 + (1 - side[real]))
    )
    members = numpy.concatenate(
        (start_corner.reshape(-1)[real], end_corner.reshape(-1)[real])
    )
    if not len(members):
        # No non-degenerate edge: every corner is its own group.
        return int(
            numpy.sum(numpy.bincount(vertex_of_corner, minlength=vertex_count) > 1)
        )
    by_group = numpy.argsort(groups, kind="stable")
    group_sorted = groups[by_group]
    group_bounds = numpy.flatnonzero(
        numpy.concatenate(([True], group_sorted[1:] != group_sorted[:-1]))
    )
    group_of_record = numpy.empty(len(groups), dtype=numpy.int64)
    group_of_record[by_group] = (
        numpy.cumsum(
            numpy.concatenate(([True], group_sorted[1:] != group_sorted[:-1]))
        )
        - 1
    )
    by_member = numpy.argsort(members, kind="stable")
    member_sorted = members[by_member]
    member_bounds = numpy.flatnonzero(
        numpy.concatenate(([True], member_sorted[1:] != member_sorted[:-1]))
    )
    member_of_bucket = member_sorted[member_bounds]
    label = numpy.arange(count * 3, dtype=numpy.int64)
    while True:
        group_min = numpy.minimum.reduceat(label[members[by_group]], group_bounds)
        candidate = group_min[group_of_record]
        corner_min = numpy.minimum.reduceat(candidate[by_member], member_bounds)
        moved = numpy.minimum(label[member_of_bucket], corner_min)
        updated = label.copy()
        updated[member_of_bucket] = moved
        # Every label points at a smaller corner index, so one indexing pass is
        # a step of path compression rather than an arbitrary permutation.
        updated = updated[updated]
        if numpy.array_equal(updated, label):
            break
        label = updated
    order = numpy.lexsort((label, vertex_of_corner))
    vertices_sorted, labels_sorted = vertex_of_corner[order], label[order]
    distinct = numpy.concatenate(
        (
            [True],
            (vertices_sorted[1:] != vertices_sorted[:-1])
            | (labels_sorted[1:] != labels_sorted[:-1]),
        )
    )
    _, per_vertex = numpy.unique(vertices_sorted[distinct], return_counts=True)
    return int(numpy.sum(per_vertex > 1))


# --------------------------------------------------------------------------
# Faces: zero area, relative to how big the mesh is.
# --------------------------------------------------------------------------


def _numpy_degenerate_faces(numpy, points, welded):
    if not len(welded) or not len(points):
        return 0
    points = numpy.asarray(points, dtype=numpy.float64)
    scale = float(numpy.max(numpy.ptp(points, axis=0))) if len(points) > 1 else 0.0
    corners = points[numpy.asarray(welded, dtype=numpy.int64).reshape(-1, 3)]
    cross = numpy.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    twice_area = numpy.sqrt(numpy.sum(cross * cross, axis=1))
    return int(numpy.sum(twice_area <= DEGENERATE_TOLERANCE * scale * scale))


def _python_degenerate_faces(points, welded):
    if not welded or not points:
        return 0
    scale = max(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )
    tolerance = DEGENERATE_TOLERANCE * scale * scale
    count = 0
    for triangle in welded:
        first, second, third = (points[index] for index in triangle)
        one = [second[axis] - first[axis] for axis in range(3)]
        two = [third[axis] - first[axis] for axis in range(3)]
        cross = (
            one[1] * two[2] - one[2] * two[1],
            one[2] * two[0] - one[0] * two[2],
            one[0] * two[1] - one[1] * two[0],
        )
        if sum(value * value for value in cross) ** 0.5 <= tolerance:
            count += 1
    return count


# --------------------------------------------------------------------------


def audit_triangles(vertices, triangles, uv_layers=0, numpy=None):
    """Count the triangles and the five defects of one triangulated mesh.

    `vertices` is a sequence (or numpy array) of x/y/z positions and
    `triangles` a sequence of three vertex indices each. Pass `numpy=False` to
    force the plain-Python arithmetic; the default uses numpy when it is
    importable, which is the path Blender takes.
    """
    if numpy is None:
        numpy = numpy_module()
    if numpy is False or numpy is None:
        points, welded = _python_welded(vertices, triangles)
        boundary, nonmanifold, inconsistent = _python_edge_counts(welded)
        vertices_split = _python_nonmanifold_vertices(welded)
        degenerate = _python_degenerate_faces(points, welded)
        total = len(welded)
    else:
        points, welded = _numpy_welded(numpy, vertices, triangles)
        boundary, nonmanifold, inconsistent = _numpy_edge_counts(
            numpy, welded, len(points)
        )
        vertices_split = _numpy_nonmanifold_vertices(numpy, welded, len(points))
        degenerate = _numpy_degenerate_faces(numpy, points, welded)
        total = len(welded)
    return {
        "triangles": int(total),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "inconsistent_winding_edges": inconsistent,
        "nonmanifold_vertices": vertices_split,
        "degenerate_faces": degenerate,
        "uv_layers": int(uv_layers),
    }


def clean(record):
    """True only when a measured record reports none of the five defects."""
    if not isinstance(record, dict):
        return False
    return all(record.get(name) == 0 for name in DEFECTS)


def totals(records):
    """Sum per-mesh audits into the one verdict a caller can act on."""
    total = {"status": "measured", "meshes_measured": len(records), "triangles": 0}
    for name in DEFECTS:
        total[name] = 0
    for record in records:
        total["triangles"] += int(record.get("triangles") or 0)
        for name in DEFECTS:
            total[name] += int(record.get(name) or 0)
    total["clean"] = clean(total)
    return total
