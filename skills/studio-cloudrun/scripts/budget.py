#!/usr/bin/env python3
"""Service host side: one total ceiling shared by several model runs (a voice
audition's casting and engine jobs), kept in $CLOUDRUN_WORK/budgets/<group>.json
under a lock.

    budget.py open GROUP TOTAL WANT RUN   reserve min(WANT, what is left) for
                                          RUN and print it, or exit 1 (nothing
                                          left, or the job names a different
                                          total than the group's first job did)
    budget.py spend GROUP UNITS RUN       release RUN's reservation and add
                                          what it really cost (setup included;
                                          0 when no runtime started)

What is left is the total minus what was spent minus what runs still hold,
so runs in parallel (or one waiting for a GPU) never share the same units.
A run is capped at what it reserved.
"""
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


def ledger(group):
    if not GROUP_RE.match(group):
        sys.exit(f"bad budget group {group!r}")
    d = Path(os.environ.get("CLOUDRUN_WORK", Path.home() / "studio-cloudrun")) / "budgets"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d / f"{group}.json"


def locked(path, change):
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.is_file() else None
        data, result = change(data)
        if data is not None:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(path)
        return result


def open_group(group, total, want=None, run=None):
    def change(data):
        if data is None:
            data = {"group": group, "total": total, "spent": 0.0, "runs": [], "reserved": {}}
        elif data["total"] != total:
            return None, (None, f"budget group {group} was opened with {data['total']} units; this job says {total}")
        held = data.setdefault("reserved", {})
        left = round(data["total"] - data["spent"] - sum(held.values()), 4)
        if left <= 0:
            return None, (None, f"budget group {group} has no units left ({data['spent']} spent, {round(sum(held.values()), 4)} held by running jobs, of {data['total']})")
        grant = left if want is None else round(min(left, want), 4)
        if run is not None:
            held[run] = grant
        return data, (grant, None)

    return locked(ledger(group), change)


def spend(group, units, run, job_id=None):
    def change(data):
        if data is None:
            data = {"group": group, "total": None, "spent": 0.0, "runs": [], "reserved": {}}
        data.setdefault("reserved", {}).pop(run, None)
        data["spent"] = round(data["spent"] + units, 4)
        data["runs"].append({"job": job_id or run, "run": run, "units": round(units, 4),
                             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return data, data["spent"]

    return locked(ledger(group), change)


def main(argv):
    if len(argv) == 5 and argv[0] == "open":
        left, err = open_group(argv[1], float(argv[2]), float(argv[3]), argv[4])
        if err:
            print(err, file=sys.stderr)
            return 1
        print(left)
        return 0
    if len(argv) in (4, 5) and argv[0] == "spend":
        print(spend(argv[1], max(0.0, float(argv[2])), argv[3], argv[4] if len(argv) == 5 else None))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
