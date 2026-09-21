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

# One CIM query is a PowerShell start and can block; cleanup makes several, so
# it gets one total budget rather than a fresh allowance for every question.
QUERY_SECONDS = 30
CLEANUP_BUDGET_SECONDS = 30


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


def _windows_query(query, hide_window, timeout=QUERY_SECONDS):
    """Run one CIM query: ("ok", rows) when it answered, ("failed", None) when it did not.

    An answer holding no rows is still an answer: it says the table has nothing
    matching. Keeping that apart from a query that never ran is what lets
    cleanup call a survivor that has already exited stopped rather than
    unaccounted for. A caller with no time left asks for none: a query that
    cannot be given a moment to answer is not started at all.
    """
    if timeout is not None and timeout <= 0:
        return "failed", None
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return "failed", None
    try:
        done = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True, text=True, timeout=timeout, check=False,
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


def _windows_rows(query, hide_window, timeout=QUERY_SECONDS):
    """Return parsed Win32_Process rows, or None when the query is unavailable."""
    state, rows = _windows_query(query, hide_window, timeout)
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


def _windows_snapshot(hide_window, timeout=QUERY_SECONDS):
    """Enumerate every process with its identity, or report the host cannot."""
    rows = _windows_rows("Get-CimInstance Win32_Process | " + CIM_IDENTITY, hide_window, timeout)
    if rows is None:
        # Keep telling an operator which of the two it is: one is fixable here.
        note = ("process enumeration failed" if shutil.which("pwsh") or shutil.which("powershell")
                else "no PowerShell to enumerate processes")
        return {"status": "unavailable", "processes": [], "note": note}
    found = [entry for entry in (_windows_row(row) for row in rows) if entry is not None]
    if not found:
        return {"status": "unavailable", "processes": [], "note": "no processes were enumerated"}
    return {"status": "ok", "processes": found, "note": None}


def _windows_identity_states(pids, hide_window, timeout=QUERY_SECONDS):
    """What the table holds for a set of PIDs, in one query.

    Each PID answers ("present", row), ("absent", None) or ("unknown", None):
    three different facts, and cleanup acts differently on each. A row that is
    present may have changed hands since the snapshot, an absent PID is a
    process that has already exited, and a query that failed says neither. One
    query answers for the whole set because each one is a PowerShell start, and
    a job with a handful of workers would otherwise spend a bounded cleanup on
    process starts alone.
    """
    wanted = sorted({int(member) for member in pids})
    if not wanted:
        return {}
    clause = " OR ".join(f"ProcessId={member}" for member in wanted)
    state, rows = _windows_query(
        f"Get-CimInstance Win32_Process -Filter '{clause}' | " + CIM_IDENTITY,
        hide_window, timeout,
    )
    if state != "ok":
        return {member: ("unknown", None) for member in wanted}
    answered, unreadable = {}, False
    for raw in rows:
        entry = _windows_row(raw)
        if entry is None:
            # A row that cannot be parsed is not proof of anything, and it may
            # be any of the PIDs asked about, so none of them may be called absent.
            unreadable = True
        else:
            answered[entry["pid"]] = entry
    found = {}
    for member in wanted:
        entry = answered.get(member)
        if entry is not None:
            found[member] = ("present", entry)
        else:
            found[member] = ("unknown", None) if unreadable else ("absent", None)
    return found


def _windows_identity_state(pid, hide_window, timeout=QUERY_SECONDS):
    """What the table holds for one PID, in the same three answers."""
    return _windows_identity_states([pid], hide_window, timeout).get(
        int(pid), ("unknown", None)
    )


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
    if baseline is None:
        # The caller owns this snapshot now, and took none: cleanup will refuse
        # to signal anything under this job rather than guess what is its own.
        note = "no prelaunch baseline was supplied"
    elif not isinstance(baseline, dict) or baseline.get("status") != "ok":
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


def _windows_survivors(pid, hide_window, ownership=None, timeout=QUERY_SECONDS):
    """Name only the descendants this job's launch evidence can account for.

    Windows has no process group to enumerate, so the parent table is all there
    is; but after the root was reaped its PID can already belong to something
    else, and walking from it would then claim a stranger's tree. A row is this
    job's descendant only when its parent chain reaches the root through rows
    that passed the same test, it was created inside the root's lifetime, and
    it was not already running when the job started. Anything else is a
    candidate reported as unverified, never a process to signal.
    """
    snapshot = _windows_snapshot(hide_window, timeout)
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


def survivors(pid, hide_window=False, ownership=None, timeout=QUERY_SECONDS):
    """List processes of this job that are still running after its leader exited.

    POSIX jobs start in a new session, so the leader's PID is the process group
    every descendant inherits; a zombie holds no resources and is not listed.
    Windows has no such group, so it needs `ownership`: the launch-time
    identity evidence `run` recorded, without which nothing can be attributed.
    `timeout` bounds the Windows enumeration, so a caller working to a deadline
    can ask for what is left of it rather than a fresh half minute.
    """
    if os.name == "nt":
        return _windows_survivors(pid, hide_window, ownership, timeout)
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


def _kill_order(before):
    """Verified descendants deepest first, so a parent outlives its children.

    Each number is signalled on its own, and every walk that checks the result
    starts at the root. A parent signalled first takes its row out of the table
    and the next walk can no longer reach what hung below it: a child whose
    kill failed would disappear from the enumeration instead of being reported.
    """
    identities = before["identities"]

    def depth(member):
        steps, seen, current = 0, {member}, member
        entry = identities.get(str(current))
        while isinstance(entry, dict) and entry.get("ppid") is not None:
            parent = entry["ppid"]
            if parent in seen:
                # A cycle cannot happen in a parent table, but a fake or a
                # corrupt row must not spin here.
                break
            steps, current = steps + 1, parent
            seen.add(parent)
            entry = identities.get(str(current))
        return steps

    return sorted(before["verified_pids"], key=lambda member: (-depth(member), member))


def _windows_stop(pid, hide_window, ownership, before):
    """Terminate the verified descendants only, each proven again at the kill.

    `taskkill` takes a PID, so the row that named a descendant a moment ago is
    re-read immediately before signalling it: a number that changed hands since
    the snapshot is skipped and reported instead of killed, and one the table no
    longer holds has stopped itself and is recorded in `exited_pids`.

    Only the proven number is signalled. The walk in `_windows_survivors`
    already enqueued every verified child, so the whole proven tree is covered
    PID by PID, while `/T` would also take whatever the same enumeration
    refused to name and anything spawned under it since the snapshot. The
    verified set is signalled deepest first, so a parent's row is still in the
    table while its children are being accounted for.

    Every walk taken here contributes, not just the first: a process this job
    cannot account for is no less unaccounted for because it only became
    visible while its parent was being stopped, and a descendant this job's
    evidence does prove is signalled and held even when it was spawned after
    the first walk. Each signalled PID is then read until it is proven gone,
    because the walk alone cannot prove it: once a parent is out of the table
    nothing below it is reachable from the root, so an enumeration that comes
    back empty would otherwise pass for a tree that stopped.

    Every query here draws on one budget. Each is a PowerShell start that can
    block, and cleanup of a job with several workers would otherwise hold its
    caller for minutes; when the budget is gone the remaining questions are not
    asked, and what could not be read is reported as unread.
    """
    unverified = {}
    identities = dict(before["identities"])
    handled, pending = set(), set()
    refused, exited, found = [], [], []
    spent_by = time.monotonic() + CLEANUP_BUDGET_SECONDS

    def query_seconds():
        """What one query may take: what is left of the budget, capped, never negative."""
        return max(0.0, min(spent_by - time.monotonic(), QUERY_SECONDS))

    def account(entries):
        for entry in entries:
            # First reason wins: it describes the moment the row was first seen.
            unverified.setdefault(entry["pid"], entry)

    def is_this_job(member, current):
        return _same_identity(identities.get(str(member)), current)

    def signal(member):
        """Signal one PID and hold it: an attempt that failed is not a process that stopped."""
        pending.add(member)
        try:
            subprocess.run(
                ["taskkill", "/PID", str(member), "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=5, **_creation_options(hide_window),
            )
        except (OSError, subprocess.SubprocessError):
            pass

    account(before["unverified"])
    order = _kill_order(before)
    # Nothing proven, nothing to ask about: a job with no verified descendant
    # must not spend a query, least of all on a host being measured.
    states = _windows_identity_states(order, hide_window, query_seconds()) if order else {}
    for member in order:
        handled.add(member)
        state, current = states.get(member, ("unknown", None))
        if state == "absent":
            # Gone between the snapshot and this lookup: already stopped, and
            # calling that unverified would report a clean run as a dirty one.
            exited.append(member)
        elif state != "present" or not is_this_job(member, current):
            refused.append({
                "pid": member,
                "reason": ("identity_changed_before_stop" if state == "present"
                           else "identity_unavailable_before_stop"),
            })
        else:
            signal(member)
    account(refused)

    def collect(after):
        """Take in one post-kill walk: what it cannot name, and what it proves is ours."""
        account(after["unverified"])
        for member in after["verified_pids"]:
            if member in handled:
                continue
            # A verified descendant that appeared while its parent was being
            # stopped is this job's by the same evidence, and once that parent
            # is out of the table no later walk can reach it: signal it now.
            handled.add(member)
            entry = after["identities"].get(str(member))
            if entry is not None:
                identities[str(member)] = entry
            found.append(member)
            signal(member)

    def confirm():
        """Release every signalled PID proven gone; name the ones nothing can be read for."""
        unreadable = set()
        if not pending:
            return unreadable
        for member, (state, current) in _windows_identity_states(
            pending, hide_window, query_seconds()
        ).items():
            if state == "unknown":
                unreadable.add(member)
            elif state == "absent" or not is_this_job(member, current):
                # Absent, or the number already belongs to something else:
                # either way the process this job signalled is not running.
                pending.discard(member)
        return unreadable

    # Termination is asynchronous; give the verified set a bounded moment to go.
    deadline = time.monotonic() + 5
    after = survivors(pid, hide_window, ownership, timeout=query_seconds())
    collect(after)
    unreadable = confirm()
    while (
        (pending or after["verified_pids"])
        and time.monotonic() < deadline and query_seconds() > 0
    ):
        time.sleep(0.025)
        after = survivors(pid, hide_window, ownership, timeout=query_seconds())
        collect(after)
        unreadable = confirm()
    # A PID whose last lookup could not be read is not known to be running and
    # not known to have stopped, which is exactly what unverified is for.
    account([{"pid": member, "reason": "stop_unconfirmed"} for member in sorted(unreadable)])
    unstopped = sorted(pending - unreadable)
    left = sorted(unverified.values(), key=lambda entry: entry["pid"])
    status = "ok" if (
        before["status"] == "ok" and after["status"] == "ok" and not left
    ) else "unavailable"
    return {
        "status": status,
        "pids": sorted(set(before["pids"]) | set(found)),
        "stopped": (status == "ok" and not after["verified_pids"] and not pending),
        "verified_pids": sorted(set(before["verified_pids"]) | set(found)),
        "exited_pids": sorted(exited),
        "unstopped_pids": unstopped,
        "unverified": left,
        "ignored": before["ignored"],
        "note": before["note"] or (
            "processes under this job were left running because this launch's "
            "evidence does not name them" if left else
            "a process this job signalled was still running when cleanup ended"
            if unstopped else None
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
    `exited_pids`: it stopped, it was simply not this job that stopped it. One
    that was signalled and is still there when cleanup ends is in
    `unstopped_pids`, and one whose last lookup could not be read is
    `stop_unconfirmed` in `unverified`; `stopped` is false for either.
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


READY_POLL_SECONDS = 0.25
READY_TAIL_LIMIT = 8192


def _scan_ready(reader, marker, tail, spawned):
    """Read whatever the child appended since the last read and look for `marker`.

    Returns (ready_seconds or None, carried-over incomplete line). The reader is
    never rewound, so each byte the child writes is examined once. Only the
    unterminated remainder is carried over, bounded so a child that never emits
    a newline cannot grow this buffer without limit. `spawned` is the instant
    the child existed, so the number is the child's load time and not this
    runner's bookkeeping.
    """
    data = reader.read()
    if not data:
        return None, tail
    text = tail + data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    tail = lines.pop()
    if any(marker in line for line in lines) or marker in tail:
        return round(time.monotonic() - spawned, 3), tail
    return None, tail[-READY_TAIL_LIMIT:]


def _wait_for_marker(process, timeout, log, marker, spawned, record):
    """Wait for the child while watching its growing log for a ready marker.

    The log is opened once and read forward at most every READY_POLL_SECONDS,
    so the wait stays a wait rather than a poll of the process. The load time is
    written straight into `record` the moment the marker is seen, rather than
    returned, because a child that came up and then hung still came up: the
    timeout raised below must not take that observation away with it.

    The deadline is taken here, at the instant the wait begins, exactly as
    `process.wait(timeout=...)` would have taken it: watching for a marker must
    never shorten the window the child was granted.
    """
    deadline = time.monotonic() + timeout
    tail = ""

    def scan(reader):
        if record["ready_seconds"] is None:
            record["ready_seconds"], carried = _scan_ready(reader, marker, tail, spawned)
            return carried
        return tail

    with open(log, "rb") as reader:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # One last read of everything written since the previous poll:
                # a marker printed inside that final fraction of a second is
                # still a load time, and this is the last chance to see it.
                scan(reader)
                # The caller tells a timeout apart by this exception type; the
                # command is withheld so no argv value reaches a traceback.
                raise subprocess.TimeoutExpired(cmd=[], timeout=timeout)
            try:
                process.wait(timeout=min(READY_POLL_SECONDS, remaining))
            except subprocess.TimeoutExpired:
                tail = scan(reader)
                continue
            # A child can print the marker and exit inside the same quarter
            # second, so the last read happens after it has been reaped.
            scan(reader)
            return


def run(
    args, *, cwd=None, timeout=180, log=None, env=None,
    hide_window=False, job_dir=None, baseline=None, ready_marker=None,
):
    """Run a foreground command; optional job_dir must be a new directory.

    The combined log is written while the child runs. A job directory also gets
    an atomic process.json before launch and after exit/failure. It contains no
    argv or environment. hide_window suppresses Windows console creation, not
    arbitrary GUI windows. Callers still choose a verified background operation.
    `baseline` is a `prelaunch_baseline()` the caller already took; without one
    the Windows ownership evidence is recorded as unavailable and nothing under
    this job is ever signalled for it. No snapshot is taken here.
    `ready_marker` is a literal substring a project says its child prints once it
    is up; the receipt then records how long that took. Without one the log is
    never read while the child runs.
    """
    if not isinstance(args, (list, tuple)) or not args:
        raise StudioError("Process command must be a nonempty argument array")
    if job_dir is not None and log is not None:
        raise StudioError("Choose job_dir or log, not both")
    if ready_marker is not None:
        if not isinstance(ready_marker, str) or not ready_marker:
            raise StudioError("A ready marker must be a nonempty literal substring")
        if "\n" in ready_marker or "\r" in ready_marker:
            # The log is examined a line at a time, so a marker spanning a line
            # break can never match; refusing beats reporting it as never seen.
            raise StudioError("A ready marker must fit on one line; it cannot contain a line break")
        if job_dir is None and log is None:
            raise StudioError("A ready marker needs a log file; pass job_dir or log")
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
        # Load-time timing only, and null whenever no marker was configured or
        # the child never printed one. Never an acceptance signal.
        "ready_seconds": None,
    }
    record_path = folder / "process.json" if folder is not None else None

    def save_record():
        if record_path is not None:
            write_json(record_path, record)

    save_record()
    # A `baseline` is the caller's to take and is never taken here: on Windows
    # it is a PowerShell enumeration of every process on the host, and a caller
    # measuring a quiet machine would see this toolkit's own query as a
    # newcomer with CPU time. Only a job directory keeps the evidence, and
    # without a baseline it is recorded as unavailable, which makes a later
    # `stop_survivors` report what it found instead of signalling it.
    owns_identity = os.name == "nt" and record_path is not None
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
            # The instant the child existed, which is what its load time is
            # measured from; `start` above also covers this runner's own
            # preparation and stays the basis for elapsed_seconds.
            spawned = time.monotonic()
            record.update(status="running", pid=process.pid)
            if owns_identity:
                # Read now, while the handle is fresh and the PID is certainly
                # this process: after the wait below reaps it, the number alone
                # proves nothing about what is running under it. Without a
                # baseline there is nothing to attribute it against, and asking
                # the host anyway could cost a query nobody can use.
                record["windows_ownership"] = _windows_ownership(
                    baseline,
                    _windows_root_identity(process, hide_window)
                    if baseline is not None else None,
                )
            save_record()
            try:
                if ready_marker is None:
                    process.wait(timeout=timeout)
                else:
                    _wait_for_marker(process, timeout, log, ready_marker, spawned, record)
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
        "ready_seconds": record["ready_seconds"],
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
    same `windows_ownership` evidence `run` writes. None is taken here: the
    enumeration belongs to the caller, which knows when its own receipts,
    measurements and interrupt handling can afford it.
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
    if os.name == "nt":
        # Read now, while the PID is certainly this process: nothing here will
        # ever see it exit, so this is the only moment it can be identified.
        record["windows_ownership"] = _windows_ownership(
            baseline,
            _windows_root_identity(process, hide_window) if baseline is not None else None,
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
