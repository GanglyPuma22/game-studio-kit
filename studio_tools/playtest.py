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
import json
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
from .processes import alive, prelaunch_baseline, run, start, stop_started, stop_survivors

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
    "an attended session is not waited for, so no time cap is enforced and "
    "--cutoff-utc gates only whether it may start, never when it ends",
]
LAUNCHER_NOTE = "game-studio-kit playtest relaunch"
# Godot 4 offers exactly these; a project declaring anything else is not read.
RENDERING_METHODS = ("forward_plus", "mobile", "gl_compatibility")
# The kit tells the harness where to write, so the two can never disagree.
HARNESS_REPORT = "harness.json"
HARNESS_ARGUMENT = "--studio-playtest="
# Every field `collect` reads out of a receipt it did not write in this process.
REQUIRED_RECEIPT_FIELDS = ("label", "engine", "expected_results", "started_utc")


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


def _setting(root, section, key):
    """One value from `project.godot`, Godot's own INI dialect, or None.

    Keys there carry `/` and `.`, values are quoted, and a per-platform
    override such as `renderer/rendering_method.mobile` is a different key that
    must not be read as the base setting, so the match is exact.
    """
    try:
        text = (root / "project.godot").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(";") or not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            continue
        name, separator, value = stripped.partition("=")
        if separator and current == section and name.strip() == key:
            return value.strip().strip('"')
    return None


def _display(root, rendering_method, resolution):
    """Decide the renderer and window size, preferring what the game declares.

    `launch --mode native` pins both, which suits a bounded smoke of a known
    configuration. A playtest is the opposite errand: it exists to show what a
    player would see, and the renderer decides whether flicker, banding and
    transparency artifacts appear at all, so substituting one can invent a
    defect the player will never hit or hide one they will. The project's own
    choice wins, an explicit flag overrides it, and a project that declares
    nothing falls back to the pinned default and says so.
    """
    if rendering_method is not None:
        if rendering_method not in RENDERING_METHODS:
            raise StudioError("Rendering method must be " + ", ".join(RENDERING_METHODS))
        method, method_source = rendering_method, "override"
    else:
        declared = _setting(root, "rendering", "renderer/rendering_method")
        method = declared if declared in RENDERING_METHODS else None
        method_source = "project" if method else "default"
    if resolution is not None:
        if not re.fullmatch(r"[1-9][0-9]{1,4}x[1-9][0-9]{1,4}", resolution):
            raise StudioError("Resolution must be WIDTHxHEIGHT, for example 1920x1080")
        size, size_source = resolution, "override"
    else:
        width = _setting(root, "display", "window/size/viewport_width")
        height = _setting(root, "display", "window/size/viewport_height")
        size = f"{width}x{height}" if (width or "").isdigit() and (height or "").isdigit() else None
        size_source = "project" if size else "default"
    return method, method_source, size, size_source


def _revision(root):
    """The project's commit and whether its tree is dirty, when it is a checkout.

    A playtest is evidence about one build of a game, so the receipt names the
    source that produced it. A project that is not a checkout reports nulls: not
    knowing the commit is a gap in the evidence, not a reason to refuse the run.
    The queries are asked rather than predicted from a `.git` entry beside the
    project, because a game inside a monorepo has its checkout further up and
    would otherwise lose the identity this receipt exists to keep.
    """
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
    quoted = f'"{value}"' if not value or re.search(r"[\s&|<>^()%!,;=]", value) else value
    # Quoting does not stop cmd.exe expanding %NAME%, so a launcher would run a
    # different argument than the session did, and could paste an environment
    # value into a file that deliberately carries none. In a batch file, %% is
    # the literal per cent sign.
    return quoted.replace("%", "%%")


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
        body = [
            f"cd /d {_cmd_quote(str(root))} || exit /b 1",
            " ".join(_cmd_quote(item) for item in args),
        ]
    else:
        name, comment, head = "relaunch.sh", "# ", ["#!/bin/sh"]
        body = [
            f"cd -- {shlex.quote(str(root))} || exit 1",
            " ".join(shlex.quote(item) for item in args),
        ]
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
        "Runs the same engine, project and scene as the recorded session,",
        "from the project directory the session ran in, so a relative path",
        "resolves the way it did then.",
        "It establishes nothing: a playtest is accepted by a person, not by a script.",
    ]
    path = run_dir / name
    path.write_text("\n".join(head + [comment + note for note in notes] + body + [""]), encoding="utf-8")
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
    label=None, max_minutes=None, cutoff_utc=None, results=(), scrub=(),
    passthrough=(), use_host_profile=False, emit_launcher=True,
    rendering_method=None, resolution=None,
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
    if script is not None and scene is not None:
        # The harness is the SceneTree entrypoint and loads its own scene, so a
        # scene named here would be recorded and hashed as evidence of a route
        # the harness never drove.
        raise StudioError(
            "A driven playtest takes its scene from the harness; set it there rather than with --scene"
        )
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
    if max_minutes is None:
        # Attended defaults to uncapped because a cap is exactly what it cannot
        # keep; the other sessions are waited for and take the ordinary default.
        max_minutes = 0 if session == "attended" else DEFAULT_MAX_MINUTES
    if type(max_minutes) not in (int, float) or not math.isfinite(max_minutes) or max_minutes < 0:
        raise StudioError("Playtest --max-minutes must be a number of minutes, or 0 for no cap")
    if session == "attended" and max_minutes != 0:
        # Nothing waits for an attended session, so a cap could only be written
        # into the receipt, never applied. Refusing beats recording a bound that
        # does not exist.
        raise StudioError(
            "An attended playtest is not waited for and cannot be capped; "
            "omit --max-minutes or pass 0, and end the session by quitting the game"
        )
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
    if any(item.startswith(HARNESS_ARGUMENT) for item in passthrough):
        # The kit knows the run directory and supplies this itself. Two values
        # would leave the report path and the recorded evidence disagreeing,
        # with nothing to say which one the harness actually used.
        raise StudioError(
            f"The playtest supplies {HARNESS_ARGUMENT}<path> for a driven session; "
            "remove it from the passthrough"
        )
    method, method_source, size, size_source = _display(root, rendering_method, resolution)
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
    # The native flag shape is the owned launcher's, so playtest inherits any
    # flag it gains; only the two values a player would notice are replaced.
    flags = mode_flags("native")
    if method is not None:
        flags[flags.index("--rendering-method") + 1] = method
    if size is not None:
        flags[flags.index("--resolution") + 1] = size
    args = [str(engine_path.resolve()), "--path", app_path(config, root, "godot")] + flags
    if script is not None:
        args += ["--script", script]
    if scene is not None:
        args.append(scene)
    args += list(passthrough)
    harness_report = None
    if session == "driven":
        # Declaring the report through --result and naming it again through the
        # passthrough meant keeping two paths in sync by hand, and getting it
        # wrong produced "declared result missing" with no hint why.
        harness_report = f"artifacts/playtests/{label}/{HARNESS_REPORT}"
        args += [] if list(passthrough)[:1] == ["--"] else ["--"]
        args.append(HARNESS_ARGUMENT + app_path(config, run_dir / HARNESS_REPORT, "godot"))
    if emit_launcher and IS_WINDOWS and any('"' in item for item in args):
        # Refuse here rather than when the launcher is written, which is after
        # the run directory exists: the advice below has to still be possible.
        raise StudioError(
            "An argument containing a quotation mark cannot be written to a "
            ".cmd launcher; rerun with --no-launcher"
        )
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Playtest directory exists; choose a new label") from None
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
        # never describe a renderer or resolution the engine was not given, and
        # say where each came from so nobody reads a fallback as the game's own
        # configuration.
        "rendering_method": flags[flags.index("--rendering-method") + 1],
        "rendering_method_source": method_source,
        "resolution": flags[flags.index("--resolution") + 1],
        "resolution_source": size_source,
        "harness_report": harness_report,
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
    # Snapshot, then bytes, then cutoff: on Windows this enumeration costs
    # seconds, and taking it after the two checks below would leave a slow
    # query between the digest this session verified and the engine it starts,
    # and would spend part of the window after the window was found open. An
    # attended session takes none: nothing ever stops its descendants for it,
    # so the evidence would only delay the human it hands the game to.
    try:
        baseline = prelaunch_baseline(hide_window=False) if session != "attended" else None
    except KeyboardInterrupt:
        # The receipts for this label already exist; an interrupt during the
        # enumeration must leave them saying so rather than "launching".
        playtest.update(status="interrupted", max_minutes_effective=None,
                        process_record=None)
        write_json(run_dir / "playtest.json", playtest)
        _finish(root, run_dir, playtest, None, "", "interrupted",
                "playtest interrupted before the engine started")
        raise
    # The digest verified above described bytes that could have been replaced
    # while this session was prepared, so the engine is re-read after that last
    # slow step: only the verified identity may start.
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
        # The cutoff above decided whether this session could start; nothing
        # here can decide when it ends, so the receipt records no cap at all
        # rather than one that was computed and then never applied.
        playtest["max_minutes_effective"] = None
        try:
            started = start(args, job_dir=run_dir / "process", cwd=str(root),
                            env=environment, baseline=baseline)
        except StudioError as exc:
            # The runner has already written a start_failed process record; the
            # session receipt must not be left claiming it is still launching,
            # and there is no session for a later collect to complete.
            playtest.update(status="start_failed")
            write_json(run_dir / "playtest.json", playtest)
            failed_record = run_dir / "process" / "process.json"
            return _finish(
                root, run_dir, playtest,
                read_json(failed_record) if failed_record.is_file() else {"status": "start_failed"},
                "", "start_failed", str(exc),
            )
        playtest.update(status="launched", pid=started["pid"])
        try:
            write_json(run_dir / "playtest.json", playtest)
        except BaseException:
            # This receipt is how anyone finds the session again, and an
            # auto-generated label is never returned to the caller, so a child
            # left running here could not even be named to clean it up.
            stop_started(started["pid"])
            raise
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
            hide_window=False, job_dir=run_dir / "process", baseline=baseline,
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
        left = stop_survivors(
            record["pid"], hide_window=False, ownership=record.get("windows_ownership"),
        )
        playtest["survivors"] = left
    verdict = None
    if interrupt is not None:
        verdict = "interrupted"
    elif playtest["engine"]["sha256_after_exit"] != actual:
        verdict = "engine_replaced"
        failure = "Engine bytes changed during the playtest; the receipts describe bytes it no longer has"
    elif left and left.get("unverified"):
        # Left running deliberately: nothing here proves they are this job's.
        verdict = "descendants_unverified"
        failure = failure or (
            "Processes under this playtest could not be attributed to it and were left "
            "running: " + ", ".join(str(entry["pid"]) for entry in left["unverified"])
        )
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


def _harness(root, run_dir, playtest):
    """The driven harness's own report, which this command supplied the path for.

    Returns (file record, fault). The harness also pushes a failed assertion to
    the engine log and quits non-zero, so this is a second reading of the same
    verdict rather than the only one; a harness that wrote nothing is the case
    the log alone would not catch.
    """
    if not playtest.get("harness_report"):
        return None, None
    path = run_dir / HARNESS_REPORT
    if not path.is_file():
        return None, "harness_report_missing"
    record = file_record(root, path)
    try:
        report = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return record, "harness_report_unreadable"
    if not isinstance(report, dict) or report.get("ok") is not True:
        return record, "harness_failed"
    return record, None


def _finish(root, run_dir, playtest, record, text, verdict, failure, survivors=None):
    diagnostics = classify_log(text)
    write_json(run_dir / "diagnostics.json", diagnostics)
    result_files = _result_files(root, playtest)
    harness_record, harness_fault = _harness(root, run_dir, playtest)
    status = record.get("status", "start_failed") if record else "refused"
    if verdict is None:
        verdict = _health(diagnostics, result_files, "completed") if status == "completed" else status
        if verdict == "completed" and harness_fault:
            verdict = harness_fault
            failure = failure or "The driven harness did not report a passing route"
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
        "harness_report": harness_record,
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
    # A receipt read back from disk is untrusted input: every field used below
    # is checked here so a truncated or hand-edited record refuses clearly
    # instead of failing somewhere deeper as a KeyError.
    if (not all(key in playtest for key in REQUIRED_RECEIPT_FIELDS)
            or not isinstance(playtest.get("engine"), dict)
            or not isinstance(playtest["engine"].get("sha256"), str)
            or not isinstance(playtest.get("expected_results"), list)):
        raise StudioError("Playtest receipt is incomplete; this session cannot be collected")
    if (run_dir / "exit.json").is_file():
        raise StudioError("That playtest was already collected; a session is collected once")
    # Claim the session before reading it. Two collects racing would otherwise
    # both pass the check above and both believe they performed a one-time
    # operation; only the process that creates this marker may finish.
    reservation = run_dir / "collect.lock"
    try:
        reservation.mkdir(exist_ok=False)
    except FileExistsError:
        raise StudioError(
            "Another collect is completing this playtest; a session is collected once"
        ) from None
    try:
        return _collected(config, root, run_dir, record_path, playtest)
    except BaseException:
        # A collect that did not finish leaves nothing claimed, so the session
        # can be collected again once whatever stopped it is fixed.
        reservation.rmdir()
        raise


def _collected(config, root, run_dir, record_path, playtest):
    """Read one attended session's evidence and write its exit receipt."""
    engine = executable(config, "godot")
    playtest["engine"]["sha256_after_exit"] = _readable_digest(Path(engine)) if engine else None
    process_path = run_dir / "process" / "process.json"
    record = read_json(process_path) if process_path.is_file() else {}
    log_path = run_dir / "process" / "stdout.log"
    text = log_path.read_bytes().decode("utf-8", errors="replace") if log_path.is_file() else ""
    running = alive(record.get("pid"))
    if running is True:
        # Refuse rather than record: writing exit.json here would consume the
        # one collection this session gets, so a call that merely raced the
        # player's last click would lock out the real receipt for good.
        raise StudioError(
            "The engine from this session is still running; collect once the game has been quit"
        )
    playtest["engine_running_at_collect"] = running
    write_json(record_path, playtest)
    diagnostics = classify_log(text)
    write_json(run_dir / "diagnostics.json", diagnostics)
    result_files = _result_files(root, playtest)
    failure = None
    after = playtest["engine"]["sha256_after_exit"]
    if after is not None and after != playtest["engine"]["sha256"]:
        verdict = "engine_replaced"
        failure = "Engine bytes changed during the session; the receipts describe bytes it no longer has"
    elif not record.get("pid"):
        verdict = record.get("status", "start_failed")
    elif after is None:
        # Collection cannot confirm the engine it started is the engine it
        # finished with, so the session does not get a clean verdict.
        verdict = "engine_unverified"
        failure = (
            "The configured engine could not be re-read at collection, so this session's "
            "engine identity after the run is unknown"
        )
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
        "status": "unobserved",
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
