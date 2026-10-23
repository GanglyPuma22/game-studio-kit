"""Cloud runs: one job file format and one queue for GPU work on rented runtimes.

A job names a game repository and branch, a setup command and a run command,
a time cap and where it runs:

- ``here``: in the current machine (a cloud agent box or a workstation), with a
  virtual screen and whatever Vulkan driver it has (a software one in a cloud
  box). Free and slow; needs no approval.
- ``colab``: on a Colab GPU runtime, started by the queue service on an
  always-on host. Fast; spends compute units; starts only after the person's
  typed go for the service.

The service host never runs a job's commands itself. It packs the named
commit with ``git archive``, copies it to the runtime and runs the commands
there, then brings back the job's ``OUT_DIR``. The shell side lives in
``skills/studio-cloudrun/scripts``; this module validates jobs and queues,
and prints the exact plan a runner would follow.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import StudioError

SCHEMA = 1
# Job types the service knows. A type fixes what the runtime prepares before
# the job's own commands run; the commands themselves come from the job.
JOB_TYPES = {
    "godot-capture": {
        "summary": "Check out a Godot game, run its own capture command on a GPU with a virtual screen, bring back OUT_DIR (clips, stills, numbers).",
        "runtime": ["virtual screen (Xvfb :99)", "Vulkan on the runtime GPU", "ffmpeg", "git checkout at OUT_DIR's parent"],
    },
}
# Reserved for job types that other queues may move onto later. Listing one
# here does not make the service run it.
RESERVED_TYPES = {
    "salvage-batch": "Salvage's existing Colab batches (tools/colab_batch); still run by Salvage's own queue",
    "model-run": "audio, music and other model generation on Colab; being tried in a separate session, the line between it and this runner is not settled yet",
}
WHERE = ("here", "colab")
GPUS = ("L4", "T4", "A100")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_MINUTES = 240
MAX_RESULTS_MB = 500


def load_job(path):
    try:
        job = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StudioError(f"cannot read job {path}: {e}")
    return job


def validate(job, allow_repos=None, allow_refs=None):
    """Every reason this job would be refused; empty when it is runnable."""
    errors = []
    if not isinstance(job, dict):
        return ["job must be a JSON object"]
    if job.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    jid = job.get("id")
    if not isinstance(jid, str) or not ID_RE.match(jid):
        errors.append("id must be 3-64 lowercase letters, digits or dashes, starting with a letter or digit")
    elif jid == "queue-status":
        errors.append("id queue-status is the service's own status branch (studio-results/queue-status)")
    jtype = job.get("type")
    if jtype in RESERVED_TYPES:
        errors.append(f"type {jtype} is reserved ({RESERVED_TYPES[jtype]})")
    elif jtype not in JOB_TYPES:
        errors.append(f"type must be one of {', '.join(sorted(JOB_TYPES))}")
    repo = job.get("repo")
    if not isinstance(repo, str) or not REPO_RE.match(repo):
        errors.append("repo must be owner/name")
    elif allow_repos and not any(_glob(repo, p) for p in allow_repos):
        errors.append(f"repo {repo} is not in the service's allowed list")
    ref = job.get("ref")
    if not isinstance(ref, str) or not REF_RE.match(ref) or ".." in ref or ref.startswith("-"):
        errors.append("ref must be a branch name or commit")
    elif allow_refs and not any(_glob(ref, p) for p in allow_refs):
        errors.append(f"ref {ref} is not in the service's allowed list")
    for key in ("setup", "command"):
        value = job.get(key, "" if key == "setup" else None)
        if not isinstance(value, str) or "\n" in value or "\r" in value or len(value) > 2000:
            errors.append(f"{key} must be one line of shell (at most 2000 characters)")
    if isinstance(job.get("command"), str) and not job["command"].strip():
        errors.append("command must not be empty")
    where = job.get("where", "colab")
    if where not in WHERE:
        errors.append(f"where must be one of {', '.join(WHERE)}")
    gpu = job.get("gpu", "L4")
    if gpu not in GPUS:
        errors.append(f"gpu must be one of {', '.join(GPUS)}")
    minutes = job.get("max_minutes")
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_MINUTES:
        errors.append(f"max_minutes must be a number from 1 to {MAX_MINUTES}")
    mb = job.get("results_max_mb", 200)
    if not isinstance(mb, (int, float)) or isinstance(mb, bool) or not 1 <= mb <= MAX_RESULTS_MB:
        errors.append(f"results_max_mb must be a number from 1 to {MAX_RESULTS_MB}")
    godot = job.get("godot")
    if godot is not None:
        if not isinstance(godot, dict) or not isinstance(godot.get("url"), str) or not godot["url"].startswith("https://"):
            errors.append("godot.url must be an https download of the engine zip")
        elif not isinstance(godot.get("sha256"), str) or not SHA_RE.match(godot["sha256"]):
            errors.append("godot.sha256 must be the zip's SHA-256 (64 hex digits)")
    env = job.get("env", {})
    if not isinstance(env, dict) or any(
        not re.match(r"^[A-Z][A-Z0-9_]{0,63}$", str(k)) or not isinstance(v, str) or "\n" in v for k, v in env.items()
    ):
        errors.append("env must map UPPER_CASE names to one-line strings")
    elif any(k in ("OUT_DIR", "GODOT", "JOB_ID", "STUDIO_COMMIT", "DISPLAY") for k in env):
        errors.append("env must not set OUT_DIR, GODOT, JOB_ID or DISPLAY (the runner sets them)")
    for k in ("token", "secret", "password", "key"):
        if any(k in str(name).lower() for name in env):
            errors.append("env must not carry credentials; runtimes get none")
            break
    return errors


def _glob(value, pattern):
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return value == pattern


def parse_queue(text):
    """Queue file lines: job file names under jobs/, in run order. Blank
    lines and # comments are skipped; a line STOP ends the queue."""
    jobs, stop = [], False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "STOP":
            stop = True
            break
        name = line.split()[0]
        if not re.match(r"^[a-z0-9][a-z0-9-]{2,63}\.json$", name):
            raise StudioError(f"bad queue line {line!r}: expected <job id>.json")
        jobs.append(name)
    return jobs, stop


def plan(job, where=None):
    """The exact steps a runner takes for this job, for review before a go."""
    errors = validate(job)
    if errors:
        raise StudioError("job is not runnable: " + "; ".join(errors))
    where = where or job.get("where", "colab")
    steps = []
    if where == "colab":
        steps += [
            f"service host: git fetch {job['repo']} {job['ref']}; git archive that commit (no .git, no credentials)",
            f"service host: colab new --gpu {job.get('gpu', 'L4')} (waits for a free GPU; the account's limit applies)",
            "service host: copy the archive and the runtime scripts in over colab ssh",
            "runtime: install xvfb, ffmpeg and Vulkan loader; start Xvfb :99; pick the NVIDIA Vulkan driver",
        ]
    else:
        steps += [
            f"here: use the checkout of {job['repo']} at {job['ref']} given with --project",
            "here: start a virtual screen with xvfb-run (any Vulkan driver, software in a cloud box)",
        ]
    if job.get("godot"):
        steps.append(f"{'runtime' if where == 'colab' else 'here'}: download Godot from {job['godot']['url']} and check SHA-256 {job['godot']['sha256'][:12]}...")
    if job.get("setup"):
        steps.append(f"{'runtime' if where == 'colab' else 'here'}: setup: {job['setup']}")
    steps.append(f"{'runtime' if where == 'colab' else 'here'}: run: {job['command']}  (OUT_DIR, GODOT, JOB_ID set; cap {job['max_minutes']} min)")
    if where == "colab":
        steps += [
            f"service host: copy OUT_DIR back (files over 10 MB and anything past {job.get('results_max_mb', 200)} MB left out and listed)",
            "service host: stop the runtime (also on error and at the time cap); push results to the results branch",
        ]
    return {"id": job["id"], "type": job["type"], "where": where, "steps": steps}
