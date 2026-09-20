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
FIRST_ERROR_LIMIT = 240
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
# A script error that names one of the engine's per-frame or lifecycle
# callbacks was raised by code the game was already running.
RUNTIME_CALLBACK = re.compile(r"\b_(?:process|physics_process|ready|input)\b")


def _is_load_error(line):
    """True when this error line is one Godot prints before the game runs."""
    return any(signature in line for signature in LOAD_SIGNATURES) or bool(
        LOAD_RESOURCE_ERROR.search(line)
    )


def classify_log(output):
    """Classify a completed log without echoing potentially private diagnostics.

    `phase` separates a game that never started from one that failed while
    running, using the first error only: a load-time signature that appears
    before any runtime script error means the engine did not get as far as the
    game, and anything else with an error is reported as runtime. Elapsed time
    is deliberately not consulted — a slow host is not a startup failure.

    `first_error` is that same first error line, stripped of terminal colour
    escapes and truncated, so an operator sees which failure to chase without
    the receipt carrying the whole log.
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
        first_error = first[:FIRST_ERROR_LIMIT]
        # A runtime callback is usually named on the `at:` continuation line
        # Godot prints under the message, so the first error is read together
        # with its own continuation lines — and with nothing else, or a later
        # unrelated error would decide this one's phase.
        block = [first]
        for line in lines[index + 1:]:
            if ERROR_LINE.search(line) or not line.strip().startswith("at:"):
                break
            block.append(line)
        runtime = bool(RUNTIME_CALLBACK.search("\n".join(block)))
        phase = "load" if _is_load_error(first) and not runtime else "runtime"
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
