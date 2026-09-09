"""Thin entrypoint for the packaged native Windows lifecycle scripts."""

import json
from pathlib import Path
import shutil
import subprocess

from .common import StudioError, relative


LIFECYCLE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "studio-blender"
    / "scripts"
    / "lifecycle"
)


def _powershell():
    for name in ("pwsh", "powershell"):
        executable = shutil.which(name)
        if executable:
            return executable
    raise StudioError("Blender MCP lifecycle needs PowerShell (pwsh or powershell)")


def _run(script, arguments, *, json_output=True):
    command = [
        _powershell(),
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(LIFECYCLE_ROOT / script),
        *map(str, arguments),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise StudioError("Could not start PowerShell for Blender MCP lifecycle") from exc
    if completed.returncode:
        raise StudioError(
            "Blender MCP lifecycle failed; inspect its receipt under the configured working root"
        )
    if not json_output:
        return {"ok": True, "summary": completed.stdout.strip()}
    try:
        return json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise StudioError("Blender MCP lifecycle returned invalid JSON") from exc


def execute(
    config,
    config_path,
    project,
    operation,
    *,
    source=None,
    session=None,
    receipt=None,
    plan_only=False,
):
    """Run a packaged lifecycle helper using one host file and project root."""
    if not config_path:
        raise StudioError("Blender MCP lifecycle requires --config")
    host_path = Path(config_path).resolve()
    if not host_path.is_file():
        raise StudioError("Blender MCP lifecycle host config is missing")
    project = Path(project).resolve()
    if not project.is_dir():
        raise StudioError("Blender MCP lifecycle project root is missing")
    try:
        mcp = config["blender_mcp"]
    except KeyError as exc:
        raise StudioError("Host config has no blender_mcp lifecycle block") from exc

    common = [
        "-WorkingRoot",
        mcp["working_root"],
        "-OwnerIdentity",
        mcp["owner"],
    ]
    if operation == "contracts":
        return _run("Test-LifecycleContracts.ps1", [], json_output=False)
    if operation == "ensure":
        if not source or not session:
            raise StudioError("Blender MCP ensure requires --source and --session")
        arguments = [
            "-SourceScene",
            relative(project, source),
            "-SessionId",
            session,
            *common,
            "-BlenderExe",
            mcp["blender_executable"],
            "-ProbePython",
            mcp["probe_python"],
            "-McpServerConfig",
            host_path,
        ]
        if plan_only:
            arguments.append("-PlanOnly")
        return _run("Ensure-SupervisedBlenderMCP.ps1", arguments)
    if operation == "status":
        arguments = [
            *common,
            "-ProbePython",
            mcp["probe_python"],
            "-McpServerConfig",
            host_path,
        ]
        if receipt:
            arguments.extend(("-OwnershipReceipt", Path(receipt).resolve()))
        return _run("Test-SupervisedBlenderMCP.ps1", arguments)
    if operation == "stop":
        if not receipt:
            raise StudioError("Blender MCP stop requires --receipt")
        return _run(
            "Stop-SupervisedBlenderMCP.ps1",
            ["-OwnershipReceipt", Path(receipt).resolve(), *common],
        )
    raise StudioError("Unknown Blender MCP lifecycle operation")
