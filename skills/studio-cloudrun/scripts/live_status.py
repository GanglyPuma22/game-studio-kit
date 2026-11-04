#!/usr/bin/env python3
"""Live status for Colab runs: one small JSON file per job, updated every minute.

colab_job.sh (on the service host) calls this; people and agents read it.

  live_status.py set  --status FILE [--mirror FILE] key=value ...
  live_status.py tick --status FILE [--mirror FILE] --probe FILE [--gpu-idle-min N] [--ssh-lost-min N]
  live_status.py line --status FILE
  live_status.py show [--work DIR] [ID ...]

`tick` reads what runtime_probe.sh printed on the runtime (key=value lines,
or ssh=fail when the runtime did not answer), updates the status and prints
what the host should do next, as one line:

  ok                     keep polling
  finished               the job finished on the runtime (any exit): fetch results
  lost <reason>          the runtime has no running job, or stopped answering: fail loudly
  idle <reason>          a GPU job showed 0 % GPU for the idle limit: stop it early

Stdlib only; never prints or stores credentials.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

STALE_S = 180  # a running status not updated for this long means the host side stopped updating it
IDLE_GAP_S = 150  # readings further apart than this (polls are 15-60 s) break the idle clock
STEP_RE = re.compile(r"(\d+)\s*(?:/|of)\s*(\d+)")


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(status, path, mirror=None):
    for p in filter(None, (path, mirror)):
        p = Path(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, p)


def parse_probe(text):
    """key=value lines from runtime_probe.sh (or ssh=fail written by the host)."""
    probe = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            probe[k.strip()] = v.strip()
    return probe


def _num(value, cast=float):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _coerce(value):
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def set_fields(status, pairs, now):
    for pair in pairs:
        k, _, v = pair.partition("=")
        if k:
            status[k] = _coerce(v) if v != "" else None
    status["updated"] = iso(now)
    status["updated_s"] = int(now)
    _derive(status, now)
    return status


def _derive(status, now):
    """Elapsed minutes and units spent so far, from the host's own clock and rate."""
    t0 = _num(status.get("runtime_started_s"))
    if t0 is not None:
        status["elapsed_min"] = round((now - t0) / 60, 1)
        rate = _num(status.get("rate"))
        if rate is not None:
            status["units_spent"] = round(rate * (now - t0) / 3600, 3)


def _eta(status, step, now):
    """ETA from a step line like 'render 140/3000': speed since the first
    reading of the same counter, times what is left."""
    m = STEP_RE.search(step or "")
    if not m:
        status.pop("eta_min", None)
        return
    n, total = int(m.group(1)), int(m.group(2))
    key = STEP_RE.sub("#", step)[:80] + f"|{total}"
    if status.get("_step_key") != key or n < (status.get("_step_n0") or 0):
        status["_step_key"], status["_step_n0"], status["_step_t0"] = key, n, int(now)
    status["step_n"], status["step_total"] = n, total
    done, spent = n - status["_step_n0"], now - status["_step_t0"]
    if done > 0 and spent > 0 and total >= n:
        status["eta_min"] = round(spent / done * (total - n) / 60, 1)
    else:
        status.pop("eta_min", None)


def tick(status, probe, now, gpu_idle_min=5.0, ssh_lost_min=5.0):
    """Update status from one probe; return the host's next action line."""
    status["updated"], status["updated_s"] = iso(now), int(now)
    _derive(status, now)
    if probe.get("ssh") == "fail":
        _idle_reset(status)  # an unobserved minute is never counted as idle
        status["ssh_fail"] = status.get("ssh_fail", 0) + 1
        since = status.setdefault("ssh_fail_since_s", int(now))
        if probe.get("session") == "gone":
            status["note"] = "the Colab session is gone (stopped or replaced)"
            return "lost the Colab session is gone: the runtime was stopped or replaced, nothing is running"
        if now - since >= ssh_lost_min * 60:
            status["note"] = f"no answer from the runtime for {round((now - since) / 60)} min"
            return f"lost no answer from the runtime over ssh for {round((now - since) / 60)} min"
        status["note"] = f"ssh did not answer ({status['ssh_fail']} in a row)"
        return "ok"
    status["ssh_fail"] = 0
    status.pop("ssh_fail_since_s", None)
    if probe.get("job") == "0":
        status["note"] = "the runtime has no job on it"
        return "lost the runtime answers but has no job on it (it was reset or replaced)"
    stage = probe.get("stage") or status.get("stage")
    status["stage"] = stage
    for src, dst in (("progress", "progress"), ("step", "step"), ("log", "last_line")):
        if probe.get(src):
            status[dst] = probe[src][:240]
    _eta(status, probe.get("step") or "", now)
    util, mem = _num(probe.get("gpu_util_max"), int), _num(probe.get("gpu_mem_mb"), int)
    status["gpu_util"], status["gpu_mem_mb"] = util, mem
    if probe.get("finished") == "1":
        status["note"] = "job finished on the runtime"
        return "finished"
    if probe.get("pid_alive") == "0":
        _idle_reset(status)
        status["not_running"] = status.get("not_running", 0) + 1
        if status["not_running"] >= 2:
            status["note"] = "the job's process is gone and it never wrote its finished mark"
            return "lost the job's process is gone on the runtime without finishing"
        return "ok"
    status["not_running"] = 0
    # Idle GPU: only for GPU jobs, only once the job's own command runs, and
    # only when the runtime actually reported GPU samples.
    # The idle clock runs only over unbroken zero readings: a gap between
    # readings (a missed poll, a probe without samples) starts it over.
    if status.get("gpu") not in (None, "CPU") and gpu_idle_min and stage == "run" and util is not None:
        if util == 0:
            last = status.get("gpu_idle_last_s")
            if last is None or now - last > IDLE_GAP_S:
                status["gpu_idle_since_s"] = int(now)
            status["gpu_idle_last_s"] = int(now)
            since = status["gpu_idle_since_s"]
            status["gpu_idle_min"] = round((now - since) / 60, 1)
            if now - since >= gpu_idle_min * 60:
                status["note"] = f"GPU at 0 % for {status['gpu_idle_min']} min"
                return f"idle the GPU showed 0 % for {status['gpu_idle_min']} min while the job ran (limit {gpu_idle_min:g} min): it is not using the GPU it pays for"
        else:
            _idle_reset(status)
    else:
        _idle_reset(status)
    status["note"] = ""
    return "ok"


def _idle_reset(status):
    status.pop("gpu_idle_since_s", None)
    status.pop("gpu_idle_last_s", None)
    status["gpu_idle_min"] = 0


def line(status, now=None):
    """One human line for a status (also used in driver.log)."""
    now = now or time.time()
    parts = [status.get("id", "?"), status.get("state", "?"), status.get("stage") or "-"]
    if status.get("step"):
        parts.append(f"step: {status['step']}")
    if status.get("eta_min") is not None:
        parts.append(f"ETA {status['eta_min']:g} min")
    if status.get("gpu") not in (None, "CPU"):
        g = status.get("gpu_util")
        parts.append(f"{status['gpu']} {'?' if g is None else g} %" + (f" {status['gpu_mem_mb']} MiB" if status.get("gpu_mem_mb") is not None else ""))
    elif status.get("gpu") == "CPU":
        parts.append("CPU runtime")
    if status.get("units_spent") is not None:
        parts.append(f"{status['units_spent']:g} units" + (f" of {status['max_units']:g}" if _num(status.get("max_units")) else ""))
    if status.get("elapsed_min") is not None:
        parts.append(f"{status['elapsed_min']:g} min")
    upd = _num(status.get("updated_s"))
    if status.get("state") == "running" and upd is not None and now - upd > STALE_S:
        parts.append(f"STALE: not updated for {round((now - upd) / 60)} min, the host runner may have died")
    if status.get("note"):
        parts.append(status["note"])
    if status.get("last_line") and status.get("last_line") != status.get("step"):
        parts.append(f"log: {status['last_line'][:120]}")
    return " | ".join(str(p) for p in parts)


def show(work, ids):
    d = Path(work) / "status"
    files = [d / f"{i}.json" for i in ids] if ids else sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print(f"no status files in {d}")
        return 1
    for f in files:
        s = load(f)
        print(line(s) if s else f"{f.stem}: no status")
    return 0


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 2
    op, args = argv[0], argv[1:]
    opts, rest = {}, []
    i = 0
    while i < len(args):
        if args[i].startswith("--") and i + 1 < len(args):
            opts[args[i][2:]] = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1
    now = float(opts.get("now", time.time()))
    if op == "show":
        return show(opts.get("work", os.environ.get("CLOUDRUN_WORK", str(Path.home() / "studio-cloudrun"))), rest)
    path = opts.get("status")
    if not path:
        print("--status FILE is required", file=sys.stderr)
        return 2
    status = load(path)
    if op == "line":
        print(line(status, now))
        return 0
    if op == "set":
        save(set_fields(status, rest, now), path, opts.get("mirror"))
        return 0
    if op == "tick":
        try:
            probe = parse_probe(Path(opts["probe"]).read_text(encoding="utf-8", errors="replace"))
        except (KeyError, OSError):
            probe = {"ssh": "fail"}
        action = tick(status, probe, now, float(opts.get("gpu-idle-min", 5)), float(opts.get("ssh-lost-min", 5)))
        save(status, path, opts.get("mirror"))
        print(action)
        return 0
    print(f"unknown operation {op}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
