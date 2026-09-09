# Optional native Windows Blender MCP lifecycle

The core background adapter needs no MCP. Optional upstream: `ahujasid/blender-mcp`, revision `c5f35d9cc54451d785ac4c00c48bf9e98a2e8db9`, project version `1.9.1`, MIT. [Pinned source](https://github.com/ahujasid/blender-mcp/tree/c5f35d9cc54451d785ac4c00c48bf9e98a2e8db9) and [retained license](../../../third_party/blender-mcp/LICENSE). No server/addon code is vendored; this studio-authored connection recipe is based on the inspected README, addon preferences and server/telemetry source.

When this route is chosen and setup is authorized, obtain **both addon and server from that exact revision**, install the server in a host-owned virtual environment, and install the matching `addon.py` in the intended Blender profile under the module filename `blender_mcp.py`. The pinned upstream `install-addon` command performs this rename; a manual installation must do it explicitly because the packaged bootstrap enables the `blender_mcp` module. Do not automatically fetch upstream main, enable addons globally, or operate an already open project. Keep a host record of exact revision, addon/server paths and actual versions. Dependencies are declared in the pinned upstream pyproject; review/license them during optional installation. The packaged lifecycle supervises an existing compatible installation; it is not an installer.

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

`Ensure` verifies its own newly launched MCP subprocess and returns an ownership receipt. That does **not** prove the app's already-running MCP client has reconnected. Before any mutation, use the current app client to call `get_addon_status`, require `source=native`, `up_to_date=true`, `protocol_version=expected_protocol_version=5`, and `telemetry_consent=false`; then call `get_scene_info` and verify the working scene returned by `Ensure`. Verify PID, file path and owner with a read-only `execute_blender_code` identity check when the client exposes it.

After a successful `Ensure`, if and only if the current client's first read-only `get_addon_status` returns `source=error` and its warning contains `WinError 10053` or `Connection to Blender lost`, repeat `get_addon_status` exactly once. Apply the full native/protocol/telemetry checks to that result. Do not retry transport exceptions, other errors, scene checks, code execution, or any mutation. A failed second status blocks work.

Save checkpoints deliberately and use only project-scoped operations within the work card; optional upstream cloud-generation integrations do not inherit authorization. When finished, close only the receipt-bound process:

```powershell
python "$Kit\scripts\studio.py" blender-mcp stop --project $Game --receipt $Ensure.ownership_receipt --config $HostConfig
```

If graceful close reports `NEEDS_USER_CLOSE`, preserve the receipt and close the visible prompt manually. Never kill by process name and never stop the app-owned MCP subprocess.

Before adopting this route on a host, run the [native Windows qualification card](windows-lifecycle-qualification.md). The migrated source and validation boundary are recorded in [lifecycle provenance](lifecycle-provenance.md). If addon/server installation or native access is unavailable, use the fully independent [background Blender route](../SKILL.md).
