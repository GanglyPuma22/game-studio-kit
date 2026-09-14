"""Interactive playtest: a pinned engine, a recorded session and a re-runnable launcher.

`launch` owns bounded, timed, receipt-gated runs an agent reads a verdict from.
A playtest is the opposite shape: open-ended, driven by a person, judged by a
person, and repeated later by that person without an agent or this kit present.
So the two never share a run directory and never share a verdict vocabulary.
The receipts follow the same rules as every other owned run — no argv values or
environment, UTC timestamps, a process record distinct from engine success —
and add the one claim that matters here: `ok` is run health, never acceptance.
"""

from __future__ import annotations
from datetime import datetime, timezone
import math
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import uuid
from .adapters.godot import classify_log, self_contained
from .common import (
    StudioError, file_record, outside_package, read_json, relative, safe_id, sha256, write_json,
)
from .config import app_path, executable, require_executable
from .launch import IS_WINDOWS, MAX_TIMEOUT, PROFILE_KEYS, _readable_digest, _scrubbed, mode_flags, parse_utc
from .processes import alive, run, start, stop_survivors

SESSIONS = ("handoff", "attended", "driven")
DEFAULT_MAX_MINUTES = 60
# A driven session has no human at the controls, so it keeps the ceiling the
# owned launcher applies to every unattended wait.
MAX_DRIVEN_MINUTES = MAX_TIMEOUT // 60
LIMITS = [
    "a playtest launch is not acceptance; a human verdict is required",
    "ok is run health only: the engine ran, logged no errors and produced the declared results",
    "stdout and stderr are combined in one log; the child may print private data",
    "script-injected input establishes wiring, not normal-input usability",
    "descendants are enumerated by process group (POSIX) or parent walk (Windows); "
    "a process that re-parented out of both is not seen",
]
# Nobody waited for an attended session, so its receipt claims strictly less.
ATTENDED_LIMITS = LIMITS + [
    "an attended session is not owned by the collecting process: its exit code, "
    "elapsed time and surviving descendants are not observed",
]
LAUNCHER_NOTE = "game-studio-kit playtest relaunch"


def _scene(scene):
    """Validate a `res://` scene path without resolving it against a host path."""
    if scene is None:
        return None
    if not isinstance(scene, str) or not scene.startswith("res://") or scene.strip() != scene:
        raise StudioError("Playtest scene must be an engine res:// path, for example res://main.tscn")
    tail = scene[len("res://"):]
    if not tail or "\\" in tail or ".." in PurePosixPath(tail).parts:
        raise StudioError("Playtest scene must name a file inside the project")
    return scene


def _revision(root):
    """The project's commit and whether its tree is dirty, when it is a checkout.

    A playtest is evidence about one build of a game, so the receipt names the
    source that produced it. A project that is not a checkout reports nulls: not
    knowing the commit is a gap in the evidence, not a reason to refuse the run.
    """
    if not (root / ".git").exists():
        return None, None
    commit = None
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if head.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}\n?", head.stdout):
            commit = head.stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return commit, None
    return commit, bool(status.stdout.strip()) if status.returncode == 0 else None


def _cmd_quote(value):
    # cmd.exe offers no escape for a quotation mark inside a quoted argument, so
    # such a value cannot be written to a .cmd launcher as a literal at all.
    if '"' in value:
        raise StudioError(
            "An argument containing a quotation mark cannot be written to a .cmd launcher; "
            "rerun with --no-launcher"
        )
    return f'"{value}"' if not value or re.search(r"[\s&|<>^()%!,;=]", value) else value


def _launcher(root, run_dir, args, playtest):
    """Write the re-runnable launcher this whole command exists to leave behind.

    It is generated from the exact argument array that ran, so it cannot drift
    from the session it documents. It carries no environment: writing one would
    either put scrubbed values back into a file or silently claim a profile
    isolation it does not actually set up, so the header says which profile the
    recorded session used and the script simply does not reproduce it.
    """
    if IS_WINDOWS:
        name, comment, head = "relaunch.cmd", "REM ", ["@echo off"]
        body = " ".join(_cmd_quote(item) for item in args)
    else:
        name, comment, head = "relaunch.sh", "# ", ["#!/bin/sh"]
        body = " ".join(shlex.quote(item) for item in args)
    notes = [
        LAUNCHER_NOTE,
        f"label: {playtest['label']}",
        f"session: {playtest['session']}",
        f"engine sha256: {playtest['engine']['sha256']}",
        "commit: " + (playtest["commit"] or "not a checkout")
        + (" (uncommitted changes)" if playtest["dirty"] else ""),
        f"profile: {playtest['profile']}"
        + (
            " (this script does not recreate the isolated profile; it plays on yours)"
            if playtest["profile"] == "isolated" else ""
        ),
        "Runs the same engine, project and scene as the recorded session.",
        "It establishes nothing: a playtest is accepted by a person, not by a script.",
    ]
    path = run_dir / name
    path.write_text("\n".join(head + [comment + note for note in notes] + [body, ""]), encoding="utf-8")
    if not IS_WINDOWS:
        path.chmod(0o755)
    return file_record(root, path)


def _window(cutoff, limit, playtest, run_dir):
    """Bound the wait by what is left of the authorized window at this instant.

    Returns (open, timeout), where a None timeout means the session runs until
    the human quits. The receipt is updated either way, so it says what was
    allowed rather than what was asked for.
    """
    if cutoff is None:
        return True, limit
    remaining = (cutoff - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        playtest.update(status="refused", max_minutes_effective=None, process_record=None)
        write_json(run_dir / "playtest.json", playtest)
        return False, None
    effective = remaining if limit is None else max(0.001, min(limit, remaining))
    if playtest["max_minutes_effective"] != round(effective / 60, 3):
        playtest["max_minutes_effective"] = round(effective / 60, 3)
        write_json(run_dir / "playtest.json", playtest)
    return True, effective


def execute(
    config, project, *, sha256_expected, session="handoff", scene=None, script=None,
    label=None, max_minutes=DEFAULT_MAX_MINUTES, cutoff_utc=None, results=(), scrub=(),
    passthrough=(), use_host_profile=False, emit_launcher=True,
):
    """Verify identity, start the game once, and record the session."""
    if session not in SESSIONS:
        raise StudioError("Unknown playtest session; use handoff, attended or driven")
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Playtest needs an existing game project directory")
    if not (root / "project.godot").is_file():
        raise StudioError("Godot project.godot is missing")
    if session == "driven":
        if not isinstance(script, str) or not script.strip():
            raise StudioError("A driven playtest needs --script naming the harness that supplies input")
    elif script is not None:
        # Handing a human the controls and scripting them at the same time
        # produces a session nobody can say who drove.
        raise StudioError("--script belongs to a driven playtest; a person drives handoff and attended")
    scene = _scene(scene)
    engine_path = Path(require_executable(config, "godot")).expanduser()
    if not engine_path.is_file():
        raise StudioError("Engine executable is missing; set executables.godot in the host config")
    if not isinstance(sha256_expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256_expected):
        raise StudioError("Expected engine SHA-256 must be 64 hex characters")
    actual = sha256(engine_path)
    if actual != sha256_expected.lower():
        raise StudioError("Engine identity mismatch; refusing to launch an unverified engine")
    if self_contained(engine_path) and not use_host_profile:
        # Such an engine keeps its state beside the executable and ignores the
        # profile environment, so only the host-profile session can be honest
        # about it — and that session is exactly what a player usually wants.
        raise StudioError(
            "An isolated playtest requires Godot without a self-contained _sc_ marker; "
            "play on the engine's own profile with --use-host-profile instead"
        )
    if type(max_minutes) not in (int, float) or not math.isfinite(max_minutes) or max_minutes < 0:
        raise StudioError("Playtest --max-minutes must be a number of minutes, or 0 for no cap")
    if max_minutes == 0:
        if session == "driven":
            raise StudioError(
                "A driven playtest must stay bounded; --max-minutes 0 needs a person at the controls"
            )
        limit = None
    else:
        if session == "driven" and max_minutes > MAX_DRIVEN_MINUTES:
            raise StudioError(f"A driven playtest must stay bounded; --max-minutes must be 1-{MAX_DRIVEN_MINUTES}")
        limit = float(max_minutes) * 60
    cutoff = parse_utc(cutoff_utc) if cutoff_utc else None
    prefixes = list(scrub)
    if not all(isinstance(p, str) and p for p in prefixes):
        raise StudioError("Environment scrub prefixes must be non-empty strings")
    if not isinstance(passthrough, (list, tuple)) or not all(isinstance(x, str) for x in passthrough):
        raise StudioError("Passthrough arguments must be strings")
    label = safe_id(label) if label else uuid.uuid4().hex
    # A separate namespace from artifacts/launches, so a playtest and an owned
    # launch can never collide on the label that refuses a reused run directory.
    run_dir = owned = outside_package(relative(root, f"artifacts/playtests/{label}"))
    expected = []
    results_before = []
    for item in results:
        target = relative(root, item)
        if target == owned or target.is_relative_to(owned):
            raise StudioError("Declared results must not be files this playtest writes")
        expected.append(item)
        present = target.is_file()
        results_before.append({
            "path": item, "present": present,
            "sha256": _readable_digest(target) if present else None,
        })
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Playtest directory exists; choose a new label") from None
    flags = mode_flags("native")
    args = [str(engine_path.resolve()), "--path", app_path(config, root, "godot")] + flags
    if script is not None:
        args += ["--script", script]
    if scene is not None:
        args.append(scene)
    args += list(passthrough)
    now = datetime.now(timezone.utc)
    effective = limit
    verdict = None
    if cutoff is not None:
        remaining = (cutoff - now).total_seconds()
        if remaining <= 0:
            verdict = "cutoff_passed"
        else:
            effective = remaining if limit is None else max(0.001, min(effective, remaining))
    commit, dirty = _revision(root)
    playtest = {
        "schema_version": 1,
        "kind": "playtest",
        "label": label,
        "session": session,
        "scene": scene,
        "scene_sha256": _scene_digest(root, scene),
        "script": script,
        "engine": {"name": engine_path.name, "sha256": actual, "sha256_after_exit": None},
        "project": str(root),
        "profile": "host" if use_host_profile else "isolated",
        "passthrough_count": len(passthrough) - (1 if list(passthrough)[:1] == ["--"] else 0),
        "commit": commit,
        "dirty": dirty,
        # Read back from the flags that were actually built, so a receipt can
        # never describe a renderer or resolution the engine was not given.
        "rendering_method": flags[flags.index("--rendering-method") + 1],
        "resolution": flags[flags.index("--resolution") + 1],
        "expected_results": expected,
        "results_before": results_before,
        "started_utc": now.isoformat(),
        "cutoff_utc": cutoff.isoformat() if cutoff else None,
        "max_minutes_effective": None if effective is None or verdict else round(effective / 60, 3),
        "status": "refused" if verdict else "launching",
        "pid": None,
        "launcher": None,
        "process_record": "process/process.json" if verdict is None else None,
    }
    write_json(run_dir / "playtest.json", playtest)
    if verdict == "cutoff_passed":
        return _finish(root, run_dir, playtest, None, "", verdict, "Authorized cutoff already passed")
    if emit_launcher:
        # Written before the engine starts: a session that fails to launch still
        # leaves the human the command that would have run.
        playtest["launcher"] = _launcher(root, run_dir, args, playtest)
        write_json(run_dir / "playtest.json", playtest)
    environment = _scrubbed(prefixes)
    if not use_host_profile:
        profile = run_dir / "profile"
        profile.mkdir()
        for key in PROFILE_KEYS:
            environment[key] = app_path(config, profile, "godot")
    # The digest verified above described bytes that could have been replaced
    # while this session was prepared, so only the verified identity may start.
    if _readable_digest(engine_path) != actual:
        playtest.update(status="refused", max_minutes_effective=None, process_record=None)
        write_json(run_dir / "playtest.json", playtest)
        return _finish(
            root, run_dir, playtest, None, "", "engine_replaced",
            "Engine bytes changed before the playtest; the verified identity did not start",
        )
    opened, effective = _window(cutoff, limit, playtest, run_dir)
    if not opened:
        return _finish(
            root, run_dir, playtest, None, "", "cutoff_passed",
            "Authorized cutoff passed while the playtest was prepared",
        )
    if session == "attended":
        started = start(args, job_dir=run_dir / "process", cwd=str(root), env=environment)
        playtest.update(status="launched", pid=started["pid"])
        write_json(run_dir / "playtest.json", playtest)
        return {
            **playtest,
            "verdict": "launched",
            "ok": True,
            "acceptance": "not_established",
            "limits": ATTENDED_LIMITS,
            "run_dir": str(run_dir),
            "playtest_record": str(run_dir / "playtest.json"),
            "process_record": started["process_record"],
            "log": started["log"],
            "next": (
                "run `playtest collect --label " + label + "` once, after the player says the "
                "session is over; repeating it to watch for the end is polling"
            ),
        }
    failure = None
    interrupt = None
    try:
        run(
            args, cwd=str(root), timeout=effective, env=environment,
            hide_window=False, job_dir=run_dir / "process",
        )
    except StudioError as exc:
        failure = str(exc)
    except KeyboardInterrupt as exc:
        # The runner has already stopped its own child; write honest receipts, then re-raise.
        interrupt = exc
        failure = "playtest interrupted before the engine finished"
    record_path = run_dir / "process" / "process.json"
    record = read_json(record_path) if record_path.is_file() else {"status": "start_failed"}
    log_path = run_dir / "process" / "stdout.log"
    text = log_path.read_bytes().decode("utf-8", errors="replace") if log_path.is_file() else ""
    playtest["engine"]["sha256_after_exit"] = _readable_digest(engine_path)
    if interrupt is not None:
        playtest.update(status="interrupted", pid=record.get("pid"))
    else:
        playtest.update(status="launched" if record.get("pid") else "start_failed", pid=record.get("pid"))
    left = None
    if interrupt is None and record.get("pid") and record.get("status") != "timed_out":
        left = stop_survivors(record["pid"], hide_window=False)
        playtest["survivors"] = left
    verdict = None
    if interrupt is not None:
        verdict = "interrupted"
    elif playtest["engine"]["sha256_after_exit"] != actual:
        verdict = "engine_replaced"
        failure = "Engine bytes changed during the playtest; the receipts describe bytes it no longer has"
    elif left and left["pids"]:
        verdict = "descendants_survived"
        failure = failure or (
            "Processes from this playtest outlived the engine; "
            + ("they were stopped" if left["stopped"] else "stopping them could not be verified")
        )
    elif left and left["status"] != "ok":
        verdict = "descendants_unverified"
        failure = failure or "Processes from this playtest could not be enumerated on this host"
    write_json(run_dir / "playtest.json", playtest)
    result = _finish(root, run_dir, playtest, record, text, verdict, failure, survivors=left)
    if interrupt is not None:
        raise interrupt
    return result


def _scene_digest(root, scene):
    """Hash the scene file when the res:// path resolves to one inside the project."""
    if scene is None:
        return None
    try:
        target = relative(root, scene[len("res://"):])
    except StudioError:
        return None
    return _readable_digest(target) if target.is_file() else None


def _result_files(root, playtest):
    """Report each declared result as produced, stale, unreadable or escaped."""
    before = {entry["path"]: entry for entry in playtest.get("results_before", [])}
    files = []
    for item in playtest["expected_results"]:
        try:
            target = relative(root, item)
        except StudioError:
            files.append({"path": item, "present": False, "stale": False,
                          "unreadable": False, "escaped": True, "sha256": None})
            continue
        exists = target.is_file()
        digest = _readable_digest(target) if exists else None
        unreadable = exists and digest is None
        prior = before.get(item, {"present": False, "sha256": None})
        # Unchanged bytes from before the session are stale, not produced by it.
        stale = exists and not unreadable and prior["present"] and prior["sha256"] == digest
        files.append({
            "path": item, "present": exists and not stale and not unreadable,
            "stale": stale, "unreadable": unreadable, "escaped": False, "sha256": digest,
        })
    return files


def _health(diagnostics, result_files, good):
    """The run-health verdict, which is never a statement about the playing."""
    if diagnostics["error_count"]:
        return "engine_errors"
    if any(entry["escaped"] for entry in result_files):
        return "results_invalid"
    if any(entry["unreadable"] for entry in result_files):
        return "results_unreadable"
    if any(not entry["present"] for entry in result_files):
        return "results_missing"
    return good


def _finish(root, run_dir, playtest, record, text, verdict, failure, survivors=None):
    diagnostics = classify_log(text)
    write_json(run_dir / "diagnostics.json", diagnostics)
    result_files = _result_files(root, playtest)
    status = record.get("status", "start_failed") if record else "refused"
    if verdict is None:
        verdict = _health(diagnostics, result_files, "completed") if status == "completed" else status
    log_path = run_dir / "process" / "stdout.log"
    record_path = run_dir / "process" / "process.json"
    exit_record = {
        "schema_version": 1,
        "kind": "playtest-exit",
        "label": playtest["label"],
        "session": playtest["session"],
        "verdict": verdict,
        # Run health only. No program can decide that a playtest went well, so
        # nothing here ever promotes a clean exit into an accepted session.
        "ok": verdict == "completed",
        "acceptance": "not_established",
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
        "playtest_record": str(run_dir / "playtest.json"),
        "exit_record": str(run_dir / "exit.json"),
        "diagnostics_record": str(run_dir / "diagnostics.json"),
        "process_record": str(record_path) if record_path.is_file() else None,
        "log": str(log_path) if log_path.is_file() else None,
        "launcher": playtest.get("launcher"),
    }


def collect(config, project, label):
    """Complete one attended session, once, after the player says it is over.

    This is called a single time. Calling it repeatedly to discover when the
    game closed is polling, which the unattended rules forbid and which this
    command cannot be made to support: the second call is refused.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Playtest collect needs an existing game project directory")
    run_dir = outside_package(relative(root, f"artifacts/playtests/{safe_id(label)}"))
    record_path = run_dir / "playtest.json"
    if not record_path.is_file():
        raise StudioError("No playtest receipt under artifacts/playtests for that label")
    playtest = read_json(record_path)
    if playtest.get("kind") != "playtest":
        raise StudioError("That record is not a playtest receipt")
    if playtest.get("session") != "attended":
        raise StudioError(
            "collect completes an attended playtest; handoff and driven write their own exit receipt"
        )
    if (run_dir / "exit.json").is_file():
        raise StudioError("That playtest was already collected; a session is collected once")
    engine = executable(config, "godot")
    playtest["engine"]["sha256_after_exit"] = _readable_digest(Path(engine)) if engine else None
    process_path = run_dir / "process" / "process.json"
    record = read_json(process_path) if process_path.is_file() else {}
    log_path = run_dir / "process" / "stdout.log"
    text = log_path.read_bytes().decode("utf-8", errors="replace") if log_path.is_file() else ""
    running = alive(record.get("pid"))
    playtest["engine_running_at_collect"] = running
    write_json(record_path, playtest)
    diagnostics = classify_log(text)
    write_json(run_dir / "diagnostics.json", diagnostics)
    result_files = _result_files(root, playtest)
    failure = None
    after = playtest["engine"]["sha256_after_exit"]
    if running is True:
        verdict = "session_incomplete"
        failure = "The engine from this session is still running; collect once the game has been quit"
    elif after is not None and after != playtest["engine"]["sha256"]:
        verdict = "engine_replaced"
        failure = "Engine bytes changed during the session; the receipts describe bytes it no longer has"
    elif not record.get("pid"):
        verdict = record.get("status", "start_failed")
    else:
        verdict = _health(diagnostics, result_files, "collected")
    started = playtest.get("started_utc")
    exit_record = {
        "schema_version": 1,
        "kind": "playtest-exit",
        "label": playtest["label"],
        "session": "attended",
        "verdict": verdict,
        "ok": verdict == "collected",
        "acceptance": "not_established",
        # Nobody waited for this process, so there is no exit status to report:
        # "unobserved" is the honest word for a session with no owner.
        "status": "running" if running is True else "unobserved",
        "returncode": None,
        "elapsed_seconds": None,
        "collected_after_seconds": round(
            (datetime.now(timezone.utc) - parse_utc(started)).total_seconds(), 3
        ) if started else None,
        "engine_running_at_collect": running,
        "timed_out": False,
        "cleanup": None,
        "survivors": None,
        "combined_log_bytes": log_path.stat().st_size if log_path.is_file() else 0,
        "diagnostics": diagnostics,
        "result_files": result_files,
        "failure": failure,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "limits": ATTENDED_LIMITS,
    }
    write_json(run_dir / "exit.json", exit_record)
    return {
        **exit_record,
        "run_dir": str(run_dir),
        "playtest_record": str(record_path),
        "exit_record": str(run_dir / "exit.json"),
        "diagnostics_record": str(run_dir / "diagnostics.json"),
        "process_record": str(process_path) if process_path.is_file() else None,
        "log": str(log_path) if log_path.is_file() else None,
        "launcher": playtest.get("launcher"),
    }
