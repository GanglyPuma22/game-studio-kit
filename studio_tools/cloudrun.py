"""Cloud runs: one job file format and one queue for GPU work on rented runtimes.

A ``godot-capture`` job names a game repository and branch, a setup command
and a run command, a time cap and where it runs. A ``model-run`` job names a
recipe shipped with this kit (``skills/studio-cloudrun/recipes``) and its plan
(prompts, seeds, lengths) instead, and adds a compute-unit ceiling. Speech
recipes (``kind`` ``speech`` or ``voice-casting``, experimental) take lines
of dialogue and an approved reference voice listed under the job's
``inputs``. Where:

- ``here``: in the current machine (a cloud agent box or a workstation), with a
  virtual screen and whatever Vulkan driver it has (a software one in a cloud
  box). Free and slow; needs no approval.
- ``colab``: on a Colab GPU runtime, started by the queue service on an
  always-on host. Fast; spends compute units; starts only after the person's
  typed go for the service.
- ``attended`` (model runs only): in a notebook the person opens and watches
  on their own free runtime (``scripts/attended.sh``). ``max_units`` is 0:
  nothing here starts, prices or pays for a runtime.

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
    "model-run": {
        "summary": "Run one of this kit's model recipes (music, sound effects, experimental speech and voice casting) on a Colab GPU with the job's plan, bring back originals, previews and a receipt.",
        "runtime": ["the recipe's pinned Python 3.12 environment (uv)", "model weights at pinned revisions, checked by SHA-256", "no screen"],
    },
}
RECIPES_DIR = Path(__file__).resolve().parent.parent / "skills" / "studio-cloudrun" / "recipes"
MAX_UNITS = 20
# Reserved for job types that other queues may move onto later. Listing one
# here does not make the service run it.
RESERVED_TYPES = {
    "salvage-batch": "Salvage's existing Colab batches (tools/colab_batch); still run by Salvage's own queue",
}
WHERE = ("here", "colab")
MODEL_WHERE = ("colab", "attended")
# Recipe kinds that read dialogue lines (and, for speech, a reference voice).
SPEECH_KINDS = ("speech", "voice-casting")
# A job input: a relative path with no "..", no leading dot or slash.
INPUT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*$")
LINE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,95}$")
MAX_INPUTS = 8
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
    if jtype == "model-run":
        return errors + _validate_model_run(job)
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


def recipes():
    """The model recipes this kit ships: name -> recipe.json."""
    found = {}
    if RECIPES_DIR.is_dir():
        for d in sorted(RECIPES_DIR.iterdir()):
            f = d / "recipe.json"
            if f.is_file():
                found[d.name] = json.loads(f.read_text(encoding="utf-8"))
    return found


def _number(job, key, low, high, errors, default=None):
    v = job.get(key, default)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not low <= v <= high:
        errors.append(f"{key} must be a number from {low} to {high}")
        return None
    return v


def _validate_model_run(job):
    errors = []
    for key in ("repo", "ref", "setup", "command", "godot", "env"):
        if key in job:
            errors.append(f"{key} is not used by model-run (the recipe brings its own setup and command)")
    where = job.get("where", "colab")
    if where not in MODEL_WHERE:
        errors.append("model-run runs on colab only (the service), or attended (a notebook the person watches)")
    _number(job, "max_minutes", 1, MAX_MINUTES, errors)
    _number(job, "results_max_mb", 1, MAX_RESULTS_MB, errors, 200)
    if where == "attended":
        # The person's own free runtime: nothing here prices or pays for it.
        if job.get("max_units") != 0 or isinstance(job.get("max_units"), bool):
            errors.append("max_units must be 0 for attended runs (spend is fixed at zero)")
        for key in ("max_rate", "budget"):
            if key in job:
                errors.append(f"{key} is not used by attended runs (they spend nothing)")
    else:
        units = _number(job, "max_units", 0.01, MAX_UNITS, errors)
        rate = job.get("max_rate")
        if rate is not None:
            _number(job, "max_rate", 0.1, 50, errors)
        errors += _validate_budget(job.get("budget"), units)
    name = job.get("recipe")
    known = recipes()
    if name not in known:
        errors.append(f"recipe must be one of {', '.join(sorted(known)) or '(none shipped)'}")
        return errors
    recipe = known[name]
    gpu = job.get("gpu", recipe.get("gpu", "L4"))
    if gpu not in recipe.get("gpus", GPUS):
        errors.append(f"recipe {name} runs on {', '.join(recipe.get('gpus', GPUS))}, not {gpu}")
    inputs, in_errors = _validate_inputs(job.get("inputs"), recipe)
    errors += in_errors
    errors += validate_plan(recipe, job.get("plan"), inputs)
    return errors


def _validate_budget(budget, units):
    """A total ceiling shared by several jobs (an audition's casting and
    engines): {"group": id, "units": total}. The runner refuses a job once
    the group has spent its total and caps each runtime at what is left."""
    if budget is None:
        return []
    if not isinstance(budget, dict) or set(budget) - {"group", "units"}:
        return ["budget must be {\"group\": id, \"units\": total}"]
    errors = []
    if not isinstance(budget.get("group"), str) or not ID_RE.match(budget["group"]):
        errors.append("budget.group must be a 3-64 character lowercase id")
    total = budget.get("units")
    if not isinstance(total, (int, float)) or isinstance(total, bool) or not 0.01 <= total <= MAX_UNITS:
        errors.append(f"budget.units must be a number from 0.01 to {MAX_UNITS}")
    elif units is not None and units > total:
        errors.append("max_units must not exceed budget.units")
    return errors


def _validate_inputs(inputs, recipe):
    """Files the job brings (an approved reference voice): relative paths,
    each with its SHA-256. Private by default: never copied to results."""
    if inputs is None:
        return {}, []
    if not recipe.get("inputs"):
        return {}, ["inputs are only used by recipes that read files (speech)"]
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_INPUTS:
        return {}, [f"inputs must be a list of 1 to {MAX_INPUTS} files"]
    found, errors = {}, []
    for i, item in enumerate(inputs):
        where = f"inputs[{i}]"
        if not isinstance(item, dict) or set(item) - {"path", "sha256", "private"}:
            errors.append(f"{where} must be {{path, sha256, private}}")
            continue
        path = item.get("path")
        if not isinstance(path, str) or len(path) > 200 or not INPUT_RE.match(path) or ".." in path.split("/"):
            errors.append(f"{where}.path must be a relative path inside the inputs folder (no .., no leading dot or slash)")
            continue
        if path in found:
            errors.append(f"{where}.path {path} is listed twice")
        if not isinstance(item.get("sha256"), str) or not SHA_RE.match(item["sha256"]):
            errors.append(f"{where}.sha256 must be the file's SHA-256 (64 lowercase hex digits)")
        if not isinstance(item.get("private", True), bool):
            errors.append(f"{where}.private must be true or false")
        found[path] = item
    return found, errors


def check_inputs(job, folder):
    """Every reason the files in folder do not match the job's inputs (missing,
    outside the folder through a link, or a different SHA-256)."""
    import hashlib

    errors = []
    root = Path(folder).resolve()
    for item in job.get("inputs") or []:
        path = root / item.get("path", "")
        try:
            real = path.resolve(strict=True)
        except (OSError, RuntimeError):
            errors.append(f"input {item.get('path')} is missing from {folder}")
            continue
        if root != real and root not in real.parents:
            errors.append(f"input {item.get('path')} leads outside {folder}")
            continue
        if not real.is_file():
            errors.append(f"input {item.get('path')} is not a file")
            continue
        h = hashlib.sha256()
        with real.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != item.get("sha256"):
            errors.append(f"input {item.get('path')} does not match its sha256")
    return errors


def check_group(jobs):
    """Jobs sharing a budget group must agree on its total."""
    totals = {}
    for j in jobs:
        b = j.get("budget") if isinstance(j, dict) else None
        if isinstance(b, dict) and "group" in b:
            totals.setdefault(b["group"], set()).add(b.get("units"))
    return [f"budget group {g} has different totals: {sorted(map(str, t))}" for g, t in totals.items() if len(t) > 1]


def validate_plan(recipe, p, inputs=None):
    """A recipe's plan: cues with an id, the recipe's text field and seeds."""
    if recipe.get("kind") in SPEECH_KINDS:
        return validate_speech_plan(recipe, p, inputs or {})
    errors = []
    if not isinstance(p, dict) or not isinstance(p.get("cues"), list) or not p["cues"]:
        return ["plan must be an object with a non-empty cues list"]
    lim = recipe.get("limits", {})
    text_key = recipe.get("text_field", "prompt")
    total, ids = 0, set()
    for i, cue in enumerate(p["cues"]):
        where = f"plan.cues[{i}]"
        if not isinstance(cue, dict):
            errors.append(f"{where} must be an object")
            continue
        cid = cue.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid) or cid in ids:
            errors.append(f"{where}.id must be a unique 3-64 character lowercase id")
        ids.add(cid)
        text = cue.get(text_key)
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            errors.append(f"{where}.{text_key} must be text (at most 2000 characters)")
        seeds = cue.get("seeds")
        if not isinstance(seeds, list) or not seeds or not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 2**31 for x in seeds) or len(set(seeds)) != len(seeds):
            errors.append(f"{where}.seeds must be a list of distinct whole numbers")
        else:
            total += len(seeds)
        secs = cue.get("seconds", p.get("seconds"))
        lo, hi = lim.get("seconds", [1, 600])
        if not isinstance(secs, (int, float)) or isinstance(secs, bool) or not lo <= secs <= hi:
            errors.append(f"{where}.seconds (or plan.seconds) must be from {lo} to {hi}")
    fade = p.get("loop_crossfade_seconds", 0)
    if not isinstance(fade, (int, float)) or isinstance(fade, bool) or fade < 0:
        errors.append("plan.loop_crossfade_seconds must be a number of seconds, 0 or more")
    elif fade:
        for i, cue in enumerate(c for c in p["cues"] if isinstance(c, dict)):
            secs = cue.get("seconds", p.get("seconds"))
            if isinstance(secs, (int, float)) and not isinstance(secs, bool) and fade * 2 >= secs:
                errors.append(f"plan.loop_crossfade_seconds must be under half of plan.cues[{i}].seconds")
    if total > lim.get("max_outputs", 32):
        errors.append(f"plan asks for {total} outputs; recipe limit is {lim.get('max_outputs', 32)}")
    return errors


def _seeds_ok(seeds):
    return (isinstance(seeds, list) and seeds and len(set(seeds)) == len(seeds)
            and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 2**31 for x in seeds))


def _controls(recipe, controls, where, errors, need_instruct=False):
    """Only the controls a recipe really reads, in its ranges. A control the
    engine would ignore is refused, so nobody believes it was applied."""
    known = recipe.get("controls", {})
    if controls is None:
        controls = {}
    if not isinstance(controls, dict):
        errors.append(f"{where}.controls must be an object")
        return
    for k, v in controls.items():
        spec = known.get(k)
        if spec is None:
            errors.append(f"{where}.controls.{k} is not supported by this recipe (supported: {', '.join(sorted(known)) or 'none'}); "
                          "record the wish as delivery intent instead")
        elif spec == "text":
            if not isinstance(v, str) or not v.strip() or len(v) > 500 or "\n" in v:
                errors.append(f"{where}.controls.{k} must be one line of text (at most 500 characters)")
        elif not isinstance(v, (int, float)) or isinstance(v, bool) or not spec[0] <= v <= spec[1]:
            errors.append(f"{where}.controls.{k} must be a number from {spec[0]} to {spec[1]}")
    if need_instruct and "instruct" not in controls:
        errors.append(f"{where}.controls.instruct (the voice description) is required")


def validate_speech_plan(recipe, p, inputs):
    """Speech and casting plans: exact lines (text, seeds, a length ceiling in
    seconds of generated audio), the controls the engine supports, and for
    speech one approved reference voice from the job's inputs."""
    if not isinstance(p, dict) or not isinstance(p.get("cues"), list) or not p["cues"]:
        return ["plan must be an object with a non-empty cues list"]
    errors = []
    lim = recipe.get("limits", {})
    lo, hi = lim.get("max_seconds", [1, 10])
    max_chars = lim.get("max_chars", 200)
    casting = recipe.get("kind") == "voice-casting"
    lang = p.get("language")
    if lang not in recipe.get("languages", ["en"]):
        errors.append(f"plan.language must be one of {', '.join(recipe.get('languages', ['en']))}")
    ch = p.get("character")
    if not isinstance(ch, dict) or not isinstance(ch.get("id"), str) or not LINE_ID_RE.match(ch["id"]) \
            or not isinstance(ch.get("profile_version"), int) or isinstance(ch.get("profile_version"), bool) or ch["profile_version"] < 1:
        errors.append("plan.character must be {id, profile_version} from the character's voice profile")
    ref = p.get("reference")
    if casting:
        if ref is not None:
            errors.append("plan.reference is not used by casting (it makes the reference)")
    elif recipe.get("reference") == "required":
        if not isinstance(ref, dict):
            errors.append("plan.reference must name the approved reference voice: {input, sha256, transcript}")
        else:
            item = inputs.get(ref.get("input"))
            if item is None:
                errors.append("plan.reference.input must be one of the job's inputs")
            elif ref.get("sha256") != item.get("sha256"):
                errors.append("plan.reference.sha256 must match that input's sha256")
            elif item.get("private", True) is not True:
                errors.append("the reference voice input must be private (never copied to results)")
            t = ref.get("transcript")
            if not isinstance(t, str) or not t.strip() or len(t) > 1000:
                errors.append("plan.reference.transcript must be the exact words spoken in the reference")
    _controls(recipe, p.get("controls"), "plan", errors)
    total, ids, seeds_of = 0, set(), {}
    for i, cue in enumerate(p["cues"]):
        where = f"plan.cues[{i}]"
        if not isinstance(cue, dict):
            errors.append(f"{where} must be an object")
            continue
        cid = cue.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid) or cid in ids:
            errors.append(f"{where}.id must be a unique 3-64 character lowercase id")
        ids.add(cid)
        if "line_id" in cue and (not isinstance(cue["line_id"], str) or not LINE_ID_RE.match(cue["line_id"])):
            errors.append(f"{where}.line_id must be the line sheet's id (lowercase letters, digits, dots, dashes)")
        text = cue.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > max_chars or "\n" in text:
            errors.append(f"{where}.text must be one line of spoken text (at most {max_chars} characters)")
        if "delivery" in cue and (not isinstance(cue["delivery"], str) or len(cue["delivery"]) > 200):
            errors.append(f"{where}.delivery must be a short description of the intended delivery")
        secs = cue.get("max_seconds", p.get("max_seconds"))
        if not isinstance(secs, (int, float)) or isinstance(secs, bool) or not lo <= secs <= hi:
            errors.append(f"{where}.max_seconds (or plan.max_seconds) must be from {lo} to {hi}")
        merged = {**(p.get("controls") or {}), **(cue.get("controls") or {})} if isinstance(cue.get("controls", {}), dict) else cue.get("controls")
        _controls(recipe, cue.get("controls"), where, errors)
        if casting and isinstance(merged, dict) and "instruct" not in merged:
            errors.append(f"{where}.controls.instruct (the voice description) is required")
        if not _seeds_ok(cue.get("seeds")):
            errors.append(f"{where}.seeds must be a list of distinct whole numbers")
        else:
            total += len(cue["seeds"])
            seeds_of[cid] = set(cue["seeds"])
    repeats = p.get("repeats", [])
    if not isinstance(repeats, list):
        errors.append("plan.repeats must be a list")
        repeats = []
    for i, r in enumerate(repeats):
        where = f"plan.repeats[{i}]"
        if not isinstance(r, dict) or r.get("after_reload") is not True or set(r) - {"cue", "seed", "after_reload"}:
            errors.append(f"{where} must be {{cue, seed, after_reload: true}}: the same cue and seed again after reloading the model")
        elif r.get("seed") not in seeds_of.get(r.get("cue"), ()):
            errors.append(f"{where} must repeat a cue and one of its own seeds")
        else:
            total += 1
    if total > lim.get("max_outputs", 40):
        errors.append(f"plan asks for {total} outputs; recipe limit is {lim.get('max_outputs', 40)}")
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


def _attended_steps(job, recipe, n):
    steps = [
        "notebook (the person's own runtime, watched): no runtime is started, priced or paid for here; spend is 0",
        f"notebook: check the job, the inputs folder against each SHA-256, and pack recipe {job['recipe']} with the plan ({n} outputs)",
        "notebook: setup: " + recipe.get("setup_summary", "the recipe's setup.sh"),
        "notebook: run: " + recipe.get("run_summary", "the recipe's run.sh") + f" (cap {job['max_minutes']} min)",
        "notebook: list every result with its SHA-256, refuse to keep any copy of a private input, zip the results to download",
    ]
    return steps


def plan(job, where=None):
    """The exact steps a runner takes for this job, for review before a go."""
    errors = validate(job)
    if errors:
        raise StudioError("job is not runnable: " + "; ".join(errors))
    where = where or job.get("where", "colab")
    steps = []
    if job["type"] == "model-run":
        recipe = recipes()[job["recipe"]]
        n = sum(len(c["seeds"]) for c in job["plan"]["cues"]) + len(job["plan"].get("repeats", []))
        gpu = job.get("gpu", recipe.get("gpu", "L4"))
        if job.get("where") == "attended":
            return {"id": job["id"], "type": job["type"], "where": "attended", "steps": _attended_steps(job, recipe, n)}
        steps += [f"service host: pack recipe {job['recipe']} from this kit checkout with the job's plan ({len(job['plan']['cues'])} cues, {n} outputs)"]
        if job.get("inputs"):
            steps.append(f"service host: check {len(job['inputs'])} input file(s) against their SHA-256 and pack them; private inputs never go to results")
        if job.get("budget"):
            b = job["budget"]
            steps.append(f"service host: budget group {b['group']}: refuse once {b['units']} units are spent across its jobs (setup included); cap this runtime at what is left")
        if recipe.get("gated"):
            steps.append(f"service host: resolve short-lived download links for {recipe['model']['repo']} with the host's Hugging Face login (the token never leaves the host)")
        steps += [
            f"service host: colab new --gpu {gpu}; read the hourly rate; refuse above {job.get('max_rate', 'no')} units/hour; cap the runtime at {job['max_minutes']} min + 20 or {job['max_units']} units, whichever comes first",
            "runtime: setup: " + recipe.get("setup_summary", "the recipe's setup.sh"),
            "runtime: run: " + recipe.get("run_summary", "the recipe's run.sh"),
            "service host: copy OUT_DIR back, check every file against the runtime's SHA-256 list, stop the runtime, push results",
        ]
        return {"id": job["id"], "type": job["type"], "where": "colab", "steps": steps}
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
