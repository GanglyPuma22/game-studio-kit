"""Owned, time-bounded engine launch that blocks and returns one verdict.

A calling agent runs this once and reads the returned verdict. It never polls,
sleeps or writes to the child's stdin. Receipts follow the process lifecycle
rules: no argv values or environment, UTC timestamps, monotonic elapsed time,
and a process record that is distinct from engine success.
"""

from __future__ import annotations
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import uuid
from .adapters.godot import classify_log
from .common import StudioError, file_record, read_json, relative, safe_id, sha256, write_json
from .config import app_path, require_executable
from .processes import run

MODES = ("import", "test", "check", "native")
MAX_TIMEOUT = 3600
LIMITS = [
    "exit zero is not acceptance",
    "stdout and stderr are combined in one log; the child may print private data",
    "headless modes never establish appearance, audible output or ordinary controls",
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


def execute(
    config, project, *, sha256_expected, engine=None, mode="import", script=None,
    timeout=None, cutoff_utc=None, label=None, scope=None, results=(), scrub=(), passthrough=(),
):
    """Verify identity, launch once, wait, and return a verdict with receipts."""
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Launch needs an existing game project directory")
    engine_path = Path(engine).expanduser() if engine else Path(require_executable(config, "godot"))
    if not engine_path.is_file():
        raise StudioError("Engine executable is missing; set executables.godot or --engine")
    if not isinstance(sha256_expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256_expected):
        raise StudioError("Expected engine SHA-256 must be 64 hex characters")
    actual = sha256(engine_path)
    if actual != sha256_expected.lower():
        raise StudioError("Engine identity mismatch; refusing to launch an unverified engine")
    args = build_args(config, root, engine_path.resolve(), mode, script, passthrough)
    limit = config["timeout"] if timeout is None else timeout
    if type(limit) not in (int, float) or not 0 < limit <= MAX_TIMEOUT:
        raise StudioError("Launch timeout must be 1–3600 seconds")
    cutoff = parse_utc(cutoff_utc) if cutoff_utc else None
    expected = []
    for item in results:
        relative(root, item)
        expected.append(item)
    prefixes = list(scrub)
    if not all(isinstance(p, str) and p for p in prefixes):
        raise StudioError("Environment scrub prefixes must be non-empty strings")
    label = safe_id(label) if label else uuid.uuid4().hex
    # The scope rung this launch is evidence for; validated like a label so a
    # receipt can be matched to a ladder rung without free text.
    scope = safe_id(scope) if scope is not None else None
    run_dir = root / "artifacts" / "launches" / label
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Launch directory exists; choose a new label") from None
    now = datetime.now(timezone.utc)
    effective = float(limit)
    verdict = None
    if cutoff is not None:
        remaining = (cutoff - now).total_seconds()
        if remaining < 1:
            verdict = "cutoff_passed"
        else:
            effective = min(effective, remaining)
    launch = {
        "schema_version": 1,
        "kind": "owned-launch",
        "label": label,
        "scope": scope,
        "mode": mode,
        "engine": {"path": str(engine_path.resolve()), "sha256": actual},
        "project": str(root),
        "profile": "profile",
        "script": script,
        "passthrough_count": len(passthrough),
        "expected_results": expected,
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
    environment = {
        key: value for key, value in os.environ.items()
        if not any(key.startswith(prefix) for prefix in prefixes)
    }
    for key in PROFILE_KEYS:
        environment[key] = app_path(config, profile, "godot")
    failure = None
    try:
        run(
            args, cwd=str(root), timeout=effective, env=environment,
            hide_window=mode != "native", job_dir=run_dir / "process",
        )
    except StudioError as exc:
        failure = str(exc)
    record_path = run_dir / "process" / "process.json"
    record = read_json(record_path) if record_path.is_file() else {"status": "start_failed"}
    log_path = run_dir / "process" / "stdout.log"
    text = log_path.read_bytes().decode("utf-8", errors="replace") if log_path.is_file() else ""
    launch.update(status="launched", pid=record.get("pid"))
    write_json(run_dir / "owned-launch.json", launch)
    return _finish(root, run_dir, launch, record, text, None, failure)


def _finish(root, run_dir, launch, record, text, verdict, failure):
    diagnostics = classify_log(text)
    write_json(run_dir / "diagnostics.json", diagnostics)
    result_files = []
    for item in launch["expected_results"]:
        target = relative(root, item)
        present = target.is_file()
        result_files.append({"path": item, "present": present, "sha256": sha256(target) if present else None})
    status = record.get("status", "start_failed") if record else "refused"
    if verdict is None:
        if status == "completed":
            if diagnostics["error_count"]:
                verdict = "engine_errors"
            elif any(not entry["present"] for entry in result_files):
                verdict = "results_missing"
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


def inventory(run_root, output=None):
    """Index every owned launch under a run root; counts and hashes only."""
    root = Path(run_root).expanduser().resolve()
    if not root.is_dir():
        raise StudioError("Launch inventory needs an existing run root directory")
    records = sorted(p for p in root.rglob("owned-launch.json") if p.is_file())
    if not records:
        raise StudioError("No owned-launch.json records under the run root")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(output).expanduser().resolve() if output else root / f"launch-inventory-{stamp}.json"
    if target.exists():
        raise StudioError("Inventory output exists; choose a new filename")
    launches = []
    totals = {"launches": 0, "completed": 0, "not_ok": 0, "timed_out": 0, "missing_exit": 0}
    for path in records:
        folder = path.parent
        launch = read_json(path)
        exit_path = folder / "exit.json"
        exit_record = read_json(exit_path) if exit_path.is_file() else None
        process_path = folder / (launch.get("process_record") or "process/process.json")
        process = read_json(process_path) if process_path.is_file() else None
        log_path = process_path.parent / "stdout.log"
        present = [r["path"] for r in (exit_record or {}).get("result_files", []) if r.get("present")]
        missing = [r["path"] for r in (exit_record or {}).get("result_files", []) if not r.get("present")]
        entry = {
            "dir": folder.relative_to(root).as_posix() or ".",
            "launch": file_record(root, path),
            "exit": file_record(root, exit_path) if exit_record else None,
            "mode": launch.get("mode"),
            "scope": launch.get("scope"),
            "verdict": (exit_record or {}).get("verdict", "no_exit_record"),
            "ok": (exit_record or {}).get("ok") is True,
            "status": (process or {}).get("status", launch.get("status")),
            "returncode": (process or {}).get("returncode"),
            "elapsed_seconds": (process or {}).get("elapsed_seconds"),
            "timed_out": (process or {}).get("status") == "timed_out",
            "cleanup": (process or {}).get("cleanup"),
            "combined_log_bytes": log_path.stat().st_size if log_path.is_file() else 0,
            "diagnostics": (exit_record or {}).get("diagnostics"),
            "result_files": {"present": present, "missing": missing},
        }
        totals["launches"] += 1
        totals["completed"] += entry["ok"]
        totals["not_ok"] += not entry["ok"]
        totals["timed_out"] += entry["timed_out"]
        totals["missing_exit"] += exit_record is None
        launches.append(entry)
    data = {
        "schema_version": 1,
        "kind": "launch-inventory",
        "run_root": str(root),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "launches": launches,
        "limits": INVENTORY_LIMITS,
        "ok": True,
    }
    write_json(target, data)
    return {**data, "output": str(target)}
