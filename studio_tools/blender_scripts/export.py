"""Export a designated collection from an existing .blend opened by Blender."""

import bpy
from pathlib import Path
import sys

args = sys.argv[sys.argv.index("--") + 1 :]
name = args[0]
out = Path(args[1])
collection = bpy.data.collections.get(name)
if collection is None:
    raise RuntimeError("Named export collection does not exist")
objects = set(collection.all_objects)
if not any(o.type == "MESH" for o in objects):
    raise RuntimeError("Export collection contains no mesh")
for obj in objects:
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object not in objects:
            raise RuntimeError("Required armature is outside export collection")
bpy.ops.object.select_all(action="DESELECT")
for obj in objects:
    obj.hide_set(False)
    obj.select_set(True)
bpy.context.view_layer.objects.active = next(iter(objects))
for obj in objects:
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:
            track.mute = False
out.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(out),
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="NLA_TRACKS",
    export_skins=True,
    export_materials="EXPORT",
    export_yup=True,
)
