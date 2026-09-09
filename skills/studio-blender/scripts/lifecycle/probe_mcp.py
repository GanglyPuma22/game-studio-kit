"""Run a real MCP protocol health check against the registered Blender server."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[4]
sys.dont_write_bytecode = True
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from studio_tools.blender_mcp import (
    load_explicit_server_config,
    require_current_native_status,
)

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROMPT = "Verify the task-owned Blender MCP lifecycle before supervised work."


def text_content(result) -> str:
    return "\n".join(item.text for item in result.content if item.type == "text")


async def run_probe(args) -> None:
    evidence = Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    config = load_explicit_server_config(args.server_config)
    receipt = {
        "status": "IN_PROGRESS",
        "client_pid": os.getpid(),
        "server_command": config["command"],
        "expected_pid": args.expected_pid,
        "expected_scene": str(Path(args.expected_scene).resolve()),
        "calls": [],
    }
    receipt_path = evidence / "probe-result.json"

    def save() -> None:
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    async def call(session, name, parameters, label):
        result = await session.call_tool(name, {"user_prompt": PROMPT, **parameters})
        record = {"tool": name, "label": label, "isError": result.isError, "content": []}
        for item in result.content:
            if item.type == "image":
                data = base64.b64decode(item.data)
                image_path = evidence / f"{label}.png"
                image_path.write_bytes(data)
                record["content"].append(
                    {
                        "type": "image",
                        "path": str(image_path),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                        "mimeType": item.mimeType,
                    }
                )
            else:
                record["content"].append(item.model_dump(mode="json"))
        receipt["calls"].append(record)
        save()
        output = text_content(result)
        if result.isError or output.startswith(("Error ", "Error:", "Rejected by safe mode")):
            raise RuntimeError(f"{label} failed: {output}")
        return output

    save()
    try:
        with (evidence / "server.stderr.log").open("w", encoding="utf-8") as error_log:
            parameters = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env", {}),
            )
            async with stdio_client(parameters, errlog=error_log) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=75)
                ) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    receipt["tools"] = [tool.name for tool in tools.tools]
                    status_text = await call(session, "get_addon_status", {}, "addon-status")
                    status = require_current_native_status(status_text)
                    await call(session, "get_scene_info", {}, "scene-info")
                    identity_code = (
                        "import bpy, json, os\n"
                        f"assert os.getpid() == {args.expected_pid}\n"
                        f"assert bpy.data.filepath == {str(Path(args.expected_scene).resolve())!r}\n"
                        f"assert bpy.context.scene.get('supervised_mcp_owner') == {args.owner!r}\n"
                        "print(json.dumps({'pid': os.getpid(), 'filepath': bpy.data.filepath}))"
                    )
                    await call(
                        session,
                        "execute_blender_code",
                        {"code": identity_code},
                        "process-scene-identity",
                    )
                    await call(
                        session,
                        "get_viewport_screenshot",
                        {"max_size": 1000},
                        "viewport",
                    )
        viewport = evidence / "viewport.png"
        if not viewport.is_file() or viewport.stat().st_size < 10_000:
            raise RuntimeError("Viewport evidence is missing or implausibly small")
        receipt["status"] = "PASS"
    except Exception as exc:
        receipt["status"] = "BLOCKED"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-config", required=True)
    parser.add_argument("--expected-pid", type=int, required=True)
    parser.add_argument("--expected-scene", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--evidence", required=True)
    asyncio.run(run_probe(parser.parse_args()))


if __name__ == "__main__":
    main()
