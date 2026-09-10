"""Attributable benchmark windows: snapshot the host before and after one owned capture.

The capture (typically `studio launch`) runs once between two host snapshots,
and a sampler walks the process table throughout the window so a program that
starts and exits between the two snapshots is still seen. Anything else that
changed inside the window is reported as contamination, and the artifact is
labelled attributable only when nothing did. Nothing but the owned capture is
ever stopped.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
from .common import StudioError, read_json, safe_id, write_json
from .processes import run

MAX_CAPTURE_TIMEOUT = 3600
DEFAULT_SAMPLE_INTERVAL = 10.0
MIN_SAMPLE_INTERVAL = 1.0
MAX_SAMPLE_INTERVAL = 60.0
RECORDER_NAMES = ("ffmpeg", "obs64", "obs32", "gamebar", "gamebarftserver", "sharex", "nvidia share")
LIMITS = [
    "process names only; command lines and environments are never recorded",
    "GPU, power and battery fields are unavailable where the host does not expose them",
    "attributable means nothing else was observed changing; it is not a performance verdict",
    "mid-window sampling is a fixed-interval walk; anything shorter-lived than the interval can be missed",
    "the owned capture is excluded by pid, and its descendants only where the host exposes parent pids",
]


def _is_recorder(name):
    lowered = str(name).lower()
    return lowered in RECORDER_NAMES or lowered.startswith("obs")


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _powershell():
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _query(args, timeout=15, on_pid=None):
    """One short read-only query. `on_pid` receives the helper's own pid so the
    child this toolkit spawned is never mistaken for a process that appeared
    inside the window. Only this helper is ever signalled."""
    try:
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (OSError, ValueError):
        return None
    if on_pid is not None:
        on_pid(child.pid)
    try:
        out, _ = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        try:
            child.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None
    return None if child.returncode else out


def read_processes_posix(*, on_pid=None):
    """A status-bearing reading; an unreadable /proc must not look like an idle host."""
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        ticks = os.sysconf("SC_CLK_TCK")
        listing = list(Path("/proc").iterdir())
    except (AttributeError, OSError, ValueError):
        return {"status": "unavailable", "reason": "/proc could not be enumerated", "processes": []}
    entries = []
    for entry in listing:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            name = (entry / "comm").read_text().strip()
            rss = int((entry / "statm").read_text().split()[1]) * page
        except (OSError, ValueError, IndexError):
            continue
        fields = stat[stat.rfind(")") + 2:].split()
        try:
            cpu = (int(fields[11]) + int(fields[12])) / ticks
            parent = int(fields[1])
        except (ValueError, IndexError):
            continue
        entries.append({"pid": int(entry.name), "ppid": parent, "name": name,
                        "cpu_seconds": round(cpu, 3), "working_set_bytes": rss})
    if not entries:
        return {"status": "unavailable", "reason": "no processes were enumerated", "processes": []}
    return {"status": "ok", "processes": entries}


def read_processes_windows(*, on_pid=None):
    shell = _powershell()
    if shell is None:
        return {"status": "unavailable", "reason": "PowerShell was not found", "processes": []}
    output = _query([
        shell, "-NoProfile", "-NonInteractive", "-Command",
        "Get-Process | Select-Object Id,ProcessName,CPU,WorkingSet64 | ConvertTo-Json -Compress",
    ], on_pid=on_pid)
    if not output:
        return {"status": "unavailable", "reason": "the Get-Process query returned nothing", "processes": []}
    try:
        rows = json.loads(output)
    except ValueError:
        return {"status": "unavailable", "reason": "the Get-Process query returned invalid JSON", "processes": []}
    if isinstance(rows, dict):
        rows = [rows]
    entries = []
    for row in rows:
        try:
            entries.append({
                "pid": int(row["Id"]), "ppid": None, "name": str(row["ProcessName"]),
                "cpu_seconds": round(float(row["CPU"] or 0.0), 3),
                "working_set_bytes": int(row["WorkingSet64"] or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if not entries:
        return {"status": "unavailable", "reason": "no processes were enumerated", "processes": []}
    return {"status": "ok", "processes": entries}


def read_processes(*, on_pid=None):
    return read_processes_windows(on_pid=on_pid) if os.name == "nt" else read_processes_posix(on_pid=on_pid)


def _enumeration(reading):
    """Normalise a reader result to (status, reason, processes).

    A plain list is still accepted, but an empty one is treated as a failed
    query rather than as a host with no processes running on it.
    """
    if isinstance(reading, dict):
        processes = list(reading.get("processes") or [])
        status = reading.get("status") or ("ok" if processes else "unavailable")
        return status, reading.get("reason"), processes
    processes = list(reading or [])
    if not processes:
        return "unavailable", "no processes were enumerated", []
    return "ok", None, processes


def read_gpu():
    if shutil.which("nvidia-smi") is None:
        return {"status": "unavailable", "reason": "nvidia-smi not found"}
    fields = "name,utilization.gpu,memory.used,memory.total,clocks.sm,temperature.gpu,power.draw"
    devices = _query(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"])
    if devices is None:
        return {"status": "unavailable", "reason": "nvidia-smi query failed"}
    names = fields.split(",")
    parsed = []
    for line in devices.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == len(names):
            parsed.append(dict(zip(names, parts)))
    apps = _query(["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"])
    if apps is None:
        # The device query is the one that matters for utilization/thermal; a
        # failed compute-apps query alone should not sink the whole snapshot.
        return {"status": "partial", "reason": "nvidia-smi compute-apps query failed", "devices": parsed, "compute_apps": []}
    compute = []
    for line in apps.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0].isdigit():
            compute.append({"pid": int(parts[0]), "name": Path(parts[1]).name, "used_memory_mib": parts[2]})
    return {"status": "ok", "devices": parsed, "compute_apps": compute}


def read_power_scheme():
    if os.name != "nt":
        return {"status": "unavailable"}
    output = _query(["powercfg", "/getactivescheme"])
    match = re.search(r"GUID:\s*([0-9a-fA-F-]+)\s*\((.*?)\)", output or "")
    if not match:
        return {"status": "unavailable"}
    return {"status": "ok", "guid": match.group(1).lower(), "name": match.group(2)}


def read_battery():
    if os.name == "nt":
        try:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong),
                ]

            status = Status()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                percent = None if status.BatteryLifePercent == 255 else int(status.BatteryLifePercent)
                return {"status": "ok", "on_ac": status.ACLineStatus == 1, "percent": percent}
        except (AttributeError, OSError):
            pass
        return {"status": "unavailable"}
    supply = Path("/sys/class/power_supply")
    if not supply.is_dir():
        return {"status": "unavailable"}
    on_ac = None
    percent = None
    for item in supply.iterdir():
        try:
            kind = (item / "type").read_text().strip()
            if kind == "Mains":
                on_ac = (item / "online").read_text().strip() == "1"
            elif kind == "Battery":
                percent = int((item / "capacity").read_text().strip())
        except (OSError, ValueError):
            continue
    if on_ac is None and percent is None:
        return {"status": "unavailable"}
    return {"status": "ok", "on_ac": on_ac, "percent": percent}


def snapshot(*, process_reader=read_processes, gpu_reader=read_gpu, power_reader=read_power_scheme, battery_reader=read_battery):
    """One host snapshot. `process_reader` is called as reader(on_pid=...) so the
    enumeration helper this snapshot spawned (PowerShell lists itself) can be
    excluded from the before/after diff."""
    helpers = []
    status, reason, processes = _enumeration(process_reader(on_pid=helpers.append))
    recorder = [p for p in processes if _is_recorder(p["name"])]
    return {
        "at_utc": _utc(),
        "monotonic": time.monotonic(),
        "processes": processes,
        "process_count": len(processes),
        "process_status": status,
        "process_reason": reason,
        "helper_pids": sorted(set(helpers)),
        "gpu": gpu_reader(),
        "power_scheme": power_reader(),
        "battery": battery_reader(),
        "recorder": [{"pid": p["pid"], "name": p["name"]} for p in recorder],
    }


class Sampler:
    """Watch the process table DURING the window, not only at its two ends.

    A recorder (OBS, ffmpeg, the Game Bar) that starts after the before snapshot
    and exits before the after snapshot is invisible to a before/after diff, and
    it is exactly the kind of program that invalidates a frame-time number. One
    long-lived sampler therefore walks the process table at a fixed interval for
    the life of the owned capture and records what it sees with timestamps.

    It only reads: nothing is ever signalled here. Its own enumeration helpers,
    the calling process and the owned capture's tree are excluded so none of
    them is reported as contamination. The first successful sample is the
    baseline; later samples are compared against it.
    """

    def __init__(self, *, interval=DEFAULT_SAMPLE_INTERVAL, reader=read_processes, clock=_utc,
                 ignore_pids=(), owned_record=None):
        self.interval = float(interval)
        self._reader = reader
        self._clock = clock
        self._ignore = set(ignore_pids)
        self._owned_record = Path(owned_record) if owned_record is not None else None
        self._owned = set()
        self._helpers = set()
        self._baseline = None
        self._recorders = {}
        self._newcomers = {}
        self._samples = 0
        self._failed = 0
        self._first = None
        self._last = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._started = False

    def _note_helper(self, pid):
        with self._lock:
            self._helpers.add(pid)

    def _read_owned(self):
        """Learn the owned capture's pid from the job receipt the runner writes."""
        if self._owned_record is None or not self._owned_record.is_file():
            return
        try:
            pid = read_json(self._owned_record).get("pid")
        except StudioError:
            return
        if isinstance(pid, int):
            with self._lock:
                self._owned.add(pid)

    def _owned_tree(self, processes):
        tree = set(self._owned)
        if not tree:
            return tree
        children = {}
        for entry in processes:
            parent = entry.get("ppid")
            if isinstance(parent, int):
                children.setdefault(parent, []).append(entry["pid"])
        frontier = list(tree)
        while frontier:
            for pid in children.get(frontier.pop(), ()):
                if pid not in tree:
                    tree.add(pid)
                    frontier.append(pid)
        return tree

    @staticmethod
    def _observe(store, entry, at):
        key = (entry["pid"], entry["name"])
        seen = store.get(key)
        if seen is None:
            store[key] = {
                "pid": entry["pid"], "name": entry["name"], "first_seen_utc": at, "last_seen_utc": at,
                "samples": 1, "cpu_seconds": entry["cpu_seconds"], "working_set_bytes": entry["working_set_bytes"],
            }
            return
        seen["last_seen_utc"] = at
        seen["samples"] += 1
        seen["cpu_seconds"] = max(seen["cpu_seconds"], entry["cpu_seconds"])
        seen["working_set_bytes"] = max(seen["working_set_bytes"], entry["working_set_bytes"])

    def sample(self):
        """Take one observation; callable directly so tests need no threads."""
        status, _reason, processes = _enumeration(self._reader(on_pid=self._note_helper))
        # Read the owned pid after enumerating: a capture that started between
        # the two reads is then still recognised as the capture, not a newcomer.
        self._read_owned()
        at = self._clock()
        with self._lock:
            if status != "ok":
                self._failed += 1
                return
            self._samples += 1
            if self._first is None:
                self._first = at
            self._last = at
            if self._baseline is None:
                self._baseline = {entry["pid"] for entry in processes}
                return
            owned = self._owned_tree(processes)
            for entry in processes:
                pid = entry["pid"]
                if pid in self._ignore or pid in self._helpers or pid in owned:
                    continue
                if _is_recorder(entry["name"]):
                    self._observe(self._recorders, entry, at)
                if pid not in self._baseline:
                    self._observe(self._newcomers, entry, at)

    def _safe_sample(self):
        try:
            self.sample()
        except Exception:  # observation must never break the capture it wraps
            with self._lock:
                self._failed += 1

    def _loop(self):
        while not self._stop.is_set():
            if self._stop.wait(self.interval):
                break
            self._safe_sample()

    def start(self):
        if self._started:
            raise StudioError("Cleanroom sampler is already running")
        self._started = True
        # Take the baseline synchronously so the window is never sampled before
        # the sampler knows what was already running.
        self._safe_sample()
        self._thread = threading.Thread(target=self._loop, name="cleanroom-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=max(self.interval, 5.0) + 20.0)
            self._safe_sample()
        return self.observation()

    def observation(self):
        with self._lock:
            return {
                "sampler": {
                    "mode": "in-process-thread",
                    "pid": os.getpid(),
                    "command": getattr(self._reader, "__name__", "process enumeration"),
                    "interval_seconds": self.interval,
                    "helper_pids": sorted(self._helpers),
                    "owned_pids": sorted(self._owned),
                },
                "samples": self._samples,
                "failed_samples": self._failed,
                "first_sample_utc": self._first,
                "last_sample_utc": self._last,
                "recorders": sorted(self._recorders.values(), key=lambda e: (e["name"], e["pid"])),
                "newcomers": sorted(self._newcomers.values(), key=lambda e: (e["name"], e["pid"])),
            }


def _timestamps_in_window(path, started, finished):
    inside = naive = 0
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise StudioError("Agent log is not readable")
    for match in pattern.finditer(text):
        raw = match.group(0).replace(" ", "T")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if stamp.tzinfo is None:
            naive += 1
            # No offset: treat it as host local time rather than discarding it.
        if started <= stamp.astimezone(timezone.utc) <= finished:
            inside += 1
    return {"path": str(path), "timestamps_in_window": inside, "naive_timestamps": naive}


def compare(before, after, window, *, busy_cpu_seconds, heavy_working_set_bytes, agent_log=None, self_pid=None, during=None):
    """Pure comparison of two snapshots around a window; returns reasons, never log text."""
    reasons = []
    limits = list(LIMITS)
    ignore = {self_pid} if self_pid is not None else set()
    # The enumeration helper each snapshot spawned lists itself; it is this
    # toolkit's own child, not a program that appeared inside the window.
    ignore |= set(before.get("helper_pids") or ()) | set(after.get("helper_pids") or ())
    prior = {p["pid"]: p for p in before.get("processes", []) if p["pid"] not in ignore}
    later = {p["pid"]: p for p in after.get("processes", []) if p["pid"] not in ignore}
    enumeration = {"before": before.get("process_status", "ok"), "after": after.get("process_status", "ok")}
    enumerated = enumeration["before"] == "ok" and enumeration["after"] == "ok"

    def heavy(p):
        return p["working_set_bytes"] >= heavy_working_set_bytes or p["cpu_seconds"] >= busy_cpu_seconds

    new_heavy, exited_heavy, busy = [], [], []
    if not enumerated:
        # A failed Get-Process/ps query is not evidence of a quiet host; without
        # both process tables nothing inside the window can be attributed.
        reasons.append("host process enumeration failed; the window cannot be attributed")
    else:
        overlap = prior.keys() & later.keys()
        # A PID the OS reused for a different program, or whose CPU counter went
        # backwards (a restart), is an exit plus a fresh appearance, not one
        # continuously-running process with a CPU delta.
        reused = {
            pid for pid in overlap
            if prior[pid]["name"] != later[pid]["name"] or later[pid]["cpu_seconds"] < prior[pid]["cpu_seconds"]
        }
        continuous = overlap - reused
        new_heavy = [later[pid] for pid in (later.keys() - prior.keys()) | reused if heavy(later[pid])]
        # An exit is judged by the same predicate as an appearance: a small,
        # CPU-hungry process that quits mid-window contaminates it just as much
        # as a large idle one does.
        exited_heavy = [prior[pid] for pid in (prior.keys() - later.keys()) | reused if heavy(prior[pid])]
        for pid in continuous:
            delta = later[pid]["cpu_seconds"] - prior[pid]["cpu_seconds"]
            if delta >= busy_cpu_seconds:
                busy.append({"pid": pid, "name": later[pid]["name"], "cpu_delta_seconds": round(delta, 3)})
        if new_heavy:
            reasons.append("heavy processes appeared inside the window")
        if exited_heavy:
            reasons.append("heavy processes exited inside the window")
        if busy:
            reasons.append("other processes consumed CPU inside the window")
    observed = None
    if during is not None:
        recorders = [dict(entry) for entry in during.get("recorders") or ()]
        transient = [
            dict(entry, present_after=entry["pid"] in later)
            for entry in during.get("newcomers") or () if heavy(entry)
        ]
        observed = {
            "sampler": during.get("sampler"),
            "samples": during.get("samples", 0),
            "failed_samples": during.get("failed_samples", 0),
            "first_sample_utc": during.get("first_sample_utc"),
            "last_sample_utc": during.get("last_sample_utc"),
            "recorders": recorders,
            "heavy_newcomers": transient,
        }
        if recorders:
            reasons.append("a recorder process ran inside the window")
        if any(not entry["present_after"] for entry in transient):
            reasons.append("heavy processes ran and exited inside the window")
        if observed["samples"] < 2:
            limits.append("the window was not sampled between the two snapshots")
    agent = None
    if agent_log is not None:
        started = datetime.fromisoformat(window["started_utc"])
        finished = datetime.fromisoformat(window["finished_utc"])
        agent = _timestamps_in_window(agent_log, started, finished)
        if agent["timestamps_in_window"]:
            reasons.append("agent activity logged inside the window")
        if agent["naive_timestamps"]:
            reasons.append("agent log has timestamps without a UTC offset")
    gpu_before, gpu_after = before.get("gpu", {}), after.get("gpu", {})
    if gpu_before.get("status") == "ok" and gpu_after.get("status") == "ok":
        apps_before = {a["pid"] for a in gpu_before.get("compute_apps", [])}
        apps_after = {a["pid"] for a in gpu_after.get("compute_apps", [])}
        if apps_after - apps_before:
            reasons.append("GPU compute processes appeared inside the window")
        if apps_before - apps_after:
            reasons.append("GPU compute processes exited inside the window")
    else:
        limits.append("GPU counters unavailable for this window")
    if before.get("power_scheme") != after.get("power_scheme"):
        reasons.append("power scheme changed inside the window")
    for snapshot_side in (before, after):
        battery = snapshot_side.get("battery", {})
        if battery.get("status") == "ok" and battery.get("on_ac") is False:
            reasons.append("host is on battery power")
            break
    if before.get("recorder") or after.get("recorder"):
        reasons.append("recorder process present")
    return {
        "attributable": not reasons,
        "reasons": reasons,
        "process_enumeration": enumeration,
        "during": observed,
        "contamination": {
            "new_heavy": [{"pid": p["pid"], "name": p["name"], "cpu_seconds": p["cpu_seconds"], "working_set_bytes": p["working_set_bytes"]} for p in new_heavy],
            "exited_heavy": [{"pid": p["pid"], "name": p["name"], "cpu_seconds": p["cpu_seconds"], "working_set_bytes": p["working_set_bytes"]} for p in exited_heavy],
            "busy": sorted(busy, key=lambda b: -b["cpu_delta_seconds"]),
            "agent_log": agent,
        },
        "thresholds": {"busy_cpu_seconds": busy_cpu_seconds, "heavy_working_set_bytes": heavy_working_set_bytes},
        "limits": limits,
    }


def execute(
    config, project, capture, *, label=None, scope=None, settle=0.0, agent_log=None, timeout=None,
    busy_fraction=0.05, busy_floor_seconds=1.0, heavy_working_set_mb=200.0,
    sample_interval=DEFAULT_SAMPLE_INTERVAL, snapshot_reader=None, sampler_factory=None, self_pid=None,
):
    # Resolved at call time, not bound as a default, so the readers stay
    # substitutable for tests and for hosts with a different enumeration.
    snapshot_reader = snapshot_reader or snapshot
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Cleanroom bench needs an existing game project directory")
    if not isinstance(capture, (list, tuple)) or not capture or not all(isinstance(x, str) for x in capture):
        raise StudioError("Cleanroom bench needs a capture command after --")
    limit = MAX_CAPTURE_TIMEOUT if timeout is None else timeout
    if type(limit) not in (int, float) or not 0 < limit <= MAX_CAPTURE_TIMEOUT:
        raise StudioError("Capture timeout must be 1–3600 seconds")
    if type(settle) not in (int, float) or not 0 <= settle <= 600:
        raise StudioError("Settle must be 0–600 seconds")
    if type(sample_interval) not in (int, float) or not MIN_SAMPLE_INTERVAL <= sample_interval <= MAX_SAMPLE_INTERVAL:
        raise StudioError("Sample interval must be 1–60 seconds")
    if agent_log is not None and not Path(agent_log).is_file():
        raise StudioError("Agent log path must be an existing file")
    label = safe_id(label) if label else uuid.uuid4().hex
    # The scope rung this bench is evidence for; validated like a label so a
    # capture cannot be silently cited for the wrong rung.
    scope = safe_id(scope) if scope is not None else None
    bench = root / "artifacts" / "bench" / label
    try:
        bench.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Bench directory exists; choose a new label") from None
    owner = os.getpid() if self_pid is None else self_pid
    if settle:
        time.sleep(settle)
    before = snapshot_reader()
    write_json(bench / "before.json", before)
    # One long-lived sampler, started before the capture and stopped after it,
    # so a recorder that lives only between the two snapshots is still recorded.
    sampler = (sampler_factory or Sampler)(
        interval=float(sample_interval),
        ignore_pids={owner} | set(before.get("helper_pids") or ()),
        owned_record=bench / "capture" / "process.json",
    )
    window = {"started_utc": _utc()}
    started = time.monotonic()
    failure = None
    sampler.start()
    try:
        run(list(capture), cwd=str(root), timeout=limit, job_dir=bench / "capture", hide_window=False)
    except StudioError as exc:
        failure = str(exc)
    finally:
        during = sampler.stop()
    window["finished_utc"] = _utc()
    window["elapsed_seconds"] = round(time.monotonic() - started, 3)
    after = snapshot_reader()
    write_json(bench / "after.json", after)
    write_json(bench / "during.json", during)
    record_path = bench / "capture" / "process.json"
    record = read_json(record_path) if record_path.is_file() else {"status": "start_failed"}
    log_path = bench / "capture" / "stdout.log"
    verdict = None
    if log_path.is_file():
        text = log_path.read_text(encoding="utf-8", errors="replace").strip()
        try:
            parsed = json.loads(text)
            verdict = parsed if isinstance(parsed, dict) else None
        except ValueError:
            verdict = None
    busy_seconds = max(float(busy_floor_seconds), float(busy_fraction) * window["elapsed_seconds"])
    comparison = compare(
        before, after, window, busy_cpu_seconds=busy_seconds,
        heavy_working_set_bytes=int(float(heavy_working_set_mb) * 1024 * 1024),
        agent_log=agent_log, self_pid=owner, during=during,
    )
    if comparison.get("during") is not None:
        comparison["during"]["record"] = str(bench / "during.json")
    # Asking for a rung is asking for proof of that rung: a capture whose own
    # receipt cannot be read, or does not name the rung, is not evidence for it.
    scope_check = None
    if scope is not None:
        if not isinstance(verdict, dict):
            scope_check = "unparsed"
            comparison["reasons"].append("capture receipt could not be parsed, so its scope is unknown")
        elif verdict.get("scope") is None:
            scope_check = "missing"
            comparison["reasons"].append("capture receipt does not name a scope rung")
        elif verdict.get("scope") != scope:
            scope_check = "mismatch"
            comparison["reasons"].append("capture scope does not match bench scope")
        else:
            scope_check = "match"
        comparison["attributable"] = not comparison["reasons"]
    result = {
        "schema_version": 1,
        "kind": "cleanroom-bench",
        "label": label,
        "scope": scope,
        "scope_check": scope_check,
        "window": window,
        "capture": {
            "status": record.get("status"), "returncode": record.get("returncode"),
            "elapsed_seconds": record.get("elapsed_seconds"), "cleanup": record.get("cleanup"),
            "failure": failure, "process_record": str(record_path) if record_path.is_file() else None,
            "log": str(log_path) if log_path.is_file() else None, "verdict": verdict,
        },
        "before": {"record": str(bench / "before.json"), "at_utc": before["at_utc"], "process_count": before["process_count"], "process_status": before.get("process_status", "ok"), "gpu": before["gpu"], "power_scheme": before["power_scheme"], "battery": before["battery"], "recorder": before["recorder"]},
        "after": {"record": str(bench / "after.json"), "at_utc": after["at_utc"], "process_count": after["process_count"], "process_status": after.get("process_status", "ok"), "gpu": after["gpu"], "power_scheme": after["power_scheme"], "battery": after["battery"], "recorder": after["recorder"]},
        **comparison,
    }
    result["ok"] = result["attributable"] and record.get("status") == "completed"
    write_json(bench / "cleanroom.json", result)
    return {**result, "bench_dir": str(bench), "record": str(bench / "cleanroom.json")}
