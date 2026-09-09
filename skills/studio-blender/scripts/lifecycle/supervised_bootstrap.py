"""Start Blender MCP inside a task-owned visible Blender process."""

import addon_utils
import bpy
import json
import os
import sys
import traceback
from pathlib import Path


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) != 4:
        raise RuntimeError(
            "Expected: <bootstrap-receipt> <working-scene> <source-sha256> <owner>"
        )
    receipt_path = Path(args[0])
    expected_scene = Path(args[1]).resolve()
    source_sha256 = args[2].lower()
    owner = args[3]

    try:
        if bpy.app.background:
            raise RuntimeError("Supervised lifecycle requires visible Blender")
        actual_scene = Path(bpy.data.filepath).resolve()
        if os.path.normcase(str(actual_scene)) != os.path.normcase(str(expected_scene)):
            raise RuntimeError(f"Unexpected scene: {actual_scene}")

        addon_utils.modules_refresh()
        addon_utils.enable("blender_mcp", default_set=False, persistent=True)
        import blender_mcp

        prefs = bpy.context.preferences.addons["blender_mcp"].preferences
        prefs.telemetry_consent = False
        scene = bpy.context.scene
        scene.blendermcp_auto_start_server = False
        scene["supervised_mcp_owner"] = owner
        scene["supervised_mcp_source_sha256"] = source_sha256
        for integration in (
            "polyhaven",
            "hyper3d",
            "hunyuan3d",
            "sketchfab",
            "polypizza",
        ):
            setattr(scene, f"blendermcp_use_{integration}", False)

        existing = getattr(bpy.types, "blendermcp_server", None)
        if existing:
            existing.stop()
            del bpy.types.blendermcp_server
        server = blender_mcp.BlenderMCPServer(host='127.0.0.1', port=9876)
        bpy.types.blendermcp_server = server
        server.start()
        scene.blendermcp_server_running = server.running
        if not server.running or server.socket.getsockname() != ("127.0.0.1", 9876):
            raise RuntimeError("Blender MCP did not bind the expected loopback listener")

        receipt = {
            "status": "PASS",
            "owner": owner,
            "pid": os.getpid(),
            "blender_version": bpy.app.version_string,
            "binary": bpy.app.binary_path,
            "working_scene": str(actual_scene),
            "source_sha256": source_sha256,
            "addon_path": blender_mcp.__file__,
            "addon_version": list(blender_mcp.bl_info["version"]),
            "protocol_version": blender_mcp.ADDON_PROTOCOL_VERSION,
            "telemetry_consent": prefs.telemetry_consent,
            "listener": list(server.socket.getsockname()),
        }
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print("SUPERVISED_MCP_BOOTSTRAP_PASS", flush=True)
    except Exception:
        receipt_path.write_text(
            json.dumps({"status": "BLOCKED", "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
