"""Explicit Godot import, bounded smoke, launch and configured export."""

from pathlib import Path
import os
import shutil
import tempfile
from contextlib import nullcontext
from ..config import require_executable, app_path
from ..common import StudioError, read_json
from ..processes import run


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
        executable_dir = Path(args[0]).parent
        if any((executable_dir / name).exists() for name in ("_sc_", "._sc_")):
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
        result = run(
            args,
            timeout=config["timeout"],
            log=logs / f"godot-{mode}.log",
            env=environment,
        )
    # Godot can log script/import failures while returning exit 0.
    if "SCRIPT ERROR:" in result["stdout"] or "ERROR:" in result["stdout"]:
        raise StudioError("Godot reported an error; inspect its local artifact log")
    if mode == "smoke":
        report = read_json(output)
        if report.get("ok") is not True:
            raise StudioError("Godot runtime assertions failed")
        return report
    if mode == "export" and (
        not Path(output).is_file() or Path(output).stat().st_size == 0
    ):
        raise StudioError("Godot export output missing")
    return {
        "status": mode + "_completed",
        "elapsed_seconds": result["elapsed_seconds"],
        "native_review": "not_run",
    }
