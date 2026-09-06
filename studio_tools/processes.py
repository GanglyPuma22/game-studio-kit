"""Bounded argument-array execution; cleanup touches only this job's process."""

from __future__ import annotations
from contextlib import ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import time
from .common import StudioError, write_json


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


def record(args, *, job_dir, duration, grace=5, cancelled=None, cwd=None):
    """Own one recorder, send FFmpeg's q on stop, then bound finalization.

    Cancellation/interrupt is retained as incomplete even if the muxer closes.
    No PID from disk is ever signalled. The caller validates the media separately.
    """
    import math
    if not isinstance(args, (list, tuple)) or not args:
        raise StudioError("Recorder requires an argument array")
    if any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in (duration, grace)) or duration > 1200 or grace > 30:
        raise StudioError("Recorder needs duration <=1200 and grace <=30 seconds")
    folder = Path(job_dir)
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Job directory exists; choose a new run identity") from None
    receipt = {"schema_version": 1, "status": "starting", "pid": None,
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "stop_reason": None, "graceful": False, "cleanup": "not_needed"}
    started = time.monotonic()
    process = None
    with (folder / "stdout.log").open("wb") as log:
        try:
            write_json(folder / "process.json", receipt)
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
                    if time.monotonic() - started >= duration:
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
                    if _stop_owned(process, True):
                        receipt["cleanup"] = "owned_tree_stopped"
            if receipt["status"] != "timed_out":
                receipt["graceful"] = process.returncode == 0
                receipt["status"] = ("cancelled" if receipt["stop_reason"] == "cancelled" else
                                     "completed" if process.returncode == 0 else "failed")
            return receipt
        finally:
            if process is not None:
                if process.poll() is None:
                    receipt.update(status="interrupted", cleanup="unverified")
                    try:
                        if _stop_owned(process, True):
                            receipt["cleanup"] = "owned_tree_stopped"
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                if process.stdin:
                    process.stdin.close()
                receipt["returncode"] = process.poll()
            receipt.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                           elapsed_seconds=round(time.monotonic() - started, 6))
            write_json(folder / "process.json", receipt)
