"""Explicit Godot import, bounded smoke, launch and configured export."""

from pathlib import Path
import os
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
    profile = logs / "godot-profile"
    profile.mkdir(exist_ok=True)
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
        command(config, root, mode, output, preset),
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
