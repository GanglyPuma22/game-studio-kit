"""Policy shared by Blender MCP probes and current-client handoffs."""

import json

from .common import StudioError


EXPECTED_PROTOCOL_VERSION = 5
STALE_CONNECTION_MARKERS = ("WinError 10053", "Connection to Blender lost")

# Two layers, never one word. The add-on's socket listener inside the owned
# Blender is what this kit supervises and what `blender-mcp status` measures;
# the connector the app (Codex) holds to that listener is a second, separate
# thing that the kit neither owns nor can restart.
HELPER_STATES = ("PASS", "FAIL")
APP_CLIENT_STATES = ("CONNECTED", "RECONNECT_REQUIRED", "UNKNOWN")
RECONNECT_INSTRUCTION = (
    "Reconnect the Codex connector. The Blender add-on listener is one layer "
    "and the Codex connector is the other: restarting the listener does not "
    "reconnect the connector, and no command in this kit can. Reconnect the "
    "Blender MCP connector from the Codex side, then read status again before "
    "any further call."
)


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


def app_client_state(value):
    """CONNECTED, RECONNECT_REQUIRED or UNKNOWN from one app-client status.

    `RECONNECT_REQUIRED` is claimed only for the one documented shape: an
    `error` status whose warning carries `WinError 10053` or `Connection to
    Blender lost`. Anything else this kit cannot read as current is `UNKNOWN`,
    because telling an operator to reconnect is an instruction, and giving it
    for a status that means something else would send them to the wrong layer.
    """
    try:
        status = _status(value)
    except StudioError:
        return "UNKNOWN"
    if is_documented_stale_connection(status):
        return "RECONNECT_REQUIRED"
    try:
        require_current_native_status(status)
    except StudioError:
        return "UNKNOWN"
    return "CONNECTED"


def connection_report(helper, app_client):
    """The two layers and the one overall word that may never outrank them.

    `overall` is `CONNECTED` only when the supervised helper passed *and* the
    app client is connected. A healthy listener with a dropped connector is a
    game that cannot be edited, and a receipt that called that CONNECTED would
    be describing the half of the route the kit happens to own.
    """
    if helper not in HELPER_STATES:
        raise StudioError("Blender MCP helper state must be PASS or FAIL")
    if app_client not in APP_CLIENT_STATES:
        raise StudioError(
            "Blender MCP app client state must be CONNECTED, RECONNECT_REQUIRED or UNKNOWN"
        )
    if helper == "PASS" and app_client == "CONNECTED":
        overall = "CONNECTED"
    elif app_client == "RECONNECT_REQUIRED":
        overall = "RECONNECT_REQUIRED"
    elif helper == "FAIL":
        overall = "FAIL"
    else:
        overall = "UNKNOWN"
    report = {"helper": helper, "app_client": app_client, "overall": overall}
    if app_client == "RECONNECT_REQUIRED":
        report["instruction"] = RECONNECT_INSTRUCTION
    return report


async def current_connection(call, *, ensure_passed, helper):
    """Read the app client's own status once, with the one documented retry.

    Exactly one retry, only for the documented stale shape and only after a
    successful Ensure. A transport exception propagates untouched: a call that
    never reached the add-on has nothing to re-read, and retrying it would be
    this kit deciding a failure was transient on the app's behalf.
    """
    first = await call("get_addon_status", {})
    state = app_client_state(first)
    if state == "RECONNECT_REQUIRED" and ensure_passed:
        state = app_client_state(await call("get_addon_status", {}))
    return connection_report(helper, state)
