"""Many owned launches, one blocking call, one verdict.

`launch` already owns a single bounded run that a caller waits for and reads a
verdict from. What did not exist was a way to ask for several of them, which is
why sessions hand-rolled a wrapper that started runs and then asked, over and
over, whether they had finished yet. That is the polling the unattended rules
forbid, and no rule can forbid it while the only alternative is to write it
yourself. This command is the alternative: it runs the plan, blocks until the
last run is finished, and returns one verdict for the whole batch.

It reuses `launch.execute` for every run rather than launching anything itself,
so each run keeps its own receipts, its own window and its own vocabulary. The
rollup adds only what a single launch cannot say: which runs ran, in what
order, under which total cap, and whether every one of them was ok.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import uuid
from . import launch
from .common import StudioError, outside_package, relative, safe_id, write_json
from .launch import MODES, parse_utc

PLAN_KIND = "launch-batch-plan"
PLAN_SCHEMA_VERSION = 1
DEFAULT_MAX_MINUTES = 60
# A batch has nobody watching it, so it stays bounded like every other
# unattended wait; a night is the longest window one of them is authorized for.
MAX_BATCH_MINUTES = 1440
# Exactly the keys a run may carry. An unknown key is refused rather than
# ignored: a misspelled `results` would otherwise silently drop the very
# evidence the run was queued to produce.
RUN_FIELDS = ("label", "scope", "mode", "script", "timeout", "cutoff_utc",
              "results", "scrub_env", "passthrough")
STRING_LISTS = ("results", "scrub_env", "passthrough")
# Statuses the launcher returns when no engine ever started: a cutoff that had
# already passed, an engine replaced before it could run, a child that failed to
# start. Each is an ordinary verdict with a null PID behind it, never a launch.
NOT_STARTED = ("refused", "start_failed")
LIMITS = [
    "exit zero is not acceptance; a green batch is a batch of runs that ran",
    "runs execute sequentially in plan order, so their elapsed times are comparable "
    "with each other; a run may still inherit host state an earlier run left behind",
    "the total cap bounds the batch, not any single run: one run may spend the whole window",
    "stdout and stderr are combined in each run's own log; the children may print private data",
]


def _where(index, entry):
    """Name the offending entry so a refusal points at one line of the plan."""
    label = entry.get("label") if isinstance(entry, dict) else None
    named = f' (label "{label}")' if isinstance(label, str) and label else ""
    return f"Batch plan run {index + 1}{named}"


def _run_entry(root, index, entry, seen, reserved):
    """Validate one planned run completely, before any engine starts."""
    if not isinstance(entry, dict):
        raise StudioError(f"{_where(index, entry)} is not a JSON object")
    unknown = sorted(set(entry) - set(RUN_FIELDS))
    if unknown:
        raise StudioError(f"{_where(index, entry)} has an unknown field: {unknown[0]}")
    if "label" not in entry:
        # Every run needs its own identity: the label is the run directory, and
        # it is the only handle the rollup and the receipts share.
        raise StudioError(f"{_where(index, entry)} is missing a required field: label")
    try:
        label = safe_id(entry["label"])
    except StudioError:
        # Every refusal here names the entry it came from: a plan is read by
        # whoever wrote it, and "which run?" is the first thing they ask.
        raise StudioError(
            f"{_where(index, entry)} has a label that is not an ID; "
            "use letters, digits, hyphens or underscores"
        ) from None
    # Two labels differing only in case name one directory on Windows, so the
    # collision is caught here rather than by whichever run reaches the
    # filesystem second, after the first has already spent its window.
    folded = label.casefold()
    if folded in seen:
        raise StudioError(f"{_where(index, entry)} reuses the label of run {seen[folded] + 1}")
    # `launch` refuses a run directory that already exists. Finding that out on
    # the last run, after every earlier one has spent its window, is exactly the
    # failure an unattended batch cannot afford, so it is found here instead.
    owned = relative(root, f"artifacts/launches/{label}")
    if owned.exists():
        raise StudioError(f"{_where(index, entry)} names a launch directory that exists; choose a new label")
    mode = entry.get("mode", "import")
    if mode not in MODES:
        raise StudioError(f"{_where(index, entry)} has an unknown mode; use import, test, check or native")
    script = entry.get("script")
    if script is not None and (not isinstance(script, str) or not script.strip()):
        raise StudioError(f"{_where(index, entry)} has an empty script; name an engine script path or omit it")
    if script is None and mode in ("test", "check"):
        raise StudioError(f"{_where(index, entry)} is missing a required field: script, which mode {mode} needs")
    timeout = entry.get("timeout")
    if timeout is not None and (type(timeout) not in (int, float)
                                or not math.isfinite(timeout) or not 0 < timeout <= launch.MAX_TIMEOUT):
        raise StudioError(f"{_where(index, entry)} has a timeout outside 1-{launch.MAX_TIMEOUT} seconds")
    if entry.get("scope") is not None:
        try:
            safe_id(entry["scope"])
        except StudioError:
            raise StudioError(
                f"{_where(index, entry)} has a scope that is not a rung ID; "
                "use letters, digits, hyphens or underscores"
            ) from None
    for field in STRING_LISTS:
        value = entry.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise StudioError(f"{_where(index, entry)} has a {field} that is not a list of nonempty strings")
    # The launcher applies the first two rules to a declared result, but only
    # once that run starts. A path that escapes the project, or that names a
    # receipt the launcher writes, would otherwise be refused after every
    # earlier run had already spent its window, which is the failure the
    # up-front validation exists to prevent. The third rule is this command's
    # own: the rollup is rewritten between runs, so a result declared inside
    # the batch record directory would be overwritten by the receipt that then
    # reports the run as completed, with a hash for bytes that are gone.
    for item in entry.get("results", []):
        try:
            target = relative(root, item)
        except StudioError:
            raise StudioError(
                f"{_where(index, entry)} declares a result outside the project; "
                "use a portable project-relative path"
            ) from None
        if any(target == kept or target.is_relative_to(kept) for kept in (owned, reserved)):
            raise StudioError(
                f"{_where(index, entry)} declares a result the launcher or this batch "
                "writes itself; name a file the run produces"
            )
    # Parsed here so a malformed instant is refused with the rest of the plan
    # rather than after the runs before it have already been spent. A present
    # but falsey value is malformed, not absent: silently dropping `""` or
    # `false` would let the run inherit the far later batch deadline instead.
    try:
        cutoff = parse_utc(entry["cutoff_utc"]) if entry.get("cutoff_utc") is not None else None
    except StudioError:
        raise StudioError(
            f"{_where(index, entry)} has a cutoff_utc that is not an ISO 8601 "
            "timestamp with a UTC offset"
        ) from None
    seen[folded] = index
    return {**entry, "label": label, "mode": mode, "cutoff": cutoff}


def _plan(root, path, reserved):
    """Read and fully validate the plan before the first engine starts.

    The plan file itself is hashed, never copied into the receipts: it carries
    the passthrough arguments each run hands the engine, and those are values a
    receipt may not hold. The bytes are read once and both the entries and the
    digest come from that one snapshot, so the receipt can never record the
    hash of a plan other than the one that ran.
    """
    plan_path = Path(path).expanduser()
    try:
        raw = plan_path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except OSError:
        raise StudioError("Batch needs an existing, readable --plan file listing the runs") from None
    except ValueError:
        raise StudioError(f"Cannot read JSON record: {plan_path.name}") from None
    if not isinstance(document, dict) or not isinstance(document.get("runs"), list):
        raise StudioError('Batch plan must be a JSON object with a "runs" list')
    # A plan says which format it is in. Reading a mistyped kind, or a version
    # this code does not know, with version-1 semantics would reinterpret the
    # file rather than refuse it as the format grows.
    if document.get("kind") != PLAN_KIND:
        raise StudioError(f'Batch plan must declare kind "{PLAN_KIND}"')
    if document.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise StudioError(f"Batch plan schema_version must be {PLAN_SCHEMA_VERSION}")
    if not document["runs"]:
        raise StudioError("Batch plan lists no runs; a batch of nothing has nothing to report")
    seen = {}
    entries = [_run_entry(root, index, entry, seen, reserved)
               for index, entry in enumerate(document["runs"])]
    return entries, {"path": str(plan_path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


def _paths(root, result):
    """Index a finished run by the project-relative paths of its own receipts.

    The values are read from the result the launcher just returned, so nothing
    here re-opens a receipt to describe bytes that were never summarized.
    """
    def under(value):
        if not value:
            return None
        return Path(value).resolve().relative_to(root).as_posix()

    return {
        "run_dir": under(result["run_dir"]),
        "launch_record": under(result["launch_record"]),
        "exit_record": under(result["exit_record"]),
        "diagnostics_record": under(result["diagnostics_record"]),
        "process_record": under(result["process_record"]),
        "log": under(result["log"]),
    }


def _receipts_on_disk(root, label):
    """Point at whatever the launcher had already written for this run.

    An interrupted launch finishes its own receipts before it re-raises, so the
    paths are deterministic; the row would otherwise disown durable evidence
    sitting beside the record that is meant to explain the interruption.
    """
    base = Path("artifacts/launches") / label
    files = {
        "launch_record": "owned-launch.json", "exit_record": "exit.json",
        "diagnostics_record": "diagnostics.json",
        "process_record": "process/process.json", "log": "process/stdout.log",
    }
    found = {"run_dir": base.as_posix() if (root / base).is_dir() else None}
    for field, name in files.items():
        found[field] = (base / name).as_posix() if (root / base / name).is_file() else None
    return found


def _summary(index, entry, status, **fields):
    """One rollup row. Passthrough values and scrub prefixes never appear here:
    the count is what a receipt may say about what the child was handed."""
    passthrough = entry.get("passthrough", [])
    return {
        "index": index,
        "label": entry["label"],
        "scope": entry.get("scope"),
        "mode": entry["mode"],
        "script": entry.get("script"),
        # Counted the way the launcher counts it, so the rollup and the launch
        # receipt never disagree about how many arguments the engine was given.
        "passthrough_count": len(passthrough) - (1 if passthrough[:1] == ["--"] else 0),
        "status": status,
        "verdict": None,
        "ok": False,
        "elapsed_seconds": None,
        "timed_out": False,
        "failure": None,
        "run_dir": None,
        "launch_record": None,
        "exit_record": None,
        "diagnostics_record": None,
        "process_record": None,
        "log": None,
        **fields,
    }


def _rollup(root, label, plan_record, started, deadline, max_minutes,
            stop_on_first_failure, runs, planned, stopped, finished=None):
    totals = {
        "planned": planned,
        # Only a row whose engine actually started counts as having run, so a
        # batch where nothing launched can never claim every entry ran.
        "ran": sum(run["status"] == "ran" for run in runs),
        "not_started": sum(run["status"] == "not_started" for run in runs),
        "ok": sum(run["ok"] for run in runs),
        "not_ok": sum(run["status"] != "not_run" and not run["ok"] for run in runs),
        "not_run": sum(run["status"] == "not_run" for run in runs),
    }
    return {
        "schema_version": 1,
        "kind": "launch-batch",
        "label": label,
        "project": str(root),
        "plan": plan_record,
        # Stated rather than implied: nothing here runs two engines at once, so
        # the elapsed times below were measured on a host running one of them.
        "execution": "sequential",
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat() if finished else None,
        "max_minutes": max_minutes,
        "max_minutes_effective": round((deadline - started).total_seconds() / 60, 3),
        "deadline_utc": deadline.isoformat(),
        "stop_on_first_failure": stop_on_first_failure,
        "stopped_early": stopped,
        "totals": totals,
        "runs": runs,
        # A batch of green launches is a batch of launches that ran. No count of
        # completed runs decides that a person would accept what they produced.
        "acceptance": "not_established",
        "limits": LIMITS,
        # Every planned run finished and every one of them was ok. A batch that
        # stopped early, or never reached a run, is not ok however green its rows.
        "ok": totals["planned"] == totals["ok"],
    }


def execute(
    config, project, *, plan, sha256_expected, label=None,
    max_minutes=None, stop_on_first_failure=False,
):
    """Run every planned launch in order, block until the last one is finished,
    and return one verdict for the batch."""
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Batch needs an existing game project directory")
    label = safe_id(label) if label else uuid.uuid4().hex
    # Its own namespace beside artifacts/launches, so a batch rollup and the
    # runs it indexes can never collide on the label that refuses a reused dir.
    # Resolved before the plan is read, because no run may declare a result
    # inside it.
    run_dir = outside_package(relative(root, f"artifacts/batches/{label}"))
    entries, plan_record = _plan(root, plan, run_dir)
    if max_minutes is None:
        max_minutes = DEFAULT_MAX_MINUTES
    if (type(max_minutes) not in (int, float) or not math.isfinite(max_minutes)
            or not 0 < max_minutes <= MAX_BATCH_MINUTES):
        # There is no uncapped batch: nobody is watching it, so `0` would mean
        # a run of unknown length rather than a run until the player quits.
        raise StudioError(f"Batch --max-minutes must be 1-{MAX_BATCH_MINUTES}; an unattended batch stays bounded")
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Batch directory exists; choose a new label") from None
    started = datetime.now(timezone.utc)
    deadline = started + timedelta(minutes=max_minutes)
    rollup_path = run_dir / "batch.json"
    runs = [_summary(index, entry, "not_run", failure="batch had not reached this run")
            for index, entry in enumerate(entries)]
    stopped = None

    def save(finished=None):
        """Rewrite the rollup as a crash record, not a progress feed.

        Nothing may read this file to find out whether the batch is done: the
        command blocks and returns the same object. It is written between runs
        so that a batch killed by the host still says what it had finished.
        """
        write_json(rollup_path, _rollup(
            root, label, plan_record, started, deadline, max_minutes,
            stop_on_first_failure, runs, len(entries), stopped, finished,
        ))

    save()
    for index, entry in enumerate(entries):
        if stopped:
            # Checked before the budget so the reason the batch stopped is the
            # first one that fired, not whichever one is noticed last.
            runs[index]["failure"] = f"batch stopped earlier: {stopped}"
            continue
        if datetime.now(timezone.utc) >= deadline:
            stopped = "budget_exhausted"
            runs[index]["failure"] = "batch wall-clock budget was spent before this run started"
            continue
        # The run's own cutoff never outlives the batch's: whichever instant
        # comes first is the one the launcher is allowed to wait until.
        cutoff = min(deadline, entry["cutoff"]) if entry["cutoff"] else deadline
        # Recorded before the call, because this file is the crash record: a
        # host that dies mid-launch must not leave a row saying the batch never
        # reached a run whose receipts are already on disk beside it.
        runs[index] = _summary(index, entry, "in_flight",
                               failure="batch was inside this launch when it last wrote this record")
        save()
        try:
            result = launch.execute(
                config, root, sha256_expected=sha256_expected, mode=entry["mode"],
                script=entry.get("script"), timeout=entry.get("timeout"),
                cutoff_utc=cutoff.isoformat(), label=entry["label"], scope=entry.get("scope"),
                results=entry.get("results", []), scrub=entry.get("scrub_env", []),
                passthrough=entry.get("passthrough", []),
            )
        except StudioError as exc:
            # A refusal is this run's verdict, not the batch's. The remaining
            # runs still have their own windows, and the message is already a
            # safe string naming the fix, so it is recorded rather than raised.
            runs[index] = _summary(index, entry, "not_started", verdict="refused", failure=str(exc))
        except KeyboardInterrupt:
            # The launcher has already stopped its child and written its own
            # receipts; the rollup records the same honestly before re-raising.
            runs[index] = _summary(index, entry, "interrupted", verdict="interrupted",
                                   failure="batch interrupted while this run was in flight",
                                   **_receipts_on_disk(root, entry["label"]))
            stopped = "interrupted"
            for later in runs[index + 1:]:
                later["failure"] = "batch stopped earlier: interrupted"
            save(datetime.now(timezone.utc))
            raise
        else:
            # A verdict is not a launch. A cutoff that had already passed, an
            # engine replaced before it started and a child that never started
            # all come back here with no process behind them.
            engine_started = result["status"] not in NOT_STARTED
            runs[index] = _summary(
                index, entry, "ran" if engine_started else "not_started",
                verdict=result["verdict"], ok=result["ok"],
                elapsed_seconds=result["elapsed_seconds"], timed_out=result["timed_out"],
                failure=result["failure"], **_paths(root, result),
            )
        # Only a failure that actually prevents a later run stopped the batch;
        # saying so about the last run would contradict `not_run: 0`.
        if not runs[index]["ok"] and stop_on_first_failure and index + 1 < len(entries):
            stopped = "first_failure"
        save()
    finished = datetime.now(timezone.utc)
    save(finished)
    return {
        **_rollup(root, label, plan_record, started, deadline, max_minutes,
                  stop_on_first_failure, runs, len(entries), stopped, finished),
        "run_dir": str(run_dir),
        "batch_record": str(rollup_path),
    }
