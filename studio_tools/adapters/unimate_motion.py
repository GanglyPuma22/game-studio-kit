"""Experimental frame math only; no inference, retargeting or Blender authoring."""

import math
from ..common import StudioError


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def rigid(rotation=None, position=(0, 0, 0)):
    rotation = rotation or [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    return [list(rotation[i]) + [position[i]] for i in range(3)] + [[0, 0, 0, 1]]


def _similarity(matrix):
    if (not isinstance(matrix, list) or len(matrix) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in matrix)
            or any(type(x) not in (int, float) or not math.isfinite(x) for row in matrix for x in row)
            or any(abs(matrix[3][j] - (1 if j == 3 else 0)) > 1e-8 for j in range(4))):
        raise StudioError("Motion frame needs a finite homogeneous 4x4 matrix")
    scale = math.sqrt(sum(matrix[i][0] ** 2 for i in range(3)))
    if scale <= 1e-12:
        raise StudioError("Motion frame has zero scale")
    r = [[matrix[i][j] / scale for j in range(3)] for i in range(3)]
    for i in range(3):
        for j in range(3):
            if abs(sum(r[k][i] * r[k][j] for k in range(3)) - (i == j)) > 1e-6:
                raise StudioError("Motion frame must have uniform scale and orthogonal axes")
    determinant = (r[0][0] * (r[1][1]*r[2][2] - r[1][2]*r[2][1])
                   - r[0][1] * (r[1][0]*r[2][2] - r[1][2]*r[2][0])
                   + r[0][2] * (r[1][0]*r[2][1] - r[1][1]*r[2][0]))
    if abs(determinant - 1) > 1e-6:
        raise StudioError("Motion frame cannot reflect the rig")
    return scale, r


def inverse_rigid(matrix):
    scale, r = _similarity(matrix)
    if abs(scale - 1) > 1e-6:
        raise StudioError("Decoded joint and trajectory frames must be rigid")
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    return rigid(rt, [-sum(rt[i][j] * matrix[j][3] for j in range(3)) for i in range(3)])


def remove_trajectory(frame, anchor, *, kind, reference_height):
    """Return (all-joint in-place global frames, removed trajectory).

    Y-up, +Z declared forward, column vectors. Mite removes planar motion/yaw
    at frame-zero height; Kite removes the entire rigid Root transform. The
    caller supplies its fixed rest anchor, never a controller/world transform.
    """
    inverse_rigid(anchor)
    root = frame["Root"]
    inverse_rigid(root)
    if kind == "mite":
        if type(reference_height) not in (int, float) or not math.isfinite(reference_height):
            raise StudioError("Mite reference height must be finite")
        x, z = root[0][2], root[2][2]
        if math.hypot(x, z) <= 1e-8:
            raise StudioError("Root forward axis has no defined planar heading")
        yaw = math.atan2(x, z)
        c, s = math.cos(yaw), math.sin(yaw)
        trajectory = rigid([[c, 0, s], [0, 1, 0], [-s, 0, c]],
                           (root[0][3], reference_height, root[2][3]))
    elif kind == "kite":
        trajectory = root
    else:
        raise StudioError("Trajectory policy must be mite or kite")
    correction = multiply(anchor, inverse_rigid(trajectory))
    result = {}
    for name, pose in frame.items():
        inverse_rigid(pose)
        result[name] = multiply(correction, pose)
    return result, trajectory


def to_source(frame, canonical_from_source):
    """Invert uniform similarity for positions and its rotation for orientations."""
    scale, r = _similarity(canonical_from_source)
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    result = {}
    for name, pose in frame.items():
        inverse_rigid(pose)
        rotation = [[sum(rt[i][k] * pose[k][j] for k in range(3))
                     for j in range(3)] for i in range(3)]
        position = [sum(rt[i][k] * (pose[k][3] - canonical_from_source[k][3])
                        for k in range(3)) / scale for i in range(3)]
        result[name] = rigid(rotation, position)
    return result


def source_locals(frame, parents):
    """Parent-relative frames; Blender rest/bind pose solving remains separate."""
    if set(frame) != set(parents):
        raise StudioError("Source frame and parent identities differ")
    result = {}
    for name, pose in frame.items():
        inverse_rigid(pose)
        seen, parent = {name}, parents[name]
        while parent is not None:
            if parent in seen or parent not in parents:
                raise StudioError("Source parents contain a cycle or missing joint")
            seen.add(parent)
            parent = parents[parent]
        result[name] = (multiply(inverse_rigid(frame[parents[name]]), pose)
                        if parents[name] is not None else pose)
    return result
