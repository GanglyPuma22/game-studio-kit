"""Owned, time-bounded engine launch that blocks and returns one verdict.

A calling agent runs this once and reads the returned verdict. It never polls,
sleeps or writes to the child's stdin. Receipts follow the process lifecycle
rules: no argv values or environment, UTC timestamps, monotonic elapsed time,
and a process record that is distinct from engine success.
"""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from .adapters.godot import classify_log, self_contained
from .common import StudioError, outside_package, read_json, relative, safe_id, sha256, write_json
from .config import app_path, require_executable
from .processes import run, stop_survivors

MODES = ("import", "test", "check", "native")
MAX_TIMEOUT = 3600
# Windows environment names are case-insensitive; tests set this flag directly
# because patching os.name would also change how pathlib parses every path.
IS_WINDOWS = os.name == "nt"
LIMITS = [
    "exit zero is not acceptance",
    "stdout and stderr are combined in one log; the child may print private data",
    "headless modes never establish appearance, audible output or ordinary controls",
    "descendants are enumerated by process group (POSIX) or parent walk (Windows); "
    "a process that re-parented out of both is not seen",
]
PROFILE_KEYS = ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA")
INVENTORY_LIMITS = [
    "exit zero is not acceptance",
    "counts and hashes only; no perceptual or gameplay verdict",
]


def parse_utc(text):
    if not isinstance(text, str) or not text.strip():
        raise StudioError("Cutoff must be an ISO 8601 timestamp with a UTC offset")
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise StudioError("Cutoff must be an ISO 8601 timestamp with a UTC offset") from None
    if value.tzinfo is None:
        raise StudioError("Cutoff needs an explicit UTC offset")
    return value.astimezone(timezone.utc)


def mode_flags(mode):
    if mode not in MODES:
        raise StudioError("Unknown launch mode; use import, test, check or native")
    if mode == "native":
        flags = ["--resolution", "1920x1080", "--rendering-method", "forward_plus"]
    else:
        flags = ["--headless", "--audio-driver", "Dummy"]
    if mode == "import":
        flags += ["--editor", "--import"]
    if mode == "check":
        flags += ["--check-only"]
    return flags


def build_args(config, project, engine, mode, script=None, passthrough=()):
    root = Path(project)
    if not (root / "project.godot").is_file():
        raise StudioError("Godot project.godot is missing")
    args = [str(engine), "--path", app_path(config, root, "godot")] + mode_flags(mode)
    if script is not None:
        if not isinstance(script, str) or not script.strip():
            raise StudioError("Launch script must be a non-empty engine script path")
        args += ["--script", script]
    elif mode in ("test", "check"):
        raise StudioError(f"Launch mode {mode} needs --script")
    if not isinstance(passthrough, (list, tuple)) or not all(isinstance(x, str) for x in passthrough):
        raise StudioError("Passthrough arguments must be strings")
    return args + list(passthrough)


def _scrubbed(prefixes):
    """The child environment without the scrubbed names.

    A Windows process cannot hold two names that differ only in case, so a
    prefix there matches whatever case the name is spelled in; elsewhere the
    comparison stays exact, since `path` and `PATH` are two different names.
    """
    wanted = [prefix.upper() for prefix in prefixes] if IS_WINDOWS else list(prefixes)
    return {
        key: value for key, value in os.environ.items()
        if not any((key.upper() if IS_WINDOWS else key).startswith(prefix) for prefix in wanted)
    }


def _remaining(cutoff, limit, launch, run_dir):
    """Bound the wait by what is left of the authorized window at this instant.

    Returns the effective timeout, or None when the window has closed. The
    launch record is updated either way, so the receipt says what was allowed.
    """
    if cutoff is None:
        return float(limit)
    remaining = (cutoff - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        launch.update(status="refused", timeout_seconds_effective=None, process_record=None)
        write_json(run_dir / "owned-launch.json", launch)
        return None
    effective = max(0.001, min(float(limit), remaining))
    if launch["timeout_seconds_effective"] != round(effective, 3):
        launch["timeout_seconds_effective"] = round(effective, 3)
        write_json(run_dir / "owned-launch.json", launch)
    return effective


def _readable_digest(path):
    """Hash a file, reporting no digest instead of raising when it cannot be read."""
    try:
        return sha256(path)
    except OSError:
        return None


def execute(
    config, project, *, sha256_expected, mode="import", script=None,
    timeout=None, cutoff_utc=None, label=None, scope=None, results=(), scrub=(), passthrough=(),
):
    """Verify identity, launch once, wait, and return a verdict with receipts."""
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Launch needs an existing game project directory")
    engine_path = Path(require_executable(config, "godot")).expanduser()
    if not engine_path.is_file():
        raise StudioError("Engine executable is missing; set executables.godot in the host config")
    if not isinstance(sha256_expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256_expected):
        raise StudioError("Expected engine SHA-256 must be 64 hex characters")
    actual = sha256(engine_path)
    if actual != sha256_expected.lower():
        raise StudioError("Engine identity mismatch; refusing to launch an unverified engine")
    if self_contained(engine_path):
        # Such an engine keeps its state beside the executable and ignores the
        # profile environment below, so isolation could not be claimed honestly.
        raise StudioError(
            "Owned launch requires Godot without a self-contained _sc_ marker; "
            "the isolated profile would be ignored"
        )
    args = build_args(config, root, engine_path.resolve(), mode, script, passthrough)
    limit = config["timeout"] if timeout is None else timeout
    if type(limit) not in (int, float) or not 0 < limit <= MAX_TIMEOUT:
        raise StudioError("Launch timeout must be 1–3600 seconds")
    cutoff = parse_utc(cutoff_utc) if cutoff_utc else None
    prefixes = list(scrub)
    if not all(isinstance(p, str) and p for p in prefixes):
        raise StudioError("Environment scrub prefixes must be non-empty strings")
    label = safe_id(label) if label else uuid.uuid4().hex
    # The scope rung this launch is evidence for; validated like a label so a
    # receipt can be matched to a ladder rung without free text.
    scope = safe_id(scope) if scope is not None else None
    # The launch directory is contained like a declared result: a symlinked
    # artifacts/ must not move these receipts out of the project or into the kit.
    run_dir = owned = outside_package(relative(root, f"artifacts/launches/{label}"))
    expected = []
    results_before = []
    for item in results:
        target = relative(root, item)
        if target == owned or target.is_relative_to(owned):
            # owned-launch.json, diagnostics.json, the process record and the log
            # are written by this launcher: declaring one as a required result
            # would let an engine that produced nothing still reach completed.
            raise StudioError("Declared results must not be files this launcher writes")
        expected.append(item)
        # A result that already exists with the same bytes after the run was not produced by it.
        present = target.is_file()
        results_before.append({
            "path": item, "present": present,
            "sha256": _readable_digest(target) if present else None,
        })
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Launch directory exists; choose a new label") from None
    now = datetime.now(timezone.utc)
    effective = float(limit)
    verdict = None
    if cutoff is not None:
        remaining = (cutoff - now).total_seconds()
        if remaining <= 0:
            verdict = "cutoff_passed"
        else:
            effective = max(0.001, min(effective, remaining))
    launch = {
        "schema_version": 1,
        "kind": "owned-launch",
        "label": label,
        "scope": scope,
        "mode": mode,
        "engine": {"name": engine_path.name, "sha256": actual, "sha256_after_exit": None},
        "project": str(root),
        "profile": "profile",
        "script": script,
        "passthrough_count": len(passthrough) - (1 if list(passthrough)[:1] == ["--"] else 0),
        "expected_results": expected,
        "results_before": results_before,
        "started_utc": now.isoformat(),
        "cutoff_utc": cutoff.isoformat() if cutoff else None,
        "timeout_seconds_effective": round(effective, 3) if verdict is None else None,
        "status": "refused" if verdict else "launching",
        "pid": None,
        "process_record": "process/process.json" if verdict is None else None,
    }
    write_json(run_dir / "owned-launch.json", launch)
    if verdict == "cutoff_passed":
        return _finish(root, run_dir, launch, None, "", verdict, "Authorized cutoff already passed")
    profile = run_dir / "profile"
    profile.mkdir()
    environment = _scrubbed(prefixes)
    for key in PROFILE_KEYS:
        environment[key] = app_path(config, profile, "godot")
    # The digest verified above described bytes that could have been replaced
    # while this launch was prepared, so the engine is re-read before starting:
    # only the verified identity may start.
    if _readable_digest(engine_path) != actual:
        launch.update(status="refused", timeout_seconds_effective=None, process_record=None)
        write_json(run_dir / "owned-launch.json", launch)
        return _finish(
            root, run_dir, launch, None, "", "engine_replaced",
            "Engine bytes changed before the launch; the verified identity did not start",
        )
    # Writing the receipts, preparing the profile and hashing the engine all
    # consume part of the window, so the authorization is rechecked last, after
    # every slow step: the wait `run` gets is what is left of it right now.
    effective = _remaining(cutoff, limit, launch, run_dir)
    if effective is None:
        return _finish(
            root, run_dir, launch, None, "", "cutoff_passed",
            "Authorized cutoff passed while the launch was prepared",
        )
    failure = None
    interrupt = None
    try:
        run(
            args, cwd=str(root), timeout=effective, env=environment,
            hide_window=mode != "native", job_dir=run_dir / "process",
        )
    except StudioError as exc:
        failure = str(exc)
    except KeyboardInterrupt as exc:
        # The runner has already stopped its own child; write honest receipts, then re-raise.
        interrupt = exc
        failure = "launch interrupted before the engine finished"
    record_path = run_dir / "process" / "process.json"
    record = read_json(record_path) if record_path.is_file() else {"status": "start_failed"}
    log_path = run_dir / "process" / "stdout.log"
    text = log_path.read_bytes().decode("utf-8", errors="replace") if log_path.is_file() else ""
    launch["engine"]["sha256_after_exit"] = _readable_digest(engine_path)
    if interrupt is not None:
        # A caller interruption is reported honestly, not folded into launched/start_failed.
        launch.update(status="interrupted", pid=record.get("pid"))
    else:
        # Only a process record with a PID proves the engine was launched.
        launch.update(status="launched" if record.get("pid") else "start_failed", pid=record.get("pid"))
    left = None
    if interrupt is None and record.get("pid") and record.get("status") != "timed_out":
        # The runner already stopped the tree on timeout; otherwise the engine
        # exited on its own and whatever it left running is still this launch's.
        left = stop_survivors(record["pid"], hide_window=mode != "native")
        launch["survivors"] = left
    verdict = None
    if interrupt is not None:
        verdict = "interrupted"
    elif launch["engine"]["sha256_after_exit"] != actual:
        verdict = "engine_replaced"
        failure = "Engine bytes changed during the launch; the receipts describe bytes it no longer has"
    elif left and left["pids"]:
        verdict = "descendants_survived"
        failure = failure or (
            "Processes from this launch outlived the engine; "
            + ("they were stopped" if left["stopped"] else "stopping them could not be verified")
        )
    elif left and left["status"] != "ok":
        verdict = "descendants_unverified"
        failure = failure or "Processes from this launch could not be enumerated on this host"
    write_json(run_dir / "owned-launch.json", launch)
    result = _finish(root, run_dir, launch, record, text, verdict, failure, survivors=left)
    if interrupt is not None:
        raise interrupt
    return result


def _finish(root, run_dir, launch, record, text, verdict, failure, survivors=None):
    diagnostics = classify_log(text)
    write_json(run_dir / "diagnostics.json", diagnostics)
    before = {entry["path"]: entry for entry in launch.get("results_before", [])}
    result_files = []
    for item in launch["expected_results"]:
        try:
            target = relative(root, item)
        except StudioError:
            # A declared result that only now resolves outside the project (a
            # symlink the run created) is not evidence, and saying so in the
            # receipt beats raising over the receipts that explain the run.
            result_files.append({"path": item, "present": False, "stale": False,
                                 "unreadable": False, "escaped": True, "sha256": None})
            continue
        exists = target.is_file()
        digest = _readable_digest(target) if exists else None
        # A result this launcher cannot read cannot be shown to be new output,
        # and it must become a verdict rather than an exception over the receipts.
        unreadable = exists and digest is None
        prior = before.get(item, {"present": False, "sha256": None})
        # Unchanged bytes from before the launch are stale, not produced by this run.
        stale = exists and not unreadable and prior["present"] and prior["sha256"] == digest
        result_files.append({
            "path": item, "present": exists and not stale and not unreadable,
            "stale": stale, "unreadable": unreadable, "escaped": False, "sha256": digest,
        })
    status = record.get("status", "start_failed") if record else "refused"
    if verdict is None:
        if status == "completed":
            if diagnostics["error_count"]:
                verdict = "engine_errors"
            elif any(entry["escaped"] for entry in result_files):
                verdict = "results_invalid"
            elif any(entry["unreadable"] for entry in result_files):
                verdict = "results_unreadable"
            elif any(not entry["present"] for entry in result_files):
                verdict = "results_missing"
            elif diagnostics["status"] == "unverified" and launch["mode"] != "native":
                # A headless engine that printed nothing has not shown it ran the script.
                verdict = "unverified"
            else:
                verdict = "completed"
        else:
            verdict = status
    log_path = run_dir / "process" / "stdout.log"
    record_path = run_dir / "process" / "process.json"
    exit_record = {
        "schema_version": 1,
        "kind": "launch-exit",
        "label": launch["label"],
        "scope": launch.get("scope"),
        "verdict": verdict,
        "ok": verdict == "completed",
        "status": status,
        "returncode": (record or {}).get("returncode"),
        "elapsed_seconds": (record or {}).get("elapsed_seconds"),
        "timed_out": status == "timed_out",
        "cleanup": (record or {}).get("cleanup"),
        "survivors": survivors,
        "combined_log_bytes": log_path.stat().st_size if log_path.is_file() else 0,
        "diagnostics": diagnostics,
        "result_files": result_files,
        "failure": failure,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "limits": LIMITS,
    }
    write_json(run_dir / "exit.json", exit_record)
    return {
        **exit_record,
        "run_dir": str(run_dir),
        "launch_record": str(run_dir / "owned-launch.json"),
        "exit_record": str(run_dir / "exit.json"),
        "diagnostics_record": str(run_dir / "diagnostics.json"),
        "process_record": str(record_path) if record_path.is_file() else None,
        "log": str(log_path) if log_path.is_file() else None,
    }


def _receipt(root, path):
    """Read a receipt once so the summarized fields and the recorded hash share bytes.

    Re-opening the file to hash it would report a digest for bytes that were never
    the ones summarized here. The returned record has the shape of file_record.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
        record = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise StudioError(f"Cannot read JSON record: {path.name}") from exc
    if not isinstance(record, dict):
        raise StudioError(f"Receipt is not a JSON object: {path.name}")
    return record, {
        "path": path.resolve().relative_to(Path(root).resolve()).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _pairing(launch, exit_record, process_owned=True, process_missing=False):
    """Refuse to summarize receipts that do not belong to this launch.

    Reasons name the mismatched field only; foreign receipt values are never echoed.
    """
    if launch.get("kind") != "owned-launch":
        return "mismatched", "launch record is not an owned-launch receipt"
    if exit_record is None:
        return "missing_exit", "no exit record beside the launch record"
    if exit_record.get("kind") != "launch-exit":
        return "mismatched", "exit record is not a launch-exit receipt"
    if exit_record.get("label") != launch.get("label"):
        return "mismatched", "exit record label does not match the launch label"
    if exit_record.get("scope") != launch.get("scope"):
        return "mismatched", "exit record scope does not match the launch scope"
    if process_missing:
        # The launch record names a process receipt: without it nothing shows
        # what this launch actually ran, so the pair cannot vouch for the run.
        return "missing_process", "declared process record is not beside the launch"
    if not process_owned:
        # A process record carried over from another run would otherwise lend
        # this launch its status, return code and elapsed time.
        return "mismatched", "process record does not belong to this launch"
    return "paired", None


def inventory(run_root, output=None):
    """Index every owned launch under a run root; counts and hashes only."""
    root = Path(run_root).expanduser().resolve()
    if not root.is_dir():
        raise StudioError("Launch inventory needs an existing run root directory")
    records = sorted(p for p in root.rglob("owned-launch.json") if p.is_file())
    if not records:
        raise StudioError("No owned-launch.json records under the run root")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if output:
        candidate = Path(output).expanduser()
        # A relative output belongs under the run root; only an absolute one may
        # leave it, and it still may not land inside the installed toolkit.
        target = outside_package(candidate) if candidate.is_absolute() else relative(root, str(output))
    else:
        target = outside_package(root / f"launch-inventory-{stamp}-{uuid.uuid4().hex[:8]}.json")
    if target.exists():
        raise StudioError("Inventory output exists; choose a new filename")
    launches = []
    totals = {"launches": 0, "completed": 0, "not_ok": 0, "timed_out": 0,
              "missing_exit": 0, "missing_process": 0, "mismatched": 0}
    for path in records:
        folder = path.parent
        launch, launch_file = _receipt(root, path)
        exit_path = folder / "exit.json"
        exit_record, exit_file = _receipt(root, exit_path) if exit_path.is_file() else (None, None)
        declared = launch.get("process_record")
        process_path = folder / (declared or "process/process.json")
        process, process_file = _receipt(root, process_path) if process_path.is_file() else (None, None)
        # A refusal that never started the engine declares no process record.
        process_missing = bool(declared) and process is None
        log_path = process_path.parent / "stdout.log"
        # A process record proves it belongs to this launch by its own schema
        # version and PID, whatever the exit record beside it says.
        owned_process = process is None or (
            process.get("schema_version") == 1 and process.get("pid") == launch.get("pid")
        )
        pairing, reason = _pairing(launch, exit_record, owned_process, process_missing)
        # Only a verified pair may lend its verdict, ok flag and result files here.
        paired = exit_record if pairing == "paired" else None
        # Nor may any unpaired entry lend a process lifecycle summary: a
        # foreign exit record leaves no verified account of what ran either.
        summary = process if pairing == "paired" else None
        verdict = (paired or {}).get("verdict", "no_exit_record")
        if pairing == "mismatched":
            verdict = "mismatched_receipts"
        elif pairing == "missing_process":
            verdict = "no_process_record"
        present = [r["path"] for r in (paired or {}).get("result_files", []) if r.get("present")]
        missing = [r["path"] for r in (paired or {}).get("result_files", []) if not r.get("present")]
        entry = {
            "dir": folder.relative_to(root).as_posix() or ".",
            "launch": launch_file,
            "exit": exit_file,
            "process": process_file,
            "pairing": pairing,
            "pairing_reason": reason,
            "mode": launch.get("mode"),
            "scope": launch.get("scope"),
            "verdict": verdict,
            "ok": (paired or {}).get("ok") is True,
            "status": (summary or {}).get(
                "status", None if pairing == "mismatched" else launch.get("status")
            ),
            "returncode": (summary or {}).get("returncode"),
            "elapsed_seconds": (summary or {}).get("elapsed_seconds"),
            "timed_out": (summary or {}).get("status") == "timed_out",
            "cleanup": (summary or {}).get("cleanup"),
            "combined_log_bytes": log_path.stat().st_size if log_path.is_file() else 0,
            "diagnostics": (paired or {}).get("diagnostics"),
            "result_files": {"present": present, "missing": missing},
        }
        totals["launches"] += 1
        totals["completed"] += entry["ok"]
        totals["not_ok"] += not entry["ok"]
        totals["timed_out"] += entry["timed_out"]
        totals["missing_exit"] += pairing == "missing_exit"
        totals["missing_process"] += pairing == "missing_process"
        totals["mismatched"] += pairing == "mismatched"
        launches.append(entry)
    data = {
        "schema_version": 1,
        "kind": "launch-inventory",
        "run_root": str(root),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "launches": launches,
        "limits": INVENTORY_LIMITS,
        # An inventory that found receipts which do not belong together, or a
        # launch whose declared process receipt is gone, is not ok.
        "ok": totals["mismatched"] == 0 and totals["missing_process"] == 0,
    }
    write_json(target, data)
    return {**data, "output": str(target)}
