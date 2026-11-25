"""Fresh-process GLB import with evaluated bounds, bones, materials and topology."""

import bpy
import importlib.util
import json
from pathlib import Path
from mathutils import Vector
import sys

# Blender runs this file by path, so the sibling audit module is loaded by path
# too rather than through a package import that --factory-startup cannot see.
_spec = importlib.util.spec_from_file_location(
    "studio_blender_topology", Path(__file__).resolve().parent / "topology.py"
)
topology = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(topology)


def uv_layout(obj, numpy):
    """Island count, map use and surface per unit of the layout the game draws.

    Measured in world units so the figure divides straight into a map size.
    None when the mesh has no layout or numpy cannot measure it: unmeasured,
    never zero islands.
    """
    mesh = obj.data
    layer = next((l for l in mesh.uv_layers if l.active_render), mesh.uv_layers.active)
    if numpy is None or layer is None or not len(mesh.loop_triangles):
        return None
    points = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float64)
    mesh.vertices.foreach_get("co", points)
    world = numpy.array(obj.matrix_world, dtype=numpy.float64)
    points = points.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
    faces = numpy.empty(len(mesh.loop_triangles) * 3, dtype=numpy.int32)
    mesh.loop_triangles.foreach_get("vertices", faces)
    loops = numpy.empty(len(mesh.loop_triangles) * 3, dtype=numpy.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    uv = numpy.empty(len(mesh.loops) * 2, dtype=numpy.float32)
    layer.data.foreach_get("uv", uv)
    record = topology.uv_layout(
        points, faces.reshape(-1, 3), uv.reshape(-1, 2)[loops].reshape(-1, 3, 2), numpy=numpy
    )
    record["layer"] = layer.name
    return record


def uv_layout_totals(records):
    """A character's layout usually spans several mesh objects: add them up."""
    measured = [r["uv_layout"] for r in records if r.get("uv_layout") and r["uv_layout"]["islands"]]
    if not measured:
        return None
    return {
        "meshes_measured": len(measured),
        "islands": sum(m["islands"] for m in measured),
        "small_islands": sum(m["small_islands"] for m in measured),
        "map_used": sum(m["map_used"] for m in measured),
        "outside_unit_square": sum(m["outside_unit_square"] for m in measured),
        "unmapped_triangles": sum(m["unmapped_triangles"] for m in measured),
    }


def audit(meshes, numpy):
    """Per-mesh triangle and defect counts; the mesh itself is never touched."""
    records = []
    for obj in meshes:
        mesh = obj.data
        mesh.calc_loop_triangles()
        if numpy is None:
            # Triangle and UV counts are free; the edge arithmetic is not, and
            # guessing it on a multi-million-triangle mesh is worse than saying so.
            record = {
                "name": obj.name,
                **topology.unavailable_mesh_record(len(mesh.loop_triangles), len(mesh.uv_layers)),
            }
        else:
            points = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float32)
            mesh.vertices.foreach_get("co", points)
            faces = numpy.empty(len(mesh.loop_triangles) * 3, dtype=numpy.int32)
            mesh.loop_triangles.foreach_get("vertices", faces)
            record = {
                "name": obj.name,
                **topology.audit_triangles(
                    points.reshape(-1, 3),
                    faces.reshape(-1, 3),
                    len(mesh.uv_layers),
                    numpy=numpy,
                ),
            }
        record["uv_layout"] = uv_layout(obj, numpy)
        if not record["triangles"]:
            # A GLB primitive of only points or lines reports zero of every
            # defect, which reads as clean rather than as never triangulated.
            record["reason"] = "no triangles"
        records.append(record)
    return records


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
numpy = topology.numpy_module()
audited = audit(meshes, numpy)
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
    "meshes": audited,
    "topology": topology.totals(audited) if numpy is not None else dict(topology.UNAVAILABLE),
    "uv_layout": uv_layout_totals(audited),
}
output.write_text(json.dumps(record, indent=2), encoding="utf-8")
bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix(".blend")))
