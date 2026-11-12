"""Key a Blender camera from a flown camera CSV (camera_rig.py fly --z-up output).

Run inside Blender, for example:
  blender scene.blend --python blender_key_camera.py -- flown.csv CameraName [fps]

Each row's lens position, look-at point and up vector become one keyframe on
the camera's location and rotation (no interpolation smoothing is added: the
rig already eased the move). Not tested in CI here (needs Blender); check the
first and last frames against the drawn camera once per scene.
"""
import csv
import sys

import bpy
from mathutils import Matrix, Vector


def key_camera(csv_path, cam_name, fps=None):
    cam = bpy.data.objects[cam_name]
    cam.rotation_mode = "XYZ"
    scene = bpy.context.scene
    fps = fps or scene.render.fps / scene.render.fps_base
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            v = {k: float(x) for k, x in row.items()}
            lens = Vector((v["px"], v["py"], v["pz"]))
            fwd = (Vector((v["lx"], v["ly"], v["lz"])) - lens).normalized()
            up = Vector((v["ux"], v["uy"], v["uz"])).normalized()
            right = fwd.cross(up).normalized()
            up = right.cross(fwd).normalized()
            # A Blender camera looks down its local -Z with local +Y up.
            rot = Matrix((right, up, -fwd)).transposed()
            prev = cam.rotation_euler.copy()
            cam.matrix_world = Matrix.Translation(lens) @ rot.to_4x4()
            # Keep Euler angles continuous across frames (no 360 degree flips).
            cam.rotation_euler = cam.matrix_world.to_euler(cam.rotation_mode, prev)
            frame = scene.frame_start + round(v["t"] * fps)
            cam.keyframe_insert("location", frame=frame)
            cam.keyframe_insert("rotation_euler", frame=frame)
    # Linear keys: the per-frame samples already carry the easing.
    if cam.animation_data and cam.animation_data.action:
        for fc in cam.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) < 2:
        raise SystemExit("usage: blender ... --python blender_key_camera.py -- flown.csv CameraName [fps]")
    key_camera(args[0], args[1], float(args[2]) if len(args) > 2 else None)
