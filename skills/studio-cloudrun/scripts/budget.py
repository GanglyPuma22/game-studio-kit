#!/usr/bin/env python3
"""Service host side: one total ceiling shared by several model runs (a voice
audition's casting and engine jobs), kept in $CLOUDRUN_WORK/budgets/<group>.json
under a lock.

    budget.py open GROUP TOTAL      print the units left, or exit 1 (spent, or
                                    the job names a different total than the
                                    group's first job did)
    budget.py spend GROUP UNITS ID  add what a run cost (setup included)

A job's own max_units still applies; the runner caps each runtime at the
smaller of that and what the group has left.
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


def open_group(group, total):
    def change(data):
        if data is None:
            data = {"group": group, "total": total, "spent": 0.0, "runs": []}
        elif data["total"] != total:
            return None, (None, f"budget group {group} was opened with {data['total']} units; this job says {total}")
        left = round(data["total"] - data["spent"], 4)
        if left <= 0:
            return None, (None, f"budget group {group} has spent its {data['total']} units")
        return data, (left, None)

    return locked(ledger(group), change)


def spend(group, units, job_id):
    def change(data):
        if data is None:
            data = {"group": group, "total": None, "spent": 0.0, "runs": []}
        data["spent"] = round(data["spent"] + units, 4)
        data["runs"].append({"job": job_id, "units": round(units, 4), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return data, data["spent"]

    return locked(ledger(group), change)


def main(argv):
    if len(argv) == 3 and argv[0] == "open":
        left, err = open_group(argv[1], float(argv[2]))
        if err:
            print(err, file=sys.stderr)
            return 1
        print(left)
        return 0
    if len(argv) == 4 and argv[0] == "spend":
        print(spend(argv[1], max(0.0, float(argv[2])), argv[3]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
