"""Flat geometric silhouettes at fixed, shared perspective cameras."""
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw, ImageOps
from trimesh.proximity import ProximityQuery

SIDES = ("front", "right", "back", "left")


def render(tm, target, distance, side, path, width, height, fov):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    shading = scene.display.shading
    shading.light = "FLAT"
    shading.color_type = "SINGLE"
    shading.single_color = (1, 1, 1)
    shading.show_shadows = False
    shading.show_cavity = False
    shading.show_object_outline = False
    scene.display.render_aa = "OFF"
    mesh = bpy.data.meshes.new("QA geometry")
    # glTF Y up -> Blender Z up, without re-fitting each LOD.
    vertices = np.column_stack((tm.vertices[:, 0], -tm.vertices[:, 2], tm.vertices[:, 1]))
    mesh.from_pydata(vertices.tolist(), [], tm.faces.tolist())
    mesh.update()
    obj = bpy.data.objects.new("QA geometry", mesh)
    scene.collection.objects.link(obj)
    camera_data = bpy.data.cameras.new("QA camera")
    camera_data.type = "PERSP"
    camera_data.sensor_fit = "VERTICAL"
    camera_data.angle = math.radians(fov)
    camera_data.clip_start = 0.001
    camera_data.clip_end = max(distance * 10, 1000)
    camera = bpy.data.objects.new("QA camera", camera_data)
    scene.collection.objects.link(camera)
    center = Vector((target[0], -target[2], target[1]))
    angle = SIDES.index(side) * math.pi / 2
    camera.location = center + Vector((math.sin(angle) * distance, -math.cos(angle) * distance, 0))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    with Image.open(path) as image:
        mask = np.array(image.getchannel("A")) >= 128
    # Save the measured binary silhouette, visible on any image viewer's theme.
    Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).save(path)
    return mask


def compare(a, b):
    union = int((a | b).sum())
    changed = int((a ^ b).sum())
    border = any(m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any() for m in (a, b))
    return {"different_pixels": changed, "union_pixels": union,
            "difference_fraction": changed / union if union else 1.0,
            "before_pixels": int(a.sum()), "after_pixels": int(b.sum()), "frame_clipped": bool(border)}


def disappeared(parts, names, lower, tolerance_mm):
    """Flag a part when at most half its vertices remain near the lower surface.

    This is a conservative geometry correspondence alarm, independent of pixels.
    It never equates a lower component count with a disappearance: merged parts
    can still be represented by the lower surface. Simplification can flag a
    moved part too; all flagged names and distances remain available for review.
    """
    query = ProximityQuery(lower)
    rows = []
    for i, part in enumerate(parts):
        _, distances, _ = query.on_surface(part.vertices)
        retained = float((distances * 1000 <= tolerance_mm).mean())
        if retained <= 0.5:
            rows.append({"part": i, "name": names[i], "retained_vertex_fraction": retained,
                         "nearest_surface_mm": float(distances.min()) * 1000,
                         "farthest_surface_mm": float(distances.max()) * 1000,
                         "centroid_m": part.centroid.tolist(), "triangles": len(part.faces)})
    return rows


def contact_sheet(tiles, out):
    tile_width, tile_height = 480, 340
    sheet = Image.new("RGB", (tile_width * 4, tile_height * max(1, (len(tiles) + 3) // 4)), "white")
    draw = ImageDraw.Draw(sheet)
    if not tiles:
        draw.text((10, 10), "No silhouette evidence produced. QA failed.", fill="black")
    # One common crop, centered on the unchanged camera target, for the whole
    # sheet. Keep native pixels where they fit; never auto-fit individual LODs.
    half_width, half_height = (tile_width - 10) / 2, (tile_height - 50) / 2
    for path, _ in tiles:
        with Image.open(path) as image:
            bounds = ImageOps.invert(image.convert("L")).getbbox()
            if bounds:
                half_width = max(half_width, image.width / 2 - bounds[0] + 12, bounds[2] - image.width / 2 + 12)
                half_height = max(half_height, image.height / 2 - bounds[1] + 12, bounds[3] - image.height / 2 + 12)
    crop_width, crop_height = math.ceil(2 * half_width), math.ceil(2 * half_height)
    scale = min((tile_width - 10) / crop_width, (tile_height - 50) / crop_height, 1.0)
    for i, (path, title) in enumerate(tiles):
        x, y = (i % 4) * tile_width, (i // 4) * tile_height
        draw.text((x + 5, y + 5), title, fill="black")
        draw.text((x + 5, y + 20), f"Shared center crop; pixel scale {scale:.3f}", fill="black")
        with Image.open(path) as image:
            left, top = (image.width - crop_width) // 2, (image.height - crop_height) // 2
            # An output smaller than the tile is padded white, not magnified.
            silhouette = Image.new("RGB", (crop_width, crop_height), "white")
            region = (max(0, left), max(0, top), min(image.width, left + crop_width), min(image.height, top + crop_height))
            silhouette.paste(image.convert("RGB").crop(region), (max(0, -left), max(0, -top)))
            if scale < 1:
                silhouette = silhouette.resize((round(crop_width * scale), round(crop_height * scale)))
            sheet.paste(silhouette, (x + 5, y + 40))
    sheet.save(Path(out) / "contact-sheet.png")
