"""Fresh-process saved-source and GLB verification for the optional raw bake."""
import itertools
import json
import math
from pathlib import Path
import struct
import sys
import bpy
import numpy as np
from studio_tools.blender_scripts import unimate_bake as bake
from studio_tools.adapters import unimate_motion as motion
from studio_tools.common import digest


def glb(path):
    raw = path.read_bytes()
    if raw[:4] != b"glTF" or struct.unpack_from("<II",raw,4) != (2,len(raw)):
        raise RuntimeError("Expected complete embedded GLB2")
    size,kind = struct.unpack_from("<II",raw,12)
    if kind != 0x4e4f534a:
        raise RuntimeError("Expected GLB JSON chunk")
    doc = json.loads(raw[20:20+size])
    bin_size,bin_kind = struct.unpack_from("<II",raw,20+size)
    if bin_kind != 0x004e4942 or any("uri" in b for b in doc.get("buffers",[])):
        raise RuntimeError("External buffers are outside the bake profile")
    return doc,raw[28+size:28+size+bin_size]


def accessor(doc,blob,index):
    a = doc["accessors"][index]
    if "sparse" in a:
        raise RuntimeError("Sparse accessor is outside this preservation check")
    view = doc["bufferViews"][a["bufferView"]]
    dtype = np.dtype({5120:"i1",5121:"u1",5122:"<i2",5123:"<u2",5125:"<u4",5126:"<f4"}[a["componentType"]])
    count = {"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}[a["type"]]
    return np.ndarray((a["count"],count),dtype=dtype,buffer=blob,
        offset=view.get("byteOffset",0)+a.get("byteOffset",0),
        strides=(view.get("byteStride",dtype.itemsize*count),dtype.itemsize)).copy()


def static_worlds(doc):
    nodes = doc["nodes"]
    parents = {child:parent for parent,node in enumerate(nodes) for child in node.get("children",[])}
    result = {}
    def get(index):
        if index in result:
            return result[index]
        node = nodes[index]
        if "matrix" in node:
            local = np.asarray(node["matrix"]).reshape(4,4).T
        else:
            q = node.get("rotation",[0,0,0,1])
            local = np.asarray(motion.quaternion_frame([q[3],*q[:3]],node.get("translation",[0,0,0])))
            local[:3,:3] = local[:3,:3] @ np.diag(node.get("scale",[1,1,1]))
        result[index] = get(parents[index]) @ local if index in parents else local
        return result[index]
    return {node["name"]:get(i) for i,node in enumerate(nodes) if "name" in node}


def compare_glbs(baseline_path,candidate_path,expected_names):
    base,base_blob = glb(baseline_path)
    new,new_blob = glb(candidate_path)
    if len(base["skins"]) != 1 or len(new["skins"]) != 1:
        raise RuntimeError("Expected one original skin")
    base_names = [base["nodes"][i]["name"] for i in base["skins"][0]["joints"]]
    new_names = [new["nodes"][i]["name"] for i in new["skins"][0]["joints"]]
    if set(base_names) != set(new_names) or set(new_names) != set(expected_names):
        raise RuntimeError("GLB changed original joint names")
    if base.get("materials") != new.get("materials") or base.get("textures") != new.get("textures"):
        raise RuntimeError("GLB changed portable materials/textures")
    if len(base.get("images",[])) != len(new.get("images",[])):
        raise RuntimeError("GLB changed embedded images")
    for old_image,new_image in zip(base.get("images",[]),new.get("images",[])):
        if "uri" in old_image or "uri" in new_image:
            raise RuntimeError("External images are outside the preservation profile")
        a,b = base["bufferViews"][old_image["bufferView"]],new["bufferViews"][new_image["bufferView"]]
        old_bytes = base_blob[a.get("byteOffset",0):a.get("byteOffset",0)+a["byteLength"]]
        new_bytes = new_blob[b.get("byteOffset",0):b.get("byteOffset",0)+b["byteLength"]]
        if old_bytes != new_bytes or old_image.get("mimeType") != new_image.get("mimeType"):
            raise RuntimeError("GLB changed embedded texture content")
    base_world,new_world = static_worlds(base),static_worlds(new)
    if set(base_world) != set(new_world):
        raise RuntimeError("GLB changed runtime node hierarchy")
    static_error = max(float(np.max(np.abs(base_world[name]-new_world[name]))) for name in base_world)
    if static_error > 1e-6:
        raise RuntimeError("GLB changed original runtime rest transforms")
    bind_base = accessor(base,base_blob,base["skins"][0]["inverseBindMatrices"])
    bind_new = accessor(new,new_blob,new["skins"][0]["inverseBindMatrices"])
    bind_error = max(float(np.max(np.abs(bind_base[base_names.index(n)]-bind_new[new_names.index(n)]))) for n in new_names)
    if bind_error > 1e-6:
        raise RuntimeError("GLB changed inverse bind matrices")
    if len(base["meshes"]) != len(new["meshes"]):
        raise RuntimeError("GLB changed mesh count")
    attr_errors = {}
    for old_mesh,new_mesh in zip(base["meshes"],new["meshes"]):
        if len(old_mesh["primitives"]) != len(new_mesh["primitives"]):
            raise RuntimeError("GLB changed primitives")
        for old,new_primitive in zip(old_mesh["primitives"],new_mesh["primitives"]):
            if old.get("material") != new_primitive.get("material") or set(old["attributes"]) != set(new_primitive["attributes"]):
                raise RuntimeError("GLB changed attributes or material assignments")
            if not np.array_equal(accessor(base,base_blob,old["indices"]),accessor(new,new_blob,new_primitive["indices"])):
                raise RuntimeError("GLB changed triangle indices")
            for name,old_index in old["attributes"].items():
                a,b = accessor(base,base_blob,old_index),accessor(new,new_blob,new_primitive["attributes"][name])
                if a.shape != b.shape:
                    raise RuntimeError("GLB changed geometry/skin dimensions")
                if name.startswith("JOINTS"):
                    if not np.array_equal(np.asarray(base_names)[a],np.asarray(new_names)[b]):
                        raise RuntimeError("GLB changed joint assignments")
                    error = 0
                else:
                    error = float(np.max(np.abs(a.astype(float)-b.astype(float))))
                    if error > 1e-6:
                        raise RuntimeError("GLB changed geometry/weights/UV/normals: " + name)
                attr_errors[name] = max(attr_errors.get(name,0),error)
    clips = []
    for animation in new["animations"]:
        times = [accessor(new,new_blob,sampler["input"]) for sampler in animation["samplers"]]
        clips.append({"name":animation["name"],"duration_seconds":max(float(v.max()) for v in times)-min(float(v.min()) for v in times)})
    return {"original_skin_count":1,"joint_names":new_names,"rest_transform_max_error":static_error,
            "inverse_bind_max_error":bind_error,"attribute_max_errors":attr_errors,"clips":clips}


def baseline_skin(path,names):
    """Use actual preserved runtime buffers, never invent a pruning threshold."""
    doc,blob = glb(path)
    if len(doc["meshes"]) != 1 or len(doc["meshes"][0]["primitives"]) != 1:
        raise RuntimeError("This roundtrip profile needs one original primitive")
    primitive = doc["meshes"][0]["primitives"][0]
    attributes = primitive["attributes"]
    if "JOINTS_1" in attributes:
        raise RuntimeError("Additional runtime influence sets need a separate qualified profile")
    node = next(n for n in doc["nodes"] if n.get("mesh") == 0)
    world = static_worlds(doc)[node["name"]]
    positions = accessor(doc,blob,attributes["POSITION"]).astype(float)
    yup = positions@world[:3,:3].T+world[:3,3]
    # Blender source world is Z-up; GLB world is Y-up (+Z maps to -Y).
    zup = yup[:,[0,2,1]]*np.array([1,-1,1])
    joint_names = [doc["nodes"][i]["name"] for i in doc["skins"][0]["joints"]]
    joints = accessor(doc,blob,attributes["JOINTS_0"])
    values = accessor(doc,blob,attributes["WEIGHTS_0"]).astype(float)
    weights = np.zeros((len(positions),len(names)))
    for component in range(4):
        ids = np.asarray([names.index(joint_names[j]) for j in joints[:,component]])
        np.add.at(weights,(np.arange(len(positions)),ids),values[:,component])
    return zup,weights


def verify_clip_durations(clips, expected_durations):
    """Reject duplicated/missing clips or changed source-time spans."""
    names = [clip["name"] for clip in clips]
    if (len(names) != len(expected_durations) or len(set(names)) != len(names)
            or set(names) != set(expected_durations)):
        raise RuntimeError("GLB changed unique authored/generated clip count or identity")
    for clip in clips:
        actual, expected = clip["duration_seconds"], expected_durations[clip["name"]]
        if (not math.isfinite(actual) or not math.isfinite(expected)
                or actual < 0 or expected < 0 or abs(actual-expected) > 1e-6):
            raise RuntimeError("GLB changed clip duration: " + clip["name"])


def vertex_mapping(mesh,names,source_vertices,source_weights):
    rest = np.array([mesh.matrix_world@v.co for v in mesh.data.vertices],dtype=float)
    weights = np.zeros((len(rest),len(names)))
    for v in mesh.data.vertices:
        for g in v.groups:
            name = mesh.vertex_groups[g.group].name
            if name in names:
                weights[v.index,names.index(name)] = g.weight
    if np.any(source_weights.sum(axis=1) <= 1e-12):
        raise RuntimeError("Unweighted vertices need a separate verified export policy")
    normalized = source_weights/source_weights.sum(axis=1,keepdims=True)
    buckets = {}
    cell = 1e-5
    for i,point in enumerate(source_vertices):
        buckets.setdefault(tuple(np.floor(point/cell).astype(int)),[]).append(i)
    offsets = list(itertools.product((-1,0,1),repeat=3))
    mapping = []
    for point,weight in zip(rest,weights):
        key = np.floor(point/cell).astype(int)
        candidates = [i for offset in offsets for i in buckets.get(tuple(key+offset),[])
                      if np.linalg.norm(source_vertices[i]-point) < 2e-6
                      and np.allclose(normalized[i],weight,atol=2e-6,rtol=0)]
        if not candidates:
            nearest = int(np.argmin(np.linalg.norm(source_vertices-point,axis=1)))
            print(json.dumps({"stage":"fresh_import_vertex_mapping_refusal","imported_vertex":len(mapping),
                              "point":point.tolist(),"nearest_source_vertex":nearest,
                              "rest_distance_m":float(np.linalg.norm(source_vertices[nearest]-point)),
                              "source_weights":dict(zip(names,normalized[nearest].tolist())),
                              "imported_weights":dict(zip(names,weight.tolist()))}),flush=True)
            raise RuntimeError("Fresh GLB import changed rest geometry or named skin weights")
        mapping.append(min(candidates,key=lambda i:np.linalg.norm(source_vertices[i]-point)))
    return np.asarray(mapping)


def main():
    root = Path.cwd().resolve()
    recipe_path = root/sys.argv[sys.argv.index("--")+1]
    recipe = bake.read(recipe_path)
    task,export,rig,clip = bake.load_job(root,recipe)
    folder = root/recipe["output"]
    receipt = bake.read(folder/"bake.json")
    if receipt["recipe_digest"] != digest(recipe) or Path(bpy.data.filepath).resolve() != bake.bound(root,receipt["blend"]):
        raise RuntimeError("Verify exact saved source belonging to the bake recipe")
    expected = np.load(bake.bound(root,receipt["expectations"]),allow_pickle=False)
    names = expected["names"].tolist()
    preserved = bake.read(bake.bound(root,receipt["source_preservation"]))
    arm,mesh = bake.rig_objects(rig)
    actual = bake.snapshot(arm,mesh)
    actual["authored_actions"].pop(recipe["clip_name"])
    actual["nla"]["tracks"] = [t for t in actual["nla"]["tracks"] if t["name"] != recipe["clip_name"]]
    if actual != preserved["before"]:
        raise RuntimeError("Fresh saved-source load changed original structures/actions/NLA")
    fps = bpy.context.scene.render.fps/bpy.context.scene.render.fps_base
    for track in arm.animation_data.nla_tracks:
        track.mute = True
    saved_world,saved_vertices = bake.sample_action(arm,mesh,bpy.data.actions[recipe["clip_name"]],names,expected["seconds"]*fps)
    saved_pose_error = float(np.max(np.abs(saved_world-expected["worlds"])))
    saved_mesh_error = float(np.max(np.linalg.norm(saved_vertices-expected["vertices"],axis=-1)))
    if saved_pose_error > 1e-5 or saved_mesh_error > 1e-5:
        raise RuntimeError("Fresh saved source does not reconstruct decoded source-space expectations")
    structure = compare_glbs(bake.bound(root,rig["baseline"]),bake.bound(root,receipt["glb"]),names)
    if {c["name"] for c in structure["clips"]} != set(receipt["clip_names"]):
        raise RuntimeError("GLB changed authored or generated clip identity")
    durations = {name:max(data["seconds"])-min(data["seconds"])
                 for name,data in preserved["authored"].items()}
    durations[recipe["clip_name"]] = float(expected["seconds"].max()-expected["seconds"].min())
    verify_clip_durations(structure["clips"],durations)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(bake.bound(root,receipt["glb"])))
    arm,mesh = bake.rig_objects(rig)
    for track in arm.animation_data.nla_tracks:
        track.mute = True
    # Imported bone display axes may differ. Skin-relative world transforms
    # compare motion independently of importer rolls; mesh checks are direct.
    imported_rest = np.asarray([bake.matrix(arm.matrix_world@arm.data.bones[n].matrix_local) for n in names])
    runtime_rest,runtime_weights = baseline_skin(bake.bound(root,rig["baseline"]),names)
    mapping = vertex_mapping(mesh,names,runtime_rest,runtime_weights)
    fps = bpy.context.scene.render.fps/bpy.context.scene.render.fps_base
    track_actions = {track.name:track.strips[0].action for track in arm.animation_data.nla_tracks if len(track.strips)==1}
    if set(track_actions) != set(receipt["clip_names"]):
        raise RuntimeError("Fresh GLB import lost clip tracks")
    actual_world,actual_vertices = bake.sample_action(arm,mesh,track_actions[recipe["clip_name"]],names,expected["seconds"]*fps)
    source_skin = expected["worlds"]@np.linalg.inv(expected["rest"])
    imported_skin = actual_world@np.linalg.inv(imported_rest)
    skin_error = float(np.max(np.abs(source_skin-imported_skin)))
    # Forward LBS from decoded/source-space bone matrices and the exact old
    # runtime skin. Source .blend keeps every weight; the established GLB
    # exporter may prune tiny influences, so do not silently equate the two.
    runtime_weights /= runtime_weights.sum(axis=1,keepdims=True)
    homogeneous = np.concatenate([runtime_rest,np.ones((len(runtime_rest),1))],axis=1)
    expected_runtime = np.zeros((60,len(runtime_rest),3))
    for index in range(len(names)):
        points = np.einsum('fij,vj->fvi',source_skin[:,index],homogeneous)[...,:3]
        expected_runtime += points*runtime_weights[None,:,index,None]
    mesh_error = float(np.max(np.linalg.norm(actual_vertices-expected_runtime[:,mapping],axis=-1)))
    if skin_error > 2e-5 or mesh_error > 2e-5:
        raise RuntimeError("Fresh GLB skin motion differs from decoded source-space expectations")
    authored_errors = {}
    for name,data in preserved["authored"].items():
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
        worlds,_ = bake.sample_action(arm,mesh,track_actions[name],names,np.asarray(data["seconds"])*fps)
        skin = worlds@np.linalg.inv(imported_rest)
        original = np.asarray(data["worlds"])@np.linalg.inv(expected["rest"])
        error = float(np.max(np.abs(skin-original)))
        authored_errors[name] = error
        if error > 2e-5:
            raise RuntimeError("Fresh GLB changed authored clip motion: " + name)
    report = {"schema_version":1,"kind":"unimate_source_roundtrip","ok":True,
              "recipe_digest":digest(recipe),"bake_receipt":bake.record(root,folder/"bake.json"),
              "worker_record":recipe["worker_record"],"worker_export":recipe["worker_export"],
              "request_digest":task["request_digest"],"glb":receipt["glb"],"source":rig["source"],
              "verifier_sha256":bake.sha(Path(__file__)),"blender_version":bpy.app.version_string,
              "saved_source_preserved":True,"saved_pose_max_error":saved_pose_error,"saved_mesh_max_error_m":saved_mesh_error,
              "glb_structure":structure,"fresh_import_generated_skin_max_error":skin_error,
              "fresh_import_generated_mesh_max_error_m":mesh_error,"authored_clip_skin_max_errors":authored_errors,
              "raw_root_preserved":True,"auxiliary_root_facing_composed":False,"presentation_compensation":"none",
              "loop_validation":"unverified","production_acceptance":"pending","qualified_in_game":False}
    bake.write(folder/"verification.json",report)
    print(json.dumps({"ok":True,"saved_pose_error":saved_pose_error,"fresh_import_skin_error":skin_error,"fresh_import_mesh_error_m":mesh_error}))


if __name__=="__main__":
    main()
