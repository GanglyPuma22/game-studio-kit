"""Experimental frame math only; no inference, retargeting or Blender authoring."""

import math
from ..common import StudioError


def _finite(values, message="Motion arithmetic must remain finite"):
    try:
        valid = all(type(value) in (int, float) and math.isfinite(value) for value in values)
    except OverflowError as exc:
        raise StudioError(message) from exc
    if not valid:
        raise StudioError(message)


def multiply(a, b):
    try:
        result = [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    except OverflowError as exc:
        raise StudioError("Motion matrix multiplication overflowed") from exc
    _finite(value for row in result for value in row)
    return result


def rigid(rotation=None, position=(0, 0, 0)):
    rotation = rotation or [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    result = [list(rotation[i]) + [position[i]] for i in range(3)] + [[0, 0, 0, 1]]
    _finite(value for row in result for value in row)
    return result


def _similarity(matrix):
    if (not isinstance(matrix, list) or len(matrix) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in matrix)):
        raise StudioError("Motion frame needs a finite homogeneous 4x4 matrix")
    _finite((x for row in matrix for x in row), "Motion frame needs finite numeric values")
    if any(abs(matrix[3][j] - (1 if j == 3 else 0)) > 1e-8 for j in range(4)):
        raise StudioError("Motion frame needs a homogeneous 4x4 matrix")
    scale = math.hypot(*(matrix[i][0] for i in range(3)))
    _finite([scale], "Motion scale overflowed")
    if scale <= 1e-12:
        raise StudioError("Motion frame has zero scale")
    r = [[matrix[i][j] / scale for j in range(3)] for i in range(3)]
    _finite(value for row in r for value in row)
    for i in range(3):
        for j in range(3):
            product = sum(r[k][i] * r[k][j] for k in range(3))
            _finite([product])
            if abs(product - (i == j)) > 1e-6:
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
        _finite([reference_height], "Mite reference height must be finite")
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
        try:
            rotation = [[sum(rt[i][k] * pose[k][j] for k in range(3))
                         for j in range(3)] for i in range(3)]
            position = [sum(rt[i][k] * (pose[k][3] - canonical_from_source[k][3])
                            for k in range(3)) / scale for i in range(3)]
        except OverflowError as exc:
            raise StudioError("Source frame conversion overflowed") from exc
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


def quaternion_frame(quaternion, position):
    """Rigid frame from a scalar-first quaternion; reject invalid evidence."""
    if len(quaternion) != 4 or len(position) != 3:
        raise StudioError("Decoded rotation/position dimensions differ")
    _finite([*quaternion, *position])
    norm = math.hypot(*quaternion)
    if not math.isfinite(norm) or norm <= 1e-12 or abs(norm - 1) > 1e-4:
        raise StudioError("Decoded quaternion must be finite and unit length")
    w, x, y, z = [value / norm for value in quaternion]
    return rigid([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                  [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                  [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]], position)


def joint_globals(local_frames, parents):
    """Recover every joint by name before projecting any unweighted leaves."""
    source_locals(local_frames, parents)  # Validate identities/rigidity/topology.
    result, remaining = {}, set(parents)
    while remaining:
        ready = [name for name in remaining if parents[name] is None or parents[name] in result]
        if not ready:
            raise StudioError("Decoded hierarchy contains a cycle")
        for name in ready:
            parent = parents[name]
            result[name] = (multiply(result[parent], local_frames[name])
                            if parent is not None else local_frames[name])
            remaining.remove(name)
    return result


def source_calibration(decoder_rest, source_rest, canonical_from_source):
    """Align identity-delta decoder rest to the captured original bone bases.

    Decoder rest has identity rotations and canonical T-pose joint positions.
    The stored T-pose bone quaternions are coordinate provenance, not decoded
    rest rotations. Applying them here would count the bone basis twice.
    """
    converted = to_source(decoder_rest, canonical_from_source)
    if not source_rest or not set(source_rest) <= set(converted):
        raise StudioError("Captured original rest contains missing decoder joint names")
    alignment = {}
    for name, rest in source_rest.items():
        # Original Blender matrices are float32 captures, not idealized rigid
        # matrices. Validate at declared capture precision and preserve their
        # exact values; strict canonical/trajectory validation is unchanged.
        if (not isinstance(rest,list) or len(rest) != 4
                or any(not isinstance(row,list) or len(row) != 4 for row in rest)):
            raise StudioError("Captured source basis needs a homogeneous 4x4 matrix")
        _finite(value for row in rest for value in row)
        if any(abs(rest[3][j]-(j == 3)) > 1e-8 for j in range(4)):
            raise StudioError("Captured source basis must be homogeneous")
        scale = math.hypot(*(rest[i][0] for i in range(3)))
        if not math.isfinite(scale) or abs(scale-1) > 1e-5:
            raise StudioError("Captured source basis must have unit scale at capture precision")
        r = [row[:3] for row in rest[:3]]
        for i in range(3):
            for j in range(3):
                if abs(sum(r[k][i]*r[k][j] for k in range(3))-(i == j)) > 1e-5:
                    raise StudioError("Captured source basis has shear/nonuniform scale")
        det = (r[0][0]*(r[1][1]*r[2][2]-r[1][2]*r[2][1])
               -r[0][1]*(r[1][0]*r[2][2]-r[1][2]*r[2][0])
               +r[0][2]*(r[1][0]*r[2][1]-r[1][1]*r[2][0]))
        if abs(det-1) > 1e-5:
            raise StudioError("Captured source basis reflects or distorts the rig")
        if max(abs(converted[name][i][3]-rest[i][3]) for i in range(3)) > 1e-5:
            raise StudioError("Canonical/source rest joint heads differ; this bridge preserves the same rig")
        alignment[name] = multiply(inverse_rigid(converted[name]), rest)
    return alignment


def calibrated_source(frame, canonical_from_source, alignment):
    """Convert the full decoded hierarchy, then retain originals by name.

    Raw Root translation and rotation survive this coordinate/rest conversion.
    No controller transform, compensation, auxiliary facing or authored channel
    is injected. Source parent-relative/Blender basis solving follows separately.
    """
    converted = to_source(frame, canonical_from_source)
    if not alignment or not set(alignment) <= set(converted):
        raise StudioError("Source calibration contains missing decoded joint names")
    return {name: multiply(converted[name], basis) for name, basis in alignment.items()}
