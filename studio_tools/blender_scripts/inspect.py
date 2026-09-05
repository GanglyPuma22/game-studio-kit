"""Fresh-process GLB import with evaluated bounds, bones and materials."""

import bpy
import json
from pathlib import Path
from mathutils import Vector
import sys

args = sys.argv[sys.argv.index("--") + 1 :]
source = Path(args[0])
output = Path(args[1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
objects = list(bpy.context.scene.objects)
rigs = [o for o in objects if o.type == "ARMATURE"]
custom_shapes = {
    bone.custom_shape for rig in rigs for bone in rig.pose.bones if bone.custom_shape
}
objects = [o for o in objects if o not in custom_shapes]
meshes = [o for o in objects if o.type == "MESH"]
points = [o.matrix_world @ Vector(corner) for o in meshes for corner in o.bound_box]
if not points:
    raise RuntimeError("Imported GLB contains no mesh bounds")
low = [min(p[i] for p in points) for i in range(3)]
high = [max(p[i] for p in points) for i in range(3)]
record = {
    "blender_version": bpy.app.version_string,
    "mesh_count": len(meshes),
    "material_count": len(bpy.data.materials),
    "material_names": [m.name for m in bpy.data.materials],
    "armature_count": len(rigs),
    "bone_names": sorted({b.name for o in rigs for b in o.data.bones}),
    "actions": [a.name for a in bpy.data.actions],
    "bounds_min": low,
    "bounds_max": high,
    "dimensions_m": [high[i] - low[i] for i in range(3)],
    "hierarchy": [
        {"name": o.name, "parent": o.parent.name if o.parent else None, "type": o.type}
        for o in objects
    ],
}
output.write_text(json.dumps(record, indent=2), encoding="utf-8")
bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix(".blend")))
