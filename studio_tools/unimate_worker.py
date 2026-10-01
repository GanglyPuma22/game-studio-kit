"""Optional isolated UniMate reference worker. ML dependencies are loaded on demand."""

import argparse
import ctypes
from datetime import datetime, timezone
import gc
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import random
import shutil
import socket
import subprocess
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio_tools.common import digest, file_record, read_json, sha256, write_json
from studio_tools.adapters.unimate import ProviderError, artifact, fail, instant, preflight, sample_id
from studio_tools.adapters.unimate_reference import GENERATION, PRESENTATION, WORKER_PROFILE, validate_rig


class Budget:
    def __init__(self, data):
        execution = data["request"]["execution"]
        seconds = min(data["request"]["limits"]["timeout_seconds"],
                      (instant(execution["cutoff_utc"]) - datetime.now(timezone.utc)).total_seconds())
        self.deadline = time.monotonic() + seconds
        self.cancel = Path(data["output"]).parent / "cancel.json"
        self.request_digest = data["request_digest"]

    def check(self):
        if time.monotonic() >= self.deadline:
            fail("CUTOFF_PASSED", "Worker budget exhausted; completed samples remain partial evidence")
        if self.cancel.is_file():
            marker = read_json(self.cancel)
            if not isinstance(marker, dict) or marker.get("request_digest") != self.request_digest:
                fail("REQUEST_INVALID", "Cancellation marker does not identify this request")
            fail("INTERRUPTED", "Request-scoped cancellation observed")


def deny_network(*args, **kwargs):
    fail("OFFLINE_NETWORK_REFUSED", "Optional worker runtime permits local assets only")


def disable_network():
    # A Python-level guard, not an OS firewall or proof against native extensions.
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.getaddrinfo = deny_network


def install_local_loaders(tokenizer, encoder, text_root, normalizer):
    """Constrain the upstream factory's known model ID to its pinned local snapshot."""
    for loader in (tokenizer, encoder):
        original = loader.from_pretrained

        def local(name, *args, _original=original, **kwargs):
            if name != "google/flan-t5-base":
                fail("CONDITION_INCOMPATIBLE", "Unexpected text model requested by provider")
            kwargs["local_files_only"] = True
            return _original(str(text_root), *args, **kwargs)

        loader.from_pretrained = staticmethod(local)
    # normalize_text=False is the explicit implemented profile. Never enter
    # WhiteSpaceTokenizer's spaCy download fallback, even if upstream changes.
    normalizer.__init__ = deny_network


def verify_dependencies(path):
    """Check the separately provisioned environment; never install or resolve versions."""
    pins = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    if not pins or any(line.count("==") != 1 for line in pins):
        fail("DEPENDENCY_MISSING", "Dependency lock requires exact package==version entries")
    for line in pins:
        name, version = line.split("==")
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            fail("DEPENDENCY_MISSING", "A pinned worker dependency is absent")
        if installed != version:
            fail("DEPENDENCY_MISSING", "Worker dependency version differs from the pinned lock")


def verify_input(data):
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("worker_profile") != WORKER_PROFILE
            or data.get("request_digest") != digest(data.get("request"))
            or data.get("offline_policy") != {"local_files_only": True, "downloads": False}):
        fail("REQUEST_INVALID", "Expected a Kit protocol-1 animated-reference worker input")
    request, root = data["request"], Path(data["project"]).resolve()
    if not isinstance(request.get("conditioning"), dict) or request["conditioning"].get("kind") != "animated_reference":
        fail("CONDITION_INCOMPATIBLE", "Rest-only inference is unvalidated; no reference fallback is allowed")
    if read_json(artifact(root, request["rig_manifest"])) != data["rig"]:
        fail("IDENTITY_MISMATCH", "Worker rig differs from the hashed request manifest")
    output = Path(data["output"]).resolve()
    if not output.is_relative_to(root) or output.exists():
        fail("RUN_EXISTS", "Worker needs a fresh output directory inside the experiment")
    physical = request["execution"]["device"]
    expected_device = "cpu" if physical == "cpu" else "cuda:0"
    mask = "" if physical == "cpu" else physical.split(":")[1]
    if data.get("worker_device") != expected_device or os.environ.get("CUDA_VISIBLE_DEVICES") != mask:
        fail("REQUEST_INVALID", "Physical GPU mask and worker-local device disagree")
    files = {}
    for item in data["assets"]:
        path = Path(item["path"])
        if not path.is_absolute() or not path.is_file():
            fail("OFFLINE_ASSET_MISSING", "Worker asset is not available locally")
        if item["id"] in files or sha256(path) != item["sha256"]:
            fail("IDENTITY_MISMATCH", "Worker assets changed after Kit preflight")
        files[item["id"]] = item
    host = {k: data[k] for k in ("runtime", "provenance", "capabilities", "worker_profile")}
    host.update(protocol_version=1, assets=[f for f in files.values() if f.get("role") is not None],
                **{key: files[data["host_entries"][key]] for key in ("python", "worker")})
    preflight({"unimate": host}, root, request)
    return root, output, files


def validate_condition(np, data, entry, source_rest):
    """Verify actual NumPy topology/rest/scale values before constructing a model."""
    joints, original = data["rig"]["joints"], data["rig"]["source_joints"]
    names = [j["name"] for j in joints]
    parents = [-1 if j["parent"] is None else names.index(j["parent"]) for j in joints]
    if list(entry["joint_names"]) != names or np.asarray(entry["parents"]).tolist() != parents:
        fail("RIG_UNSUPPORTED", "Condition's actual joint order/parents differ from manifest")
    for key, field, shape in (("tpos_offsets", "rest_offset", (len(names), 3)),
                              ("tpos_local_rotations", "rest_rotation", (len(names), 4)),
                              ("tpos_global_rotations", "rest_global_rotation", (len(names), 4))):
        values = np.asarray(entry[key])
        if (values.shape != shape or not np.isfinite(values).all()
                or not np.allclose(values, [j[field] for j in joints], atol=1e-6, rtol=1e-6)):
            fail("RIG_UNSUPPORTED", "Condition rest values differ from manifest: " + key)
    scale = float(entry["scale_factor"])
    if not math.isfinite(scale) or scale <= 0:
        fail("RIG_UNSUPPORTED", "Condition scale must be positive and finite")
    C = np.asarray(source_rest["C"])
    if C.shape != (4, 4) or not np.allclose(C, data["rig"]["canonical_from_source"], atol=1e-6, rtol=1e-6):
        fail("RIG_UNSUPPORTED", "Captured canonical transform differs from manifest")
    source_names = source_rest["names"].tolist()
    source_parents = np.asarray(source_rest["parents"]).tolist()
    if (len(source_names) != len(original) or set(source_names) != {j["name"] for j in original}
            or len(source_parents) != len(original)):
        fail("RIG_UNSUPPORTED", "Captured source rest must contain exactly the original rig")
    mapped = {name: None if p == -1 else source_names[p] for name, p in zip(source_names, source_parents)
              if type(p) is int and -1 <= p < len(source_names)}
    if mapped != {j["name"]: j["parent"] for j in original}:
        fail("RIG_UNSUPPORTED", "Captured source-rest parents differ from baseline")
    matrices = source_rest["rest_world_bones"]
    if matrices.shape != (len(original), 4, 4) or not np.isfinite(matrices).all():
        fail("RIG_UNSUPPORTED", "Captured source rest matrices are invalid")
    # Blender capture is float32. Validate its authored matrices at capture
    # precision without normalizing/mutating them or weakening canonical math.
    for matrix in matrices:
        matrix_scale = math.hypot(*(float(v) for v in matrix[:3, 0]))
        if not math.isfinite(matrix_scale) or matrix_scale <= 1e-12:
            fail("RIG_UNSUPPORTED", "Captured source rest has invalid scale")
        rotation = np.asarray(matrix[:3, :3], dtype=np.float64) / matrix_scale
        if (not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8, rtol=0)
                or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5, rtol=0)
                or abs(float(np.linalg.det(rotation)) - 1) > 1e-5):
            fail("RIG_UNSUPPORTED", "Captured source rest has shear/nonuniform scale/reflection")
    # Source rest matrices are captured evidence, not proof of an original
    # Blender roundtrip. The existing bake route must independently verify them.
    return names, parents, scale, C


def validate_decoded(np, raw, anim, names, parents):
    if raw.shape != (60, len(names), 12) or not np.isfinite(raw).all():
        fail("OUTPUT_INVALID", "Sampler returned nonfinite features or unexpected dimensions")
    for values, shape in ((anim.positions, (60, len(names), 3)),
                          (anim.rotations.qs, (60, len(names), 4)),
                          (anim.offsets, (len(names), 3))):
        if np.asarray(values).shape != shape or not np.isfinite(values).all():
            fail("OUTPUT_INVALID", "Decoded motion has invalid dimensions or nonfinite values")
    if np.asarray(anim.parents).tolist() != parents or not np.allclose(np.linalg.norm(anim.rotations.qs, axis=-1), 1, atol=1e-4):
        fail("OUTPUT_INVALID", "Decoded topology/quaternions are invalid")
    leaves = [i for i in range(len(names)) if i not in parents]
    if not np.allclose(np.abs(anim.rotations.qs[:, leaves, 0]), 1, atol=1e-5):
        fail("OUTPUT_INVALID", "Stock decoder unexpectedly proposed independent leaf rotations")
    root_orients = np.asarray(anim.orients.qs)
    if (root_orients.shape != (60, 4) or not np.isfinite(root_orients).all()
            or not np.allclose(np.linalg.norm(root_orients, axis=-1), 1, atol=1e-4)):
        fail("OUTPUT_INVALID", "Decoded auxiliary Root facing is invalid")


def write_decoded(np, path, anim, condition, C, evidence):
    """Serialize decoded arrays using the same validated scale recorded in evidence."""
    np.savez(path, positions=anim.positions, rotations=anim.rotations.qs,
             offsets=anim.offsets, parents=anim.parents,
             tpos_global_rot=condition["tpos_global_rotations"], root_orients=anim.orients.qs,
             joint_names=np.array(condition["joint_names"]), C=C,
             scale_factor=evidence["canonical_scale_factor"],
             source_joint_indices=np.array(evidence["source_joint_indices"]))


def free_ram_mib():
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            fail("RESOURCE_BUSY", "Host RAM probe unavailable")
        return status.available / 2**20
    try:
        lines = Path("/proc/meminfo").read_text().splitlines()
        return int(next(line.split()[1] for line in lines if line.startswith("MemAvailable:"))) / 1024
    except (OSError, StopIteration, ValueError):
        fail("RESOURCE_BUSY", "Host RAM probe unavailable")


def resource_gate(data, budget, evidence, *, resident=False):
    budget.check()
    ram = free_ram_mib()
    if ram < 2048:
        fail("RESOURCE_BUSY", "Insufficient free host RAM; no sampling started")
    if data["worker_device"] == "cpu":
        return
    # Coordinator reservation is not arbitration. Refuse contention; do not
    # interrupt applications, sleep with a resident model, or retry sampling.
    ordinal = data["request"]["execution"]["device"].split(":")[1]
    result = subprocess.run(["nvidia-smi", "-i", ordinal,
                             "--query-gpu=memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=min(10, max(.1, budget.deadline - time.monotonic())),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        fail("RESOURCE_BUSY", "Selected physical GPU resource probe failed")
    try:
        free, utilization = [int(v.strip()) for v in result.stdout.strip().split(",")]
    except ValueError:
        fail("RESOURCE_BUSY", "Selected physical GPU resource probe was ambiguous")
    evidence["resource_checks"].append({"physical_device": "cuda:" + ordinal,
        "worker_device": data["worker_device"], "free_vram_mib": free, "utilization_percent": utilization,
        "free_ram_mib": ram,
        "model_resident": resident, "at_utc": datetime.now(timezone.utc).isoformat()})
    budget.check()
    if free < 3072 or utilization >= 65:
        fail("RESOURCE_BUSY", "GPU contention or insufficient headroom; no other process interrupted")


def sample(data, root, output, files, budget, evidence):
    """The pilot's stock reference route, parameterized by the existing Kit envelope."""
    sys.dont_write_bytecode = True
    runtime, request, rig = data["runtime"], data["request"], data["rig"]
    verify_dependencies(Path(next(f["path"] for f in files.values() if f.get("role") == "dependency_lock")))
    sys.path[:0] = [runtime["unimate_root"], runtime["motion_root"]]
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_IMPLICIT_TOKEN="1", HF_HUB_DISABLE_TELEMETRY="1",
                      TOKENIZERS_PARALLELISM="false", MPLCONFIGDIR=str(output / "mpl-cache"))
    disable_network()
    import numpy as np
    import torch
    from transformers import T5Tokenizer, T5EncoderModel
    from unimate.models.text_encoder.t5 import WhiteSpaceTokenizer
    install_local_loaders(T5Tokenizer, T5EncoderModel, Path(runtime["text_root"]), WhiteSpaceTokenizer)
    from unimate.models.text_encoder import factory as text_factory
    original_factory = text_factory.create_text_encoder
    def cpu_text_encoder(*args, **kwargs):
        kwargs["device"] = "cpu"
        return original_factory(*args, **kwargs)
    text_factory.create_text_encoder = cpu_text_encoder
    from unimate.configs.schema import MainConfig
    from unimate.dataset.factory import create_dataset
    from unimate.dataset.conditioning import create_sample_condition
    from unimate.models.factory import create_model, create_transport
    from unimate.models.flow.transport import Sampler
    from unimate.inference.generate import generate_samples
    from unimate.inference.sample import _make_text_encoder, _encode_prompt
    from unimate.training.ema import EMAModel
    from unimate.utils.motion_utils import recover_unimate_anim_from_rot

    asset = lambda role: Path(next(f["path"] for f in files.values() if f.get("role") == role))
    conditioning = request["conditioning"]
    c = np.load(artifact(root, rig["condition"]), allow_pickle=True).item()[conditioning["object_type"]]
    with np.load(artifact(root, rig["source_rest"]), allow_pickle=False) as source_rest:
        names, parents, scale, C = validate_condition(np, data, c, source_rest)
    stage = output / "features"
    (stage / "motions").mkdir(parents=True)
    reference = artifact(root, conditioning["reference"])
    for src, dest in ((artifact(root, rig["condition"]), stage / "cond.npy"),
                      (artifact(root, conditioning["captions"]), stage / "captions.json"),
                      (reference, stage / "motions" / reference.name)):
        shutil.copyfile(src, dest)  # Upstream text caches may write only in this new run.
    config_json = read_json(asset("model_config"))
    config_json["dataset"]["dataset_list"] = ["objaverse"]
    config_json["objaverse"]["path"] = str(stage)
    config_path = output / "resolved-config.json"
    write_json(config_path, config_json)
    evidence.update(resolved_config=file_record(root, config_path), generation=GENERATION,
                    dependencies={"python": sys.version, "numpy": np.__version__, "torch": torch.__version__},
                    source_joint_indices=[names.index(j["name"]) for j in rig["source_joints"]],
                    decoded_space="canonical_normalized", canonical_scale_factor=scale,
                    source_rest_matrix_tolerance=1e-5,
                    resource_checks=[], cases=[])
    write_json(output / "evidence.json", evidence)
    budget.check()
    config = MainConfig.from_json(config_path)
    if data["worker_device"] != "cpu" and not torch.cuda.is_available():
        fail("DEPENDENCY_MISSING", "Requested CUDA worker device is unavailable")
    resource_gate(data, budget, evidence)
    dataset = create_dataset(config.dataset, config.model, inference=True,
                             target_object_types={conditioning["object_type"]},
                             target_clip_stems={reference.stem}, stats_path=str(asset("statistics")))
    # Release the factory's joint/caption encoder before denoiser construction.
    dataset.motion_dataset.text_encoder = None
    gc.collect()
    encoder = _make_text_encoder(config, torch.device("cpu"))
    encodings = {clip["prompt"]: _encode_prompt(encoder, clip["prompt"]) for clip in request["clips"]}
    del encoder
    gc.collect()
    model = create_model(config.dataset, config.model)
    state = torch.load(asset("checkpoint"), map_location="cpu", weights_only=True)
    model.load_state_dict(state["model_state_dict"])
    ema = EMAModel(model.parameters(), decay=config.training.ema_decay, use_ema_warmup=True)
    ema.load_state_dict(state["ema_state_dict"])
    ema.copy_to(model.parameters())
    del state, ema
    gc.collect()
    budget.check()
    device = torch.device(data["worker_device"])
    model.float().to(device).eval()
    transport = create_transport(training_config=config.training)
    sampler = Sampler(transport)
    clips = []
    for clip in request["clips"]:
        resource_gate(data, budget, evidence, resident=True)
        seed = clip["seed"]
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
        _, cond = create_sample_condition(config, dataset,
            test_case_captions=[(conditioning["object_type"], clip["prompt"], encodings[clip["prompt"]], reference.name)],
            gt_start_frame=conditioning["start_frame"])
        if int(cond["n_joints"][0]) != len(names):
            fail("RIG_UNSUPPORTED", "Factory conditioning lost joints")
        tensors = {k: {"sha256": hashlib.sha256(v.cpu().contiguous().numpy().tobytes()).hexdigest(),
                       "shape": list(v.shape), "dtype": str(v.dtype)}
                   for k, v in cond.items() if torch.is_tensor(v)}
        cond = {k: v.to(device) if torch.is_tensor(v) else v for k, v in cond.items()}
        budget.check()
        if device.type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = generate_samples(model, cond, (1, config.dataset.max_joints, 12, 60),
                "flow", transport, sampler, cfg_scale=3., device=device)
        if device.type == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        budget.check()
        raw = generated[0, :len(names)].cpu().permute(2, 0, 1).numpy()
        raw = raw * cond["std"][0, :len(names)].cpu().numpy()[None] + cond["mean"][0, :len(names)].cpu().numpy()[None]
        anim = recover_unimate_anim_from_rot(raw, np.asarray(parents), np.asarray(c["tpos_offsets"]))
        validate_decoded(np, raw, anim, names, parents)
        stem = sample_id(clip)
        raw_path, decoded_path = output / (stem + ".npy"), output / (stem + "-decoded.npz")
        np.save(raw_path, raw)
        write_decoded(np, decoded_path, anim, c, C, evidence)
        item = dict(clip, duration_seconds=59 / 30, sample_rate=30, frame_count=60,
                    loop_validation="unverified", raw=file_record(root, raw_path),
                    decoded=file_record(root, decoded_path))
        clips.append(item)
        metrics = {"sample_id": stem, "name": clip["name"], "prompt": clip["prompt"],
                   "seed": seed, "seeded_libraries": ["python", "numpy", "torch"],
                   "condition_tensors": tensors, "sampling_seconds": elapsed,
                   "timing_method": "perf_counter; CUDA synchronized when selected; sampling phase only",
                   "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20 if device.type == "cuda" else None,
                   "peak_reserved_mib": torch.cuda.max_memory_reserved() / 2**20 if device.type == "cuda" else None}
        evidence["cases"].append(metrics)
        write_json(output / "evidence.json", evidence)
        print(json.dumps({"sample_id": stem, "status": "sample_written", "sampling_seconds": elapsed}), flush=True)
        del generated, cond
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()
    return clips


def execute(data, output_path, sampler=sample):
    root, output, files = verify_input(data)
    budget = Budget(data)
    budget.check()
    output.mkdir(parents=True, exist_ok=False)
    evidence = {"schema_version": 1, "request_digest": data["request_digest"],
                "worker_sha256": sha256(Path(__file__)),
                "inventory": [{k: f[k] for k in ("id", "sha256", "role") if k in f} for f in data["assets"]],
                "runtime_offline": "python_guard_only; native/OS isolation unverified",
                "reproducibility": "seeded_not_bitwise_guaranteed", "cases": []}
    try:
        clips = sampler(data, root, output, files, budget, evidence)
        budget.check()
        # Recheck original inputs and all pinned files after the optional code ran.
        validate_rig(root, data["request"], data["rig"])
        for item in files.values():
            if sha256(Path(item["path"])) != item["sha256"]:
                fail("IDENTITY_MISMATCH", "Pinned runtime asset changed during sampling")
        write_json(output / "evidence.json", evidence)
        result = {"schema_version": 1, "request_digest": data["request_digest"],
                  "rig_sha256": data["request"]["rig_manifest"]["sha256"],
                  "provenance_digest": digest(data["provenance"]),
                  "capabilities_digest": digest(data["capabilities"]),
                  "conditioning_digest": digest(data["request"]["conditioning"]),
                  "generation_digest": digest(data["request"]["generation"]),
                  "runtime_digest": digest(data["runtime"]), "raw_motion": "preserved",
                  "array_validation": "worker_checked", "clips": clips,
                  "evidence": file_record(root, output / "evidence.json")}
        export = {"format": "studio-unimate-motion-export", "schema_version": 1,
                  "request_digest": data["request_digest"], "rig": data["rig"],
                  "provenance": data["provenance"], "capabilities": data["capabilities"],
                  "conditioning": data["request"]["conditioning"], "generation": GENERATION,
                  "production_acceptance": "pending", "raw_playback_primary": True,
                  "presentation_contract": PRESENTATION,
                  "presentation_warning": "Full Root compensation removes translation AND rotation, including banking.",
                  "clips": clips, "evidence": result["evidence"]}
        write_json(output / "motion-export.json", export)
        result["export"] = file_record(root, output / "motion-export.json")
        write_json(output_path, result)
        return result
    except BaseException:
        write_json(output / "evidence.json", evidence)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    data = None
    try:
        data = read_json(Path(args.input))
        result_path = Path(args.output).resolve()
        if result_path != Path(data["output"]).resolve().parent / "result.json":
            fail("REQUEST_INVALID", "Result must belong to this Kit run")
        execute(data, result_path)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        error = {"code": exc.code if isinstance(exc, ProviderError) else
                 "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "WORKER_FAILED",
                 "retryable": False, "message": str(exc) if isinstance(exc, ProviderError) else
                 "Worker failed; inspect the complete owned process log"}
        if isinstance(data, dict):
            write_json(Path(args.output), {"schema_version": 1, "request_digest": data.get("request_digest"),
                                          "status": "failed", "provider_error": error})
        print(json.dumps(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
