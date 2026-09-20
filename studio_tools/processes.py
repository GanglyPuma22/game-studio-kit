"""Bounded argument-array execution; cleanup touches only this job's process."""

from __future__ import annotations
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
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


def _windows_query(query, hide_window):
    """Run one CIM query: ("ok", rows) when it answered, ("failed", None) when it did not.

    An answer holding no rows is still an answer: it says the table has nothing
    matching. Keeping that apart from a query that never ran is what lets
    cleanup call a survivor that has already exited stopped rather than
    unaccounted for.
    """
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return "failed", None
    try:
        done = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True, text=True, timeout=30, check=False,
            **_creation_options(hide_window),
        )
        if done.returncode:
            return "failed", None
        text = done.stdout.strip()
        rows = json.loads(text) if text else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return "failed", None
    if isinstance(rows, dict):
        return "ok", [rows]
    return ("ok", rows) if isinstance(rows, list) else ("failed", None)


def _windows_rows(query, hide_window):
    """Return parsed Win32_Process rows, or None when the query is unavailable."""
    state, rows = _windows_query(query, hide_window)
    return rows if state == "ok" else None


# A PID alone names a slot in the process table, not a process: Windows hands
# the same number to something new as soon as the old holder exits. The image
# name and the creation time are what keep a row a process this job started.
CIM_IDENTITY = (
    "Select-Object ProcessId,ParentProcessId,Name,@{Name='CreationFileTime';Expression={"
    "if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().ToFileTimeUtc()} else {$null}}} "
    "| ConvertTo-Json -Compress"
)


def _windows_row(row):
    """Normalize one CIM row to the identity fields classification reads."""
    try:
        parent, name = row.get("ParentProcessId"), row.get("Name")
        created = row.get("CreationFileTime")
        return {
            "pid": int(row["ProcessId"]),
            "ppid": None if parent is None else int(parent),
            "name": str(name) if name else None,
            "created_filetime": str(created) if created else None,
        }
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _windows_snapshot(hide_window):
    """Enumerate every process with its identity, or report the host cannot."""
    rows = _windows_rows("Get-CimInstance Win32_Process | " + CIM_IDENTITY, hide_window)
    if rows is None:
        # Keep telling an operator which of the two it is: one is fixable here.
        note = ("process enumeration failed" if shutil.which("pwsh") or shutil.which("powershell")
                else "no PowerShell to enumerate processes")
        return {"status": "unavailable", "processes": [], "note": note}
    found = [entry for entry in (_windows_row(row) for row in rows) if entry is not None]
    if not found:
        return {"status": "unavailable", "processes": [], "note": "no processes were enumerated"}
    return {"status": "ok", "processes": found, "note": None}


def _windows_identity_state(pid, hide_window):
    """What the table holds for one PID: ("present", row), ("absent", None) or ("unknown", None).

    Three different facts, and cleanup acts differently on each: a row that is
    present may have changed hands since the snapshot, an absent PID is a
    process that has already exited, and a query that failed says neither.
    """
    state, rows = _windows_query(
        f"Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' | " + CIM_IDENTITY,
        hide_window,
    )
    if state != "ok":
        return "unknown", None
    if not rows:
        return "absent", None
    entry = _windows_row(rows[0])
    # A row that cannot be parsed is not proof of anything, absence included.
    return ("present", entry) if entry is not None else ("unknown", None)


def _windows_identity(pid, hide_window):
    """Read what one PID holds right now, or None when it cannot be read."""
    return _windows_identity_state(pid, hide_window)[1]


def _windows_handle_times(process):
    """Read (creation, exit) FILETIME through the handle `Popen` still owns.

    The handle keeps an exited process's times readable after it was reaped,
    which a PID query cannot do: by then the number may name something else.
    An exit time of zero means the process is still running.
    """
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FileTime)] * 4
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    creation, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
    if not kernel32.GetProcessTimes(
        wintypes.HANDLE(int(process._handle)), ctypes.byref(creation),
        ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user),
    ):
        raise OSError(ctypes.get_last_error(), "GetProcessTimes failed")
    ticks = lambda value: (int(value.high) << 32) | int(value.low)
    return str(ticks(creation)), (str(ticks(exited)) if ticks(exited) else None)


def _windows_image_name(process):
    """Image name of the owned process, read from its handle."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    size = wintypes.DWORD(32768)
    image = ctypes.create_unicode_buffer(size.value)
    if not kernel32.QueryFullProcessImageNameW(
        wintypes.HANDLE(int(process._handle)), wintypes.DWORD(0), image, ctypes.byref(size)
    ):
        raise OSError(ctypes.get_last_error(), "QueryFullProcessImageNameW failed")
    # Windows path, parsed as one whatever host the fakes in the tests run on.
    return PureWindowsPath(image.value).name


def _windows_root_identity(process, hide_window):
    """Identity of the process this job just started, or None when unreadable."""
    try:
        created, _ = _windows_handle_times(process)
        name = _windows_image_name(process)
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        # No handle identity on this host; the live CIM row is the only source,
        # and it is read now, while the PID still belongs to this process.
        row = _windows_identity(process.pid, hide_window)
        if row is None:
            return None
        created, name = row["created_filetime"], row["name"]
    return {"pid": int(process.pid), "name": name,
            "created_filetime": created, "exited_filetime": None}


def _identified(entry):
    """Whether a row carries what makes it a process rather than a PID."""
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("pid"), int)
        and bool(entry.get("name"))
        and bool(entry.get("created_filetime"))
    )


def _same_identity(left, right):
    return (
        _identified(left) and _identified(right)
        and left["pid"] == right["pid"]
        and left["name"] == right["name"]
        and left["created_filetime"] == right["created_filetime"]
    )


def _born_in_root_lifetime(entry, identity):
    """Whether this row was created while the job's root process was alive."""
    try:
        created = int(entry["created_filetime"])
        return int(identity["created_filetime"]) <= created <= int(identity["exited_filetime"])
    except (KeyError, TypeError, ValueError):
        return False


def _windows_ownership(baseline, identity):
    """The launch-time evidence post-exit cleanup needs to name a descendant.

    Only the pid and creation time of the prelaunch table are kept: that is all
    the "was already running" test reads, and a receipt should not carry an
    inventory of unrelated software running on the host.
    """
    note = None
    if not isinstance(baseline, dict) or baseline.get("status") != "ok":
        note = "prelaunch process snapshot unavailable"
    elif not _identified(identity):
        note = "launched process identity unavailable"
    return {
        "status": "ok" if note is None else "unavailable",
        "identity": identity,
        "prelaunch": [
            {"pid": entry["pid"], "created_filetime": entry["created_filetime"]}
            for entry in (baseline.get("processes", []) if isinstance(baseline, dict) else [])
        ],
        "note": note,
    }


def _windows_candidates(children, pid):
    """Every PID reachable from `pid` by parent links, proven or not."""
    found, seen, queue = [], {pid}, [pid]
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in seen:
                seen.add(child)
                found.append(child)
                queue.append(child)
    return sorted(found)


def _windows_survivors(pid, hide_window, ownership=None):
    """Name only the descendants this job's launch evidence can account for.

    Windows has no process group to enumerate, so the parent table is all there
    is; but after the root was reaped its PID can already belong to something
    else, and walking from it would then claim a stranger's tree. A row is this
    job's descendant only when its parent chain reaches the root through rows
    that passed the same test, it was created inside the root's lifetime, and
    it was not already running when the job started. Anything else is a
    candidate reported as unverified, never a process to signal.
    """
    snapshot = _windows_snapshot(hide_window)
    if snapshot["status"] != "ok":
        return {"status": "unavailable", "pids": [], "verified_pids": [], "identities": {},
                "unverified": [], "ignored": [], "note": snapshot["note"]}
    processes = {entry["pid"]: entry for entry in snapshot["processes"]}
    children = {}
    for entry in processes.values():
        children.setdefault(entry["ppid"], []).append(entry["pid"])
    identity = ownership.get("identity") if isinstance(ownership, dict) else None
    if (
        not isinstance(ownership, dict) or ownership.get("status") != "ok"
        or not _identified(identity) or not identity.get("exited_filetime")
        or identity["pid"] != pid
    ):
        # Without the evidence nothing under this PID can be attributed, so the
        # tree is reported in full and left alone rather than walked and killed.
        candidates = _windows_candidates(children, pid)
        return {
            "status": "unavailable", "pids": candidates, "verified_pids": [], "identities": {},
            "unverified": [{"pid": member, "reason": "ownership_evidence_unavailable"}
                           for member in candidates],
            "ignored": [], "note": "launch identity evidence for this job is unavailable",
        }
    prelaunch = {entry["pid"]: entry for entry in ownership.get("prelaunch", [])
                 if isinstance(entry, dict) and isinstance(entry.get("pid"), int)}
    verified, unverified, ignored = [], [], []
    seen, queue = {pid}, [pid]
    while queue:
        for child in children.get(queue.pop(), ()):
            if child in seen:
                continue
            seen.add(child)
            entry, older = processes[child], prelaunch.get(child)
            if older is not None and not older.get("created_filetime"):
                unverified.append({"pid": child, "reason": "prelaunch_identity_incomplete"})
            elif not _identified(entry):
                unverified.append({"pid": child, "reason": "current_identity_incomplete"})
            elif older is not None and older["created_filetime"] == entry["created_filetime"]:
                # The same process was running before this job started.
                ignored.append(child)
            elif not _born_in_root_lifetime(entry, identity):
                unverified.append({"pid": child, "reason": "created_outside_root_lifetime"})
            else:
                verified.append(child)
                # Only a verified parent extends the chain: an unproven row
                # cannot lend its children this job's name.
                queue.append(child)
    return {
        "status": "unavailable" if unverified else "ok",
        "pids": sorted(verified + [entry["pid"] for entry in unverified]),
        "verified_pids": sorted(verified),
        "identities": {str(member): processes[member] for member in verified},
        "unverified": sorted(unverified, key=lambda entry: entry["pid"]),
        "ignored": sorted(ignored),
        "note": "a process under this job could not be identified" if unverified else None,
    }


def _windows_alive(pid):
    """Ask the process table `_windows_survivors` walks whether this PID is present.

    Windows has no zombie state to exclude: a PID the table still lists is a
    process that has not exited.
    """
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return None
    query = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' | Measure-Object).Count"
    try:
        done = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True, text=True, timeout=30, check=False,
            **_creation_options(True),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    counted = done.stdout.strip()
    if done.returncode or not counted.isdigit():
        return None
    return int(counted) > 0


def alive(pid):
    """Whether `pid` is still a running process, or None where this host cannot tell.

    This is the only signal available about a job nobody waited for: a caller
    that did not start a process cannot reap it, so it has no exit status to
    read. A zombie has already finished. A host that cannot answer gets None
    rather than a guess, because a wrong "finished" would describe a session
    that is still going and a wrong "running" would block the caller. A true
    answer is a statement about the PID, not proof that the original process
    still holds it.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if os.name == "nt":
        return _windows_alive(pid)
    if not PROC.is_dir():
        return None
    state = _proc_state(pid)
    return state is not None and state[0] != "Z"


def survivors(pid, hide_window=False, ownership=None):
    """List processes of this job that are still running after its leader exited.

    POSIX jobs start in a new session, so the leader's PID is the process group
    every descendant inherits; a zombie holds no resources and is not listed.
    Windows has no such group, so it needs `ownership`: the launch-time
    identity evidence `run` recorded, without which nothing can be attributed.
    """
    if os.name == "nt":
        return _windows_survivors(pid, hide_window, ownership)
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


def _windows_stop(pid, hide_window, ownership, before):
    """Terminate the verified descendants only, each proven again at the kill.

    `taskkill` takes a PID, so the row that named a descendant a moment ago is
    re-read immediately before signalling it: a number that changed hands since
    the snapshot is skipped and reported instead of killed, and one the table no
    longer holds has stopped itself and is recorded in `exited_pids`.

    Only the proven number is signalled. The walk in `_windows_survivors`
    already enqueued every verified child, so the whole proven tree is covered
    PID by PID, while `/T` would also take whatever the same enumeration
    refused to name and anything spawned under it since the snapshot.

    Every snapshot taken here contributes to `unverified`, not just the first:
    a process this job cannot account for is no less unaccounted for because it
    only became visible while its parent was being stopped.
    """
    unverified = {}

    def account(entries):
        for entry in entries:
            # First reason wins: it describes the moment the row was first seen.
            unverified.setdefault(entry["pid"], entry)

    account(before["unverified"])
    refused, exited = [], []
    for member in before["verified_pids"]:
        state, current = _windows_identity_state(member, hide_window)
        if state == "absent":
            # Gone between the snapshot and this lookup: already stopped, and
            # calling that unverified would report a clean run as a dirty one.
            exited.append(member)
            continue
        if state != "present" or not _same_identity(
            before["identities"].get(str(member)), current
        ):
            refused.append({
                "pid": member,
                "reason": ("identity_changed_before_stop" if state == "present"
                           else "identity_unavailable_before_stop"),
            })
            continue
        try:
            subprocess.run(
                ["taskkill", "/PID", str(member), "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=5, **_creation_options(hide_window),
            )
        except (OSError, subprocess.SubprocessError):
            pass
    account(refused)
    # Termination is asynchronous; give the verified set a bounded moment to go.
    deadline = time.monotonic() + 5
    after = survivors(pid, hide_window, ownership)
    account(after["unverified"])
    while after["verified_pids"] and time.monotonic() < deadline:
        time.sleep(0.025)
        after = survivors(pid, hide_window, ownership)
        account(after["unverified"])
    left = sorted(unverified.values(), key=lambda entry: entry["pid"])
    status = "ok" if (
        before["status"] == "ok" and after["status"] == "ok" and not left
    ) else "unavailable"
    return {
        "status": status,
        "pids": before["pids"],
        "stopped": status == "ok" and not after["verified_pids"],
        "verified_pids": before["verified_pids"],
        "exited_pids": sorted(exited),
        "unverified": left,
        "ignored": before["ignored"],
        "note": before["note"] or (
            "processes under this job were left running because this launch's "
            "evidence does not name them" if left else None
        ),
    }


def stop_survivors(pid, hide_window=False, ownership=None):
    """Stop what outlived this job's leader, then re-enumerate to prove it.

    `pids` are the candidates found before stopping. POSIX signals the process
    group, which no reused PID can join. Windows has only PIDs, and the leader
    has already been reaped, so a PID is signalled there only when the launch
    evidence in `ownership` shows it as a descendant created during the
    leader's life; anything else is left running and reported in `unverified`,
    because a process this job cannot name may well belong to somebody else.
    A verified PID that had already exited when its turn came is reported in
    `exited_pids`: it stopped, it was simply not this job that stopped it.
    """
    before = survivors(pid, hide_window, ownership)
    if os.name == "nt":
        return _windows_stop(pid, hide_window, ownership, before)
    if before["pids"] or before["note"]:
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
        # One shape for both hosts: a POSIX group signal reaches every member,
        # so nothing there is ever left behind unattributed.
        "unverified": [],
    }


def prelaunch_baseline(hide_window=False):
    """The process table as it was before a job started, or None off Windows.

    On Windows this is a full CIM enumeration and can cost seconds, which is
    why a caller working against an authorized cutoff takes it here, before its
    last cutoff check, rather than paying for it inside `run` after the window
    was already judged still open. Everywhere else there is nothing to take:
    a POSIX job is identified by its process group, not by a prior snapshot.
    """
    return _windows_snapshot(hide_window) if os.name == "nt" else None


def run(
    args, *, cwd=None, timeout=180, log=None, env=None,
    hide_window=False, job_dir=None, baseline=None,
):
    """Run a foreground command; optional job_dir must be a new directory.

    The combined log is written while the child runs. A job directory also gets
    an atomic process.json before launch and after exit/failure. It contains no
    argv or environment. hide_window suppresses Windows console creation, not
    arbitrary GUI windows. Callers still choose a verified background operation.
    `baseline` is a `prelaunch_baseline()` the caller already took; without one
    a Windows job directory gets its own, taken here.
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

    # Written before the snapshot below, which can take seconds: an interrupt
    # during it must not leave a reserved job directory with no receipt in it.
    save_record()
    # The baseline is from before the child exists, so every process it can
    # later be confused with is already on record as somebody else's. Only a
    # job directory keeps the evidence, so a run without one does not pay for
    # the enumeration; a caller that already took one does not pay twice.
    owns_identity = os.name == "nt" and record_path is not None
    if owns_identity and baseline is None:
        baseline = _windows_snapshot(hide_window)
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
            if owns_identity:
                # Read now, while the handle is fresh and the PID is certainly
                # this process: after the wait below reaps it, the number alone
                # proves nothing about what is running under it.
                record["windows_ownership"] = _windows_ownership(
                    baseline, _windows_root_identity(process, hide_window)
                )
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
            owned_identity = (record.get("windows_ownership") or {}).get("identity")
            if owns_identity and process is not None and isinstance(owned_identity, dict):
                # The exit time closes the window a descendant of this job could
                # have been created in; without it nothing can be attributed.
                try:
                    _, exited = _windows_handle_times(process)
                except (AttributeError, ImportError, OSError, TypeError, ValueError):
                    exited = None
                owned_identity["exited_filetime"] = exited
                if not exited:
                    record["windows_ownership"].update(
                        status="unavailable", note="launched process exit identity unavailable"
                    )
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


def start(args, *, job_dir, cwd=None, env=None, hide_window=False, baseline=None):
    """Start a job, record it, and return while it is still running.

    The opposite trade from `run`, and the only form that makes one: the caller
    gets no exit status, because the process is meant to outlive it. It exists
    for a session a human ends, where waiting would hold an agent at the child's
    mercy for as long as somebody feels like playing. The log and `process.json`
    are written exactly as `run` writes them, so one reader serves both forms,
    but the record keeps `status: running` and `owned: false` for good: nothing
    here ever observes the exit, and a later caller can only ask `alive`.

    A `baseline` the caller took with `prelaunch_baseline()` is recorded as the
    same `windows_ownership` evidence `run` writes. None is taken here: a
    session that is meant to outlive this process should not be delayed by an
    enumeration its caller can pay for before it decides to start at all.
    """
    if not isinstance(args, (list, tuple)) or not args:
        raise StudioError("Process command must be a nonempty argument array")
    folder = Path(job_dir).resolve()
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Job directory exists; choose a new run identity") from None
    log = folder / "stdout.log"
    record_path = folder / "process.json"
    record = {
        "schema_version": 1,
        "status": "starting",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "pid": None,
        "returncode": None,
        "hidden_console_requested": hide_window,
        "owned": False,
    }
    write_json(record_path, record)
    # The child holds its own descriptor on the log, so this process closes the
    # file as soon as the child has it: nothing stays behind to drain or wait.
    with log.open("wb") as capture:
        try:
            process = subprocess.Popen(
                [str(a) for a in args], cwd=cwd, env=env,
                stdout=capture, stderr=subprocess.STDOUT, **_creation_options(hide_window),
            )
        except (OSError, ValueError, TypeError) as exc:
            record["status"] = "start_failed"
            write_json(record_path, record)
            raise StudioError(
                f"Could not start {Path(str(args[0])).name}; check executable configuration"
            ) from exc
    record.update(status="running", pid=process.pid)
    if os.name == "nt" and baseline is not None:
        # Read now, while the PID is certainly this process: nothing here will
        # ever see it exit, so this is the only moment it can be identified.
        record["windows_ownership"] = _windows_ownership(
            baseline, _windows_root_identity(process, hide_window)
        )
    try:
        write_json(record_path, record)
    except BaseException:
        # Without this receipt nothing records the PID, so the session could
        # neither be collected nor accounted for: stop the child rather than
        # leave a game running that no record claims.
        try:
            _stop_owned(process, hide_window)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    return {"pid": process.pid, "log": str(log), "process_record": str(record_path)}


def stop_started(pid, hide_window=False):
    """Stop a job `start` launched, by PID, when its receipt could not be written.

    `start` deliberately keeps no handle on the child, so the PID it recorded a
    moment ago is the only way for a caller to take responsibility for what it
    launched. A POSIX job is its own process group, so the group signal reaches
    the leader and everything it spawned; Windows needs the tree walk taskkill
    performs. A PID can be reused, which is why this is only ever called
    immediately after the launch that produced it.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            return subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=5, **_creation_options(hide_window),
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        return False
    return True


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
