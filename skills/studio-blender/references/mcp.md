# Optional Blender MCP connection

The core background adapter needs no MCP. Optional upstream: `ahujasid/blender-mcp`, revision `c5f35d9cc54451d785ac4c00c48bf9e98a2e8db9`, project version `1.9.1`, MIT. [Pinned source](https://github.com/ahujasid/blender-mcp/tree/c5f35d9cc54451d785ac4c00c48bf9e98a2e8db9) and [retained license](../../../third_party/blender-mcp/LICENSE). No server/addon code is vendored; this studio-authored connection recipe is based on the inspected README, addon preferences and server/telemetry source.

When this route is chosen and setup is authorized, obtain **both addon and server from that exact revision**, install the server in a host-owned virtual environment, and install the matching `addon.py` in the intended Blender profile. Do not automatically fetch upstream main, enable addons globally, or operate an already open project. Keep a host record of exact revision, addon/server paths and actual versions. Dependencies are declared in the pinned upstream pyproject; review/license them during optional installation.

Configure the host's MCP entry to the already installed server executable, with these environment values:

```json
{
  "BLENDER_HOST": "127.0.0.1",
  "BLENDER_PORT": "9876",
  "DISABLE_TELEMETRY": "true",
  "BLENDER_MCP_DISABLE_TELEMETRY": "true"
}
```

Use the virtual environment's `blender-mcp` executable as the MCP command (Windows normally `Scripts/blender-mcp.exe`, Linux `bin/blender-mcp`). Do not supply a network-installing command in the normal production connection. On the intended addon instance also uncheck **Allow Telemetry** before connecting; it defaults on upstream. Confirm the addon/server connection remains local, and no other operator owns that port. The studio does not start competing bridges.

After setup, inspect scene identity and the connection's reported telemetry consent before permitting code execution. Save the editable source before a mutation. Use only project-scoped operations within the work card; optional upstream cloud-generation integrations do not inherit authorization. Close only the owned connection/process when done, leaving user-open Blender files and other tools intact.

MCP pairing/interactive operation remains unverified in this package's compatibility matrix. If addon/server installation or native access is unavailable, use the fully independent [background Blender route](../SKILL.md).
