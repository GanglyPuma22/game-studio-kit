# Optional native Windows Blender MCP lifecycle

The core background adapter needs no MCP. Optional upstream: `ahujasid/blender-mcp`, revision `c5f35d9cc54451d785ac4c00c48bf9e98a2e8db9`, project version `1.9.1`, MIT. [Pinned source](https://github.com/ahujasid/blender-mcp/tree/c5f35d9cc54451d785ac4c00c48bf9e98a2e8db9) and [retained license](../../../third_party/blender-mcp/LICENSE). No server/addon code is vendored; this studio-authored connection recipe is based on the inspected README, addon preferences and server/telemetry source.

When this route is chosen and setup is authorized, obtain **both addon and server from that exact revision**, install the server in a host-owned virtual environment, and install the matching `addon.py` in the intended Blender profile. The pinned upstream `install-addon` command renames the file to `blender_mcp.py` (module id `blender_mcp`); installing the file under its literal upstream name registers it under module id `addon` instead. The packaged bootstrap accepts either: it tries, in order, the module names `blender_mcp` then `addon`, and before enabling a candidate it validates that module's own `bl_info` against the pinned add-on — `name = "MCP for Blender"`, `version = (1, 6)` (the add-on's own `bl_info` version; distinct from the upstream project version `1.9.1` pinned above, which is the pyproject/packaging version). A candidate whose `bl_info` does not match is skipped rather than enabled. If neither module name is present with matching metadata, the bootstrap fails with an explicit message naming every module id it checked and what it found there. Do not automatically fetch upstream main, enable addons globally, or operate an already open project. Keep a host record of exact revision, addon/server paths and actual versions. Dependencies are declared in the pinned upstream pyproject; review/license them during optional installation. The packaged lifecycle supervises an existing compatible installation; it is not an installer.

Add one `blender_mcp` block to the same explicit host JSON used by `doctor`. Keep the file and `working_root` outside KIT so an installed plugin cache remains immutable:

```json
"blender_mcp": {
  "working_root": "C:\\Studio Host\\blender-mcp-runs",
  "blender_executable": "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe",
  "probe_python": "C:\\Studio Host\\blender-mcp-1.9.1\\Scripts\\python.exe",
  "owner": "game-studio-kit-blender-mcp-v1",
  "server": {
    "command": "C:\\Studio Host\\blender-mcp-1.9.1\\Scripts\\blender-mcp.exe",
    "args": [],
    "env": {
      "BLENDER_HOST": "127.0.0.1",
      "BLENDER_PORT": "9876",
      "DISABLE_TELEMETRY": "true",
      "BLENDER_MCP_DISABLE_TELEMETRY": "true"
    }
  }
}
```

`BLENDER_PORT` is a host fact, not a constant. Any integer 1024–65535 is accepted and 9876 is only the default; `BLENDER_HOST` must still be exactly `127.0.0.1`. Set it to something outside the host's reserved ranges when the default is unavailable — a Windows box that has handed 9806–9905 to Hyper-V or WinNAT cannot bind 9876 at all, and `netsh int ipv4 show excludedportrange protocol=tcp` is what says so. The kit resolves the port once from this file and passes it to every packaged script explicitly; the listener checks, the add-on bootstrap and the ownership receipt's `listener` and `port` all use that one value. The lifecycle lock does not: `Global\GameStudioKit-BlenderMCP` is deliberately host-wide and portless, because this lifecycle supervises one session per host and refuses to run beside a second Blender at all. An excluded or occupied port is refused before any Blender starts, naming `port_excluded` or `port_occupied`, and a `stop` or a reuse whose receipt names a different port is refused rather than applied to whatever happens to be listening.

Point the app's MCP registration at that same `server` object. Do not supply a network-installing command in the normal production connection. On the intended addon instance also uncheck **Allow Telemetry** before connecting; it defaults on upstream. Confirm the addon/server connection remains local, and no other operator owns that port. The studio refuses competing Blender processes or bridges rather than adopting them.

## Owned session

Use PowerShell and values from the single host file. `Ensure` copies the source to a new external run directory; edit only the returned `working_scene`.

```powershell
$Kit = "C:\Tools\game-studio-kit"
$Game = "C:\Projects\Game"
$HostConfig = "C:\Studio Host\host.json"
$Session = "agent-task-unique-id"
$Ensure = python "$Kit\scripts\studio.py" blender-mcp ensure --project $Game --source "source/asset.blend" --session $Session --config $HostConfig | ConvertFrom-Json
```

`Ensure` returns while the Blender it started stays open. It is invoked only through `studio blender-mcp ensure`, which redirects PowerShell's own stdout and stderr to files under the configured working root and waits a bounded **180 seconds**: the script's own 60-second startup window for the bootstrap receipt, plus the 75-second read timeout of the initial protocol probe that follows it, plus 45 seconds for the working-copy hash, the listener assertions, the receipts and process startup. A captured *pipe* would be inherited by the launched Blender and never reach end-of-file until the GUI was closed, so `Ensure` refuses to launch at all when either of its own standard handles is a pipe, with `ensure_stdio_is_pipe`. Only a pipe is refused: the handle type comes from `GetStdHandle`/`GetFileType`, so a file, a console nobody is reading, and a process with no standard handle at all are all fine to inherit. A parent that outlives the bound is stopped and the call returns `status: ensure_did_not_return`; a Blender an ownership receipt already names is left running and is closed only through that receipt.

`Ensure` verifies its own newly launched MCP subprocess and returns an ownership receipt. That does **not** prove the app's already-running MCP client has reconnected. Before any mutation, use the current app client to call `get_addon_status`, require `source=native`, `up_to_date=true`, `protocol_version=expected_protocol_version=5`, and `telemetry_consent=false`; then call `get_scene_info` and verify the working scene returned by `Ensure`. Verify PID, file path and owner with a read-only `execute_blender_code` identity check when the client exposes it.

There are two layers here and they are never one answer. The **helper** is the add-on's socket listener inside the owned Blender: that is what this kit supervises, starts, health-checks and stops. The **app client** is the Codex connector that speaks to that listener: this kit neither owns it nor can restart it. `blender-mcp status` says both, separately — `helper: PASS|FAIL`, `app_client: CONNECTED|RECONNECT_REQUIRED|UNKNOWN`, and an `overall` that is never `CONNECTED` unless both are. The packaged status reports `app_client: UNKNOWN`, because a probe it opened itself would be a third party rather than the connector the work will run through; only the current app client's own `get_addon_status` can move it to `CONNECTED`. After a listener restart the connector must be reconnected from the Codex side before any further call, and `RECONNECT_REQUIRED` carries exactly that instruction, because no command in this kit performs it.

After a successful `Ensure`, if and only if the current client's first read-only `get_addon_status` returns `source=error` and its warning contains `WinError 10053` or `Connection to Blender lost`, repeat `get_addon_status` exactly once. Apply the full native/protocol/telemetry checks to that result. Do not retry transport exceptions, other errors, scene checks, code execution, or any mutation. A failed second status blocks work.

Save checkpoints deliberately and use only project-scoped operations within the work card; optional upstream cloud-generation integrations do not inherit authorization. When finished, close only the receipt-bound process:

```powershell
python "$Kit\scripts\studio.py" blender-mcp stop --project $Game --receipt $Ensure.ownership_receipt --config $HostConfig
```

If graceful close reports `NEEDS_USER_CLOSE`, preserve the receipt and close the visible prompt manually. Never kill by process name and never stop the app-owned MCP subprocess.

Before adopting this route on a host, run the [native Windows qualification card](windows-lifecycle-qualification.md). The migrated source and validation boundary are recorded in [lifecycle provenance](lifecycle-provenance.md). If addon/server installation or native access is unavailable, use the fully independent [background Blender route](../SKILL.md).
