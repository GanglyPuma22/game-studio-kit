"""Close-up evidence renders for findings, with a capture sidecar per image.

Each flagged site gets a Workbench render looking at it from the direction the
check saw it, with back faces culled the way a game engine draws single-sided
materials, and the site ringed in red. The sidecar records what the image is
evidence of (file hash, LOD, pose, view, distance, FOV, resolution, renderer),
so a reviewer, or a later visual-claim step, knows exactly what was and was
not shown. Mechanical results never depend on these images.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw

FIELDS = ("glb_sha256", "lod", "pose", "time_s", "check", "site", "view", "direction", "distance_m",
          "fov_deg", "resolution", "renderer", "back_faces", "target_m")


def _scene(tm, double_faces=None, part=None, width=640, height=640):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "OBJECT"
    shading.show_backface_culling = True
    shading.show_cavity = True
    shading.show_object_outline = True
    scene.world = bpy.data.worlds.new("QA") if scene.world is None else scene.world
    scene.world.color = (0.82, 0.84, 0.88)
    culled = np.ones(len(tm.faces), bool) if double_faces is None else ~np.asarray(double_faces, bool)
    for label, keep in (("single", culled), ("double", ~culled)):
        if not keep.any():
            continue
        faces = tm.faces[keep]
        mesh = bpy.data.meshes.new(label)
        v = tm.vertices
        mesh.from_pydata(np.column_stack((v[:, 0], -v[:, 2], v[:, 1])).tolist(), [], faces.tolist())
        mesh.update()
        obj = bpy.data.objects.new(label, mesh)
        obj.color = (0.78, 0.72, 0.62, 1) if label == "single" else (0.55, 0.68, 0.80, 1)
        if label == "double":
            # Workbench culls per scene; double-sided faces are drawn from both sides by adding the flipped copy.
            flip = bpy.data.meshes.new("double-back")
            flip.from_pydata(np.column_stack((v[:, 0], -v[:, 2], v[:, 1])).tolist(), [], faces[:, ::-1].tolist())
            flip.update()
            back = bpy.data.objects.new("double-back", flip)
            back.color = obj.color
            scene.collection.objects.link(back)
        scene.collection.objects.link(obj)
    return scene


def render_site(tm, at, direction, path, *, distance, fov=40.0, double_faces=None, size=640, ring_px=26):
    """Render looking along `direction` (glTF Y up) at `at`, from `distance` m away; ring the site."""
    scene = _scene(tm, double_faces, width=size, height=size)
    cam_data = bpy.data.cameras.new("QA camera")
    cam_data.type = "PERSP"
    cam_data.angle = math.radians(fov)
    cam_data.clip_start = max(distance * 1e-3, 1e-3)
    cam_data.clip_end = distance * 50
    cam = bpy.data.objects.new("QA camera", cam_data)
    scene.collection.objects.link(cam)
    target = Vector((at[0], -at[2], at[1]))
    d = Vector((direction[0], -direction[2], direction[1])).normalized()
    cam.location = target - d * distance
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    with Image.open(path) as image:
        image = image.convert("RGB")
        draw = ImageDraw.Draw(image)
        c = size / 2
        draw.ellipse((c - ring_px, c - ring_px, c + ring_px, c + ring_px), outline=(220, 20, 20), width=3)
        image.save(path)
    return {"view": "site", "direction": [round(float(x), 4) for x in direction], "distance_m": round(float(distance), 4),
            "fov_deg": fov, "resolution": [size, size], "renderer": f"Blender {bpy.app.version_string} Workbench",
            "back_faces": "culled except doubleSided materials", "target_m": [round(float(x), 4) for x in at]}


def write_sidecar(path, glb, lod, pose, time_s, check, site, capture):
    record = {"schema_version": 1, "glb_sha256": hashlib.sha256(Path(glb).read_bytes()).hexdigest(),
              "image_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "lod": lod, "pose": pose,
              "time_s": round(float(time_s), 4), "check": check, "site": site, **capture}
    Path(str(path) + ".json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
