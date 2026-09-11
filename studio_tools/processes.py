"""Bounded argument-array execution; cleanup touches only this job's process."""

from __future__ import annotations
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import time
from .common import StudioError, write_json

# Module level so a test can point the POSIX enumeration at a host without it.
PROC = Path("/proc")


def _creation_options(hide_window):
    if os.name != "nt":
        return {"start_new_session": True}
    flags = subprocess.CREATE_NEW_PROCESS_GROUP
    if hide_window:
        flags |= subprocess.CREATE_NO_WINDOW
    return {"creationflags": flags}


def _stop_owned(process, hide_window):
    """Bound cleanup too; failure must not be reported as a stopped process tree."""
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
            **_creation_options(hide_window),
        )
        if result.returncode:
            return False
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)
    return True


def _proc_state(pid):
    """Read (state, process group) from /proc/<pid>/stat, or None when unreadable.

    A process name may contain spaces and parentheses, so the fixed-width fields
    start after the last ')': state, ppid, then the process group.
    """
    try:
        stat = PROC / str(pid) / "stat"
        fields = stat.read_text(encoding="utf-8", errors="replace").rpartition(")")[2].split()
    except (OSError, ValueError):
        return None
    if len(fields) < 3:
        return None
    try:
        return fields[0], int(fields[2])
    except ValueError:
        return None


def _windows_survivors(pid, hide_window):
    """Walk the parent/child table; Windows has no process group to enumerate."""
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return {"status": "unavailable", "pids": [], "note": "no PowerShell to enumerate processes"}
    query = (
        "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId "
        "| ConvertTo-Json -Compress"
    )
    try:
        done = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True, text=True, timeout=30, check=False,
            **_creation_options(hide_window),
        )
        rows = json.loads(done.stdout) if not done.returncode and done.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        rows = None
    if rows is None:
        return {"status": "unavailable", "pids": [], "note": "process enumeration failed"}
    children = {}
    for row in [rows] if isinstance(rows, dict) else rows:
        try:
            child, parent = int(row["ProcessId"]), int(row["ParentProcessId"])
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        children.setdefault(parent, []).append(child)
    found, seen, queue = [], {pid}, [pid]
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in seen:
                seen.add(child)
                found.append(child)
                queue.append(child)
    return {"status": "ok", "pids": sorted(found), "note": None}


def survivors(pid, hide_window=False):
    """List processes of this job that are still running after its leader exited.

    POSIX jobs start in a new session, so the leader's PID is the process group
    every descendant inherits; a zombie holds no resources and is not listed.
    """
    if os.name == "nt":
        return _windows_survivors(pid, hide_window)
    if PROC.is_dir():
        found = []
        for entry in PROC.iterdir():
            if not entry.name.isdigit() or int(entry.name) == pid:
                continue
            state = _proc_state(entry.name)
            if state is not None and state[1] == pid and state[0] != "Z":
                found.append(int(entry.name))
        return {"status": "ok", "pids": sorted(found), "note": None}
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        # An empty process group is proof that nothing outlived the leader.
        return {"status": "ok", "pids": [], "note": None}
    except OSError:
        pass
    return {
        "status": "unavailable", "pids": [],
        "note": "process group members cannot be enumerated without /proc",
    }


def stop_survivors(pid, hide_window=False):
    """Stop what outlived this job's leader, then re-enumerate to prove it.

    `pids` are the survivors found before stopping. The leader has already been
    reaped by its own waiter, so a reused PID is an accepted, bounded risk here.
    """
    before = survivors(pid, hide_window)
    if before["pids"] or before["note"]:
        if os.name == "nt":
            for member in before["pids"]:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(member), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=False, timeout=5, **_creation_options(hide_window),
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    # Signal delivery is asynchronous; give the group a bounded moment to go.
    deadline = time.monotonic() + 5
    after = survivors(pid, hide_window)
    while after["status"] == "ok" and after["pids"] and time.monotonic() < deadline:
        time.sleep(0.025)
        after = survivors(pid, hide_window)
    return {
        "status": before["status"],
        "pids": before["pids"],
        "stopped": after["status"] == "ok" and not after["pids"],
    }


def run(
    args, *, cwd=None, timeout=180, log=None, env=None,
    hide_window=False, job_dir=None,
):
    """Run a foreground command; optional job_dir must be a new directory.

    The combined log is written while the child runs. A job directory also gets
    an atomic process.json before launch and after exit/failure. It contains no
    argv or environment. hide_window suppresses Windows console creation, not
    arbitrary GUI windows. Callers still choose a verified background operation.
    """
    if not isinstance(args, (list, tuple)) or not args:
        raise StudioError("Process command must be a nonempty argument array")
    if job_dir is not None and log is not None:
        raise StudioError("Choose job_dir or log, not both")
    folder = Path(job_dir).resolve() if job_dir is not None else None
    if folder is not None:
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise StudioError("Job directory exists; choose a new run identity") from None
        log = folder / "stdout.log"
    if log is not None:
        log = Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    record = {
        "schema_version": 1,
        "status": "starting",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "pid": None,
        "returncode": None,
        "hidden_console_requested": hide_window,
    }
    record_path = folder / "process.json" if folder is not None else None

    def save_record():
        if record_path is not None:
            write_json(record_path, record)

    save_record()
    process = None
    # Redirect to a file, not a pipe: partial output survives timeout and does
    # not depend on draining a descendant's inherited pipe during cleanup.
    with ExitStack() as files:
        previous_log = None
        if folder is None and log is not None and log.is_file():
            previous_log = files.enter_context(tempfile.TemporaryFile())
            with log.open("rb") as original:
                shutil.copyfileobj(original, previous_log)
            previous_log.seek(0)
        capture = files.enter_context(
            log.open("w+b") if log is not None else tempfile.TemporaryFile()
        )
        try:
            try:
                process = subprocess.Popen(
                    [str(a) for a in args],
                    cwd=cwd,
                    env=env,
                    stdout=capture,
                    stderr=subprocess.STDOUT,
                    **_creation_options(hide_window),
                )
            except (OSError, ValueError, TypeError) as exc:
                record["status"] = "start_failed"
                if previous_log is not None:
                    capture.seek(0)
                    shutil.copyfileobj(previous_log, capture)
                    capture.truncate()
                raise StudioError(
                    f"Could not start {Path(str(args[0])).name}; check executable configuration"
                ) from exc
            record.update(status="running", pid=process.pid)
            save_record()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                record["status"] = "timed_out"
                try:
                    stopped = _stop_owned(process, hide_window)
                except (OSError, subprocess.TimeoutExpired):
                    stopped = False
                record["cleanup"] = "owned_tree_stopped" if stopped else "unverified"
                detail = "owned process stopped" if stopped else "owned process cleanup unverified"
                raise StudioError(
                    f"{Path(str(args[0])).name} timed out; {detail}"
                ) from exc
            record["status"] = "completed" if process.returncode == 0 else "failed"
            if process.returncode:
                # Never echo arbitrary output or credential-bearing argv/env.
                raise StudioError(
                    f"{Path(str(args[0])).name} exited with code {process.returncode}; inspect the local application log"
                )
        except BaseException:
            # A receipt-write failure or caller interruption after launch must
            # not leave a running job behind or give it a completed status.
            if process is not None and (
                record["status"] in ("starting", "running")
                or (record["status"] == "timed_out" and "cleanup" not in record)
            ):
                if record["status"] != "timed_out":
                    record["status"] = "interrupted"
                record["pid"] = process.pid
                # A second interruption must still leave an honest receipt.
                record["cleanup"] = "unverified"
                # Avoid signaling a PID already reaped by a successful wait.
                # Pending timeout cleanup must still account for descendants.
                needs_cleanup = (
                    process.returncode is None if record["status"] == "timed_out"
                    else process.poll() is None
                )
                if needs_cleanup:
                    try:
                        stopped = _stop_owned(process, hide_window)
                    except (OSError, subprocess.TimeoutExpired):
                        stopped = False
                    record["cleanup"] = "owned_tree_stopped" if stopped else "unverified"
            raise
        finally:
            capture.flush()
            record.update(
                finished_utc=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=round(time.monotonic() - start, 3),
                returncode=process.poll() if process is not None else None,
            )
            save_record()
        capture.seek(0)
        text = capture.read().decode("utf-8", errors="replace")
    return {
        "returncode": process.returncode,
        "elapsed_seconds": record["elapsed_seconds"],
        "stdout": text,
        "log": str(log) if log is not None else None,
        "process_record": str(record_path) if record_path is not None else None,
    }


def record(args, *, job_dir, duration, grace=5, startup=0, cancelled=None, cwd=None):
    """Own one recorder, send FFmpeg's q on stop, then bound finalization.

    Cancellation/interrupt is retained as incomplete even if the muxer closes.
    No PID from disk is ever signalled. The caller validates the media separately.
    """
    import math
    if not isinstance(args, (list, tuple)) or not args:
        raise StudioError("Recorder requires an argument array")
    if any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in (duration, grace)) or duration > 1200 or grace > 30:
        raise StudioError("Recorder needs duration <=1200 and grace <=30 seconds")
    if type(startup) not in (int, float) or not math.isfinite(startup) or not 0 <= startup <= 30:
        raise StudioError("Recorder startup allowance must be 0–30 seconds")
    folder = Path(job_dir)
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Job directory exists; choose a new run identity") from None
    receipt = {"schema_version": 1, "status": "starting", "pid": None,
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "stop_reason": None, "graceful": False, "cleanup": "not_needed", "watchdog_seconds": duration + startup, "finalization_seconds": grace}
    started = time.monotonic()
    process = None
    with (folder / "stdout.log").open("wb") as log:
        try:
            write_json(folder / "process.json", receipt)
            if cancelled and cancelled():
                receipt.update(status="cancelled", stop_reason="cancelled_before_start")
                return receipt
            try:
                process = subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE,
                    stdout=log, stderr=subprocess.STDOUT, cwd=cwd, **_creation_options(True))
            except (OSError, ValueError, TypeError):
                receipt["status"] = "start_failed"
                return receipt
            receipt.update(status="running", pid=process.pid)
            write_json(folder / "process.json", receipt)
            try:
                while process.poll() is None:
                    if cancelled and cancelled():
                        receipt["stop_reason"] = "cancelled"
                        break
                    if time.monotonic() - started >= duration + startup:
                        receipt["stop_reason"] = "duration"
                        break
                    time.sleep(.025)
            except KeyboardInterrupt:
                receipt["stop_reason"] = "cancelled"
            if process.poll() is None:
                try:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    receipt["status"] = "timed_out"
                    receipt["cleanup"] = "unverified"
                    try:
                        if _stop_owned(process, True):
                            receipt["cleanup"] = "owned_tree_stopped"
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            if receipt["status"] != "timed_out":
                receipt["graceful"] = process.returncode == 0
                receipt["status"] = ("cancelled" if receipt["stop_reason"] == "cancelled" else
                                     "completed" if process.returncode == 0 else "failed")
            return receipt
        finally:
            if process is not None:
                if process.poll() is None:
                    receipt.update(status=receipt["status"] if receipt["status"] == "timed_out" else "interrupted", cleanup="unverified")
                    try:
                        if _stop_owned(process, True):
                            receipt["cleanup"] = "owned_tree_stopped"
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                if process.stdin:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                receipt["returncode"] = process.poll()
            receipt.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                           elapsed_seconds=round(time.monotonic() - started, 6))
            write_json(folder / "process.json", receipt)
