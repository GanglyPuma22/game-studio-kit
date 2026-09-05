"""Run only inside Blender: original two-bone harbor bell and named NLA clips."""

import bpy
import json
import math
from mathutils import Vector
from pathlib import Path
import sys

out = Path(sys.argv[sys.argv.index("--") + 1])
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1
scene.render.fps = 24
asset = bpy.data.collections.new("HarborBell")
scene.collection.children.link(asset)


def move(obj):
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    asset.objects.link(obj)
    return obj


def material(name, color, roughness):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1)
    node.inputs["Roughness"].default_value = roughness
    return mat


shell = material("Ochre ceramic", (0.7, 0.32, 0.12), 0.8)
leaf = material("Sea glass", (0.08, 0.5, 0.4), 0.55)
ivory = material("Ivory ribs", (0.9, 0.85, 0.66), 0.8)
arm_data = bpy.data.armatures.new("HarborBellRig")
rig = bpy.data.objects.new("HarborBellRig", arm_data)
asset.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
root = arm_data.edit_bones.new("Root")
root.head = (0, 0, 0)
root.tail = (0, 0, 0.5)
tip = arm_data.edit_bones.new("Frond")
tip.head = (0, 0, 0.5)
tip.tail = (0, 0, 1.5)
tip.parent = root
tip.use_connect = True
bpy.ops.object.mode_set(mode="OBJECT")
rig.show_in_front = True


def bind(obj, weight):
    obj.parent = rig
    groups = {name: obj.vertex_groups.new(name=name) for name in ("Root", "Frond")}
    for v in obj.data.vertices:
        w = max(0, min(1, weight(v)))
        if w < 1:
            groups["Root"].add([v.index], 1 - w, "REPLACE")
        if w > 0:
            groups["Frond"].add([v.index], w, "REPLACE")
    modifier = obj.modifiers.new("Deform", "ARMATURE")
    modifier.object = rig


bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=(0, 0, 0.3))
body = move(bpy.context.object)
body.name = "BellBody"
body.scale = (0.52, 0.42, 0.3)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
body.data.materials.append(shell)
bind(body, lambda v: 0)
verts = []
faces = []
rings = 9
segments = 12
for row in range(rings):
    z = 0.35 + row / (rings - 1) * 1.15
    radius = 0.13 + 0.1 * math.sin(math.pi * row / (rings - 1))
    for col in range(segments):
        angle = 2 * math.pi * col / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), z))
for row in range(rings - 1):
    for col in range(segments):
        a = row * segments + col
        b = row * segments + (col + 1) % segments
        faces.append((a, b, b + segments, a + segments))
faces.append(tuple(reversed(range(segments))))
faces.append(tuple((rings - 1) * segments + i for i in range(segments)))
mesh = bpy.data.meshes.new("FrondMesh")
mesh.from_pydata(verts, [], faces)
mesh.update()
frond = bpy.data.objects.new("FlexibleFrond", mesh)
asset.objects.link(frond)
frond.data.materials.append(leaf)
bind(frond, lambda v: (v.co.z - 0.35) / 0.8)
for x in (-0.35, 0.35):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=12, ring_count=8, location=(x, -0.32, 0.14)
    )
    foot = move(bpy.context.object)
    foot.name = "Foot"
    foot.scale = (0.18, 0.2, 0.14)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    foot.data.materials.append(ivory)
    bind(foot, lambda v: 0)
for obj in asset.objects:
    if obj.type == "MESH":
        for poly in obj.data.polygons:
            poly.use_smooth = True

rig.animation_data_create()
for name, end, amplitude in [("idle", 49, 0.12), ("response", 25, 0.65)]:
    action = bpy.data.actions.new(name)
    rig.animation_data.action = action
    bone = rig.pose.bones["Frond"]
    bone.rotation_mode = "XYZ"
    for frame in range(1, end + 1):
        t = (frame - 1) / (end - 1)
        angle = (
            amplitude * math.sin(2 * math.pi * t)
            if name == "idle"
            else amplitude * math.sin(math.pi * t) ** 2
        )
        bone.rotation_euler = (
            angle,
            0,
            0.08 * math.sin(2 * math.pi * t) if name == "idle" else 0,
        )
        bone.keyframe_insert(data_path="rotation_euler", frame=frame, group="Frond")
    track = rig.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 1, action)
    strip.name = name
    # NLA tracks export as separate clips; do not blend idle and response together at rest.
    track.mute = True
rig.animation_data.action = None
rig.pose.bones["Frond"].rotation_euler = (0, 0, 0)
scene.frame_set(1)
scene.frame_start = 1
scene.frame_end = 49
# Cameras/lights remain outside the runtime collection.
bpy.ops.object.camera_add(location=(3, -4, 2.8))
camera = bpy.context.object
camera.name = "ReviewCamera"
camera.rotation_euler = (
    (Vector((0, 0, 0.75)) - camera.location).to_track_quat("-Z", "Y").to_euler()
)
camera.data.lens = 50
scene.camera = camera
bpy.ops.object.light_add(type="AREA", location=(2, -3, 4))
bpy.context.object.data.energy = 450
bpy.context.object.data.shape = "DISK"
bpy.context.object.data.size = 4
scene.world = bpy.data.worlds.new("ReviewWorld")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (
    0.18,
    0.23,
    0.28,
    1,
)
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 640
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "Standard"
bpy.ops.wm.save_as_mainfile(filepath=str(out / "harbor-bell.blend"))
# Explicit collection selection retains every weighted mesh and its armature.
bpy.ops.object.select_all(action="DESELECT")
for obj in asset.all_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = rig
for track in rig.animation_data.nla_tracks:
    track.mute = False
bpy.ops.export_scene.gltf(
    filepath=str(out / "harbor-bell.glb"),
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="NLA_TRACKS",
    export_skins=True,
    export_materials="EXPORT",
    export_yup=True,
)
for track in rig.animation_data.nla_tracks:
    track.mute = True
samples = []
for clip, frames in [("idle", [1, 13, 25, 37, 49]), ("response", [1, 7, 13, 19, 25])]:
    rig.animation_data.action = bpy.data.actions[clip]
    for frame in frames:
        scene.frame_set(frame)
        name = f"{clip}-{frame:03d}.png"
        scene.render.filepath = str(out / name)
        bpy.ops.render.render(write_still=True)
        samples.append(name)
rig.animation_data.action = None
rig.pose.bones["Frond"].rotation_euler = (0, 0, 0)
scene.frame_set(1)
(out / "source-inspection.json").write_text(
    json.dumps(
        {
            "blender_version": bpy.app.version_string,
            "collection": "HarborBell",
            "mesh_count": 4,
            "bone_names": ["Root", "Frond"],
            "clips": [
                {
                    "name": "idle",
                    "duration_seconds": 2,
                    "sample_rate": 24,
                    "loop": True,
                    "root_motion": "in_place",
                },
                {
                    "name": "response",
                    "duration_seconds": 1,
                    "sample_rate": 24,
                    "loop": False,
                    "root_motion": "in_place",
                },
            ],
            "renders": samples,
            "stress_pose": "response-013.png",
            "rest_pose": "response-001.png",
            "render_engine": scene.render.engine,
        },
        indent=2,
    )
)
