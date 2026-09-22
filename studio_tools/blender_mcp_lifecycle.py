"""Thin entrypoint for the packaged native Windows lifecycle scripts."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .blender_mcp import connection_report
from .common import StudioError, outside_package, relative
from .config import blender_mcp_port


LIFECYCLE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "studio-blender"
    / "scripts"
    / "lifecycle"
)

# A successful `ensure` has two bounded phases, not one. First the script waits
# up to its own `-StartupTimeoutSeconds` (60) for Blender to write the
# bootstrap receipt; only then does it run the initial protocol probe, whose
# MCP client session reads with a 75-second timeout (`probe_mcp.py`). 60 + 75
# is 135 seconds of work this kit has already authorized, so the bound is 180:
# both phases plus 45 seconds for the working-copy hash, the listener
# assertions, the receipts and process startup. A PowerShell parent still
# running after that has not been slow; it has stopped returning, which is the
# failure this bound exists to name.
STARTUP_TIMEOUT_SECONDS = 60
PROBE_READ_TIMEOUT_SECONDS = 75
RUN_TIMEOUT_SECONDS = 180
DID_NOT_RETURN = "ensure_did_not_return"
# How far before the call a run directory's timestamp may sit and still be
# read as this call's. Filesystems round timestamps -- whole seconds on some
# of them -- so a directory created immediately after the Popen can carry an
# mtime a moment earlier. The endpoint-wide lifecycle mutex is what keeps this
# from reaching a different session's run: no second Ensure can be inside its
# own startup while this one holds the lock.
RUN_DIRECTORY_CLOCK_SLACK_SECONDS = 2


def _powershell():
    for name in ("pwsh", "powershell"):
        executable = shutil.which(name)
        if executable:
            return executable
    raise StudioError("Blender MCP lifecycle needs PowerShell (pwsh or powershell)")


def _command(script, arguments):
    """The argument list that runs one packaged lifecycle script."""
    return [
        _powershell(),
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(LIFECYCLE_ROOT / script),
        *map(str, arguments),
    ]


def _run_directory(working_root, operation):
    """One directory per call, named by operation and UTC stamp.

    The streams of a lifecycle call belong beside the run they describe, under
    the host's own external working root — never in the installed kit and never
    in a pipe the launched Blender can inherit and hold open.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(working_root) / "lifecycle" / f"{operation}-{stamp}-{uuid.uuid4().hex[:8]}"
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise StudioError(
            "Blender MCP lifecycle could not create a run directory under the "
            "configured working root"
        ) from exc
    return directory


def _run(script, arguments, *, working_root, operation, json_output=True):
    """Run one lifecycle script with file-backed streams and a bounded wait.

    `subprocess.run(capture_output=True)` hands PowerShell a pipe. The Blender
    the script starts inherits that pipe's write handle and keeps it open for
    as long as the GUI is open, so the read never reaches end-of-file: `ensure`
    returned only when the human closed Blender, however healthy the receipt
    and the health probe already were. Redirecting both streams to files in the
    run's own directory removes the pipe entirely, and the JSON is read back
    from the file once the parent has exited.
    """
    run_directory = _run_directory(working_root, operation)
    stdout_path = run_directory / "powershell.stdout.json"
    stderr_path = run_directory / "powershell.stderr.log"
    command = _command(script, arguments)
    started = time.time()
    try:
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
            try:
                returncode = process.wait(timeout=RUN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # Looked for before the parent is stopped, so the receipt is
                # read while the script that wrote it is still the thing that
                # last touched the directory.
                owned = _owned_receipt(working_root, started)
                # Only the PowerShell parent is stopped. A Blender the receipt
                # already owns is left exactly as it is: it is closed through
                # its own receipt, never by killing whatever is still running.
                process.kill()
                process.wait()
                return _did_not_return(run_directory, operation, owned)
    except OSError as exc:
        raise StudioError("Could not start PowerShell for Blender MCP lifecycle") from exc
    text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
    if returncode:
        raise StudioError(
            "Blender MCP lifecycle failed; inspect its receipt under the configured working root"
        )
    if not json_output:
        return {"ok": True, "summary": text}
    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise StudioError("Blender MCP lifecycle returned invalid JSON") from exc


def _owned_receipt(working_root, started):
    """The ownership receipt this timed-out call had already written, if any.

    A timeout that names no receipt leaves an operator with a Blender on the
    desktop and no supported way to close it: `blender-mcp stop` is
    receipt-bound by design, and the alternative is killing by process name,
    which this lifecycle exists to refuse. `Ensure` writes `ownership.json`
    into a new directory under `<working_root>/runs/` as soon as the process
    exists, so the newest such directory belonging to this call is the handle.
    Returns (receipt path, directory leaf) or (None, None).
    """
    runs = Path(working_root) / "runs"
    newest = None
    try:
        candidates = list(runs.iterdir())
    except OSError:
        return None, None
    for directory in candidates:
        receipt = directory / "ownership.json"
        try:
            if not directory.is_dir() or not receipt.is_file():
                continue
            stamp = directory.stat().st_mtime
        except OSError:
            continue
        if stamp < started - RUN_DIRECTORY_CLOCK_SLACK_SECONDS:
            # Older than this call: somebody else's session, or a run this
            # call never made. Naming it would hand out a stop handle for a
            # process this timeout knows nothing about.
            continue
        if newest is None or stamp > newest[0]:
            newest = (stamp, receipt, directory.name)
    if newest is None:
        return None, None
    return str(newest[1].resolve()), newest[2]


def _did_not_return(run_directory, operation, owned=(None, None)):
    """The terminal receipt for a PowerShell parent that outlived its bound.

    Written beside the streams it describes and returned to the caller. It
    carries the lifecycle run's own directory name rather than a host path,
    with one exception: the ownership receipt of a Blender this call started
    is an absolute path, because it is the argument `blender-mcp stop
    --receipt` has to be given and a name alone could not be passed to it.
    """
    ownership_receipt, owned_directory = owned
    receipt = {
        "schema_version": 1,
        "kind": "blender-mcp-lifecycle-timeout",
        "status": DID_NOT_RETURN,
        "operation": operation,
        "ok": False,
        "run": run_directory.name,
        "timeout_seconds": RUN_TIMEOUT_SECONDS,
        # Nothing this call started was stopped except the PowerShell parent.
        "owned_process_action": "none",
        # The handle for closing what it did start, or null when it had not
        # got as far as owning a process.
        "ownership_receipt": ownership_receipt,
        "run_directory": owned_directory,
        "failure": (
            "The lifecycle PowerShell process did not return within "
            f"{RUN_TIMEOUT_SECONDS} seconds and was stopped. Any Blender an "
            "ownership receipt already names was left running; close it through "
            "that receipt with `blender-mcp stop --receipt`."
            if ownership_receipt is None else
            "The lifecycle PowerShell process did not return within "
            f"{RUN_TIMEOUT_SECONDS} seconds and was stopped. The Blender it had "
            "already started was left running; close it with `blender-mcp stop "
            "--receipt <ownership_receipt>` using the path in this record."
        ),
    }
    (run_directory / "lifecycle-timeout.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


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
    probe=False,
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
    # Resolved once, here, and handed to every script as an explicit argument:
    # no packaged script may decide for itself which port this host listens on.
    port = blender_mcp_port(mcp)
    working_root = mcp["working_root"]

    common = [
        "-WorkingRoot",
        working_root,
        "-OwnerIdentity",
        mcp["owner"],
        "-Port",
        port,
    ]
    if operation == "contracts":
        return _run(
            "Test-LifecycleContracts.ps1", [],
            working_root=working_root, operation=operation, json_output=False,
        )
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
        if probe:
            arguments.append("-Probe")
        return _run(
            "Ensure-SupervisedBlenderMCP.ps1", arguments,
            working_root=working_root, operation=operation,
        )
    if operation == "status":
        arguments = [
            *common,
            "-ProbePython",
            mcp["probe_python"],
            "-McpServerConfig",
            host_path,
        ]
        if receipt:
            arguments.extend(
                ("-OwnershipReceipt", outside_package(receipt, "Blender MCP receipt"))
            )
        # A full protocol probe opens a second MCP bridge that can contend
        # with an already-connected app client for the add-on's single
        # active connection; default to the lightweight, non-probing check
        # and only pay for the round-trip when --probe is explicitly asked
        # for (which requires no connected app client).
        if not probe:
            arguments.append("-SkipProtocolProbe")
        result = _run(
            "Test-SupervisedBlenderMCP.ps1", arguments,
            working_root=working_root, operation=operation,
        )
        return _with_connection_state(result)
    if operation == "stop":
        if not receipt:
            raise StudioError("Blender MCP stop requires --receipt")
        return _run(
            "Stop-SupervisedBlenderMCP.ps1",
            [
                "-OwnershipReceipt",
                outside_package(receipt, "Blender MCP receipt"),
                *common,
            ],
            working_root=working_root, operation=operation,
        )
    raise StudioError("Unknown Blender MCP lifecycle operation")


def _with_connection_state(result):
    """Report the helper and the app client as the two separate layers they are.

    The packaged health check speaks to the listener the kit itself supervises.
    It cannot see the connector the app holds, and a probe that opened its own
    bridge would be a third party rather than that connector, so the app-client
    layer is reported `UNKNOWN` here rather than promoted to the helper's word.
    """
    if not isinstance(result, dict):
        return result
    helper = "PASS" if result.get("status") == "PASS" else "FAIL"
    return {**result, **connection_report(helper, "UNKNOWN")}
