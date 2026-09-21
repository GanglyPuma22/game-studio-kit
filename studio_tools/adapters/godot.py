"""Explicit Godot import, bounded smoke, launch and configured export."""

from pathlib import Path
import os
import re
import shutil
import tempfile
import uuid
from contextlib import nullcontext
from ..config import require_executable, app_path
from ..common import StudioError, read_json, write_json
from ..processes import run


SELF_CONTAINED_MARKERS = ("_sc_", "._sc_")


def self_contained(executable):
    """True when a marker beside the engine makes that Godot self-contained.

    Such an installation keeps its data next to the executable and ignores the
    environment profile, so any claim of profile isolation would be false.
    """
    path = Path(executable).expanduser()
    folders = {path.parent, path.resolve().parent}
    return any(
        (folder / name).exists()
        for folder in folders
        for name in SELF_CONTAINED_MARKERS
    )


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
ERROR_LINE = re.compile(r"(?:SCRIPT )?ERROR:")
FIRST_ERROR_LIMIT = 200
# Signatures Godot prints while it is still loading the project: a script that
# would not compile, a resource or scene that would not open. They describe a
# game that never reached its first frame, not one that failed while playing.
LOAD_SIGNATURES = (
    "Parse Error",
    "Failed to load script",
    "Failed loading resource",
    "Cannot open file",
    "Could not load",
    "Failed to instantiate scene",
    "Unable to load",
)
LOAD_RESOURCE_ERROR = re.compile(r"res://.*: Error")
# Godot prints the stack under the message as `at: <function> (<source>:<line>)`.
FRAME = re.compile(r"\bat:\s*(?P<function>[^(]*?)\s*\((?P<source>[^)]*)\)")
# A path this kit may keep: a project resource, whose name the project chose.
KEPT_PATH = re.compile(r"res://")
# The first project resource named on a line, with its line number when Godot
# printed one. The character class stops at a quote, a bracket or a space, so a
# resource name is taken whole and nothing beside it comes along.
RESOURCE = re.compile(r"res://[A-Za-z0-9_\-./]*(?::\d+)?")
# Every error phrase this kit is willing to repeat, in the order they are
# tried, each paired with the exact words that go into the receipt. A message
# Godot words differently is reported as `unrecognized` rather than quoted:
# the whole point is that no text from the log reaches a receipt unexamined.
# `Condition ... is true/false` collapses to its verdict because the condition
# Godot prints is an arbitrary expression from somebody's code.
ERROR_CATEGORIES = (
    (re.compile(r"Parse Error"), "Parse Error"),
    (re.compile(r"Failed to load script"), "Failed to load script"),
    (re.compile(r"Failed loading resource"), "Failed loading resource"),
    (re.compile(r"Cannot open file"), "Cannot open file"),
    (re.compile(r"Could not load"), "Could not load"),
    (re.compile(r"Failed to instantiate scene"), "Failed to instantiate scene"),
    (re.compile(r"Unable to load"), "Unable to load"),
    (re.compile(r"Resource file not found"), "Resource file not found"),
    (re.compile(r"Script inherits from native type"), "Script inherits from native type"),
    (re.compile(r"Invalid call"), "Invalid call"),
    (re.compile(r"Invalid get index"), "Invalid get index"),
    (re.compile(r"Invalid set index"), "Invalid set index"),
    (re.compile(r"Nonexistent function"), "Nonexistent function"),
    (re.compile(r"Division by zero"), "Division by zero"),
    (re.compile(r"Out of bounds"), "Out of bounds"),
    (re.compile(r"Assertion failed"), "Assertion failed"),
    (re.compile(r"Condition\b.*?\bis true"), "Condition is true"),
    (re.compile(r"Condition\b.*?\bis false"), "Condition is false"),
)
UNRECOGNIZED = "unrecognized"
SCRIPT_PREFIX = "SCRIPT ERROR:"
ENGINE_PREFIX = "ERROR:"


def _is_load_error(line):
    """True when this error line is one Godot prints before the game runs."""
    return any(signature in line for signature in LOAD_SIGNATURES) or bool(
        LOAD_RESOURCE_ERROR.search(line)
    )


def _game_frame(line):
    """True when this stack frame was executing the project's own GDScript.

    The function's name is not consulted: `_process`, `_on_button_pressed` and
    anything else a project calls its handlers are all the game running. What
    distinguishes them is the source the frame names — a `res://` script the
    project owns, rather than an engine translation unit such as
    `modules/gdscript/gdscript.cpp`, which Godot also prints while it is still
    loading. A frame in neither form proves nothing and is not counted.
    """
    match = FRAME.search(line)
    return bool(match) and bool(KEPT_PATH.search(match.group("source")))


def error_signature(line):
    """One error line rebuilt from an allowlist, never edited down from the log.

    The result is `<prefix> <category>` and, when the line named one, the first
    `res://` resource with its line number: three pieces this kit chose, in
    words this kit chose. Nothing else survives, because a redaction pass can
    only remove the shapes it was taught — an API token, an email address, a
    player's name in a message body all look like ordinary words — while an
    allowlist is wrong in the safe direction. A message Godot phrases in a way
    this list does not know becomes `unrecognized`: the log still has the whole
    line, and a receipt that says less is the price of a receipt that cannot
    leak. The cap is kept for the one remaining variable-length piece, the
    resource name.
    """
    prefix = SCRIPT_PREFIX if SCRIPT_PREFIX in line else ENGINE_PREFIX
    category = next(
        (label for pattern, label in ERROR_CATEGORIES if pattern.search(line)),
        UNRECOGNIZED,
    )
    resource = RESOURCE.search(line)
    parts = [prefix, category] + ([resource.group(0)] if resource else [])
    return " ".join(parts)[:FIRST_ERROR_LIMIT]


def classify_log(output):
    """Classify a completed log without echoing potentially private diagnostics.

    `phase` separates a game that never started from one that failed while
    running, using the first error only: a load-time signature that appears
    before any runtime script error means the engine did not get as far as the
    game, and anything else with an error is reported as runtime. Elapsed time
    is deliberately not consulted — a slow host is not a startup failure.

    `first_error` is a signature of that same first error line: terminal colour
    escapes removed, host paths and URLs replaced, anything from `user://`
    onwards dropped, and the result capped. An operator sees which failure to
    chase; the receipt never carries the log's raw text.
    """
    # Preserve the adapter's conservative substring detection, including
    # diagnostics prefixed by terminal color escapes or a host wrapper.
    errors = len(re.findall(r"(?:SCRIPT )?ERROR:", output))
    warnings = len(re.findall(r"WARNING:|Orphan StringName:", output))
    first_error = None
    phase = None
    if errors:
        # Escapes are removed before the line is read or recorded; they do not
        # affect the counts above, which match the same substrings either way.
        lines = ANSI.sub("", output).splitlines()
        index = next(i for i, line in enumerate(lines) if ERROR_LINE.search(line))
        first = lines[index].strip()
        first_error = error_signature(first)
        # The first error's own continuation frames decide, and no others: a
        # later, unrelated error must not classify this one. A frame in the
        # project's own script means the game was executing, so a load-worded
        # message raised from one is a runtime fault.
        executing = False
        for line in lines[index + 1:]:
            if ERROR_LINE.search(line) or not line.strip().startswith("at:"):
                break
            executing = executing or _game_frame(line)
        phase = "load" if _is_load_error(first) and not executing else "runtime"
    return {
        "status": "errors" if errors else "warnings" if warnings else "clean" if output.strip() else "unverified",
        "error_count": errors,
        "warning_count": warnings,
        "phase": phase,
        "first_error": first_error,
    }


def command(config, project, mode="import", output=None, preset=None):
    root = Path(project)
    if not (root / "project.godot").is_file():
        raise StudioError("Godot project.godot is missing")
    args = [
        require_executable(config, "godot"),
        "--path",
        app_path(config, root, "godot"),
    ]
    if mode == "import":
        args += ["--headless", "--editor", "--import"]
    elif mode == "smoke":
        metadata = (
            read_json(root / "project.json")
            if (root / "project.json").is_file()
            else {}
        )
        capabilities = (
            metadata.get("capabilities", {}) if isinstance(metadata, dict) else {}
        )
        if (
            not isinstance(capabilities, dict)
            or capabilities.get("godot_smoke") != "studio-smoke-v1"
        ):
            raise StudioError(
                "This project has not declared capabilities.godot_smoke=studio-smoke-v1 "
                "in project.json. Use its project-specific tests and native review, or "
                "implement the protocol documented in skills/studio-godot/references/execution.md."
            )
        if output is None:
            raise StudioError("Smoke requires an explicit evidence output path")
        args += [
            "--headless",
            "--",
            "--studio-smoke=" + app_path(config, output, "godot"),
        ]
    elif mode == "run":
        pass
    elif mode == "export":
        if not preset or not output or not (root / "export_presets.cfg").is_file():
            raise StudioError(
                "Export requires a project preset, installed export templates and explicit output"
            )
        args += [
            "--headless",
            "--export-release",
            preset,
            app_path(config, output, "godot"),
        ]
    else:
        raise StudioError("Unknown Godot mode")
    return args


def execute(config, project, mode="import", output=None, preset=None):
    root = Path(project)
    logs = root / "artifacts"
    logs.mkdir(parents=True, exist_ok=True)
    if mode == "smoke":
        output = Path(output or logs / "runtime-smoke.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise StudioError("Smoke output exists; choose a new evidence filename")
    args = command(config, root, mode, output, preset)
    templates = None
    if mode == "export":
        configured = config.get("godot_export_templates")
        templates = Path(configured).expanduser() if configured else None
        if templates is None or not templates.is_dir() or not any(templates.iterdir()):
            raise StudioError(
                "Set host config godot_export_templates to an existing nonempty "
                "export_templates directory containing matching version subdirectories; "
                "templates are copied into an isolated profile for export."
            )
        if logs.resolve().is_relative_to(templates.resolve()):
            raise StudioError(
                "Export template source must not contain the project artifacts directory"
            )
        if self_contained(args[0]):
            raise StudioError(
                "Isolated export requires Godot without a self-contained _sc_ marker"
            )
    # Each export receives a fresh copy: no stale templates and no writes to the source.
    context = (
        tempfile.TemporaryDirectory(prefix="godot-export-", dir=logs)
        if mode == "export"
        else nullcontext(str(logs / "godot-profile"))
    )
    with context as profile_name:
        profile = Path(profile_name)
        profile.mkdir(exist_ok=True)
        if templates is not None:
            folder = (
                "Godot"
                if os.name == "nt" or args[0].lower().endswith(".exe")
                else "godot"
            )
            shutil.copytree(templates, profile / folder / "export_templates")
        environment = os.environ.copy()
        for key in (
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
            "XDG_DATA_HOME",
            "APPDATA",
            "LOCALAPPDATA",
        ):
            environment[key] = app_path(config, profile, "godot")
        job = (logs / "jobs" / f"godot-{mode}-{uuid.uuid4().hex}").resolve()
        try:
            result = run(
                args,
                timeout=config["timeout"],
                job_dir=job,
                hide_window=mode != "run",
                env=environment,
            )
            # Godot can log script/import failures while returning exit 0.
            diagnostics = classify_log(result["stdout"])
            write_json(job / "diagnostics.json", diagnostics)
            if mode != "run" and diagnostics["status"] == "unverified":
                raise StudioError("Godot produced no captured output; diagnostics unverified")
            if diagnostics["error_count"]:
                raise StudioError("Godot reported an error")
            process_evidence = {
                "process_record": result.get("process_record"),
                "log": result.get("log"),
                "diagnostics": diagnostics,
                "diagnostics_record": str(job / "diagnostics.json"),
            }
            if mode == "smoke":
                report = read_json(output)
                if not isinstance(report, dict) or report.get("ok") is not True:
                    raise StudioError("Godot runtime assertions failed")
                return {**report, "process_evidence": process_evidence}
            if mode == "export" and (
                not Path(output).is_file() or Path(output).stat().st_size == 0
            ):
                raise StudioError("Godot export output missing")
            return {
                "status": mode + "_completed",
                "elapsed_seconds": result["elapsed_seconds"],
                "native_review": "not_run",
                "process_evidence": process_evidence,
            }
        except (StudioError, OSError) as exc:
            raise StudioError(
                f"{exc}; inspect artifacts/jobs/{job.name}/stdout.log "
                "and its adjacent process/diagnostic records"
            ) from exc
