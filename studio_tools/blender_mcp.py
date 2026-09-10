"""Policy shared by Blender MCP probes and current-client handoffs."""

import json

from .common import StudioError


EXPECTED_PROTOCOL_VERSION = 5
STALE_CONNECTION_MARKERS = ("WinError 10053", "Connection to Blender lost")


def load_explicit_server_config(path):
    if path is None:
        raise StudioError("An explicit Blender MCP host config path is required")
    try:
        from .config import load

        return load(path=path)["blender_mcp"]["server"]
    except KeyError as exc:
        raise StudioError(
            "Could not load the explicit Blender MCP host config"
        ) from exc


def _status(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StudioError("Blender MCP addon status was not valid JSON") from exc
    if not isinstance(value, dict):
        raise StudioError("Blender MCP addon status must be an object")
    return value


def require_current_native_status(value):
    status = _status(value)
    if status.get("source") != "native":
        raise StudioError("Blender MCP addon status did not come from the native addon")
    if status.get("up_to_date") is not True:
        raise StudioError("Blender MCP addon/server pair is not current")
    if (
        status.get("protocol_version") != EXPECTED_PROTOCOL_VERSION
        or status.get("expected_protocol_version") != EXPECTED_PROTOCOL_VERSION
    ):
        raise StudioError(
            "Blender MCP native protocol 5 compatibility was not verified"
        )
    if status.get("telemetry_consent") is not False:
        raise StudioError("Blender MCP telemetry must be explicitly disabled")
    return status


def is_documented_stale_connection(value):
    status = _status(value)
    warning = status.get("warning")
    return (
        status.get("source") == "error"
        and isinstance(warning, str)
        and any(marker in warning for marker in STALE_CONNECTION_MARKERS)
    )


async def call_current_addon_status(call, *, ensure_passed):
    """Call only addon status, with the one documented post-Ensure recovery."""
    first = await call("get_addon_status", {})
    if ensure_passed and is_documented_stale_connection(first):
        first = await call("get_addon_status", {})
    return require_current_native_status(first)
