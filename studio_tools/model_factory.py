"""Resumable, local model diagnostics with an explicit grouped publication boundary.

Native work goes through existing kit adapters. Nothing in this module selects
a reviewer, generates an asset, calls a provider or supplies an upload service.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import shutil

from . import host
from .adapters import blender
from .common import StudioError, digest, file_record, outside_package, read_json, relative, safe_id, sha256, write_json
from .config import executable, load
from .model_qa import __main__ as model_qa
from .model_qa.report import CHECKS

SCHEMA = 1
TRUST_LIMIT = "Attestations and evidence identities are checked; human authorship and authenticity are not independently authenticated."
REVIEW_METHODS = {"native_observation", "capture_comparison"}
_SHA = re.compile(r"[0-9a-f]{64}")


def _object(value, required, optional=(), name="object"):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise StudioError(f"Invalid {name} fields")
    return value


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {
        "unknown", "n/a", "none", "pending", "not set", "predicted", "prediction", "tbd"}


def _number(value, *, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def policy_subject(brief):
    """An approval of policy cannot transfer to different numeric or applicability rules."""
    return digest({"policy": brief["policy"], "lods": brief["lods"], "size_m": brief["size_m"],
                   "tolerance_m": brief["tolerance_m"], "structure": brief["structure"],
                   "ground_y_m": brief.get("ground_y_m", 0),
                   "ecology_applicability": {k: brief["ecology"][k] for k in ("living", "reason")}})


def _known_evidence(value):
    """Metadata may be structured, but empty, unknown and predictive leaves are not observations."""
    if isinstance(value, str):
        return _text(value) and not any(token in value.lower() for token in ("predict", "unknown", "unmeasured", "not set", "tbd"))
    if isinstance(value, dict):
        return bool(value) and all(_text(k) and _known_evidence(v) for k, v in value.items())
    if isinstance(value, list):
        return bool(value) and all(_known_evidence(v) for v in value)
    return type(value) in (int, float) and math.isfinite(value)


def _capture(root, capture, group_sha, models):
    _object(capture, ("path", "sha256", "metadata"), name="review capture")
    _reference(root, {k: capture[k] for k in ("path", "sha256")})
    metadata = read_json(_reference(root, capture["metadata"]))
    _object(metadata, ("schema_version", "capture_sha256", "group_sha256", "models", "camera", "viewport", "lighting", "pose", "renderer"), name="capture metadata")
    if type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1:
        raise StudioError("Capture metadata schema_version must be 1")
    if metadata["capture_sha256"] != capture["sha256"] or metadata["group_sha256"] != group_sha or metadata["models"] != models:
        raise StudioError("Capture metadata identity does not match the actual capture and full LOD group")
    viewport = metadata["viewport"]
    if not isinstance(viewport, list) or len(viewport) != 2 or any(type(n) is not int or n <= 0 for n in viewport):
        raise StudioError("Capture viewport must be explicit positive pixel width and height")
    if not all(_known_evidence(metadata[key]) for key in ("camera", "lighting", "pose", "renderer")):
        raise StudioError("Capture camera, lighting, pose and renderer must contain known observed values")


def _reference(root, ref, *, nullable=False):
    if nullable and ref is None:
        return None
    _object(ref, ("path", "sha256"), name="file reference")
    if not isinstance(ref["sha256"], str) or not _SHA.fullmatch(ref["sha256"]):
        raise StudioError("File references need a lowercase SHA-256")
    path = relative(root, ref["path"])
    if not path.is_file() or sha256(path) != ref["sha256"]:
        raise StudioError("Missing or changed referenced input: " + ref["path"])
    return path


def validate_brief(root, brief):
    """Validate shape and exact available inputs; unknown policy stays unknown."""
    _object(brief, ("schema_version", "id", "version", "policy", "ecology", "size_m", "tolerance_m", "structure", "lods", "build"),
            ("concept", "ground_y_m"), "model brief")
    if type(brief["schema_version"]) is not int or brief["schema_version"] != SCHEMA:
        raise StudioError("Model brief schema_version must be 1")
    safe_id(brief["id"])
    if not _text(brief["version"]):
        raise StudioError("Model brief version must be a nonempty string")
    _reference(root, brief.get("concept"), nullable=True)
    policy = _object(brief["policy"], ("reference", "allow_nonliving_na", "allow_clump_info"), name="policy")
    _reference(root, policy["reference"], nullable=True)
    if any(type(policy[k]) is not bool for k in ("allow_nonliving_na", "allow_clump_info")):
        raise StudioError("Policy applicability flags must be explicit booleans")
    ecology = _object(brief["ecology"], ("living", "reference", "reason"), name="ecology")
    if type(ecology["living"]) is not bool:
        raise StudioError("Ecology living must be an explicit boolean")
    _reference(root, ecology["reference"], nullable=True)
    if ecology["living"]:
        if ecology["reason"] is not None:
            raise StudioError("Living ecology has no nonliving reason")
    elif ecology["reference"] is not None or not _text(ecology["reason"]):
        raise StudioError("Nonliving ecology needs a reason and no ecology reference")
    size = brief["size_m"]
    if size is not None and (not isinstance(size, list) or len(size) != 3 or not all(_number(n, positive=True) for n in size)):
        raise StudioError("size_m must be three positive finite glTF Y-up dimensions or null")
    if brief["tolerance_m"] is not None and not _number(brief["tolerance_m"]):
        raise StudioError("tolerance_m must be nonnegative finite or null")
    if brief["structure"] not in ("assembly", "scatter", "clump"):
        raise StudioError("Unknown model structure")
    ground = brief.get("ground_y_m", 0)
    if type(ground) not in (int, float) or not math.isfinite(ground):
        raise StudioError("ground_y_m must be finite")
    lods = brief["lods"]
    if not isinstance(lods, list) or len(lods) < 2:
        raise StudioError("At least two contiguous LODs are required")
    known_distances = []
    for level, lod in enumerate(lods):
        _object(lod, ("level", "maximum_triangles", "switch_distance_m"), name="LOD")
        if type(lod["level"]) is not int or lod["level"] != level:
            raise StudioError("LOD levels must be contiguous from zero")
        cap, distance = lod["maximum_triangles"], lod["switch_distance_m"]
        if cap is not None and (type(cap) is not int or cap <= 0):
            raise StudioError("Triangle maximum must be a positive integer or null")
        if distance is not None:
            if not _number(distance, positive=True):
                raise StudioError("LOD distances must be positive finite numbers or null")
            known_distances.append(distance)
    if any(a >= b for a, b in zip(known_distances, known_distances[1:])):
        raise StudioError("Known LOD distances must be strictly increasing")
    build = brief["build"]
    if not isinstance(build, dict):
        raise StudioError("Build must be an object")
    if build.get("mode") == "blender":
        _object(build, ("mode", "source", "builder", "dependencies"), name="Blender build")
        for key, suffix in (("source", ".blend"), ("builder", ".py")):
            if _reference(root, build[key]).suffix.lower() != suffix:
                raise StudioError(f"Build {key} must name {suffix}")
        if not isinstance(build["dependencies"], list):
            raise StudioError("Build dependencies must be a list")
        for ref in build["dependencies"]:
            _reference(root, ref)
    elif build.get("mode") == "reuse":
        _object(build, ("mode", "models"), name="reuse build")
        if not isinstance(build["models"], list) or len(build["models"]) != len(lods):
            raise StudioError("Reuse needs exactly one hashed GLB per LOD")
        for level, model in enumerate(build["models"]):
            _object(model, ("level", "path", "sha256"), name="reuse model")
            if type(model["level"]) is not int or model["level"] != level:
                raise StudioError("Reuse GLBs must be aligned to the brief LODs")
            if _reference(root, {k: model[k] for k in ("path", "sha256")}).suffix.lower() != ".glb":
                raise StudioError("Reuse models must be GLBs")
    else:
        raise StudioError("Build mode must be blender or reuse")
    return brief


def _workflow(config):
    # Read fresh on every invocation, unlike common.kit_identity's process cache.
    package = Path(__file__).parent
    sources = {p.relative_to(package).as_posix(): sha256(p) for p in sorted(package.rglob("*.py"))}
    binary = executable(config, "blender")
    deps = config.get("model_qa_python_site_packages")
    dependency_files = None
    if deps and Path(deps).is_dir():
        base = Path(deps).resolve()
        dependency_files = {p.relative_to(base).as_posix(): sha256(p) for p in sorted(base.rglob("*"))
                            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    return {"source_sha256": digest(sources), "config_sha256": digest(config),
            "blender_sha256": sha256(binary) if binary else None,
            "dependencies_sha256": digest(dependency_files) if dependency_files is not None else None}


@contextmanager
def writer_lock(path):
    """Fail promptly on another writer; a crash releases the OS lock, not files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    locked = False
    try:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise StudioError("Model factory run already has a writer") from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _new_json(path, value):
    if path.exists():
        raise StudioError("Immutable factory artifact already exists: " + path.name)
    write_json(path, value)


def _inventory(root, folder):
    return [file_record(root, p) for p in sorted(folder.rglob("*")) if p.is_file()]


def _verify_records(root, records):
    for ref in records:
        _reference(root, ref)


def _checkpoint(root, attempt, name, value):
    path = attempt / f"{name}.json"
    _new_json(path, value)
    _new_json(attempt / f"{name}-confirmation.json", {"schema_version": 1, "checkpoint": file_record(root, path)})


def _confirmed(root, attempt, name):
    path, confirmation = attempt / f"{name}.json", attempt / f"{name}-confirmation.json"
    if not path.is_file() or not confirmation.is_file():
        return None
    record = _object(read_json(confirmation), ("schema_version", "checkpoint"), name="checkpoint confirmation")
    if record["schema_version"] != 1 or record["checkpoint"].get("path") != path.relative_to(root).as_posix():
        raise StudioError("Checkpoint confirmation identity mismatch")
    _reference(root, record["checkpoint"])
    return read_json(path)


def _size_row(root, brief, level, output):
    info = read_json(output)
    raw = info.get("dimensions_m")
    valid = isinstance(raw, list) and len(raw) == 3 and all(_number(n) for n in raw)
    actual = [raw[0], raw[2], raw[1]] if valid else None
    known = brief["size_m"] is not None and brief["tolerance_m"] is not None
    pose_verified = info.get("bounds_pose") == "armature_rest"
    state = "NOT SET" if not known else "UNMEASURED" if not valid or not pose_verified else (
        "PASS" if all(abs(a - b) <= brief["tolerance_m"] for a, b in zip(actual, brief["size_m"])) else "FAIL")
    return {"level": level, "result": state, "dimensions_m_gltf_y_up": actual,
            "bounds_pose": info.get("bounds_pose"), "raw_inspection": file_record(root, output)}


def _verified_candidate(root, attempt, brief, finish):
    """Reconstruct cached gates from mandatory, hash-verified stage evidence."""
    confirmed = _confirmed(root, attempt, "finish")
    if confirmed is None or confirmed != finish or confirmed.get("completed") is not True:
        raise StudioError("Completed factory checkpoint is unconfirmed")
    _verify_records(root, finish["evidence"])
    required = ["build.json", "build-confirmation.json", "qa-gate.json", "size-gate.json",
                "qa/report.json", "qa/execution.json", "qa-return.json", "request.json"]
    required += [f"size/lod{lod['level']}.json" for lod in brief["lods"]]
    recorded = {ref["path"] for ref in finish["evidence"]}
    if any((attempt / name).relative_to(root).as_posix() not in recorded for name in required):
        raise StudioError("Factory finish lacks required checkpoint evidence")
    build = _confirmed(root, attempt, "build")
    if build is None:
        raise StudioError("Factory build checkpoint is unconfirmed")
    _verify_records(root, build["evidence"])
    models = build["models"]
    expected_paths = [(attempt / "build" / f"{brief['id']}-lod{lod['level']}.glb").relative_to(root).as_posix()
                      for lod in brief["lods"]]
    if ([m["level"] for m in models] != list(range(len(brief["lods"])))
            or [m["path"] for m in models] != expected_paths
            or build["operation"] not in ("exported", "reused", "reused_build")):
        raise StudioError("Factory build does not identify the exact output group")
    _verify_records(root, [{k: m[k] for k in ("path", "sha256")} for m in models])
    qa = _qa_gate(brief, models, read_json(attempt / "qa/report.json"),
                  read_json(attempt / "qa/execution.json"), read_json(attempt / "qa-return.json")["returncode"])
    sizes = [_size_row(root, brief, lod["level"], attempt / "size" / f"lod{lod['level']}.json") for lod in brief["lods"]]
    candidate = {"operation": build["operation"], "models": models, "qa": qa, "size": sizes,
                 "group_sha256": digest([{k: m[k] for k in ("level", "sha256")} for m in models])}
    if (qa != read_json(attempt / "qa-gate.json") or sizes != read_json(attempt / "size-gate.json")
            or candidate != finish["candidate"]
            or finish["qualified"] != (qa["ok"] and all(s["result"] == "PASS" for s in sizes))):
        raise StudioError("Cached factory candidate disagrees with verified stage evidence")
    return candidate


def _timeout(config, cutoff):
    limit = min(float(config.get("timeout", 180)), 3600)
    if cutoff:
        limit = min(limit, (cutoff - datetime.now(timezone.utc)).total_seconds())
    if not math.isfinite(limit) or limit < 1:
        raise StudioError("Factory cutoff exhausted before the next operation")
    return int(limit)


def _qa_gate(brief, models, report, execution, returncode):
    """Keep original rows intact; add independent exact per-LOD qualification."""
    reasons, budgets = [], []
    process = execution.get("process", {})
    verdict = report.get("result")
    passing = ("PASS", "INFO", "N/A")
    nonpassing = ("FAIL", "UNMEASURED", "NOT SET")
    # model_qa.main returns 1 for completed non-passing measurements too. Its
    # process receipt, not that quality exit code, establishes worker completion.
    if returncode not in (0, 1) or process.get("returncode") != 0:
        reasons.append("QA execution did not complete successfully")
    if execution.get("result") not in passing + nonpassing or execution.get("result") != verdict:
        reasons.append("QA execution verdict is missing, unknown or inconsistent with its report")
    if verdict in passing + nonpassing and returncode in (0, 1) and returncode != (0 if verdict in passing else 1):
        reasons.append("QA runner exit code is inconsistent with its report verdict")
    if report.get("errors"):
        reasons.append("QA report contains execution or measurement errors")
    if verdict == "FAIL":
        reasons.append("QA measurements failed quality checks")
    elif verdict == "UNMEASURED":
        reasons.append("QA report has incomplete measurements")
    elif verdict == "NOT SET":
        reasons.append("QA policy is NOT SET")
    elif verdict not in passing:
        reasons.append("QA report verdict is missing or unknown")
    rows = report.get("models", [])
    if not isinstance(rows, list) or len(rows) != len(models):
        return {"ok": False, "reasons": reasons + ["QA lacks exact LOD coverage"], "budgets": budgets}
    by_level = {}
    for row in rows:
        level = row.get("lod")
        if type(level) is not int or level in by_level:
            reasons.append("QA contains duplicate or invalid LOD rows")
        else:
            by_level[level] = row
    for model, lod in zip(models, brief["lods"]):
        level = lod["level"]
        row = by_level.get(level, {})
        if row.get("sha256") != model["sha256"] or row.get("file") != Path(model["path"]).name:
            reasons.append(f"LOD{level} QA model identity mismatch")
        checks = row.get("checks", [])
        if not isinstance(checks, list) or len(checks) != len(CHECKS) or {c.get("check") for c in checks} != set(CHECKS):
            reasons.append(f"LOD{level} QA check coverage is incomplete")
            continue
        for check in checks:
            state, kind = check.get("result"), check.get("check")
            allowed = state == "PASS"
            if state == "N/A":
                allowed = kind == "ecology" and not brief["ecology"]["living"] and brief["policy"]["allow_nonliving_na"]
            elif state == "INFO":
                allowed = kind == "M13" and brief["structure"] == "clump" and brief["policy"]["allow_clump_info"]
            if not allowed:
                reasons.append(f"LOD{level} {kind}: {state or 'UNKNOWN'}")
        triangle_row = next(c for c in checks if c["check"] == "triangles")
        count = triangle_row.get("details", {}).get("triangles")
        cap = lod["maximum_triangles"]
        state = "NOT SET" if cap is None else "UNMEASURED" if type(count) is not int or count < 0 else "PASS" if count <= cap else "FAIL"
        budgets.append({"level": level, "triangles": count, "maximum_triangles": cap, "result": state})
        if state != "PASS":
            reasons.append(f"LOD{level} exact triangle maximum: {state}")
    if any(lod["switch_distance_m"] is None for lod in brief["lods"]):
        reasons.append("Exact LOD switch distances are NOT SET")
    return {"ok": not reasons, "reasons": reasons, "budgets": budgets}


def _approval_gates(root, brief, brief_sha, group_sha, models, bundle):
    expected = {"concept": (brief.get("concept") or {}).get("sha256"),
                "policy": policy_subject(brief) if brief["policy"]["reference"] else None,
                "model": group_sha}
    if brief["ecology"]["living"]:
        expected["ecology"] = digest(brief["ecology"]) if brief["ecology"]["reference"] else None
    gates = {key: {"status": "pending", "subject_sha256": value} for key, value in expected.items()}
    reasons = []
    if bundle is None:
        bundle = {"schema_version": 1, "approvals": [], "review": None}
    try:
        _object(bundle, ("schema_version", "approvals", "review"), name="approval bundle")
        if type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1 or not isinstance(bundle["approvals"], list):
            raise StudioError("Invalid approval bundle schema")
        seen = set()
        for approval in bundle["approvals"]:
            _object(approval, ("kind", "authority", "decision", "subject_sha256", "reviewer", "evidence"), name="human approval")
            kind = approval["kind"]
            if kind not in ("concept", "policy", "ecology", "model") or kind in seen:
                raise StudioError("Unknown or duplicate approval kind")
            seen.add(kind)
            evidence = approval["evidence"]
            if not isinstance(evidence, list) or not evidence:
                raise StudioError("Approval needs hashed original evidence")
            for ref in evidence:
                _reference(root, ref)
            valid = (kind in expected and expected[kind] is not None and approval["authority"] == "human"
                     and approval["decision"] == "approved" and _text(approval["reviewer"])
                     and approval["subject_sha256"] == expected[kind])
            if kind in gates:
                gates[kind]["status"] = "approved" if valid else "invalid"
        review = bundle["review"]
        review_ok = False
        if review is not None:
            _object(review, ("verdict", "group_sha256", "concept_sha256", "brief_sha256", "observer", "method", "captures", "observations"), name="visual review")
            if not isinstance(review["captures"], list) or not review["captures"]:
                raise StudioError("Visual review needs hashed capture evidence")
            for capture in review["captures"]:
                _capture(root, capture, group_sha, models)
            review_ok = (review["verdict"] == "pass" and review["group_sha256"] == group_sha
                         and expected["concept"] is not None and review["concept_sha256"] == expected["concept"]
                         and review["brief_sha256"] == brief_sha and _text(review["observer"]) and review["method"] in REVIEW_METHODS)
            observations = review["observations"]
            review_ok = review_ok and isinstance(observations, list) and bool(observations) and all(_text(v) for v in observations)
        gates["visual_review"] = {"status": "approved" if review_ok else "pending"}
    except (StudioError, OSError, TypeError, KeyError) as exc:
        reasons.append(str(exc) if isinstance(exc, StudioError) else "Malformed approval evidence")
        gates["visual_review"] = {"status": "invalid"}
    reasons += [f"{key} approval: {gate['status']}" for key, gate in gates.items() if gate["status"] != "approved"]
    return {"ok": not reasons, "gates": gates, "reasons": reasons, "trust_limit": TRUST_LIMIT}


def execute(project, brief, run_id, *, config=None, approvals=None, retry_failed=False,
            cutoff_utc=None, publish=False, publication_callback=None):
    """Run diagnostics or resume verified evidence. Publishing is API-only and opt-in."""
    if type(publish) is not bool or type(retry_failed) is not bool:
        raise StudioError("publish and retry_failed must be explicit booleans")
    root = outside_package(project)
    if not root.is_dir():
        raise StudioError("Factory project must already exist")
    run_id = safe_id(run_id)
    config = load(overrides=config or {})
    cutoff = host.parse_utc(cutoff_utc, "Factory cutoff") if cutoff_utc else None
    brief_path = relative(root, brief)
    data = validate_brief(root, read_json(brief_path))
    brief_sha = sha256(brief_path)
    identity = {"schema_version": 1, "brief": file_record(root, brief_path), "workflow": _workflow(config)}
    run = outside_package(relative(root, f"artifacts/model-factory/{run_id}"))
    with writer_lock(run / "writer.lock"):
        identity_path = run / "identity.json"
        if identity_path.exists():
            if read_json(identity_path) != identity:
                raise StudioError("Factory inputs or workflow changed; choose a new run id")
        else:
            _new_json(identity_path, identity)
        def inputs_unchanged():
            validate_brief(root, read_json(brief_path))
            if sha256(brief_path) != brief_sha or _workflow(config) != identity["workflow"]:
                raise StudioError("Factory inputs or workflow changed during execution")

        attempts = sorted((p for p in run.glob("attempt-*") if p.is_dir()), key=lambda p: int(p.name.split("-")[-1]))
        attempt = attempts[-1] if attempts else None
        finish = _confirmed(root, attempt, "finish") if attempt else None
        previous_attempt, previous_finish = attempt, finish
        if attempt and (finish is None or finish.get("completed") is not True):
            if not retry_failed:
                return {"ok": False, "status": "retry_required", "run_id": run_id,
                        "attempt": attempt.name, "reasons": ["Failed or interrupted attempt preserved; explicit --retry-failed is required"],
                        "failure": finish}
            attempt = None
        elif attempt and retry_failed and finish.get("qualified") is not True:
            attempt = None
        if attempt:
            candidate = _verified_candidate(root, attempt, data, finish)
        else:
            previous_build = None
            if previous_attempt:
                recorded_build = any(ref["path"] == (previous_attempt / "build.json").relative_to(root).as_posix()
                                     for ref in (previous_finish or {}).get("evidence", []))
                if (recorded_build or (previous_attempt / "build-confirmation.json").exists()) and not (previous_attempt / "build.json").is_file():
                    raise StudioError("Recorded successful build checkpoint is missing; refusing to rerun the builder")
            if previous_attempt and (previous_attempt / "build.json").is_file():
                # Only a committed successful build checkpoint is reusable. A
                # partial builder's files without that checkpoint are not a build.
                build_path = previous_attempt / "build.json"
                if previous_finish:
                    build_ref = next((r for r in previous_finish["evidence"] if r["path"] == build_path.relative_to(root).as_posix()), None)
                    if not build_ref:
                        raise StudioError("Previous build checkpoint is not bound to its attempt evidence")
                    _reference(root, build_ref)
                previous_build = _confirmed(root, previous_attempt, "build")
                if previous_build is None:
                    raise StudioError("Previous build checkpoint is unconfirmed; cannot reuse it")
                if (len(previous_build["models"]) != len(data["lods"])
                        or [m["level"] for m in previous_build["models"]] != list(range(len(data["lods"])))):
                    raise StudioError("Previous build does not cover the exact LOD group")
                _verify_records(root, previous_build["evidence"])
                _verify_records(root, [{k: m[k] for k in ("path", "sha256")} for m in previous_build["models"]])
            attempt = run / f"attempt-{len(attempts) + 1}"
            attempt.mkdir(exist_ok=False)
            _new_json(attempt / "attempt.json", {"started_utc": datetime.now(timezone.utc).isoformat(), "identity": identity})
            try:
                external_evidence = []
                build_evidence = []
                _timeout(config, cutoff)
                preflight = host.preflight(config, output=attempt / "preflight.json")
                if preflight.get("ready") is not True and preflight.get("host_kind") != "unsupported":
                    raise StudioError("Host preflight blocked: " + "; ".join(preflight.get("reasons", [])))
                build_dir = attempt / "build"
                build_dir.mkdir()
                outputs = [{"level": lod["level"], "path": (build_dir / f"{data['id']}-lod{lod['level']}.glb").relative_to(root).as_posix()}
                           for lod in data["lods"]]
                request = {"schema_version": 1, "root": str(root), "brief": data,
                           "brief_sha256": brief_sha, "outputs": outputs}
                request_path = attempt / "request.json"
                _new_json(request_path, request)
                inputs_unchanged()
                if previous_build:
                    for source, output in zip(previous_build["models"], outputs):
                        _timeout(config, cutoff)
                        shutil.copyfile(relative(root, source["path"]), relative(root, output["path"]))
                    operation = "reused_build"
                elif data["build"]["mode"] == "blender":
                    result = blender.script_run(config, root, source=data["build"]["source"]["path"],
                                                script=data["build"]["builder"]["path"],
                                                label=f"factory-{digest([run_id, attempt.name])[:24]}",
                                                timeout=_timeout(config, cutoff), results=[m["path"] for m in outputs],
                                                passthrough=["--factory-request", request_path.relative_to(root).as_posix()])
                    _new_json(attempt / "build-execution.json", result)
                    if result.get("run_dir"):
                        native_run = Path(result["run_dir"]).resolve()
                        if not native_run.is_relative_to(root):
                            raise StudioError("Blender run evidence escaped the project")
                        external_evidence = _inventory(root, native_run)
                    if result.get("ok") is not True:
                        raise StudioError("Blender build did not complete successfully")
                    operation = "exported"
                else:
                    for source, output in zip(data["build"]["models"], outputs):
                        _timeout(config, cutoff)
                        shutil.copyfile(relative(root, source["path"]), relative(root, output["path"]))
                    operation = "reused"
                inputs_unchanged()
                models = [{**m, "sha256": sha256(relative(root, m["path"]))} for m in outputs]
                build_evidence = _inventory(root, build_dir) + [file_record(root, request_path)] + external_evidence
                if (attempt / "build-execution.json").is_file():
                    build_evidence.append(file_record(root, attempt / "build-execution.json"))
                origin = None
                if previous_build:
                    origin = {"build": file_record(root, previous_attempt / "build.json"),
                              "operation": previous_build.get("original_operation", previous_build["operation"])}
                    build_evidence += [origin["build"], *previous_build["evidence"]]
                _checkpoint(root, attempt, "build", {"operation": operation, "models": models, "origin": origin,
                          "original_operation": origin["operation"] if origin else operation, "evidence": build_evidence})
                qa_manifest = attempt / "model-qa.json"
                _new_json(qa_manifest, {"schema_version": 1, "structure": data["structure"],
                                        "living": data["ecology"]["living"], "ground_y_m": data.get("ground_y_m", 0)})
                qa_dir = attempt / "qa"
                caps = [lod["maximum_triangles"] for lod in data["lods"]]
                args = [str(relative(root, m["path"])) for m in models]
                args += ["--out", str(qa_dir), "--manifest", str(qa_manifest), "--budget-tris",
                         str(max(caps)) if all(c is not None for c in caps) else "not-set",
                         "--timeout", str(_timeout(config, cutoff))]
                binary = executable(config, "blender")
                if binary:
                    args += ["--blender", binary]
                else:
                    # Do not inherit an unbound MODEL_QA_BLENDER environment override.
                    args += ["--blender", str(attempt / "unavailable-blender")]
                dependencies = config.get("model_qa_python_site_packages")
                args += ["--python-site-packages", str(dependencies or "")]
                if not data["ecology"]["living"]:
                    args += ["--ecology", "none", "--reason", data["ecology"]["reason"]]
                elif data["ecology"]["reference"]:
                    args += ["--ecology", str(relative(root, data["ecology"]["reference"]["path"]))]
                distances = [lod["switch_distance_m"] for lod in data["lods"]]
                if all(d is not None for d in distances):
                    args += ["--switch-distances", *map(str, distances)]
                inputs_unchanged()
                args[args.index("--timeout") + 1] = str(_timeout(config, cutoff))
                code = model_qa.main(args)
                _new_json(attempt / "qa-return.json", {"returncode": code})
                report, execution = read_json(qa_dir / "report.json"), read_json(qa_dir / "execution.json")
                _verify_records(root, [{k: m[k] for k in ("path", "sha256")} for m in models])
                qa = _qa_gate(data, models, report, execution, code)
                _new_json(attempt / "qa-gate.json", qa)
                sizes = []
                for model in models:
                    inputs_unchanged()
                    output = attempt / "size" / f"lod{model['level']}.json"
                    blender.inspect({**config, "timeout": _timeout(config, cutoff)}, relative(root, model["path"]), output,
                                    rest_pose=True)
                    sizes.append(_size_row(root, data, model["level"], output))
                _new_json(attempt / "size-gate.json", sizes)
                inputs_unchanged()
                _verify_records(root, [{k: m[k] for k in ("path", "sha256")} for m in models])
                candidate = {"operation": operation, "models": models, "qa": qa, "size": sizes,
                             "group_sha256": digest([{k: m[k] for k in ("level", "sha256")} for m in models])}
                evidence = _inventory(root, attempt) + external_evidence + build_evidence
                finish = {"completed": True, "qualified": qa["ok"] and all(s["result"] == "PASS" for s in sizes),
                          "candidate": candidate, "evidence": evidence}
                _checkpoint(root, attempt, "finish", finish)
            except (Exception, KeyboardInterrupt) as exc:
                failure = {"completed": False, "status": "UNMEASURED", "error_type": type(exc).__name__,
                           "reason": str(exc) if isinstance(exc, StudioError) else "Operation did not complete; inspect preserved local evidence",
                           "evidence": _inventory(root, attempt) + external_evidence + build_evidence}
                if not (attempt / "finish.json").exists():
                    _checkpoint(root, attempt, "finish", failure)
                else:
                    _new_json(attempt / "finalization-failure.json", failure)
                return {"ok": False, "status": "failed", "run_id": run_id, "attempt": attempt.name, "failure": failure}

        inputs_unchanged()
        candidate = _verified_candidate(root, attempt, data, finish)
        bundle = read_json(relative(root, approvals)) if approvals else None
        model_identities = [{k: model[k] for k in ("level", "sha256")} for model in candidate["models"]]
        review = _approval_gates(root, data, brief_sha, candidate["group_sha256"], model_identities, bundle)
        reasons = list(candidate["qa"]["reasons"]) + review["reasons"]
        reasons += [f"LOD{s['level']} size: {s['result']}" for s in candidate["size"] if s["result"] != "PASS"]
        manifest = {"schema_version": 1, "kind": "model-factory-group", "id": data["id"], "version": data["version"],
                    "brief": identity["brief"], "concept": data.get("concept"), "policy": data["policy"], "ecology": data["ecology"],
                    "group_sha256": candidate["group_sha256"], "models": candidate["models"], "lods": data["lods"],
                    "size_m": data["size_m"], "tolerance_m": data["tolerance_m"], "operation": candidate["operation"],
                    "qa": candidate["qa"], "size": candidate["size"], "review": review, "approval_bundle": bundle,
                    "trust_limit": TRUST_LIMIT}
        review_dir = attempt / f"review-{len(list(attempt.glob('review-*'))) + 1}"
        review_dir.mkdir(exist_ok=False)
        _new_json(review_dir / "manifest.json", manifest)
        result = {"ok": not reasons, "status": "blocked" if reasons else "ready", "published": False,
                  "run_id": run_id, "attempt": attempt.name, "operation": candidate["operation"],
                  "group_sha256": candidate["group_sha256"], "manifest": file_record(root, review_dir / "manifest.json"),
                  "reasons": reasons, "review": review}
        publication = run / "publication"
        if publication.exists():
            receipt_path = publication / "receipt.json"
            receipt = read_json(receipt_path) if receipt_path.is_file() else None
            intent = read_json(publication / "intent.json") if (publication / "intent.json").is_file() else None
            confirmation = read_json(publication / "confirmation.json") if (publication / "confirmation.json").is_file() else None
            if receipt and intent and confirmation and receipt.get("published") is True and receipt.get("idempotency_key") == intent.get("idempotency_key") and receipt.get("group_sha256") == candidate["group_sha256"] and _text(receipt.get("remote_ref")):
                _verify_records(root, [confirmation["receipt"], confirmation["intent"]])
                _verify_records(root, [intent["manifest"]])
                published_manifest = read_json(relative(root, intent["manifest"]["path"]))
                original_review = _approval_gates(root, data, brief_sha, candidate["group_sha256"], model_identities, published_manifest["approval_bundle"])
                result["reasons"].extend(original_review["reasons"])
                result.update(ok=not result["reasons"], status="published" if not result["reasons"] else "blocked", published=True,
                              publication_receipt=receipt, publication_confirmation=file_record(root, publication / "confirmation.json"))
            else:
                result.update(ok=False, status="publication_uncertain")
                result["reasons"].append("Existing sending intent is unresolved; automatic publication retry is forbidden")
        elif publish and not reasons:
            if not callable(publication_callback):
                raise StudioError("publish=True requires an explicit trusted publication callback")
            _timeout(config, cutoff)
            inputs_unchanged()
            if _verified_candidate(root, attempt, data, finish) != candidate:
                raise StudioError("Factory candidate changed before publication")
            # Check approval evidence again immediately before the durable sending intent.
            current_review = _approval_gates(root, data, brief_sha, candidate["group_sha256"], model_identities, bundle)
            if not current_review["ok"]:
                raise StudioError("Approval evidence changed before publication")
            key = digest({"brief_sha256": brief_sha, "group_sha256": candidate["group_sha256"], "id": data["id"], "version": data["version"]})
            publication.mkdir(exist_ok=False)
            _new_json(publication / "intent.json", {"status": "sending", "idempotency_key": key,
                      "group_sha256": candidate["group_sha256"], "manifest": result["manifest"],
                      "started_utc": datetime.now(timezone.utc).isoformat()})
            try:
                receipt = publication_callback(manifest, key)
                if not isinstance(receipt, dict) or receipt.get("published") is not True or receipt.get("idempotency_key") != key or receipt.get("group_sha256") != candidate["group_sha256"] or not _text(receipt.get("remote_ref")):
                    raise StudioError("Publication callback returned an ambiguous receipt")
                _new_json(publication / "receipt.json", receipt)
                _new_json(publication / "confirmation.json", {"receipt": file_record(root, publication / "receipt.json"),
                          "intent": file_record(root, publication / "intent.json")})
                result.update(status="published", published=True, publication_receipt=receipt,
                              publication_confirmation=file_record(root, publication / "confirmation.json"))
            except (Exception, KeyboardInterrupt) as exc:
                _new_json(publication / "uncertain.json", {"status": "uncertain", "error_type": type(exc).__name__,
                          "idempotency_key": key, "reason": "Sending may have occurred; reconcile externally, never retry automatically"})
                result.update(ok=False, status="publication_uncertain")
                result["reasons"].append("Publication outcome is uncertain; automatic retry is forbidden")
        _new_json(review_dir / "result.json", result)
        return result
