"""Immutable fieldbook attempts, isolated native fixtures and append-only evidence.

The fixture adapter belongs to the project. Kit owns identity, launch lifecycle
and publication, and never supplies a gameplay or human acceptance verdict.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import urllib.request
import zlib

from .common import (StudioError, digest, file_record, kit_identity,
                     outside_package, read_json, relative, safe_id, sha256, write_json)
from .config import require_executable
from .launch import execute as launch


def request(url, route, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Review-Token"] = token
    req = urllib.request.Request(url.rstrip("/") + route,
                                 data=json.dumps(body, allow_nan=False).encode() if body is not None else None,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except (OSError, ValueError) as exc:
        raise StudioError(f"Fieldbook request failed: {route.split('?')[0]}") from exc


def resolve(catalog, identity, selected=True):
    matches = [a for a in catalog["attempts"] if a["id"] == identity["attempt_id"]]
    if len(matches) != 1:
        raise StudioError("Attempt is absent or ambiguous")
    attempt = matches[0]
    if attempt["sha256"] != identity["sha256"] or attempt["model_id"] != identity["model_id"]:
        raise StudioError("Attempt identity does not match immutable fieldbook bytes")
    target = identity["target"]
    if target not in attempt["targets"]:
        raise StudioError("Attempt does not contain the requested target")
    key = attempt["id"] + ":" + target
    review = catalog["reviews"].get(key)
    if selected and (catalog["baselines"].get(attempt["model_id"] + ":" + target) != attempt["id"]
                     or not review or review["status"] != "selected"):
        raise StudioError("Qualification requires the currently selected immutable attempt")
    return attempt, review


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise StudioError("Expected identity must be a lowercase SHA-256")
    return value


def clip_name(attempt, target):
    """Use the fieldbook's verified embedded clip/target order, never a name guess."""
    clips = attempt.get("clips")
    targets = attempt["targets"]
    if (not isinstance(clips, list) or len(clips) != len(targets)
            or len(set(targets)) != len(targets)
            or any(not isinstance(c, dict) or not isinstance(c.get("name"), str)
                   or not c["name"] for c in clips)
            or len({c["name"] for c in clips}) != len(clips)):
        raise StudioError("Qualification requires unambiguous embedded clip/target identities")
    if target not in targets:
        raise StudioError("Qualification target is absent")
    return clips[targets.index(target)]["name"]


def png_dimensions(path):
    """Check a complete PNG container and CRCs before trusting its dimensions."""
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG signature missing")
    offset, dimensions, image_data = 8, None, False
    while offset + 12 <= len(raw):
        size = struct.unpack_from(">I", raw, offset)[0]
        end = offset + 12 + size
        if end > len(raw):
            raise ValueError("PNG chunk truncated")
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:offset + 8 + size]
        if zlib.crc32(kind + data) & 0xffffffff != struct.unpack_from(">I", raw, end - 4)[0]:
            raise ValueError("PNG CRC mismatch")
        if offset == 8:
            if kind != b"IHDR" or size != 13:
                raise ValueError("PNG header missing")
            dimensions = list(struct.unpack_from(">II", data))
        if kind == b"IDAT":
            image_data = True
        if kind == b"IEND":
            if size or end != len(raw) or not image_data:
                raise ValueError("PNG image incomplete")
            return dimensions
        offset = end
    raise ValueError("PNG terminator missing")


def validate_evidence(root, plan, plan_digest, role, observed, folder, native):
    """A result verdict cannot replace actual complete identity-bound evidence."""
    failures = []
    identity = {"role": role, "attempt_id": plan["attempt" if role == "candidate" else "baseline"]["attempt_id"],
                "glb_sha256": plan["attempt" if role == "candidate" else "baseline"]["sha256"],
                "plan_digest": plan_digest}
    if observed.get("identity") != identity or observed.get("native_rendered") is not native:
        failures.append("result identity/render phase mismatch")
    expected_frames = plan["replay"]["frames"]
    replay_path = folder / "replay.jsonl"
    replay_record = observed.get("replay") or {}
    replay_frames = 0
    try:
        if replay_record != {"path": replay_path.relative_to(root).as_posix(),
                             "sha256": sha256(replay_path), "frames": expected_frames}:
            raise ValueError("replay manifest mismatch")
        with replay_path.open(encoding="utf-8") as stream:
            for index, line in enumerate(stream):
                frame = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                if type(frame.get("frame")) is not int or frame["frame"] != index or frame.get("identity") != identity:
                    raise ValueError("replay frame identity/order mismatch")
                replay_frames += 1
        if replay_frames != expected_frames:
            raise ValueError("replay frame count mismatch")
    except (OSError, ValueError, TypeError, AttributeError):
        failures.append("missing, changed, incomplete or incorrectly identified replay")
    captures = observed.get("captures")
    expected_capture_frames = sorted(plan["replay"]["capture_frames"]) if native else []
    if native and not expected_capture_frames:
        failures.append("native capture plan is empty")
    if not isinstance(captures, list) or len(captures) != len(expected_capture_frames):
        failures.append("planned capture count mismatch")
    else:
        for frame, item in zip(expected_capture_frames, captures):
            path = folder / f"frame-{frame:04d}.png"
            try:
                if (item != {"frame": frame, "path": path.relative_to(root).as_posix(),
                             "sha256": sha256(path), "dimensions": plan["settings"]["resolution"]}
                        or png_dimensions(path) != plan["settings"]["resolution"]):
                    raise ValueError("capture manifest/dimensions mismatch")
            except (OSError, ValueError, TypeError):
                failures.append(f"missing, changed or invalid planned capture at frame {frame}")
    return {"ok": not failures, "reasons": failures, "replay_frames": replay_frames,
            "planned_capture_frames": expected_capture_frames, "identity": identity}


def verify(root):
    record = read_json(root / "qualification.json")
    for item in record["files"]:
        path = relative(root, item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise StudioError("Qualification input changed: " + item["path"])
    if digest(record["plan"]) != record["plan_digest"]:
        raise StudioError("Qualification plan changed")
    return record


def prepare(project, plan_path, url):
    root = outside_package(project)
    if root.exists():
        raise StudioError("Qualification destination must not exist; preserve earlier evidence")
    plan = read_json(plan_path)
    safe_id(plan["id"])
    _hash(plan["engine"]["sha256"])
    if not re.fullmatch("[0-9a-f]{40}", plan["source_commit"]):
        raise StudioError("Source must name a committed revision")
    for name, value in plan["thresholds"].items():
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise StudioError("Thresholds must be finite nonnegative numbers: " + name)
    replay = plan["replay"]
    if (type(replay["frames"]) is not int or not 1 <= replay["frames"] <= 3600
            or type(replay["warmup_frames"]) is not int or not 0 <= replay["warmup_frames"] < replay["frames"]
            or not isinstance(replay["capture_frames"], list) or not replay["capture_frames"]
            or any(type(frame) is not int or not 0 <= frame < replay["frames"] for frame in replay["capture_frames"])
            or len(set(replay["capture_frames"])) != len(replay["capture_frames"])):
        raise StudioError("Replay requires bounded integer frames and distinct planned captures")
    if plan["settings"] != {"resolution": [1920, 1080], "renderer": "forward_plus", "physics_hz": 60}:
        raise StudioError("Qualification requires the matched native launch settings")
    catalog = request(url, "/api/catalog")
    attempt, review = resolve(catalog, plan["attempt"])
    baseline, _ = resolve(catalog, plan["baseline"], selected=False)
    resolved_clips = {"candidate": clip_name(attempt, plan["attempt"]["target"]),
                      "baseline": clip_name(baseline, plan["baseline"]["target"])}
    if "clip_names" in plan and plan["clip_names"] != resolved_clips:
        raise StudioError("Requested clips differ from the immutable fieldbook target mapping")
    plan["clip_names"] = resolved_clips
    model = next(m for m in catalog["models"] if m["id"] == attempt["model_id"])
    if model["current_game_sha256"] != baseline["sha256"]:
        raise StudioError("Matched baseline must be the current game pin")
    # Validate all copied source bytes before creating the destination.
    inputs = []
    for item in plan["inputs"]:
        dest = relative(root, item["path"])
        source = Path(item["source"]).resolve()
        if not source.is_file() or sha256(source) != _hash(item["sha256"]):
            raise StudioError("Pinned fixture input is missing or changed: " + item["path"])
        if source == root or source.is_relative_to(root):
            raise StudioError("Fixture sources must be outside the new destination")
        if item.get("git_path"):
            # Read committed bytes, never claim a mutable worktree is a release.
            repo = str(Path(plan["source_repository"]).resolve())
            try:
                committed = subprocess.check_output(
                    ["git", "-c", "safe.directory=" + repo, "-C", repo,
                     "show", plan["source_commit"] + ":" + item["git_path"]], stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as exc:
                raise StudioError("Cannot resolve pinned source commit") from exc
            if committed != source.read_bytes():
                raise StudioError("Fixture source differs from declared game commit")
        inputs.append((dest, source.read_bytes()))
    assets = []
    for role, asset in (("candidate", attempt), ("baseline", baseline)):
        path = "/blobs/" + _hash(asset["sha256"]) + ".glb"
        with urllib.request.urlopen(url.rstrip("/") + path, timeout=30) as response:
            data = response.read()
        import hashlib
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise StudioError("Fieldbook blob hash mismatch")
        assets.append((relative(root, "assets/" + role + ".glb"), data))
    destinations = [p for p, _ in inputs + assets]
    reserved = [root / "qualification.json", root / "catalog-before.json"]
    if len(set(destinations)) != len(destinations) or any(p in reserved or p.is_relative_to(root / "artifacts") for p in destinations):
        raise StudioError("Fixture input destinations collide with each other or owned evidence")
    root.mkdir(parents=True)
    for path, data in inputs + assets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if not (root / "project.godot").is_file() or not relative(root, plan["script"]).is_file():
        raise StudioError("Fixture requires project.godot and the declared adapter")
    write_json(root / "catalog-before.json", catalog)
    record = {"schema_version": 1, "kind": "animation-qualification-inputs",
              "kit": kit_identity(), "plan": plan, "plan_digest": digest(plan),
              "attempt": attempt, "review": review, "baseline": baseline,
              "cursor": catalog["cursor"],
              "files": [file_record(root, p) for p in destinations],
              "acceptance": "pending-human-review"}
    write_json(root / "qualification.json", record)
    return {"ok": True, "project": str(root), "plan_digest": record["plan_digest"],
            "attempt_id": attempt["id"], "ready_for_game": None}


def run(config, project, url, phase, label, cutoff, reservation=None):
    root = outside_package(project)
    record = verify(root)
    plan = record["plan"]
    current = request(url, "/api/catalog")
    attempt, review = resolve(current, plan["attempt"])
    if review != record["review"]:
        raise StudioError("Review changed since preparation; reconcile before running")
    model = next(m for m in current["models"] if m["id"] == attempt["model_id"])
    if model["current_game_sha256"] != record["baseline"]["sha256"]:
        raise StudioError("Game baseline pin changed since preparation")
    if sha256(require_executable(config, "godot")) != plan["engine"]["sha256"]:
        raise StudioError("Pinned engine mismatch")
    label = safe_id(label)
    if phase == "native" and not reservation:
        raise StudioError("Native qualification needs a parent-coordinated resource reservation receipt")
    reservation_record = None
    if reservation:
        reservation_record = read_json(reservation)
        from .launch import parse_utc
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if (reservation_record.get("plan_digest") != record["plan_digest"]
                or reservation_record.get("coordinator") is None
                or not parse_utc(reservation_record["start_utc"]) <= now < parse_utc(reservation_record["end_utc"])):
            raise StudioError("Resource reservation does not cover this plan and current time")
        if not cutoff or parse_utc(cutoff) > parse_utc(reservation_record["end_utc"]):
            raise StudioError("Native cutoff must stay within the reservation")
        if phase == "native":
            preflight = read_json(reservation_record["host_preflight"])
            diagnostic_authorization = reservation_record.get("bounded_diagnostic_authorization")
            if (sha256(reservation_record["host_preflight"]) != reservation_record["host_preflight_sha256"] or
                    (not preflight.get("ready") and not diagnostic_authorization)):
                raise StudioError("Native reservation requires a passing pinned host preflight")
            if diagnostic_authorization and (not isinstance(diagnostic_authorization, dict)
                    or not diagnostic_authorization.get("instruction") or not diagnostic_authorization.get("source_thread_id")):
                raise StudioError("Diagnostic exception requires the explicit coordinating instruction and its source")
            window = preflight.get("window") or {}
            if (not window.get("start_utc") or not window.get("end_utc") or
                    parse_utc(window["start_utc"]) > parse_utc(reservation_record["start_utc"]) or
                    parse_utc(window["end_utc"]) < parse_utc(reservation_record["end_utc"])):
                raise StudioError("Host preflight does not cover the reserved window")
            from .cleanroom import snapshot
            snapshot_before = snapshot()
            if snapshot_before.get("process_status") != "ok":
                raise StudioError("Competing process check unavailable; refusing native run")
            if any("godot" in p.get("name", "").lower() or p.get("name", "").lower() in ("blender.exe", "ffmpeg.exe")
                   for p in snapshot_before["processes"]):
                raise StudioError("Competing game/render process detected; it was left untouched")
            if not reservation_record.get("competing_heavy_jobs_verified"):
                raise StudioError("Coordinator must verify no competing heavy job")
    if phase == "import":
        verdict = launch(config, root, sha256_expected=plan["engine"]["sha256"], mode="import",
                         timeout=120, cutoff_utc=cutoff, label=label)
        return verdict
    if phase not in ("cpu", "native"):
        raise StudioError("Qualification phase must be import, cpu or native")
    results = []
    imported = [file_record(root, p) for p in sorted(root.rglob("*.glb.import")) if p.is_file()]
    imported += [file_record(root, p) for p in sorted(root.glob(".godot/imported/*.scn")) if p.is_file()]
    # Each run has its own result/replay/captures. Never overwrite another run.
    for role in ("baseline", "candidate"):
        result = f"artifacts/qualification/{label}-{role}/result.json"
        passthrough = ["--", "--role=" + role, "--output=" + Path(result).parent.as_posix()]
        bench = None
        if phase == "cpu":
            verdict = launch(config, root, sha256_expected=plan["engine"]["sha256"],
                             mode="test", script="res://" + plan["script"],
                             timeout=60, cutoff_utc=cutoff, label=label + "-" + role,
                             scope=plan["id"], results=[result], passthrough=passthrough)
        else:
            from .cleanroom import execute as cleanroom
            host = relative(root, f"artifacts/qualification/{label}-host.json")
            write_json(host, {"executables": {"godot": require_executable(config, "godot")}, "timeout": 60})
            capture = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/studio.py"),
                       "launch", "--project", str(root), "--config", str(host),
                       "--sha256", plan["engine"]["sha256"], "--mode", "native",
                       "--script", "res://" + plan["script"], "--timeout", "60", "--cutoff-utc", cutoff,
                       "--label", label + "-" + role, "--scope", plan["id"], "--result", result] + passthrough
            bench = cleanroom(config, root, capture, label=label + "-" + role,
                             scope=plan["id"], timeout=90)
            verdict = bench["capture"].get("verdict") or {"ok": False}
        results.append({"role": role, "launch": verdict, "cleanroom": bench})
        if not verdict.get("ok"):
            break
    verify(root)
    receipt = {"schema_version": 1, "kind": "animation-qualification-run", "kit": kit_identity(),
               "plan_digest": record["plan_digest"], "attempt_id": attempt["id"],
               "glb_sha256": attempt["sha256"], "phase": phase,
               "reservation": reservation_record, "runs": results,
               "input_record": file_record(root, root / "qualification.json"),
               "import_build": imported, "import_build_digest": digest(imported),
               "files": [], "automated_checks": "failed", "human_visual_review": "pending",
               "performance_qualification": "unverified", "acceptance": "pending"}
    for role_result in results:
        folder = relative(root, f"artifacts/qualification/{label}-{role_result['role']}")
        if folder.is_dir():
            receipt["files"].extend(file_record(root, p) for p in sorted(folder.rglob("*")) if p.is_file())
        for prefix in ("launches", "bench"):
            lifecycle = relative(root, f"artifacts/{prefix}/{label}-{role_result['role']}")
            if lifecycle.is_dir():
                receipt["files"].extend(file_record(root, p) for p in sorted(lifecycle.rglob("*.json"))
                                        if p.is_file() and "profile" not in p.parts)
    passed = len(results) == 2 and all(r["launch"].get("ok") for r in results)
    if any(sha256(relative(root, item["path"])) != item["sha256"] for item in imported):
        passed = False
        receipt["import_build_changed"] = True
    observations = []
    evidence = []
    for role_result in results:
        result_path = relative(root, f"artifacts/qualification/{label}-{role_result['role']}/result.json")
        if result_path.is_file():
            try:
                observed = read_json(result_path)
                if not isinstance(observed, dict):
                    raise StudioError("Adapter result must be an object")
            except StudioError:
                evidence.append({"ok": False, "reasons": ["invalid adapter result"], "role": role_result["role"]})
                passed = False
                continue
            observations.append(observed)
            passed = passed and observed.get("automated_checks") == "passed"
            verified = validate_evidence(root, plan, record["plan_digest"], role_result["role"], observed,
                                         result_path.parent, phase == "native")
            evidence.append(verified)
            passed = passed and verified["ok"]
        else:
            passed = False
    receipt["observations"] = observations
    receipt["evidence_verification"] = evidence
    receipt["evidence_complete"] = len(evidence) == 2 and all(item["ok"] for item in evidence)
    receipt["automated_checks"] = "passed" if passed else "failed"
    if (phase == "native" and receipt["evidence_complete"] and len(results) == 2
            and all(r["cleanroom"].get("ok") for r in results)):
        receipt["performance"] = compare_timing(observations, plan["thresholds"])
        if reservation_record.get("bounded_diagnostic_authorization"):
            receipt["performance_qualification"] = "unverified-host-preflight-diagnostic"
        else:
            receipt["performance_qualification"] = receipt["performance"]["verdict"]
    receipt["ok"] = passed
    receipt["limitations"] = ["Bounded isolated fixture, not whole-game acceptance",
                               "CPU mode has no rendering or GPU performance evidence",
                               "Native timing requires attributable cleanroom evidence before qualification",
                               "Human review and explicit acceptance remain required"]
    dest = relative(root, f"artifacts/qualification/{label}.json")
    if dest.exists():
        raise StudioError("Qualification receipt already exists")
    write_json(dest, receipt)
    return {**receipt, "receipt": str(dest)}


def compare_timing(observations, thresholds):
    """Require real rendered matched samples before applying numerical budgets."""
    summary = []
    for observed in observations:
        if not observed.get("native_rendered"):
            return {"verdict": "unverified", "reason": "non-rendered samples"}
        row = {}
        for key in ("frame_ms", "controller_cpu_ms", "viewport_gpu_ms"):
            values = observed.get("timing", {}).get(key, [])
            if len(values) < 120 or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
                return {"verdict": "unverified", "reason": "missing or invalid timing samples"}
            if key == "viewport_gpu_ms" and max(values) <= 0:
                return {"verdict": "unverified", "reason": "GPU timing unavailable"}
            values = sorted(values)
            row[key + "_p95"] = values[math.ceil(len(values) * 0.95) - 1]
        summary.append(row)
    if len(summary) != 2:
        return {"verdict": "unverified", "reason": "matched baseline/candidate pair missing"}
    required = ("frame_p95_ms", "gpu_p95_ms", "controller_cpu_p95_ms", "max_relative_frame_cost")
    if not all(k in thresholds for k in required):
        return {"verdict": "unverified", "reason": "numerical performance budgets missing"}
    baseline, candidate = summary
    passed = (candidate["frame_ms_p95"] <= thresholds["frame_p95_ms"]
              and candidate["viewport_gpu_ms_p95"] <= thresholds["gpu_p95_ms"]
              and candidate["controller_cpu_ms_p95"] <= thresholds["controller_cpu_p95_ms"]
              and candidate["frame_ms_p95"] <= baseline["frame_ms_p95"] * thresholds["max_relative_frame_cost"])
    return {"verdict": "passed" if passed else "failed", "baseline": baseline, "candidate": candidate}


def attach(project, url, receipt_path, actor):
    root = outside_package(project)
    record = verify(root)
    path = relative(root, receipt_path)
    receipt = read_json(path)
    if (receipt.get("kind") != "animation-qualification-run" or
            receipt.get("plan_digest") != record["plan_digest"] or
            receipt.get("attempt_id") != record["attempt"]["id"] or
            receipt.get("glb_sha256") != record["attempt"]["sha256"]):
        raise StudioError("Receipt belongs to a different immutable attempt or plan")
    for item in receipt["files"]:
        if sha256(relative(root, item["path"])) != item["sha256"]:
            raise StudioError("Qualification evidence changed")
    if receipt.get("input_record") and sha256(relative(root, receipt["input_record"]["path"])) != receipt["input_record"]["sha256"]:
        raise StudioError("Tested input record changed")
    if receipt.get("automated_checks") == "passed" or receipt.get("performance_qualification") == "passed":
        results = [relative(root, item["path"]) for item in receipt["files"] if item["path"].endswith("/result.json")]
        roles = set()
        for result in results:
            observed = read_json(result)
            role = observed.get("identity", {}).get("role")
            if role not in ("baseline", "candidate") or role in roles:
                raise StudioError("Passing evidence requires distinct role identities")
            verified = validate_evidence(root, record["plan"], record["plan_digest"], role,
                                         observed, result.parent, receipt["phase"] == "native")
            if not verified["ok"]:
                raise StudioError("Passing evidence is incomplete or invalid")
            required = [observed["replay"], *observed["captures"]]
            if any(not any(item["path"] == artifact["path"] and item["sha256"] == artifact["sha256"]
                           for item in receipt["files"]) for artifact in required):
                raise StudioError("Passing evidence artifacts missing from receipt hashes")
            roles.add(role)
        if roles != {"baseline", "candidate"} or not receipt.get("evidence_complete"):
            raise StudioError("Passing evidence requires complete capture/replay verification for both roles")
    before = request(url, "/api/catalog")
    attempt, _ = resolve(before, record["plan"]["attempt"])
    if not isinstance(actor, str) or not actor.strip():
        raise StudioError("Evidence publisher must have an actor label")
    metadata = {"actor": actor, "model": next(m for m in before["models"] if m["id"] == attempt["model_id"]),
                "sha256": attempt["sha256"], "label": attempt["label"],
                "session": attempt["session"], "targets": attempt["targets"],
                "provenance": {"location": str(path), "native_qualification": {
                    "receipt_sha256": sha256(path), "plan_digest": record["plan_digest"],
                    "attempt_id": attempt["id"], "phase": receipt["phase"],
                    "automated_checks": receipt["automated_checks"], "human_visual_review": "pending",
                    "performance_qualification": receipt["performance_qualification"], "acceptance": "pending"}}}
    metadata["provenance"]["native_qualification"]["evidence_complete"] = bool(receipt.get("evidence_complete"))
    token = request(url, "/api/session")["token"]
    registered = request(url, "/api/register", metadata, token)
    if not registered.get("existing") or registered["attempt"]["id"] != attempt["id"]:
        raise StudioError("Server did not append evidence to the same existing attempt")
    after = request(url, "/api/catalog")
    unchanged = all(before.get(k) == after.get(k) for k in ("models", "model_aliases", "reviews", "baselines", "notes"))
    history = request(url, "/api/changes?after=" + str(before["cursor"]))
    result = {"ok": unchanged, "attempt_id": attempt["id"], "existing": True,
              "before_cursor": before["cursor"], "after_cursor": after["cursor"],
              "decisions_comments_gamepins_preserved": unchanged, "history": history,
              "receipt": file_record(root, path)}
    publication = relative(root, receipt_path + ".publication.json")
    if publication.exists():
        # Keep the first audit when the same stable provenance is retried.
        publication = relative(root, receipt_path + f".publication-{before['cursor']}-{after['cursor']}.json")
    if not publication.exists():
        write_json(publication, result)
    return result
