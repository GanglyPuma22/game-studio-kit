"""Fixed-camera frame samples or a turntable around an explicit source-space target."""

import bpy
import json
import math
from mathutils import Vector, Matrix
from pathlib import Path
import sys

args = sys.argv[sys.argv.index("--") + 1 :]
out = Path(args[0])
camera = bpy.data.objects.get(args[1])
frames = [int(v) for v in args[2].split(",")]
angles = [float(v) for v in args[3].split(",")]
target = Vector([float(v) for v in args[4].split(",")])
if camera is None or camera.type != "CAMERA":
    raise RuntimeError("Named review camera is missing from the source")
if not 1 <= len(frames) * len(angles) <= 120:
    raise RuntimeError("Render job must contain 1–120 samples")
out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
scene.camera = camera
scene.render.image_settings.file_format = "PNG"
origin = camera.location.copy()
rotation = camera.rotation_euler.copy()
samples = []
for angle in angles:
    if angle == 0:
        camera.location = origin
        camera.rotation_euler = rotation
    else:
        camera.location = target + Matrix.Rotation(math.radians(angle), 4, "Z") @ (
            origin - target
        )
        camera.rotation_euler = (
            (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
    for frame in frames:
        scene.frame_set(frame)
        name = f"view-{angle:07.2f}-frame-{frame:04d}.png"
        scene.render.filepath = str(out / name)
        bpy.ops.render.render(write_still=True)
        samples.append({"file": name, "frame": frame, "angle_degrees": angle})
(out / "renders.json").write_text(
    json.dumps(
        {
            "blender_version": bpy.app.version_string,
            "camera": camera.name,
            "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "resolution_percentage": scene.render.resolution_percentage,
            "source_space_target": list(target),
            "samples": samples,
        },
        indent=2,
    ),
    encoding="utf-8",
)
