"""Attributable benchmark windows: snapshot the host before and after one owned capture.

The capture (typically `studio launch`) runs once between two host snapshots.
Anything else that changed inside the window is reported as contamination, and
the artifact is labelled attributable only when nothing did. Nothing but the
owned capture is ever stopped.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
from .common import StudioError, read_json, safe_id, write_json
from .processes import run

MAX_CAPTURE_TIMEOUT = 3600
RECORDER_NAMES = ("ffmpeg", "obs64", "obs32", "gamebar", "gamebarftserver", "sharex", "nvidia share")
LIMITS = [
    "process names only; command lines and environments are never recorded",
    "GPU, power and battery fields are unavailable where the host does not expose them",
    "attributable means nothing else was observed changing; it is not a performance verdict",
]


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _powershell():
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _query(args, timeout=15):
    try:
        completed = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode:
        return None
    return completed.stdout


def read_processes_posix():
    page = os.sysconf("SC_PAGE_SIZE")
    ticks = os.sysconf("SC_CLK_TCK")
    entries = []
    for entry in Path("/proc").iterdir():
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
        except (ValueError, IndexError):
            continue
        entries.append({"pid": int(entry.name), "name": name, "cpu_seconds": round(cpu, 3), "working_set_bytes": rss})
    return entries


def read_processes_windows():
    shell = _powershell()
    if shell is None:
        return []
    output = _query([
        shell, "-NoProfile", "-NonInteractive", "-Command",
        "Get-Process | Select-Object Id,ProcessName,CPU,WorkingSet64 | ConvertTo-Json -Compress",
    ])
    if not output:
        return []
    try:
        rows = json.loads(output)
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    entries = []
    for row in rows:
        try:
            entries.append({
                "pid": int(row["Id"]), "name": str(row["ProcessName"]),
                "cpu_seconds": round(float(row["CPU"] or 0.0), 3),
                "working_set_bytes": int(row["WorkingSet64"] or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return entries


def read_processes():
    return read_processes_windows() if os.name == "nt" else read_processes_posix()


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
    processes = list(process_reader())
    recorder = [p for p in processes if p["name"].lower() in RECORDER_NAMES or p["name"].lower().startswith("obs")]
    return {
        "at_utc": _utc(),
        "monotonic": time.monotonic(),
        "processes": processes,
        "process_count": len(processes),
        "gpu": gpu_reader(),
        "power_scheme": power_reader(),
        "battery": battery_reader(),
        "recorder": [{"pid": p["pid"], "name": p["name"]} for p in recorder],
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


def compare(before, after, window, *, busy_cpu_seconds, heavy_working_set_bytes, agent_log=None, self_pid=None):
    """Pure comparison of two snapshots around a window; returns reasons, never log text."""
    reasons = []
    ignore = {self_pid} if self_pid is not None else set()
    prior = {p["pid"]: p for p in before["processes"] if p["pid"] not in ignore}
    later = {p["pid"]: p for p in after["processes"] if p["pid"] not in ignore}

    def heavy(p):
        return p["working_set_bytes"] >= heavy_working_set_bytes or p["cpu_seconds"] >= busy_cpu_seconds

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
    exited_heavy = [
        prior[pid] for pid in (prior.keys() - later.keys()) | reused
        if prior[pid]["working_set_bytes"] >= heavy_working_set_bytes
    ]
    busy = []
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
    limits = list(LIMITS)
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
        "contamination": {
            "new_heavy": [{"pid": p["pid"], "name": p["name"], "cpu_seconds": p["cpu_seconds"], "working_set_bytes": p["working_set_bytes"]} for p in new_heavy],
            "exited_heavy": [{"pid": p["pid"], "name": p["name"], "working_set_bytes": p["working_set_bytes"]} for p in exited_heavy],
            "busy": sorted(busy, key=lambda b: -b["cpu_delta_seconds"]),
            "agent_log": agent,
        },
        "thresholds": {"busy_cpu_seconds": busy_cpu_seconds, "heavy_working_set_bytes": heavy_working_set_bytes},
        "limits": limits,
    }


def execute(
    config, project, capture, *, label=None, scope=None, settle=0.0, agent_log=None, timeout=None,
    busy_fraction=0.05, busy_floor_seconds=1.0, heavy_working_set_mb=200.0,
    snapshot_reader=snapshot, self_pid=None,
):
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
    if settle:
        time.sleep(settle)
    before = snapshot_reader()
    write_json(bench / "before.json", before)
    window = {"started_utc": _utc()}
    started = time.monotonic()
    failure = None
    try:
        run(list(capture), cwd=str(root), timeout=limit, job_dir=bench / "capture", hide_window=False)
    except StudioError as exc:
        failure = str(exc)
    window["finished_utc"] = _utc()
    window["elapsed_seconds"] = round(time.monotonic() - started, 3)
    after = snapshot_reader()
    write_json(bench / "after.json", after)
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
        agent_log=agent_log, self_pid=os.getpid() if self_pid is None else self_pid,
    )
    if scope is not None and isinstance(verdict, dict) and "scope" in verdict and verdict.get("scope") != scope:
        # A launch receipt naming a different (or no) rung must not be citable for this one.
        comparison["reasons"].append("capture scope does not match bench scope")
        comparison["attributable"] = not comparison["reasons"]
    result = {
        "schema_version": 1,
        "kind": "cleanroom-bench",
        "label": label,
        "scope": scope,
        "window": window,
        "capture": {
            "status": record.get("status"), "returncode": record.get("returncode"),
            "elapsed_seconds": record.get("elapsed_seconds"), "cleanup": record.get("cleanup"),
            "failure": failure, "process_record": str(record_path) if record_path.is_file() else None,
            "log": str(log_path) if log_path.is_file() else None, "verdict": verdict,
        },
        "before": {"record": str(bench / "before.json"), "at_utc": before["at_utc"], "process_count": before["process_count"], "gpu": before["gpu"], "power_scheme": before["power_scheme"], "battery": before["battery"], "recorder": before["recorder"]},
        "after": {"record": str(bench / "after.json"), "at_utc": after["at_utc"], "process_count": after["process_count"], "gpu": after["gpu"], "power_scheme": after["power_scheme"], "battery": after["battery"], "recorder": after["recorder"]},
        **comparison,
    }
    result["ok"] = result["attributable"] and record.get("status") == "completed"
    write_json(bench / "cleanroom.json", result)
    return {**result, "bench_dir": str(bench), "record": str(bench / "cleanroom.json")}
