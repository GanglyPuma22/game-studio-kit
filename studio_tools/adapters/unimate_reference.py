"""Stdlib contracts for the optional animated-reference worker; no ML imports."""

import math
from pathlib import Path

from ..common import digest, read_json
from .unimate import MITE_NAMES, artifact, baseline_joints, fail, sample_id
from .unimate_motion import _finite, _similarity

KITE_NAMES = {"Root", "Chest", "Head", "LWingInner", "LWingOuter", "LForeGrip",
              "RWingInner", "RWingOuter", "RForeGrip", "Tail01", "Tail02", "Tail03",
              "LHindGrip", "RHindGrip"}
HELPERS = {name + "Endpoint": name for name in
           ("LWingOuter", "RWingOuter", "LHindGrip", "RHindGrip")}
PROFILES = {"mite31": MITE_NAMES, "kite14": KITE_NAMES, "kite18_endpoints": KITE_NAMES}
GENERATION = {"frames": 60, "sample_rate": 30, "batch_size": 1, "cfg_scale": 3.0,
              "solver": "dopri5", "dtype": "float32", "ema": True}
PRESENTATION = {"method": "source_rest_root_times_inverse_current_root", "space": "source_world",
                "reference": "captured_source_rest", "scope": "whole_mesh_and_normals",
                "removes": ["translation", "rotation"], "applied_to_raw": False}
WORKER_PROFILE = "unimate-reference-v2"
SOURCE_REVISION = "f7f2fec067996f206e819f0fe81b0c264f78077d"
TEXT_REVISION = "7bcac572ce56db69c1ea7c8af255c5d7c9672fc2"
CHECKPOINT_HASH = "cbcfb7a057e45f967d5964fecf6b3f83358096f1306f25831e1644a18a50eb34"
STATISTICS_HASH = "c13ecfe8317c5e7b4a04089b71817d0787494d8f3f1df66b0ac8f496842d2c89"


def joint_map(entries, names, *, rest=False):
    if (not isinstance(entries, list) or len(entries) != len(names)
            or any(not isinstance(j, dict) or not isinstance(j.get("name"), str) for j in entries)
            or {j["name"] for j in entries} != names):
        fail("RIG_UNSUPPORTED", "Joint identity differs from the declared rig profile")
    parents = {j["name"]: j.get("parent") for j in entries}
    if parents.get("Root") is not None:
        fail("RIG_UNSUPPORTED", "Rig requires one Root")
    for name in parents:
        seen, parent = {name}, parents[name]
        if name != "Root" and parent is None:
            fail("RIG_UNSUPPORTED", "Rig must be connected")
        while parent is not None:
            if not isinstance(parent, str) or parent in seen or parent not in parents:
                fail("RIG_UNSUPPORTED", "Joint parents contain a cycle or unknown joint")
            seen.add(parent)
            parent = parents[parent]
    if rest:
        if entries[0]["name"] != "Root":
            fail("RIG_UNSUPPORTED", "Condition order must begin with Root")
        order = {j["name"]: i for i, j in enumerate(entries)}
        for j in entries:
            if j["parent"] is not None and order[j["parent"]] >= order[j["name"]]:
                fail("RIG_UNSUPPORTED", "Condition order must place each parent before its child")
            for key, count in (("rest_offset", 3), ("rest_rotation", 4), ("rest_global_rotation", 4)):
                values = j.get(key)
                if not isinstance(values, list) or len(values) != count:
                    fail("RIG_UNSUPPORTED", "Declare finite condition rest offsets/quaternions")
                _finite(values, "Condition rest values must be finite and representable")
                if count == 4 and abs(math.hypot(*values) - 1) > 1e-5:
                    fail("RIG_UNSUPPORTED", "Condition rest quaternions must be normalized")
    return parents


def validate_rig(root, request, rig):
    profile = rig.get("profile")
    if profile not in PROFILES or rig.get("preparation") != "animated_reference":
        fail("RIG_UNSUPPORTED", "Use an explicit supported animated-reference rig profile")
    expected_subject = "chalk_mite" if profile == "mite31" else "kite"
    if rig.get("schema_version") != 1 or rig.get("subject") != expected_subject:
        fail("RIG_UNSUPPORTED", "Rig subject and profile disagree")
    source_names = PROFILES[profile]
    names = source_names | (set(HELPERS) if profile == "kite18_endpoints" else set())
    source = artifact(root, rig.get("source"))
    baseline = artifact(root, rig.get("baseline"))
    condition = artifact(root, rig.get("condition"))
    source_rest = artifact(root, rig.get("source_rest"))
    if (source.suffix, baseline.suffix, condition.suffix, source_rest.suffix) != (".blend", ".glb", ".npy", ".npz"):
        fail("RIG_UNSUPPORTED", "Declare original source/baseline, condition and captured source rest")
    parents = joint_map(rig.get("joints"), names, rest=True)
    source_parents = joint_map(rig.get("source_joints"), source_names)
    if source_parents != baseline_joints(baseline, source_names):
        fail("RIG_UNSUPPORTED", "Original source hierarchy differs from baseline GLB")
    if any(parents[name] != source_parents[name] for name in source_names):
        fail("RIG_UNSUPPORTED", "Condition changed original source parent relations")
    helpers = rig.get("helpers")
    if not isinstance(helpers, list) or len(helpers) != len(names - source_names):
        fail("RIG_UNSUPPORTED", "Declare every disposable helper explicitly")
    if {h.get("name") for h in helpers if isinstance(h, dict)} != names - source_names:
        fail("RIG_UNSUPPORTED", "Helper identity differs from endpoint profile")
    for h in helpers:
        if (h.get("parent") != HELPERS[h["name"]] or parents[h["name"]] != h["parent"]
                or any(h.get(k) is not False for k in ("weighted", "use_deform", "animated"))):
            fail("RIG_UNSUPPORTED", "Helpers must retain pinned parents and be unweighted/nondeforming/unanimated")
        helper_joint = next(j for j in rig["joints"] if j["name"] == h["name"])
        if math.hypot(*helper_joint["rest_offset"]) <= 1e-8:
            fail("RIG_UNSUPPORTED", "Endpoint markers require a nonzero rest offset")
    prepared = artifact(root, rig.get("prepared_baseline"))
    if prepared.suffix != ".glb" or baseline_joints(prepared, names) != parents:
        fail("RIG_UNSUPPORTED", "Prepared GLB must retain all conditioning joints")
    evidence = read_json(artifact(root, rig.get("rig_evidence")))
    if (not isinstance(evidence, dict) or evidence.get("source_names_parents_rest_preserved") is not True
            or evidence.get("mesh_skin_preserved") is not True
            or evidence.get("baseline_sha256") != rig["baseline"]["sha256"]
            or evidence.get("prepared_baseline_sha256") != rig["prepared_baseline"]["sha256"]):
        fail("RIG_UNSUPPORTED", "Bind original rest/geometry/skin preservation evidence to both GLBs")
    if rig.get("canonical_axes") != "Y_up_Z_forward":
        fail("CONDITION_INCOMPATIBLE", "Declare canonical axes")
    _similarity(rig.get("canonical_from_source"))
    cond = request.get("conditioning")
    if (not isinstance(cond, dict) or cond.get("kind") != "animated_reference"
            or not isinstance(cond.get("object_type"), str) or not cond["object_type"]
            or type(cond.get("start_frame")) is not int or cond["start_frame"] < 0):
        fail("CONDITION_INCOMPATIBLE", "Reference conditioning needs object identity and an explicit start frame")
    refs = rig.get("reference_motion_clips")
    if not isinstance(refs, list) or len(refs) != 1 or cond.get("reference") != refs[0]:
        fail("CONDITION_INCOMPATIBLE", "This worker uses one explicit hashed reference clip per rig request")
    reference = artifact(root, cond["reference"])
    if reference.suffix != ".npz" or not reference.name.startswith(cond["object_type"] + "-"):
        fail("CONDITION_INCOMPATIBLE", "Reference filename must match the dataset object key")
    captions = read_json(artifact(root, cond.get("captions")))
    if not isinstance(captions, dict) or not isinstance(captions.get(reference.stem), str):
        fail("CONDITION_INCOMPATIBLE", "Hashed captions must identify the selected reference clip")
    if not isinstance(cond.get("alignment"), str) or not cond["alignment"].strip():
        fail("CONDITION_INCOMPATIBLE", "Record source/reference sampling alignment")
    if request.get("generation") != GENERATION:
        fail("CONDITION_INCOMPATIBLE", "Only the pinned v2 60-frame/30Hz/float32/CFG3/EMA/dopri5 profile is implemented")
    roles = {"idle", "walk", "graze", "startle"} if profile == "mite31" else {"glide", "powered_flap", "bank_left", "bank_right"}
    for clip in request.get("clips", []):
        if (not isinstance(clip, dict) or clip.get("name") not in roles
                or type(clip.get("loop")) is not bool or clip.get("root_motion") != "raw_preserved"
                or clip.get("desired_runtime_root_policy") not in ("in_place", "controller_owned")
                or clip.get("presentation_compensation") not in ("none", "full_root_view_only")):
            fail("REQUEST_INVALID", "Declare raw output, desired runtime policy and separate view-only compensation")
    return names, parents


def validate_host(root, request, rig, host, files):
    if host.get("worker_profile") != WORKER_PROFILE:
        fail("DEPENDENCY_MISSING", "Choose the optional Kit reference worker profile explicitly")
    caps = host["capabilities"]
    if caps.get("conditioning_modes") != ["animated_reference"]:
        fail("CONDITION_INCOMPATIBLE", "Rest-only sampling has not been validated for this worker")
    names = {j["name"] for j in rig["joints"]}
    leaves = names - {j["parent"] for j in rig["joints"]}
    if not leaves <= set(caps["unsupported_rotation_joints"]):
        fail("CONDITION_INCOMPATIBLE", "Stock recovery cannot independently propose leaf rotations")
    if (caps.get("translation_policy") != "fixed_rest_offsets"
            or set(caps.get("unsupported_translation_joints", [])) != names - {"Root"}):
        fail("CONDITION_INCOMPATIBLE", "Disclose fixed-offset nonroot translation loss")
    runtime = host.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("text_model") != "google/flan-t5-base":
        fail("DEPENDENCY_MISSING", "Configure local Flan-T5 assets and pinned provider roots")
    for key, role in (("unimate_root", "provider_source"), ("motion_root", "motion_source"), ("text_root", "text_asset")):
        path = Path(runtime.get(key, "")).resolve()
        if not Path(runtime.get(key, "")).is_absolute() or not path.is_dir():
            fail("DEPENDENCY_MISSING", "Runtime roots must be existing absolute local directories")
        required = {p.resolve() for p in path.rglob("*") if p.is_file()
                    and (key == "text_root" or p.suffix == ".py")
                    and not any(part in (".git", "__pycache__") for part in p.relative_to(path).parts)}
        inventoried = {Path(f["path"]).resolve() for f in files.values() if f.get("role") == role}
        if not required or required != inventoried:
            fail("OFFLINE_ASSET_MISSING", "Inventory every local source/text file for " + key)
    for role in ("checkpoint", "model_config", "statistics", "dependency_lock"):
        if len([f for f in files.values() if f.get("role") == role]) != 1:
            fail("DEPENDENCY_MISSING", "Choose exactly one pinned " + role)
    text = Path(runtime["text_root"])
    if (any(not (text / name).is_file() for name in
            ("config.json", "tokenizer_config.json", "special_tokens_map.json", "spiece.model"))
            or not any((text / name).is_file() for name in ("model.safetensors", "pytorch_model.bin"))):
        fail("OFFLINE_ASSET_MISSING", "Incomplete local Flan-T5 snapshot; downloads are forbidden")
    if host["provenance"].get("text_revision") != TEXT_REVISION:
        fail("IDENTITY_MISMATCH", "Pin the pilot's Flan-T5 revision explicitly")
    for role in ("encoder_config", "encoder_weights", "tokenizer"):
        paths = [Path(f["path"]).resolve() for f in files.values() if f.get("role") == role]
        if not paths or any(not p.is_relative_to(text.resolve()) for p in paths):
            fail("OFFLINE_ASSET_MISSING", "Text loader roles must identify files in the pinned local snapshot")
    normalizers = [f for f in files.values() if f.get("role") == "normalizer"]
    if len(normalizers) != 1 or read_json(Path(normalizers[0]["path"])) != {
            "profile": "identity_no_normalization", "normalize_text": False}:
        fail("CONDITION_INCOMPATIBLE", "Pin the explicit no-normalization policy file")
    checkpoint = next(f for f in files.values() if f.get("role") == "checkpoint")
    stats = next(f for f in files.values() if f.get("role") == "statistics")
    if (checkpoint["sha256"] != CHECKPOINT_HASH or stats["sha256"] != STATISTICS_HASH
            or host["provenance"]["code_revision"] != SOURCE_REVISION):
        fail("IDENTITY_MISMATCH", "Only the pilot's pinned v2 checkpoint/source profile is implemented")
    if host["provenance"]["normalizer_profile"] != "identity_no_normalization":
        fail("CONDITION_INCOMPATIBLE", "This worker has no spaCy/download normalization fallback")
    config = read_json(Path(next(f["path"] for f in files.values() if f.get("role") == "model_config")))
    if (config.get("model", {}).get("text_encoder_type") != "t5"
            or config.get("model", {}).get("text_encoder_version") != runtime["text_model"]
            or config.get("dataset", {}).get("max_motion_length") != 60
            or config.get("dataset", {}).get("feature_len") != 12
            or config.get("dataset", {}).get("topology_condition_type") != "tpos"
            or config.get("dataset", {}).get("use_dataset_stats") is not True
            or config.get("dataset", {}).get("max_joints") != 71
            or config.get("dataset", {}).get("max_depth") != 19
            or config.get("training", {}).get("diff_model") != "flow"):
        fail("CONDITION_INCOMPATIBLE", "Model config is incompatible with the reference worker")


def validate_result(root, folder, request, host, result):
    if (result.get("conditioning_digest") != digest(request["conditioning"])
            or result.get("generation_digest") != digest(request["generation"])
            or result.get("runtime_digest") != digest(host["runtime"])
            or result.get("raw_motion") != "preserved"
            or result.get("array_validation") != "worker_checked"):
        fail("OUTPUT_INVALID", "Worker omitted conditioning/profile/raw-motion validation identity")
    outputs = []
    for key in ("evidence", "export"):
        path = artifact(root, result.get(key))
        if not path.is_relative_to(folder / "output") or path.suffix != ".json":
            fail("OUTPUT_INVALID", "Evidence/export must belong to this run")
        outputs.append(result[key])
    evidence = read_json(root / result["evidence"]["path"])
    inventory = [{k: f[k] for k in ("id", "sha256", "role") if k in f}
                 for f in [host["python"], host["worker"], *host["assets"]]]
    if (not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int
            or evidence["schema_version"] != 1
            or evidence.get("request_digest") != digest(request)
            or evidence.get("worker_sha256") != host["worker"]["sha256"]
            or evidence.get("inventory") != inventory):
        fail("OUTPUT_INVALID", "Evidence schema/request/worker/inventory identity differs from this run")
    cases = evidence.get("cases")
    if not isinstance(cases, list) or len(cases) != len(request["clips"]):
        fail("OUTPUT_INVALID", "Evidence omitted the requested sample inventory")
    expected = {sample_id(c): c for c in request["clips"]}
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("sample_id"), str):
            fail("OUTPUT_INVALID", "Evidence sample inventory is malformed")
        identity = case["sample_id"]
        if identity not in expected or identity in seen:
            fail("OUTPUT_INVALID", "Evidence sample inventory is foreign or duplicated")
        seen.add(identity)
        for key in ("name", "prompt", "seed"):
            if type(case.get(key)) is not type(expected[identity][key]) or case[key] != expected[identity][key]:
                fail("OUTPUT_INVALID", "Evidence changed requested sample identity")
    export = read_json(root / result["export"]["path"])
    if (not isinstance(export, dict)
            or export.get("format") != "studio-unimate-motion-export" or export.get("schema_version") != 1
            or export.get("request_digest") != digest(request)
            or export.get("production_acceptance") != "pending"
            or export.get("raw_playback_primary") is not True
            or export.get("presentation_contract") != PRESENTATION
            or export.get("rig") != read_json(artifact(root, request["rig_manifest"]))
            or export.get("provenance") != host["provenance"]
            or export.get("capabilities") != host["capabilities"]
            or export.get("conditioning") != request["conditioning"]
            or export.get("generation") != request["generation"]
            or export.get("evidence") != result["evidence"]
            or export.get("clips") != result["clips"]):
        fail("OUTPUT_INVALID", "Viewer export identity or clip inventory differs from result")
    for clip in result["clips"]:
        expected = next(c for c in request["clips"] if sample_id(c) == sample_id(clip))
        for key in ("desired_runtime_root_policy", "presentation_compensation"):
            if clip.get(key) != expected[key]:
                fail("OUTPUT_INVALID", "Worker changed desired/view root policy")
        if (clip.get("frame_count") != 60 or clip.get("sample_rate") != 30
                or abs(clip["duration_seconds"] - 59 / 30) > 1e-8
                or clip.get("loop_validation") != "unverified"):
            fail("OUTPUT_INVALID", "Frame timing is not loop-closure evidence")
    return outputs
