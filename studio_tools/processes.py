"""Bounded argument-array execution; cleanup touches only this job's process."""

from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import time
from .common import StudioError


def run(args, *, cwd=None, timeout=180, log=None, env=None):
    if not isinstance(args, (list, tuple)) or not args:
        raise StudioError("Process command must be a nonempty argument array")
    start = time.monotonic()
    kwargs = (
        {"start_new_session": True}
        if os.name != "nt"
        else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    )
    try:
        process = subprocess.Popen(
            [str(a) for a in args],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
    except OSError as exc:
        raise StudioError(
            f"Could not start {Path(str(args[0])).name}; check executable configuration"
        ) from exc
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            # /T is restricted to the PID we just created, never an executable name.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise StudioError(
            f"{Path(str(args[0])).name} timed out; owned process stopped"
        ) from exc
    text = output.decode("utf-8", errors="replace")
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        Path(log).write_text(text, encoding="utf-8")
    if process.returncode:
        # Do not echo arbitrary app/provider output, environment or credential-bearing argv.
        raise StudioError(
            f"{Path(str(args[0])).name} exited with code {process.returncode}; inspect the local application log"
        )
    return {
        "returncode": process.returncode,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "stdout": text,
    }
