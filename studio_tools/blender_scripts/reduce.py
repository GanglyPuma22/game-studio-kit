"""Weld and decimate mesh objects, auditing topology before and after.

This script reduces triangle count and does nothing else. It never fills a
hole, never dissolves a boundary, never merges by distance beyond the coincident
weld below and never edits materials or UV layers: a mesh that arrives with
holes leaves with holes, and the receipt says so. Repair is a modelling decision
a person makes about a specific asset, not something a reduction may do quietly
on the way past.

Any modifier stack the source already carried is applied first, in its declared
order, before anything is measured. Auditing the base mesh while saving the
evaluated one would qualify a surface nobody ever sees; applying first means
what is measured is what is written. The applied names are recorded.

Several objects can point at one mesh datablock. The stack is applied once,
on that datablock's first user, and the rest are pointed at the result
afterward with their own copies of that stack removed, so a shared tree mesh
stays one datablock with many instances rather than becoming one copy per
object and nothing is applied twice; instances whose stacks disagree are
refused rather than reduced to a guess about which one was meant.

Objects are identified in the audit by index and by a digest of their name,
never by the name itself: `--object` is a value the caller passed in, and a
receipt is not the place to echo one back.

Every mesh in `bpy.data` is reduced, not only the ones the active scene happens
to link. A .blend with a second scene, or with a mesh linked to no scene at
all, would otherwise be saved with objects that were audited by nobody; the
scene count is recorded so a reader can see what the file held. An object
linked into the active scene only so this script could reach it is unlinked
again before the file is saved, so that scene membership does not leak into
the saved result; the audit already made of its mesh is unaffected.
"""

import bpy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

_spec = importlib.util.spec_from_file_location(
    "studio_blender_topology", Path(__file__).resolve().parent / "topology.py"
)
topology = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(topology)

# Coincident only: exported meshes duplicate vertices along texture seams, and
# a threshold large enough to close a real gap would be repairing the mesh.
WELD_DISTANCE = 1e-7


def triangles(mesh):
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def measure(obj, numpy):
    mesh = obj.data
    mesh.calc_loop_triangles()
    if numpy is None:
        return topology.unavailable_mesh_record(len(mesh.loop_triangles), len(mesh.uv_layers))
    points = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float32)
    mesh.vertices.foreach_get("co", points)
    faces = numpy.empty(len(mesh.loop_triangles) * 3, dtype=numpy.int32)
    mesh.loop_triangles.foreach_get("vertices", faces)
    return topology.audit_triangles(
        points.reshape(-1, 3), faces.reshape(-1, 3), len(mesh.uv_layers), numpy=numpy
    )


def apply_modifier(obj, modifier):
    if obj.data.users > 1:
        # Applying to data another object shares would edit that object too.
        obj.data = obj.data.copy()
    with bpy.context.temp_override(
        object=obj,
        active_object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    ):
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def apply_existing_stack(obj):
    """Apply whatever modifiers the source already had, in order, and say so."""
    names = [modifier.name for modifier in obj.modifiers]
    for name in names:
        apply_modifier(obj, obj.modifiers[name])
    return names


def identify(obj, index):
    """Name an object in the receipt without repeating the name back."""
    return {
        "index": index,
        "name_sha256": hashlib.sha256(obj.name.encode("utf-8")).hexdigest(),
    }


args = sys.argv[sys.argv.index("--") + 1 :]
source = Path(args[0])
target = int(args[1])
output = Path(args[2])
audit_path = Path(args[3])
selected = args[4] if len(args) > 4 else ""

bpy.ops.wm.read_factory_settings(use_empty=True)
if source.suffix.lower() == ".blend":
    bpy.ops.wm.open_mainfile(filepath=str(source))
else:
    bpy.ops.import_scene.gltf(filepath=str(source))
meshes = sorted(
    (o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: o.name
)
if selected:
    meshes = [o for o in meshes if o.name == selected]
if not meshes:
    raise RuntimeError("No mesh object to reduce; check --source and --object")
# An object no scene links has no view layer, so it can be neither unhidden nor
# handed to modifier_apply. Linking it here is what lets it be measured at
# all; every object this links is unlinked again below, before the file is
# saved, so scene membership added only for that reason does not persist.
scene_collection = bpy.context.scene.collection
temporarily_linked = []
for obj in meshes:
    if obj.name not in bpy.context.scene.objects:
        scene_collection.objects.link(obj)
        temporarily_linked.append(obj)

numpy = topology.numpy_module()
report = {
    "schema_version": 1,
    "blender_version": bpy.app.version_string,
    "status": "measured" if numpy is not None else topology.UNAVAILABLE["status"],
    "target_triangles": target,
    "weld_distance": WELD_DISTANCE,
    "scenes": len(bpy.data.scenes),
    "objects": [],
    "saved": False,
}
if numpy is None:
    # Without the audit there is nothing to qualify the result against, so the
    # reduction is not attempted and no output is written.
    report["reason"] = topology.UNAVAILABLE["reason"]
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0)

index_of = {id(obj): index for index, obj in enumerate(meshes)}

# Group by datablock, not by object: several objects can point at one mesh,
# and applying a stack per object would give each of them its own copy.
groups = {}
group_order = []
for obj in meshes:
    key = id(obj.data)
    if key not in groups:
        groups[key] = []
        group_order.append(key)
    groups[key].append(obj)

for key in group_order:
    users = groups[key]
    if len(users) < 2:
        continue
    stack = [(modifier.name, modifier.type) for modifier in users[0].modifiers]
    if any(
        [(modifier.name, modifier.type) for modifier in other.modifiers] != stack
        for other in users[1:]
    ):
        raise RuntimeError(
            "Objects sharing one mesh datablock declare different modifier "
            "stacks; reduce them separately"
        )

for obj in meshes:
    obj.hide_set(False)

processed = {}
for key in group_order:
    users = groups[key]
    owner = users[0]
    # Every other user gets a throwaway datablock first, so applying the
    # stack below sees a datablock only `owner` holds and edits it in place
    # instead of `apply_modifier`'s own users>1 guard silently copying it.
    detached = []
    for sibling in users[1:]:
        placeholder = bpy.data.meshes.new(sibling.data.name + ".StudioPlaceholder")
        detached.append((sibling, placeholder))
        sibling.data = placeholder
    applied = apply_existing_stack(owner)
    before = measure(owner, numpy)
    weld = owner.modifiers.new(name="StudioWeld", type="WELD")
    weld.merge_threshold = WELD_DISTANCE
    apply_modifier(owner, weld)
    current = triangles(owner.data)
    collapse = 1.0
    decimated = False
    if current > target:
        collapse = target / current
        decimate = owner.modifiers.new(name="StudioDecimate", type="DECIMATE")
        decimate.decimate_type = "COLLAPSE"
        decimate.use_collapse_triangulate = True
        decimate.ratio = collapse
        apply_modifier(owner, decimate)
        decimated = True
    for sibling, placeholder in detached:
        # The other users point at the one processed result, so a stack
        # applied once still leaves every one of them a linked instance. The
        # stack is now baked into that datablock, so a sibling keeping its own
        # copy of the same modifiers would evaluate it a second time.
        sibling.data = owner.data
        bpy.data.meshes.remove(placeholder)
        for name in applied:
            sibling.modifiers.remove(sibling.modifiers[name])
    processed[key] = {
        "applied": applied,
        "before": before,
        "welded_triangles": current,
        "collapse_ratio": collapse,
        "decimated": decimated,
    }

entries = {}
for key in group_order:
    result = processed[key]
    for obj in groups[key]:
        index = index_of[id(obj)]
        entries[index] = {
            **identify(obj, index),
            "applied_modifiers": result["applied"],
            "before": result["before"],
            "welded_triangles": result["welded_triangles"],
            "collapse_ratio": result["collapse_ratio"],
            "decimated": result["decimated"],
            "after": measure(obj, numpy),
        }
report["objects"] = [entries[index] for index in range(len(meshes))]
report["shared_datablocks"] = sum(1 for key in group_order if len(groups[key]) > 1)
report["datablock_user_counts"] = [len(groups[key]) for key in group_order]

report["before"] = topology.totals([o["before"] for o in report["objects"]])
report["after"] = topology.totals([o["after"] for o in report["objects"]])
# What the saved mesh actually holds, not what Decimate was asked for.
report["ratio"] = (
    report["after"]["triangles"] / report["before"]["triangles"]
    if report["before"]["triangles"]
    else None
)
# The scene link above was only so modifier_apply had a view layer to work
# through; the receipt already holds everything measured about these
# objects, so only the scene membership it added needs to be undone.
for obj in temporarily_linked:
    scene_collection.objects.unlink(obj)
report["temporarily_linked_objects"] = len(temporarily_linked)
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(output))
report["saved"] = output.is_file()
audit_path.parent.mkdir(parents=True, exist_ok=True)
audit_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
