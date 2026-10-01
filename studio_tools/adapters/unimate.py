"""Optional experimental worker contract. Stdlib only; no model is bundled."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import struct

from ..common import StudioError, digest, file_record, kit_identity, outside_package, read_json, relative, safe_id, sha256, write_json
from ..processes import prelaunch_baseline, run, stop_survivors
from .requests import claim
from .unimate_motion import _similarity

ROLES = {"idle": True, "walk": True, "graze": True, "startle": False}
MITE_NAMES = {"Root", "L_Mandible", "R_Mandible"} | {
    f"{side}{index:02d}_{segment}" for side in ("L", "R")
    for index in range(7) for segment in ("Upper", "Lower")
}
ASSET_ROLES = {"checkpoint", "model_config", "statistics", "encoder_weights", "encoder_config", "tokenizer", "normalizer"}
JAW_NAMES = {"L_Mandible", "R_Mandible"}
STOCK_UNSUPPORTED_ROTATIONS = JAW_NAMES | {f"{side}{index:02d}_Lower" for side in ("L", "R") for index in range(7)}
HASH = re.compile(r"[a-f0-9]{64}")
REVISION = re.compile(r"[a-f0-9]{40}")


class ProviderError(StudioError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message):
    raise ProviderError(code, message)


def sample_id(clip):
    return safe_id(clip.get("sample_id", clip.get("name")))


def artifact(root, value):
    if not isinstance(value, dict) or not HASH.fullmatch(str(value.get("sha256", ""))):
        fail("IDENTITY_MISMATCH", "Artifact needs an exact SHA-256")
    path = relative(root, value.get("path"))
    if not path.is_file() or sha256(path) != value["sha256"]:
        fail("IDENTITY_MISMATCH", "Project artifact is missing or changed")
    return path


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError()
        return parsed
    except (ValueError, AttributeError, TypeError):
        fail("REQUEST_INVALID", "Cutoff/reservation time must have an explicit UTC offset")


def baseline_joints(path, names_required=None):
    from .blender import glb_info
    glb_info(path)  # Existing structural GLB validation; does not start Blender.
    data = path.read_bytes()
    doc = json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
    names_required = MITE_NAMES if names_required is None else names_required
    if len(doc.get("skins", [])) != 1:
        fail("RIG_UNSUPPORTED", "Baseline must contain exactly one skin")
    nodes = doc["nodes"]
    joints = doc["skins"][0]["joints"]
    if (not isinstance(nodes, list) or not isinstance(joints, list) or len(joints) != len(names_required)
            or any(type(index) is not int or not 0 <= index < len(nodes) for index in joints)
            or len(set(joints)) != len(names_required) or any(not isinstance(node, dict) for node in nodes)):
        fail("RIG_UNSUPPORTED", "Baseline joint count differs from the pinned rig profile")
    parent = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            if type(child) is not int or not 0 <= child < len(nodes):
                fail("RIG_UNSUPPORTED", "Baseline child index is invalid")
            if child in parent:
                fail("RIG_UNSUPPORTED", "Baseline node has ambiguous parents")
            parent[child] = index
    names = [nodes[index].get("name") for index in joints]
    if set(names) != names_required:
        fail("RIG_UNSUPPORTED", "Baseline names differ from the pinned rig profile")
    result = {}
    for index in joints:
        ancestor, seen = parent.get(index), {index}
        while ancestor is not None and ancestor not in joints:
            if ancestor in seen:
                fail("RIG_UNSUPPORTED", "Baseline hierarchy contains a cycle")
            seen.add(ancestor)
            ancestor = parent.get(ancestor)
        result[nodes[index]["name"]] = nodes[ancestor]["name"] if ancestor is not None else None
    return result


def preflight(config, project, request):
    root = outside_package(project)
    if not root.is_dir():
        fail("REQUEST_INVALID", "UniMate requires an existing experimental project")
    if not isinstance(request, dict) or request.get("schema_version") != 1 or request.get("provider") != "unimate":
        fail("REQUEST_INVALID", "Expected UniMate request schema_version 1")
    safe_id(request.get("work_card"))
    if request.get("mode") != "text_tpos" or request.get("experimental") is not True:
        fail("CONDITION_INCOMPATIBLE", "Only explicit experimental text_tpos requests are supported")
    rig_path = artifact(root, request.get("rig_manifest"))
    rig = read_json(rig_path)
    reference_mode = "conditioning" in request
    if reference_mode:
        from .unimate_reference import validate_rig
        if not isinstance(rig, dict):
            fail("RIG_UNSUPPORTED", "Rig manifest must be an object")
        rig_names, expected = validate_rig(root, request, rig)
    elif (not isinstance(rig, dict) or rig.get("schema_version") != 1 or rig.get("subject") != "chalk_mite"
          or rig.get("preparation") != "rest_only" or rig.get("reference_motion_clips") != []):
        fail("RIG_UNSUPPORTED", "Prepare a disposable rest-only Chalk Mite condition; preserve the animated baseline")
    source = artifact(root, rig.get("source"))
    baseline = artifact(root, rig.get("baseline"))
    condition = artifact(root, rig.get("condition"))
    if source.suffix != ".blend" or baseline.suffix != ".glb" or condition.suffix != ".npy":
        fail("RIG_UNSUPPORTED", "Rig needs hashed .blend source, baseline .glb and prepared .npy condition")
    if not reference_mode:
        rig_names, expected = MITE_NAMES, baseline_joints(baseline)
        joints = rig.get("joints", [])
        if (not isinstance(joints, list) or len(joints) != 31
                or any(not isinstance(j, dict) or set(j) != {"name", "parent"} for j in joints)
                or len({j["name"] for j in joints}) != 31
                or {j["name"]: j["parent"] for j in joints} != expected):
            fail("RIG_UNSUPPORTED", "Rest-only condition must retain every baseline joint name and parent")
    if expected.get("Root") is not None or any(name != "Root" and parent is None for name, parent in expected.items()):
        fail("RIG_UNSUPPORTED", "Rig needs one Root and a connected hierarchy")
    for name in expected:
        seen, parent = {name}, expected[name]
        while parent is not None:
            if parent in seen or parent not in expected:
                fail("RIG_UNSUPPORTED", "Rig hierarchy contains a cycle or missing parent")
            seen.add(parent)
            parent = expected[parent]
    _similarity(rig.get("canonical_from_source"))
    if rig.get("canonical_axes") != "Y_up_Z_forward":
        fail("CONDITION_INCOMPATIBLE", "Declare Y_up_Z_forward canonical axes")
    clips = request.get("clips")
    if not isinstance(clips, list) or not 1 <= len(clips) <= 8:
        fail("REQUEST_INVALID", "Declare one to eight named samples")
    names = set()
    for clip in clips:
        if not isinstance(clip, dict):
            fail("REQUEST_INVALID", "Clip must be an object")
        name = clip.get("name")
        identity = sample_id(clip)
        if (not reference_mode and name not in ROLES) or identity in names:
            fail("REQUEST_INVALID", "Use supported roles and distinct sample IDs")
        names.add(identity)
        if (not isinstance(clip.get("prompt"), str) or not clip["prompt"].strip()
                or type(clip.get("seed")) is not int or not 0 <= clip["seed"] < 2**32
                or (not reference_mode and (clip.get("loop") is not ROLES[name] or clip.get("root_motion") != "in_place"))):
            fail("REQUEST_INVALID", "Clip needs text, uint32 seed and its declared motion policy")
    limits = request.get("limits", {})
    if not isinstance(limits, dict):
        fail("REQUEST_INVALID", "Limits must be an object")
    timeout = limits.get("timeout_seconds")
    if (limits.get("batch_size") != 1 or limits.get("maximum_attempts") != 1
            or type(limits.get("maximum_samples")) is not int
            or not len(clips) <= limits["maximum_samples"] <= 8
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600):
        fail("REQUEST_INVALID", "Foundation needs batch 1, one attempt and a bounded 1-3600 second timeout")
    execution = request.get("execution", {})
    if not isinstance(execution, dict):
        fail("REQUEST_INVALID", "Execution must be an object")
    safe_id(execution.get("resource_owner"))
    cutoff = instant(execution.get("cutoff_utc"))
    device = execution.get("device")
    if not isinstance(device, str) or not re.fullmatch(r"cpu|cuda:[0-9]+", device):
        fail("REQUEST_INVALID", "Choose cpu or one explicit cuda device")
    if device != "cpu":
        if not execution.get("reservation"):
            fail("RESOURCE_BUSY", "GPU work needs an externally owned reservation")
        reservation = read_json(artifact(root, execution.get("reservation")))
        if (not isinstance(reservation, dict) or reservation.get("owner") != execution["resource_owner"] or reservation.get("device") != device
                or reservation.get("exclusive") is not True or instant(reservation.get("expires_utc")) < cutoff):
            fail("RESOURCE_BUSY", "GPU work needs a matching externally owned reservation through the cutoff")
    host = config.get("unimate")
    if not isinstance(host, dict) or host.get("protocol_version") != 1:
        fail("DEPENDENCY_MISSING", "Configure an explicit isolated protocol-1 worker and pinned local assets")
    provenance = host.get("provenance", {})
    if not isinstance(provenance, dict):
        fail("IDENTITY_MISMATCH", "Provenance must be an object")
    for key in ("code_revision", "bridge_revision", "model_revision"):
        if not REVISION.fullmatch(str(provenance.get(key, ""))):
            fail("IDENTITY_MISMATCH", "Pin code, bridge and model to immutable revisions")
    for key in ("normalizer_profile", "license", "model_profile"):
        if not isinstance(provenance.get(key), str) or not provenance[key].strip():
            fail("IDENTITY_MISMATCH", "Declare model profile, normalizer and license provenance")
    if request.get("model_profile") != provenance["model_profile"]:
        fail("IDENTITY_MISMATCH", "Requested model profile differs from the pinned host profile")
    capabilities = host.get("capabilities")
    if not isinstance(capabilities, dict) or capabilities.get("unsupported_joint_policy") != "source_rest_only":
        fail("CONDITION_INCOMPATIBLE", "Declare rotation capabilities; unsupported joints must stay at source rest")
    generated = capabilities.get("independent_rotation_joints")
    unsupported = capabilities.get("unsupported_rotation_joints")
    for values in (generated, unsupported):
        if (not isinstance(values, list) or any(not isinstance(name, str) for name in values)
                or len(set(values)) != len(values)):
            fail("CONDITION_INCOMPATIBLE", "Rotation capability lists need distinct joint names")
    if (set(generated) & set(unsupported) or set(generated) | set(unsupported) != rig_names
            or (not reference_mode and not STOCK_UNSUPPORTED_ROTATIONS <= set(unsupported))):
        fail("CONDITION_INCOMPATIBLE", "Disclose every rig rotation capability and its unsupported independent proposals")
    files = {}
    assets = host.get("assets", [])
    roles = {a.get("role") for a in assets if isinstance(a, dict)} if isinstance(assets, list) else set()
    allowed = ASSET_ROLES | ({"provider_source", "motion_source", "text_asset", "dependency_lock"} if reference_mode else set())
    if not ASSET_ROLES <= roles or not roles <= allowed:
        fail("OFFLINE_ASSET_MISSING", "Inventory checkpoint, config, stats, encoder, tokenizer and normalizer files locally")
    for item in [host.get("python"), host.get("worker"), *assets]:
        if not isinstance(item, dict):
            fail("DEPENDENCY_MISSING", "Configure hashed local interpreter and worker")
        item_id = safe_id(item.get("id"))
        path = Path(item.get("path", ""))
        if item_id in files or not path.is_absolute() or not HASH.fullmatch(str(item.get("sha256", ""))):
            fail("IDENTITY_MISMATCH", "Host inventory needs unique IDs, absolute paths and exact hashes")
        if not path.is_file():
            fail("OFFLINE_ASSET_MISSING", "Missing local asset: " + item_id + "; provision it separately, never during execution")
        if sha256(path) != item["sha256"]:
            fail("IDENTITY_MISMATCH", "Local asset changed: " + item_id)
        files[item_id] = dict(item)
    if reference_mode:
        from .unimate_reference import validate_host
        validate_host(root, request, rig, host, files)
    return root, rig, host, files, cutoff


def inspect(config, project, request):
    preflight(config, project, request)
    return {"ok": True, "support": "experimental_foundation", "status": "preflight_passed",
            "condition_values": "unverified", "offline_execution": "unverified",
            "generation": "not_run", "production_acceptance": "pending",
            "capabilities": config["unimate"]["capabilities"], "capability_validation": "declared_only"}


def _outputs(root, folder, request, host, result):
    if (not isinstance(result, dict) or result.get("schema_version") != 1 or result.get("request_digest") != digest(request)
            or result.get("rig_sha256") != request["rig_manifest"]["sha256"]
            or result.get("capabilities_digest") != digest(host["capabilities"])
            or result.get("provenance_digest") != digest(host["provenance"])):
        fail("OUTPUT_INVALID", "Worker result does not belong to this request, rig and pinned profile")
    clips = result.get("clips", [])
    expected = {sample_id(clip): clip for clip in request["clips"]}
    if not isinstance(clips, list) or len(clips) != len(expected):
        fail("OUTPUT_INVALID", "Worker omitted requested clips")
    seen, paths, outputs = set(), set(), []
    for clip in clips:
        if not isinstance(clip, dict):
            fail("OUTPUT_INVALID", "Worker clip must be an object")
        name = sample_id(clip)
        if name not in expected or name in seen:
            fail("OUTPUT_INVALID", "Worker returned duplicate or unexpected clips")
        seen.add(name)
        for key in ("name", "prompt", "seed", "loop", "root_motion"):
            if type(clip.get(key)) is not type(expected[name][key]) or clip[key] != expected[name][key]:
                fail("OUTPUT_INVALID", "Worker changed clip seed or motion policy")
        for key in ("duration_seconds", "sample_rate"):
            number = clip.get(key)
            if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
                fail("OUTPUT_INVALID", "Worker must report measured finite clip timing")
        for key, suffix in (("raw", ".npy"), ("decoded", ".npz")):
            path = artifact(root, clip.get(key))
            if not path.is_relative_to(folder / "output") or path.suffix != suffix or path in paths or path.stat().st_size == 0:
                fail("OUTPUT_INVALID", "Worker outputs must be distinct new raw/decoded files under this run's output")
            paths.add(path)
            outputs.append(file_record(root, path))
    if "conditioning" in request:
        from .unimate_reference import validate_result
        outputs.extend(validate_result(root, folder, request, host, result))
    return outputs


def generate(config, project, request, record):
    root, rig, host, files, cutoff = preflight(config, project, request)
    parts = Path(record).parts
    if len(parts) != 4 or parts[:2] != ("artifacts", "unimate") or parts[-1] != "task.json":
        fail("REQUEST_INVALID", "Use artifacts/unimate/<new-run-id>/task.json")
    safe_id(parts[2])
    destination = outside_package(relative(root, record))
    folder = destination.parent
    if folder.exists():
        fail("RUN_EXISTS", "Run already exists; inspect its receipts instead of resubmitting")
    if datetime.now(timezone.utc) >= cutoff:
        fail("CUTOFF_PASSED", "Generation cutoff has passed; nothing started")
    physical_device = request["execution"]["device"]
    worker_device = "cpu" if physical_device == "cpu" else "cuda:0"
    folder.mkdir(parents=True, exist_ok=False)
    receipt = {"schema_version": 1, "provider": "unimate", "support": "experimental_foundation",
               "request_digest": digest(request), "request": request, "kit": kit_identity(),
               "provenance": host["provenance"], "inventory": [{k: f[k] for k in ("id", "sha256")} for f in files.values()],
               "capabilities": host["capabilities"], "capability_validation": "declared_only",
               "device_mapping": {"requested_physical_device": physical_device, "worker_device": worker_device},
               "status": "starting", "ok": False, "production_acceptance": "pending",
               "offline_execution": "unverified", "condition_values": "unverified", "outputs": []}
    claim(destination, receipt)
    interrupted = None
    try:
        baseline = prelaunch_baseline(hide_window=True)
        if os.name == "nt" and (not isinstance(baseline, dict) or baseline.get("status") != "ok"):
            fail("OWNERSHIP_UNVERIFIED", "Windows ownership baseline unavailable; no worker started")
        preflight(config, project, request)  # Recheck bytes after the slow ownership query.
        remaining = (cutoff - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            fail("CUTOFF_PASSED", "Cutoff passed during preflight; no worker started")
        input_path, result_path = folder / "input.json", folder / "result.json"
        payload = {"schema_version": 1, "request": request, "request_digest": digest(request),
                               "rig": rig, "project": str(root), "assets": list(files.values()),
                               "provenance": host["provenance"], "output": str(folder / "output"),
                               "capabilities": host["capabilities"],
                               "worker_device": worker_device,
                               "offline_policy": {"local_files_only": True, "downloads": False}}
        if "conditioning" in request:
            payload["runtime"] = host["runtime"]
            payload["worker_profile"] = host["worker_profile"]
            payload["host_entries"] = {key: host[key]["id"] for key in ("python", "worker")}
        write_json(input_path, payload)
        env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONNOUSERSITE="1",
                   CUDA_VISIBLE_DEVICES="" if physical_device == "cpu" else physical_device.split(":")[1])
        run([host["python"]["path"], host["worker"]["path"], "--input", str(input_path), "--output", str(result_path)],
            cwd=root, timeout=min(request["limits"]["timeout_seconds"], remaining), env=env,
            hide_window=True, job_dir=folder / "process", baseline=baseline)
        receipt["status"] = "worker_completed"
    except KeyboardInterrupt as exc:
        interrupted = exc
        receipt.update(status="interrupted", error="Generation interrupted")
    except ProviderError as exc:
        receipt.update(status="refused", error=str(exc), provider_error={"code": exc.code, "retryable": False})
    except (StudioError, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        receipt.update(status="worker_failed", error=str(exc) if isinstance(exc, StudioError) else "Worker/filesystem failure; inspect local logs")
    finally:
        process_path = folder / "process" / "process.json"
        try:
            if process_path.is_file():
                process = read_json(process_path)
                receipt["process"] = file_record(root, process_path)
                if not isinstance(process, dict):
                    fail("CLEANUP_UNVERIFIED", "Worker process receipt is invalid")
                if receipt["status"] == "worker_completed" and (process.get("status") != "completed" or type(process.get("returncode")) is not int or process["returncode"] != 0):
                    fail("CLEANUP_UNVERIFIED", "Worker completion differs from its process receipt")
                if process.get("status") in ("completed", "failed") and type(process.get("pid")) is int and process["pid"] > 0:
                    cleanup = stop_survivors(process["pid"], hide_window=True, ownership=process.get("windows_ownership"))
                    receipt["cleanup"] = cleanup
                    if (not isinstance(cleanup, dict) or cleanup.get("status") != "ok" or cleanup.get("pids")
                            or cleanup.get("unverified") or not cleanup.get("stopped")):
                        fail("CLEANUP_UNVERIFIED", "Worker descendants survived or ownership/cleanup is unverified")
                elif receipt["status"] == "worker_completed" or process.get("cleanup") == "unverified":
                    fail("CLEANUP_UNVERIFIED", "Owned worker cleanup is unverified")
            elif receipt["status"] == "worker_completed":
                fail("CLEANUP_UNVERIFIED", "Worker process receipt is missing")
        except (StudioError, OSError, KeyError, TypeError, ValueError):
            receipt.update(status="cleanup_unverified", error="Worker process or cleanup evidence is unavailable; inspect local receipts")
        if receipt["status"] == "worker_failed" and (folder / "result.json").is_file():
            try:
                failure = read_json(folder / "result.json")
                error = failure.get("provider_error", {})
                if (failure.get("request_digest") == digest(request) and failure.get("status") == "failed"
                        and error.get("code") in {"CONDITION_INCOMPATIBLE", "RIG_UNSUPPORTED", "IDENTITY_MISMATCH",
                            "OFFLINE_ASSET_MISSING", "OFFLINE_NETWORK_REFUSED", "DEPENDENCY_MISSING", "RESOURCE_BUSY",
                            "CUTOFF_PASSED", "INTERRUPTED", "REQUEST_INVALID", "OUTPUT_INVALID", "WORKER_FAILED"}
                        and error.get("retryable") is False):
                    receipt["provider_error"] = {"code": error["code"], "retryable": False}
                    receipt["worker_failure"] = file_record(root, folder / "result.json")
            except (StudioError, OSError, KeyError, TypeError, ValueError, AttributeError):
                pass  # Unbound failure detail cannot replace the process evidence.
        if receipt["status"] == "worker_completed":
            try:
                preflight(config, project, request)
                receipt["outputs"] = _outputs(root, folder, request, host, read_json(folder / "result.json"))
                receipt.update(status="completed", ok=True, result=file_record(root, folder / "result.json"), artifact_validation="manifest_only")
                if "conditioning" in request:
                    receipt.update(condition_values="worker_checked", raw_motion="preserved")
            except (StudioError, OSError, KeyError, TypeError, ValueError) as exc:
                receipt.update(status="output_invalid", error=str(exc) if isinstance(exc, StudioError) else "Worker result is invalid")
        if not receipt["ok"] and "provider_error" not in receipt:
            codes = {"output_invalid": "OUTPUT_INVALID", "cleanup_unverified": "CLEANUP_UNVERIFIED",
                     "interrupted": "INTERRUPTED", "worker_failed": "WORKER_FAILED"}
            receipt["provider_error"] = {"code": codes.get(receipt["status"], "WORKER_FAILED"), "retryable": False}
        write_json(destination, receipt)
    if interrupted is not None:
        raise interrupted
    return receipt


def execute(config, project, operation, request_path, record=None):
    try:
        root = outside_package(project)
        request = read_json(relative(root, request_path))
        if operation == "inspect":
            return inspect(config, root, request)
        if operation != "generate" or not record:
            fail("REQUEST_INVALID", "UniMate generate requires an explicit new task record")
        return generate(config, root, request, record)
    except ProviderError as exc:
        return {"ok": False, "status": "refused", "support": "experimental_foundation",
                "error": str(exc), "provider_error": {"code": exc.code, "retryable": False}}
    except (StudioError, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        return {"ok": False, "status": "refused", "support": "experimental_foundation",
                "error": "Invalid request, project artifact or local configuration",
                "provider_error": {"code": "REQUEST_INVALID", "retryable": False}}
