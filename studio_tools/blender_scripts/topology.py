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

The module is plain Python so the arithmetic can be tested without Blender. It
uses numpy when numpy is present, because the meshes this was written for hold
millions of triangles; `numpy_module()` lets a caller decide what to do when it
is absent instead of discovering it mid-audit.
"""

# The three defects that disqualify a mesh for rigging, collision or baking.
DEFECTS = ("boundary_edges", "nonmanifold_edges", "inconsistent_winding_edges")

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


def _numpy_counts(numpy, vertices, triangles):
    points = numpy.asarray(vertices, dtype=numpy.float32).reshape(-1, 3)
    faces = numpy.asarray(triangles, dtype=numpy.int64).reshape(-1, 3)
    if not len(faces):
        return 0, 0, 0
    unique, inverse = numpy.unique(points, axis=0, return_inverse=True)
    # numpy has returned this as (n,) and as (n, 1) across versions.
    welded = numpy.asarray(inverse).reshape(-1)[faces].astype(numpy.uint64)
    count = numpy.uint64(len(unique))
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


def _python_counts(vertices, triangles):
    positions = {}
    welded = []
    for point in vertices:
        welded.append(positions.setdefault(tuple(point), len(positions)))
    shared = {}
    winding = {}
    for triangle in triangles:
        first, second, third = (welded[int(i)] for i in triangle)
        for start, end in ((first, second), (second, third), (third, first)):
            key = (start, end) if start < end else (end, start)
            shared[key] = shared.get(key, 0) + 1
            winding[key] = winding.get(key, 0) + (1 if start < end else -1)
    return (
        sum(1 for count in shared.values() if count == 1),
        sum(1 for count in shared.values() if count > 2),
        sum(1 for key, count in shared.items() if count == 2 and winding[key]),
    )


def audit_triangles(vertices, triangles, uv_layers=0, numpy=None):
    """Count the triangles and the three defects of one triangulated mesh.

    `vertices` is a sequence (or numpy array) of x/y/z positions and
    `triangles` a sequence of three vertex indices each. Pass `numpy=False` to
    force the plain-Python arithmetic; the default uses numpy when it is
    importable, which is the path Blender takes.
    """
    if numpy is None:
        numpy = numpy_module()
    if numpy is False or numpy is None:
        counts = _python_counts(vertices, triangles)
        total = len(triangles)
    else:
        counts = _numpy_counts(numpy, vertices, triangles)
        total = len(numpy.asarray(triangles).reshape(-1, 3))
    boundary, nonmanifold, inconsistent = counts
    return {
        "triangles": int(total),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "inconsistent_winding_edges": inconsistent,
        "uv_layers": int(uv_layers),
    }


def clean(record):
    """True only when a measured record reports none of the three defects."""
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
