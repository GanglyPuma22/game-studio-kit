"""Verify registered source-slot baselines without selecting or publishing a take.

Godot runs are made with Kit's owned ``launch`` command. This module checks
their immutable source, asset, launch, report and capture evidence afterwards.
It intentionally has no fieldbook write path or candidate acceptance verdict.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
import re
import subprocess
import zlib

from .common import StudioError, digest, file_record, kit_identity, outside_package, read_json, relative, safe_id, sha256, write_json
from .qualification import png_dimensions


def _committed(repo: Path, commit: str, path: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not path.startswith("game/") or ".." in Path(path).parts:
        raise StudioError("Baseline source must use a committed game path")
    try:
        return subprocess.check_output(
            ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo), "show", commit + ":" + path],
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise StudioError("Cannot read pinned game source") from exc


def _source_slot(root: Path, repo: Path, commit: str, slot: dict, attempts: dict,
                 models: dict | None = None) -> dict:
    attempt = attempts.get(slot["attempt_id"])
    if not attempt or attempt["model_id"] != slot["model_id"] or attempt["sha256"] != slot["sha256"]:
        raise StudioError("Source slot does not match its registered immutable attempt: " + slot["name"])
    asset_path = relative(root, slot["asset"])
    if not asset_path.is_file() or sha256(asset_path) != slot["sha256"]:
        raise StudioError("Source-slot asset bytes changed: " + slot["name"])
    committed_asset = _committed(repo, commit, "game/" + slot["asset"])
    lfs_oid = re.fullmatch(
        rb"version https://git-lfs.github.com/spec/v1\n"
        rb"oid sha256:([0-9a-f]{64})\nsize (0|[1-9][0-9]*)\n?", committed_asset
    )
    if lfs_oid:
        if (lfs_oid.group(1).decode() != slot["sha256"]
                or int(lfs_oid.group(2)) != asset_path.stat().st_size):
            raise StudioError("Committed LFS pointer differs from source-slot bytes: " + slot["name"])
        committed_proof = "lfs-oid"
    elif hashlib.sha256(committed_asset).hexdigest() == slot["sha256"]:
        committed_proof = "full-git-blob"
    else:
        raise StudioError("Committed game asset differs from source-slot bytes: " + slot["name"])
    result = {"name": slot["name"], "model_id": slot["model_id"],
              "attempt_id": slot["attempt_id"], "asset": file_record(root, asset_path),
              "runtime_slot": bool(slot.get("runtime_slot", True)),
              "committed_asset_proof": committed_proof}
    if models is not None:
        model = models.get(slot["model_id"])
        if model is None:
            raise StudioError("Baseline slot model is absent from the fieldbook")
        pinned_sha = model.get("current_game_sha256")
        pinned_path = model.get("current_game_path")
        result["catalog_current_pin"] = {"sha256": pinned_sha, "path": pinned_path}
        result["matches_catalog_current_sha256"] = pinned_sha == slot["sha256"]
        result["matches_catalog_current_path"] = pinned_path == "res://" + slot["asset"]
        if slot.get("catalog_current") and not (result["matches_catalog_current_sha256"]
                                                and result["matches_catalog_current_path"]):
            raise StudioError("Claimed catalog-current slot differs from the fieldbook pin")
    if not result["runtime_slot"]:
        if any(key in slot for key in ("source", "sha_constant", "path_constant")):
            raise StudioError("Catalog-only comparison cannot impersonate a runtime source slot")
        return result
    source_path = relative(root, slot["source"])
    if not source_path.is_file():
        raise StudioError("Runtime source file missing: " + slot["name"])
    committed = _committed(repo, commit, slot["git_path"])
    checkout = source_path.read_bytes()
    if checkout != committed and checkout.replace(b"\r\n", b"\n") != committed.replace(b"\r\n", b"\n"):
        raise StudioError("Runtime source differs from pinned commit: " + slot["name"])
    source = committed.decode("utf-8")
    for constant, expected in ((slot["sha_constant"], slot["sha256"]),
                               (slot["path_constant"], "res://" + slot["asset"])):
        match = re.search(r"(?m)^const " + re.escape(constant) + r'\s*:=\s*"([^"]+)"', source)
        if not match or match.group(1) != expected:
            raise StudioError("Pinned runtime source does not name this asset slot: " + slot["name"])
    result["source"] = {"path": slot["source"], "git_path": slot["git_path"],
                        "committed_sha256": hashlib.sha256(committed).hexdigest(),
                        "copied_sha256": sha256(source_path), "line_endings_normalized": checkout != committed}
    return result


def _value(data: dict, path: str):
    value = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise StudioError("Baseline report lacks required value: " + path)
        value = value[part]
    return value


def _equal(actual, expected):
    """JSON equality preserves types, including inside lists and objects."""
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _checks(report: dict, rules: dict) -> None:
    if (not isinstance(rules, dict) or not (
            any(rules.get(kind) for kind in ("equal", "minimum", "maximum"))
            or any(item.get("required") for item in rules.get("coverage", [])))):
        raise StudioError("Baseline requires at least one functional assertion")
    for path, expected in rules.get("equal", {}).items():
        if not _equal(_value(report, path), expected):
            raise StudioError("Baseline report equality check failed: " + path)
    for comparison in ("minimum", "maximum"):
        for path, bound in rules.get(comparison, {}).items():
            value = _value(report, path)
            if (type(value) not in (int, float) or type(bound) not in (int, float)
                    or not math.isfinite(value) or not math.isfinite(bound)
                    or (value < bound if comparison == "minimum" else value > bound)):
                raise StudioError("Baseline report numerical check failed: " + path)
    for coverage in rules.get("coverage", []):
        items = _value(report, coverage["path"])
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise StudioError("Baseline state coverage is not a list of records")
        field = coverage["field"]
        if any(field not in item for item in items):
            raise StudioError("Baseline state coverage lacks required field: " + field)
        observed = [item[field] for item in items]
        if any(not any(_equal(value, required) for value in observed) for required in coverage["required"]):
            raise StudioError("Baseline state coverage is incomplete: " + coverage["path"])


def _time(value, label):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed
    except (AttributeError, TypeError, ValueError) as exc:
        raise StudioError("Invalid baseline timestamp: " + label) from exc


def _engine_platform(raw: bytes) -> str:
    """Use pinned executable bytes, never missing ownership, to select proof."""
    header = raw[:64]
    if header[:2] == b"MZ" and len(header) == 64:
        offset = int.from_bytes(header[60:64], "little")
        if raw[offset:offset + 4] == b"PE\x00\x00":
            return "windows"
    if header[:4] in (b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                       b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
                       b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
                       b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
        return "posix"
    raise StudioError("Baseline engine platform cannot be verified from executable bytes")


def _fixture_inputs(root: Path, repo: Path, commit: str, run: dict) -> list:
    extra = run.get("fixture_inputs", [])
    if not isinstance(extra, list) or any(not isinstance(name, str) or not name for name in extra):
        raise StudioError("Baseline fixture inputs must be project-relative file paths")
    names = list(dict.fromkeys(["project.godot", run["script"].removeprefix("res://"), *extra]))
    records = []
    for name in names:
        path = relative(root, name)
        committed = _committed(repo, commit, "game/" + name)
        if not path.is_file():
            raise StudioError("Baseline fixture input is missing: " + name)
        copied = path.read_bytes()
        pointer = re.fullmatch(rb"version https://git-lfs.github.com/spec/v1\n"
                               rb"oid sha256:([0-9a-f]{64})\nsize (0|[1-9][0-9]*)\n?", committed)
        if pointer:
            matches = pointer.group(1).decode() == sha256(path) and int(pointer.group(2)) == len(copied)
        else:
            text = path.suffix in (".godot", ".gd", ".tscn", ".tres", ".json", ".cfg")
            matches = copied == committed or (text and copied.replace(b"\r\n", b"\n") == committed.replace(b"\r\n", b"\n"))
        if not matches:
            raise StudioError("Baseline fixture input differs from pinned game commit: " + name)
        records.append({**file_record(root, path), "committed_sha256": hashlib.sha256(committed).hexdigest()})
    return records


def _run(root: Path, repo: Path, commit: str, run: dict, engine_sha256: str,
         producer_kit: dict, retained: dict, process_platform: str) -> dict:
    if process_platform not in ("windows", "posix"):
        raise StudioError("Baseline process platform is unverified")
    if run.get("mode") not in ("test", "native"):
        raise StudioError("Baseline fixture mode must be test or native")
    safe_id(run.get("scope"))
    folder = "artifacts/launches/" + run["label"] + "/"
    exit_path = relative(root, "artifacts/launches/" + run["label"] + "/exit.json")
    exit_record = read_json(exit_path)
    if (exit_record.get("schema_version") != 1 or exit_record.get("kind") != "launch-exit"
            or exit_record.get("kit") != producer_kit
            or exit_record.get("ok") is not True or exit_record.get("verdict") != "completed"
            or exit_record.get("status") != "completed" or exit_record.get("returncode") != 0
            or exit_record.get("timed_out") is not False
            or exit_record.get("cleanup") is not None
            or exit_record.get("label") != run["label"]
            or exit_record.get("scope") != run["scope"]
            or exit_record.get("survivors", {}).get("status") != "ok"
            or exit_record.get("survivors", {}).get("stopped") is not True
            or exit_record.get("survivors", {}).get("pids") != []
            or exit_record.get("survivors", {}).get("unstopped_pids", [] if process_platform == "posix" else None) != []
            or exit_record.get("survivors", {}).get("unverified") != []):
        raise StudioError("Owned Godot launch did not finish cleanly: " + run["label"])
    launch_path = relative(root, folder + "owned-launch.json")
    if not launch_path.is_file() or sha256(launch_path) != run.get("owned_launch_sha256"):
        raise StudioError("Retained owned launch bytes changed: " + run["label"])
    launch = read_json(launch_path)
    if (launch.get("schema_version") != 1 or launch.get("kind") != "owned-launch"
            or launch.get("kit") != producer_kit or launch.get("status") != "launched"
            or launch.get("label") != run["label"] or launch.get("scope") != run["scope"] or
            Path(launch.get("project", "")).resolve() != root.resolve() or
            launch.get("mode") != run["mode"] or launch.get("script") != run["script"] or
            type(launch.get("passthrough_count")) is not int or launch["passthrough_count"] != 0 or
            launch.get("engine", {}).get("sha256") != engine_sha256 or
            launch.get("engine", {}).get("sha256_after_exit") != engine_sha256 or
            launch.get("survivors") != exit_record.get("survivors") or
            launch.get("process_record") != "process/process.json"):
        raise StudioError("Owned Godot launch differs from the pinned fixture: " + run["label"])
    process_path = relative(root, folder + launch["process_record"])
    if not process_path.is_file() or sha256(process_path) != run.get("process_sha256"):
        raise StudioError("Retained process receipt bytes changed: " + run["label"])
    process = read_json(process_path)
    ownership = process.get("windows_ownership", {})
    if (process.get("schema_version") != 1 or process.get("status") != "completed"
            or process.get("returncode") != 0 or process.get("pid") != launch.get("pid")
            or type(process.get("pid")) is not int or process["pid"] <= 0
            or process.get("cleanup") is not None
            or process.get("elapsed_seconds") != exit_record.get("elapsed_seconds")):
        raise StudioError("Owned Godot process receipt does not pair with launch: " + run["label"])
    if process_platform == "windows":
        if (not isinstance(ownership, dict) or ownership.get("status") != "ok"
                or ownership.get("identity", {}).get("pid") != launch.get("pid")
                or ownership.get("identity", {}).get("name") != launch.get("engine", {}).get("name")
                or not ownership.get("identity", {}).get("created_filetime")
                or not ownership.get("identity", {}).get("exited_filetime")):
            raise StudioError("Windows process ownership is unverified: " + run["label"])
    elif "windows_ownership" in process:
        raise StudioError("POSIX process receipt contains incompatible Windows ownership")
    started = _time(launch.get("started_utc"), "launch started")
    process_started = _time(process.get("started_utc"), "process started")
    process_finished = _time(process.get("finished_utc"), "process finished")
    finished = _time(exit_record.get("finished_utc"), "launch finished")
    cutoff = _time(launch.get("cutoff_utc"), "launch cutoff")
    timeout = launch.get("timeout_seconds_effective")
    if (not started <= process_started <= process_finished <= finished <= cutoff
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
            or (process_finished - process_started).total_seconds() > timeout + 5):
        raise StudioError("Owned Godot process exceeded its bounded launch: " + run["label"])
    if not run["script"].startswith("res://"):
        raise StudioError("Baseline fixture script must be project-relative")
    script_name = run["script"].removeprefix("res://")
    fixture_inputs = _fixture_inputs(root, repo, commit, run)
    reservation = None
    if run["mode"] == "native":
        pin = run.get("reservation")
        if not isinstance(pin, dict):
            raise StudioError("Native baseline requires its resource reservation")
        reservation_path = Path(pin["path"]).resolve()
        if sha256(reservation_path) != pin["sha256"]:
            raise StudioError("Native resource reservation changed")
        reservation = read_json(reservation_path)
        checked = _time(reservation.get("checked_utc"), "reservation checked")
        ending = _time(reservation.get("window_end_utc"), "reservation ended")
        age = (started - checked).total_seconds()
        if (not 0 <= age <= 300 or finished > ending
                or reservation.get("process_status") != "ok"
                or reservation.get("competing_godot_blender_ffmpeg") != []
                or reservation.get("competing_heavy_jobs_verified") is not True
                or reservation.get("host_ready") is not True):
            raise StudioError("Native resource reservation did not cover this launch")
    report_path = relative(root, run["report"])
    report = read_json(report_path)
    if launch.get("expected_results") != [run["report"]]:
        raise StudioError("Baseline report was not declared to the owned launch: " + run["label"])
    if not any(item.get("path") == run["report"] and item.get("sha256") == sha256(report_path)
               and item.get("present") is True and item.get("stale") is False
               and item.get("unreadable") is False and item.get("escaped") is False
               for item in exit_record.get("result_files", [])):
        raise StudioError("Baseline report is not the owned launch result: " + run["label"])
    _checks(report, run["checks"])
    if run["captures"] and not run.get("capture_report"):
        raise StudioError("Claimed baseline captures require a complete report manifest")
    if run.get("capture_report"):
        declared = _value(report, run["capture_report"])
        entries = list(declared.values()) if isinstance(declared, dict) else declared
        if (not isinstance(entries, list) or len(entries) != len(run["captures"])
                or any(not isinstance(item, dict) or type(item.get("save_error")) is not int
                       or item["save_error"] != 0 for item in entries)):
            raise StudioError("Native baseline capture manifest is incomplete: " + run["label"])
        paths = set()
        for item in entries:
            name = item.get("path")
            if not isinstance(name, str):
                raise StudioError("Native baseline capture path is invalid")
            if name.startswith("res://"):
                paths.add(name.removeprefix("res://"))
            else:
                path = Path(name).resolve()
                if not path.is_relative_to(root):
                    raise StudioError("Native baseline capture escaped the project")
                paths.add(path.relative_to(root).as_posix())
        if paths != set(run["captures"]):
            raise StudioError("Native baseline captures differ from report: " + run["label"])
    captures = []
    for name in run["captures"]:
        capture = relative(root, name)
        try:
            dimensions = png_dimensions(capture)
        except (OSError, ValueError, zlib.error) as exc:
            raise StudioError("Native baseline capture is missing or invalid: " + name) from exc
        if dimensions != [1920, 1080]:
            raise StudioError("Native baseline capture dimensions changed: " + name)
        captures.append(file_record(root, capture))
    if len(captures) != len(set(run["captures"])):
        raise StudioError("Baseline capture plan repeats a path")
    result = {"name": run["name"], "scope": run["scope"], "launch": file_record(root, exit_path),
            "owned_launch": file_record(root, launch_path), "process": file_record(root, process_path),
            "fixture_source_sha256": hashlib.sha256(_committed(repo, commit, "game/" + script_name)).hexdigest(),
            "fixture_inputs": fixture_inputs,
            "process_platform": process_platform,
            "resource_reservation": {"sha256": pin["sha256"], "checked_utc": reservation["checked_utc"],
                                     "host_ready": reservation.get("host_ready")}
            if reservation is not None else None,
            "report": file_record(root, report_path), "captures": captures,
            "functional_checks": "passed", "human_visual_review": "pending",
            "performance_qualification": "unverified", "selected_animation_qualification": "not_attempted"}
    if any(result[key] != retained.get(key) for key in
           ("scope", "launch", "owned_launch", "process", "fixture_source_sha256", "fixture_inputs",
            "report", "captures")):
        raise StudioError("Retained run or capture bytes differ from historical evidence: " + run["label"])
    return result


def verify(project, manifest_path, receipt_path):
    """Fail closed on input/evidence drift; write one local baseline-only receipt."""
    root = outside_package(project)
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "source-context-baseline":
        raise StudioError("Expected source-context baseline manifest v1")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", "")):
        raise StudioError("Baseline manifest needs an exact game commit")
    for collection in ("slots", "runs"):
        if not isinstance(manifest.get(collection), list) or not manifest[collection]:
            raise StudioError("Baseline requires nonempty " + collection)
    for collection, key in (("slots", "name"), ("runs", "name"), ("runs", "label")):
        values = [item.get(key) for item in manifest[collection] if isinstance(item, dict)]
        if (len(values) != len(manifest[collection]) or any(not isinstance(value, str) or not value for value in values)
                or len(set(values)) != len(values)):
            raise StudioError("Baseline " + collection + " " + key + " values must be distinct nonempty strings")
    for run in manifest["runs"]:
        safe_id(run.get("scope"))
    repo = Path(manifest["source_repository"]).resolve()
    catalog_path = Path(manifest["catalog_snapshot"]).resolve()
    catalog_bytes = catalog_path.read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != manifest["catalog_sha256"]:
        raise StudioError("Fieldbook catalog snapshot changed")
    try:
        catalog = json.loads(catalog_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise StudioError("Fieldbook catalog snapshot is invalid JSON") from exc
    if not isinstance(catalog, dict):
        raise StudioError("Fieldbook catalog snapshot must be an object")
    for collection in ("attempts", "models"):
        entries = catalog.get(collection)
        if not isinstance(entries, list):
            raise StudioError("Baseline catalog " + collection + " must be a list")
        ids = [item.get("id") for item in entries if isinstance(item, dict)]
        if (len(ids) != len(entries) or any(not isinstance(value, str) or not value for value in ids)
                or len(set(ids)) != len(ids)):
            raise StudioError("Baseline catalog " + collection + " IDs must be distinct nonempty strings")
    attempts = {attempt["id"]: attempt for attempt in catalog["attempts"]}
    models = {model["id"]: model for model in catalog["models"]}
    engine = Path(manifest["engine"]["path"]).resolve()
    engine_bytes = engine.read_bytes()
    if hashlib.sha256(engine_bytes).hexdigest() != manifest["engine"]["sha256"]:
        raise StudioError("Baseline engine executable hash changed")
    process_platform = _engine_platform(engine_bytes)
    pin = manifest.get("retained_evidence")
    if not isinstance(pin, dict):
        raise StudioError("Baseline requires pinned retained run evidence")
    retained_path = relative(root, pin["path"])
    if sha256(retained_path) != pin.get("sha256"):
        raise StudioError("Retained run evidence bytes changed")
    retained = read_json(retained_path)
    original_plan = {key: value for key, value in manifest.items()
                     if key not in ("producer_kit", "retained_evidence")}
    original_plan["runs"] = [{key: value for key, value in run.items()
                              if key not in ("owned_launch_sha256", "process_sha256")}
                             for run in manifest["runs"]]
    if (retained.get("kind") != "source-context-baseline-evidence"
            or retained.get("manifest_digest") != digest(original_plan)
            or retained.get("source_commit") != manifest["source_commit"]
            or retained.get("engine_sha256") != manifest["engine"]["sha256"]
            or retained.get("catalog_snapshot") != {"cursor": catalog["cursor"],
                                                    "sha256": manifest["catalog_sha256"]}
            or retained.get("ok") is not True):
        raise StudioError("Retained run evidence differs from pinned source or engine")
    retained_runs = {item["name"]: item for item in retained["runs"]}
    if (len(retained_runs) != len(retained["runs"])
            or set(retained_runs) != {run["name"] for run in manifest["runs"]}):
        raise StudioError("Retained run evidence does not cover the baseline plan")
    slots = [_source_slot(root, repo, manifest["source_commit"], slot, attempts, models)
             for slot in manifest["slots"]]
    if len({slot["name"] for slot in slots}) != len(slots):
        raise StudioError("Baseline context slot names must be distinct")
    runs = [_run(root, repo, manifest["source_commit"], run, manifest["engine"]["sha256"],
                 manifest["producer_kit"], retained_runs[run["name"]], process_platform)
            for run in manifest["runs"]]
    if len({run["name"] for run in runs}) != len(runs):
        raise StudioError("Baseline run names must be distinct")
    receipt = {"schema_version": 1, "kind": "source-context-baseline-evidence",
               "kit": kit_identity(), "producer_kit": manifest["producer_kit"],
               "retained_evidence": file_record(root, retained_path),
               "manifest_digest": digest(manifest), "source_commit": manifest["source_commit"],
               "catalog_snapshot": {"cursor": catalog["cursor"], "sha256": manifest["catalog_sha256"]},
               "engine_sha256": manifest["engine"]["sha256"], "slots": slots, "runs": runs,
               "selected_animation_qualification": "not_attempted", "fieldbook_mutation": False,
               "performance_qualification": "unverified", "human_visual_review": "pending",
               "acceptance": "pending", "ok": True}
    dest = relative(root, receipt_path)
    if dest.exists():
        raise StudioError("Baseline evidence receipt already exists")
    write_json(dest, receipt)
    return {"ok": True, "receipt": str(dest), "slots": len(slots), "runs": len(runs)}
