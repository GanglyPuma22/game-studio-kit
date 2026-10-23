"""Optional raw UniMate source bake, run by an explicit project-owned wrapper.

Use the existing `studio blender run`; this script does not launch another app,
install dependencies, generate motion, select a take or qualify gameplay.
"""
import bpy
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
from mathutils import Matrix
from studio_tools.adapters import unimate_motion as motion
from studio_tools.common import digest


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def bound(root, record):
    path = (root / record["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or sha(path) != record["sha256"]:
        raise RuntimeError("Bake input missing, changed or outside experiment: " + record["path"])
    return path


def record(root, path):
    return {"path": path.relative_to(root).as_posix(), "sha256": sha(path)}


def matrix(value):
    return [list(row) for row in value]


def curves(action):
    # Native 4.4+ layered Action API; no global RNA compatibility monkeypatch.
    return [curve for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for curve in bag.fcurves]


def action_signature(action):
    return digest({"slots": [slot.identifier for slot in action.slots],
                   "curves": [{"path": c.data_path, "index": c.array_index,
                                "keys": [{"co": list(k.co), "left": list(k.handle_left),
                                          "right": list(k.handle_right), "interpolation": k.interpolation,
                                          "left_type": k.handle_left_type, "right_type": k.handle_right_type}
                                         for k in c.keyframe_points],
                                "modifiers": [m.type for m in c.modifiers]} for c in curves(action)]})


def nla_signature(arm):
    data = arm.animation_data
    return {"active_action": data.action.name if data and data.action else None,
            "active_slot": getattr(data.action_slot,"identifier",None) if data else None,
            "use_nla": data.use_nla if data else None,
            "action_blend_type": data.action_blend_type if data else None,
            "action_influence": data.action_influence if data else None,
            "tracks": [{"name": t.name, "mute": t.mute, "solo": t.is_solo,
                        "strips": [{"name": s.name, "action": s.action.name if s.action else None,
                                    "slot": getattr(s.action_slot,"identifier",None),
                                    "start": s.frame_start, "end": s.frame_end,
                                    "action_start": s.action_frame_start, "action_end": s.action_frame_end,
                                    "scale": s.scale, "repeat": s.repeat, "influence": s.influence,
                                    "blend": s.blend_type, "extrapolation": s.extrapolation}
                                   for s in t.strips]} for t in data.nla_tracks] if data else []}


def material_signature(material):
    nodes, links = [], []
    if material and material.use_nodes:
        for node in material.node_tree.nodes:
            inputs = []
            for socket in node.inputs:
                value = getattr(socket, "default_value", None)
                if value is not None and not isinstance(value, (str, bool, int, float)):
                    value = list(value) if hasattr(value, "__len__") else getattr(value, "name", None)
                inputs.append([socket.identifier, value])
            nodes.append([node.name, node.bl_idname, inputs])
        links = sorted([link.from_node.name, link.from_socket.identifier,
                        link.to_node.name, link.to_socket.identifier] for link in material.node_tree.links)
    return {"name": material.name if material else None, "nodes": nodes, "links": links}


def snapshot(arm, mesh):
    return {"bones": {b.name: {"parent": b.parent.name if b.parent else None,
                               "rest": matrix(b.matrix_local), "deform": b.use_deform,
                               "inherit_scale": b.inherit_scale, "inherit_rotation": b.use_inherit_rotation,
                               "local_location": b.use_local_location} for b in arm.data.bones},
            "armature_world": matrix(arm.matrix_world), "mesh_world": matrix(mesh.matrix_world),
            "mesh_geometry_skin_materials": digest({
                "vertices": [list(v.co) for v in mesh.data.vertices],
                "polygons": [[list(p.vertices), p.material_index] for p in mesh.data.polygons],
                "groups": [g.name for g in mesh.vertex_groups],
                "weights": [[(g.group, g.weight) for g in v.groups] for v in mesh.data.vertices],
                "uv": [[list(v.uv) for v in layer.data] for layer in mesh.data.uv_layers],
                "materials": [material_signature(m) for m in mesh.data.materials],
                "modifiers": [{"name": m.name, "type": m.type, "object": m.object.name,
                               "preserve_volume": m.use_deform_preserve_volume,
                               "vertex_groups": m.use_vertex_groups,
                               "envelopes": m.use_bone_envelopes} for m in mesh.modifiers]}),
            "rotation_modes": {p.name: p.rotation_mode for p in arm.pose.bones},
            "authored_actions": {a.name: action_signature(a) for a in bpy.data.actions},
            "nla": nla_signature(arm), "fps": bpy.context.scene.render.fps,
            "fps_base": bpy.context.scene.render.fps_base,
            "range": [bpy.context.scene.frame_start, bpy.context.scene.frame_end]}


def rig_objects(rig):
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise RuntimeError("Bake profile needs exactly one original armature")
    arm = arms[0]
    expected = {j["name"]: j["parent"] for j in rig["source_joints"]}
    if {b.name: b.parent.name if b.parent else None for b in arm.data.bones} != expected:
        raise RuntimeError("Opened source hierarchy differs from original source names/parents")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"
              and any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]
    if len(meshes) != 1:
        raise RuntimeError("This bounded bake profile supports one weighted mesh")
    mesh = meshes[0]
    if (arm.constraints or any(p.constraints for p in arm.pose.bones)
            or (arm.animation_data and arm.animation_data.drivers)
            or mesh.data.shape_keys or len(mesh.modifiers) != 1):
        raise RuntimeError("Constraints, drivers, shape keys or extra modifiers need a separate authoring route")
    if any(b.inherit_scale != "FULL" or not b.use_inherit_rotation or not b.use_local_location
           for b in arm.data.bones):
        raise RuntimeError("This bake profile has not qualified alternative bone inheritance settings")
    return arm, mesh


def load_job(root, recipe):
    if recipe.get("schema_version") != 1 or recipe.get("kind") != "unimate_source_bake":
        raise RuntimeError("Expected explicit source bake recipe")
    kit = Path(__file__).resolve().parents[2]
    for relative, expected in recipe["implementation"].items():
        if relative not in {"studio_tools/blender_scripts/unimate_bake.py", "studio_tools/adapters/unimate_motion.py"}:
            raise RuntimeError("Unexpected bake implementation pin")
        if sha(kit / relative) != expected:
            raise RuntimeError("Bake implementation differs from pinned recipe")
    if len(recipe["implementation"]) != 2:
        raise RuntimeError("Pin both bake script and frame math")
    task = read(bound(root, recipe["worker_record"]))
    export = read(bound(root, recipe["worker_export"]))
    if (not task.get("ok") or task.get("status") != "completed"
            or task["request_digest"] != digest(task["request"])
            or export["request_digest"] != task["request_digest"]
            or task["cleanup"]["status"] != "ok" or task["cleanup"]["pids"] or task["cleanup"]["unverified"]):
        raise RuntimeError("Bake requires completed request-bound worker evidence and verified cleanup")
    result = read(bound(root, task["result"]))
    if result["export"] != recipe["worker_export"] or result["clips"] != export["clips"]:
        raise RuntimeError("Bake export is not the completed worker result")
    rig = read(bound(root, task["request"]["rig_manifest"]))
    if rig != export["rig"]:
        raise RuntimeError("Bake rig differs from worker rig")
    clips = [c for c in export["clips"] if c["sample_id"] == recipe["sample_id"]]
    if len(clips) != 1:
        raise RuntimeError("Choose exactly one request-bound sample")
    clip = clips[0]
    if clip["root_motion"] != "raw_preserved" or clip["presentation_compensation"] != "none":
        raise RuntimeError("This bridge preserves raw trajectory only; presentation compensation is separate")
    for item in task["outputs"]:
        bound(root, item)
    return task, export, rig, clip


def world_poses(root, rig, clip, arm, condition_object):
    with np.load(bound(root, clip["decoded"]), allow_pickle=False) as data:
        names, parents = data["joint_names"].tolist(), data["parents"].tolist()
        positions, rotations, C = data["positions"].copy(), data["rotations"].copy(), data["C"].tolist()
        offsets, scale = data["offsets"].copy(), float(data["scale_factor"])
    if names != [j["name"] for j in rig["joints"]] or C != rig["canonical_from_source"]:
        raise RuntimeError("Decoded joint identities or source transform differs")
    expected_parents = [-1 if j["parent"] is None else names.index(j["parent"]) for j in rig["joints"]]
    if parents != expected_parents or positions.shape != (60,len(names),3) or rotations.shape != (60,len(names),4):
        raise RuntimeError("Decoded hierarchy/frame shape differs")
    if not np.isfinite(positions).all() or not np.isfinite(rotations).all():
        raise RuntimeError("Decoded frames are nonfinite")
    c = np.load(bound(root, rig["condition"]), allow_pickle=True).item()[condition_object]
    if scale != float(c["scale_factor"]) or not np.allclose(offsets,c["tpos_offsets"],atol=1e-6,rtol=1e-6):
        raise RuntimeError("Decoded scale/rest offsets differ from condition")
    if abs(motion._similarity(C)[0]-scale)/scale > 1e-6:
        raise RuntimeError("Canonical source scale differs from conditioning normalization")
    mapping = {name:None if parent == -1 else names[parent] for name,parent in zip(names,parents)}
    D0 = motion.joint_globals({name:motion.rigid(position=offsets[i].tolist()) for i,name in enumerate(names)},mapping)
    if not np.allclose([D0[n][i][3] for n in names for i in range(3)],c["tpos_first_frame"].ravel(),atol=1e-6,rtol=1e-6):
        raise RuntimeError("Identity-delta rest does not reconstruct canonical condition heads")
    with np.load(bound(root,rig["source_rest"]),allow_pickle=False) as capture:
        capture_names = capture["names"].tolist()
        B0 = {name:capture["rest_world_bones"][i].tolist() for i,name in enumerate(capture_names)}
    for name,rest in B0.items():
        actual = matrix(arm.matrix_world @ arm.data.bones[name].matrix_local)
        if not np.allclose(actual,rest,atol=1e-6,rtol=0):
            raise RuntimeError("Captured source rest differs from opened source: " + name)
    alignment = motion.source_calibration(D0,B0,C)
    names14 = [b.name for b in arm.data.bones]
    rest_reconstructed = motion.calibrated_source(D0,C,alignment)
    rest_error = max(abs(rest_reconstructed[n][i][j]-B0[n][i][j]) for n in B0 for i in range(4) for j in range(4))
    poses = []
    for p,q in zip(positions,rotations):
        all18 = motion.joint_globals({name:motion.quaternion_frame(q[i].tolist(),p[i].tolist()) for i,name in enumerate(names)},mapping)
        converted14 = motion.calibrated_source(all18,C,alignment)
        poses.append([converted14[n] for n in names14])
    return names14,np.asarray(poses),np.asarray([B0[n] for n in names14]),rest_error,C


def bind_action(arm, action):
    arm.animation_data_create()
    arm.animation_data.action = action
    if action:
        arm.animation_data.action_slot = action.slots[0]


def frame(scene, value):
    base = math.floor(value)
    scene.frame_set(base, subframe=value-base)
    bpy.context.view_layer.update()


def evaluated_mesh(mesh):
    evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    try:
        return np.array([evaluated.matrix_world @ v.co for v in data.vertices],dtype=np.float64)
    finally:
        evaluated.to_mesh_clear()


def build_action(arm,names,poses,action_name,fps):
    if bpy.data.actions.get(action_name):
        raise RuntimeError("Generated action already exists; use a fresh bake")
    action = bpy.data.actions.new(action_name)
    action.slots.new(id_type="OBJECT",name=arm.name)
    bind_action(arm,action)
    inv_arm = arm.matrix_world.inverted()
    previous = {}
    for index,world in enumerate(poses):
        target = {name:inv_arm @ Matrix(pose.tolist()) for name,pose in zip(names,world)}
        for name in names:
            pb = arm.pose.bones[name]
            kwargs = {"parent_matrix":target[pb.parent.name],"parent_matrix_local":pb.parent.bone.matrix_local} if pb.parent else {}
            basis = pb.bone.convert_local_to_pose(target[name],pb.bone.matrix_local,invert=True,**kwargs)
            location,rotation,scale = basis.decompose()
            if max(abs(v-1) for v in scale) > 1e-5:
                raise RuntimeError("Pose solve unexpectedly generated nonunit scale")
            pb.location, pb.scale = location,scale
            if pb.rotation_mode == "QUATERNION":
                if name in previous and rotation.dot(previous[name]) < 0:
                    rotation.negate()
                pb.rotation_quaternion = rotation
                previous[name] = rotation.copy()
                channel = "rotation_quaternion"
            elif pb.rotation_mode == "AXIS_ANGLE":
                axis, angle = rotation.to_axis_angle()
                pb.rotation_axis_angle = [angle,*axis]
                channel = "rotation_axis_angle"
            else:
                euler = rotation.to_euler(pb.rotation_mode,previous.get(name,pb.rotation_euler))
                pb.rotation_euler = euler
                previous[name] = euler.copy()
                channel = "rotation_euler"
            time = index * fps / 30
            for attribute in ("location",channel,"scale"):
                pb.keyframe_insert(data_path=attribute,frame=time,group=name)
    for curve in curves(action):
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"
    return action


def sample_action(arm,mesh,action,names,times):
    bind_action(arm,action)
    worlds,vertices = [],[]
    for time in times:
        frame(bpy.context.scene,time)
        worlds.append([matrix(arm.matrix_world @ arm.pose.bones[n].matrix) for n in names])
        vertices.append(evaluated_mesh(mesh))
    return np.asarray(worlds),np.asarray(vertices)


def bake(root,recipe,task,export,rig,clip):
    if Path(bpy.data.filepath).resolve() != bound(root,rig["source"]):
        raise RuntimeError("Opened source is not the request's original source")
    destination = (root/recipe["output"]).resolve()
    if not destination.is_relative_to(root) or destination.exists():
        raise RuntimeError("Bake requires a fresh directory inside the experiment")
    destination.mkdir(parents=True)
    arm,mesh = rig_objects(rig)
    before = snapshot(arm,mesh)
    old_frame = bpy.context.scene.frame_current + bpy.context.scene.frame_subframe
    old_action = arm.animation_data.action if arm.animation_data else None
    old_pose = {p.name:p.matrix_basis.copy() for p in arm.pose.bones}
    source_fps = before["fps"]/before["fps_base"]
    condition_object = task["request"]["conditioning"]["object_type"]
    names,poses,rest,rest_error,C = world_poses(root,rig,clip,arm,condition_object)
    # Reference control is independent, full-DOF authored source evidence. Its
    # pose and vertex samples are not substituted into the generated action.
    gold = np.load(bound(root,recipe["authored_control"]),allow_pickle=False)
    gold_names = gold["names"].tolist()
    gold_order = [gold_names.index(n) for n in names]
    control_world = gold["world_bones"][:60,gold_order].astype(float)
    calibration_local = {n:motion.rigid(position=offset.tolist()) for n,offset in zip(
        [j["name"] for j in rig["joints"]],np.load(bound(root,rig["condition"]),allow_pickle=True).item()[condition_object]["tpos_offsets"])}
    parents18 = {j["name"]:j["parent"] for j in rig["joints"]}
    D0 = motion.joint_globals(calibration_local,parents18)
    alignment = motion.source_calibration(D0,{n:r.tolist() for n,r in zip(names,rest)},C)
    # Express known authored poses in the delta coordinate frame independently:
    # source basis inverse, then explicit forward C; verify through the bridge.
    s,R = motion._similarity(C)
    control_canonical = []
    for known in control_world:
        canonical = {}
        for n,B in zip(names,known):
            # Captured bases retain float32 precision; invert their exact
            # affine values here rather than normalizing original bone rolls.
            unaligned = B @ np.linalg.inv(np.asarray(alignment[n]))
            canonical[n] = motion.rigid((np.asarray(R)@unaligned[:3,:3]).tolist(),
                (np.asarray(C)[:3,:3]@unaligned[:3,3]+np.asarray(C)[:3,3]).tolist())
        # Helpers are irrelevant to the authored original14 control; full18
        # recovery for the actual generated output already precedes projection.
        control_canonical.append([motion.calibrated_source(canonical,C,alignment)[n] for n in names])
    control_action = build_action(arm,names,np.asarray(control_canonical),"__unimate_authored_control",source_fps)
    control_actual,control_vertices = sample_action(arm,mesh,control_action,names,np.arange(60)*source_fps/30)
    control_pose_error = float(np.max(np.abs(control_actual-control_world)))
    control_mesh_error = float(np.max(np.linalg.norm(control_vertices-gold["vertices"][:60],axis=-1)))
    if control_pose_error > 1e-5 or control_mesh_error > 1e-5:
        raise RuntimeError("Authored source/control pose or mesh reconstruction failed")
    print(json.dumps({"stage":"authored_control","pose_max_error":control_pose_error,
                      "mesh_max_error_m":control_mesh_error}),flush=True)
    bind_action(arm,None)
    bpy.data.actions.remove(control_action)
    generated = build_action(arm,names,poses,recipe["clip_name"],source_fps)
    actual,vertices = sample_action(arm,mesh,generated,names,np.arange(60)*source_fps/30)
    pose_error = float(np.max(np.abs(actual-poses)))
    if pose_error > 1e-5:
        raise RuntimeError("Generated source-world reconstruction failed")
    # Store authored playback expectations separately at known times; these
    # are quality-neutral references for preservation through GLB roundtrip.
    authored = {}
    for name in before["authored_actions"]:
        action = bpy.data.actions[name]
        # An authored clip may omit channels. Evaluate it from the original
        # source pose, never from leftovers of the generated/control action.
        for bone_name,basis in old_pose.items():
            arm.pose.bones[bone_name].matrix_basis = basis
        start,end = action.frame_range
        seconds = np.linspace(0,(end-start)/source_fps,5)
        worlds,_ = sample_action(arm,mesh,action,names,start+seconds*source_fps)
        authored[name] = {"seconds":seconds.tolist(),"worlds":worlds.tolist()}
    bind_action(arm,old_action)
    frame(bpy.context.scene,old_frame)
    for name,basis in old_pose.items():
        arm.pose.bones[name].matrix_basis = basis
    after = snapshot(arm,mesh)
    after["authored_actions"].pop(generated.name)
    if before != after:
        raise RuntimeError("Bake changed original structure, material, authored action or evaluation metadata")
    track = arm.animation_data.nla_tracks.new()
    track.name = generated.name
    strip = track.strips.new(generated.name,0,generated)
    strip.action_slot = generated.slots[0]
    track.mute = True
    blend = destination/"Kite-original14-raw.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend),copy=True)
    mesh_rest = np.array([mesh.matrix_world@v.co for v in mesh.data.vertices],dtype=np.float64)
    weights = np.zeros((len(mesh.data.vertices),len(names)))
    for v in mesh.data.vertices:
        for g in v.groups:
            group = mesh.vertex_groups[g.group].name
            if group in names:
                weights[v.index,names.index(group)] = g.weight
    if np.max(np.sum(weights > 0,axis=1)) > 4:
        raise RuntimeError("Original skin needs more than four influences; this export profile is not qualified")
    np.savez_compressed(destination/"expected-source.npz",names=np.array(names),worlds=poses,rest=rest,
                        vertices=vertices,rest_vertices=mesh_rest,weights=weights,
                        seconds=np.arange(60)/30)
    write(destination/"source-preservation.json",{"before":before,"authored":authored,
          "rest_reconstruction_max_error":rest_error,"generated_pose_max_error":pose_error,
          "authored_control_pose_max_error":control_pose_error,"authored_control_mesh_max_error_m":control_mesh_error,
          "source_fps":source_fps,"sample_rate":30,"control_is_full_dof_authored_reference":True})
    # Export-only copies move every clip's first key to zero and rescale frames
    # to30Hz, preserving seconds. The saved original24fps actions/NLA are intact.
    bind_action(arm,None)
    for t in list(arm.animation_data.nla_tracks):
        arm.animation_data.nla_tracks.remove(t)
    bpy.context.scene.render.fps=30
    bpy.context.scene.render.fps_base=1
    clip_names = [*before["authored_actions"],generated.name]
    for name in clip_names:
        action = bpy.data.actions[name].copy()
        start,end = action.frame_range
        duration = (end-start)/source_fps*30
        for curve in curves(action):
            for key in curve.keyframe_points:
                for co in (key.co,key.handle_left,key.handle_right):
                    co.x = (co.x-start)/source_fps*30
        t = arm.animation_data.nla_tracks.new(); t.name=name
        staged = t.strips.new(name,0,action)
        staged.action_slot=action.slots[0]
        staged.action_frame_start=0; staged.action_frame_end=duration
        staged.frame_start=0; staged.frame_end=duration
        staged.blend_type="REPLACE"; staged.influence=1
    bpy.ops.object.select_all(action="DESELECT")
    for obj in (arm,mesh):
        obj.hide_set(False); obj.select_set(True)
    bpy.context.view_layer.objects.active=arm
    glb = destination/"Kite-original14-raw.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb),export_format="GLB",use_selection=True,
        export_animation_mode="NLA_TRACKS",export_force_sampling=True,export_frame_range=False,
        export_rest_position_armature=True,export_skins=True,export_materials="EXPORT",export_yup=True)
    if sha(bound(root,rig["source"])) != rig["source"]["sha256"]:
        raise RuntimeError("Original source changed during bake")
    write(destination/"bake.json",{"schema_version":1,"kind":"unimate_source_bake","ok":True,
          "recipe_digest":digest(recipe),"worker_record":recipe["worker_record"],"worker_export":recipe["worker_export"],
          "request_digest":task["request_digest"],"source":rig["source"],"decoded":clip["decoded"],
          "implementation":recipe["implementation"],"blend":record(root,blend),"glb":record(root,glb),
          "expectations":record(root,destination/"expected-source.npz"),
          "source_preservation":record(root,destination/"source-preservation.json"),
          "raw_root_preserved":True,"presentation_compensation":"none","authored_channels_injected":False,
          "export_sample_rate":30,"saved_source_fps":source_fps,"clip_names":clip_names,
          "unsupported_rotation_joints":export["capabilities"]["unsupported_rotation_joints"],
          "production_acceptance":"pending","loop_validation":"unverified","qualified_in_game":False})


def main():
    args = sys.argv[sys.argv.index("--")+1:]
    root = Path.cwd().resolve()
    recipe = read((root/args[0]).resolve())
    task,export,rig,clip = load_job(root,recipe)
    bake(root,recipe,task,export,rig,clip)


if __name__ == "__main__":
    main()
