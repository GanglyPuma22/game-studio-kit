"""No implicit credential files or shell profiles."""

from pathlib import Path, PureWindowsPath
import os
import re
import shutil
from .common import StudioError, read_json

DEFAULTS = {
    "executables": {},
    "credentials": {"meshy": "MESHY_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY", "fish": "FISH_AUDIO_API_KEY", "gemini": "GEMINI_API_KEY"},
    "timeout": 180,
    "path_mappings": [],
}

BLENDER_MCP_REQUIRED = {
    "working_root",
    "blender_executable",
    "probe_python",
    "owner",
    "server",
}


def _is_absolute_lifecycle_path(value):
    # The supervised lifecycle only runs on native Windows, so a value is
    # only ever resolved there: a drive-qualified path (`C:\...`, drive AND
    # root; `C:foo` is drive-relative and must be rejected) or a UNC path
    # (`\\server\share\...`). `Path(...).is_absolute()` is host-dependent —
    # it would also accept a drive-less POSIX-style root such as `/runs`,
    # which this Windows-only lifecycle cannot use — so check the Windows
    # form explicitly regardless of which host runs this validator.
    return PureWindowsPath(value).is_absolute()


def _kit_root():
    return Path(__file__).resolve().parents[1]


def _working_root_is_outside_kit(working_root_value, kit_root_path):
    working_root_concrete = Path(working_root_value)
    if working_root_concrete.exists():
        # An already-existing working_root can be a symlink/junction whose
        # real target lies inside the installed kit; the lexical
        # PureWindowsPath comparison below cannot see that, since it never
        # touches the filesystem. Path.resolve() follows reparse points on
        # this host, so prefer it whenever the directory is real. A
        # not-yet-created directory has nothing to resolve yet, so fall
        # through to the lexical, host-independent comparison.
        resolved_working_root = working_root_concrete.resolve()
        resolved_kit_root = kit_root_path.resolve()
        return not (
            resolved_working_root == resolved_kit_root
            or resolved_working_root.is_relative_to(resolved_kit_root)
        )
    kit_root = PureWindowsPath(str(kit_root_path))
    working_root = PureWindowsPath(working_root_value)
    return not (working_root == kit_root or working_root.is_relative_to(kit_root))


def _validate_blender_mcp(block):
    if not isinstance(block, dict):
        raise StudioError("blender_mcp must be an object")
    missing = BLENDER_MCP_REQUIRED - block.keys()
    if missing:
        raise StudioError("blender_mcp is missing: " + ", ".join(sorted(missing)))
    for key in BLENDER_MCP_REQUIRED - {"server"}:
        if not isinstance(block[key], str) or not block[key].strip():
            raise StudioError(f"blender_mcp.{key} must be a non-empty string")
    for key in ("working_root", "blender_executable", "probe_python"):
        if not _is_absolute_lifecycle_path(block[key]):
            raise StudioError(f"blender_mcp.{key} must be absolute")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", block["owner"]):
        raise StudioError(
            "blender_mcp.owner must use 1-128 letters, digits, dots, "
            "underscores, or hyphens"
        )
    server = block["server"]
    if (
        not isinstance(server, dict)
        or not isinstance(server.get("command"), str)
        or not server["command"].strip()
    ):
        raise StudioError("blender_mcp.server.command must be explicit")
    if not _is_absolute_lifecycle_path(server["command"]):
        raise StudioError("blender_mcp.server.command must be absolute")
    if not isinstance(server.get("args", []), list) or not all(
        isinstance(item, str) for item in server.get("args", [])
    ):
        raise StudioError("blender_mcp.server.args must be a string array")
    env = server.get("env")
    required_env = {
        "BLENDER_HOST": "127.0.0.1",
        "BLENDER_PORT": "9876",
        "DISABLE_TELEMETRY": "true",
        "BLENDER_MCP_DISABLE_TELEMETRY": "true",
    }
    if (
        not isinstance(env, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in env.items()
        )
        or any(env.get(k) != v for k, v in required_env.items())
    ):
        raise StudioError(
            "blender_mcp.server.env must select loopback port 9876 with "
            "telemetry disabled"
        )
    if not _working_root_is_outside_kit(block["working_root"], _kit_root()):
        raise StudioError("blender_mcp.working_root must be outside the installed kit")


def load(path=None, overrides=None):
    config = {
        **DEFAULTS,
        "executables": {},
        "credentials": dict(DEFAULTS["credentials"]),
    }
    # Host config is explicit, or named by STUDIO_CONFIG, never searched in a home directory.
    path = path or os.environ.get("STUDIO_CONFIG")
    for update in [read_json(path) if path else {}, overrides or {}]:
        if not isinstance(update, dict):
            raise StudioError("Host configuration must be a JSON object")
        for key, value in update.items():
            if key in {"executables", "credentials"}:
                if not isinstance(value, dict):
                    raise StudioError(f"{key} must be an object")
                config[key].update(value)
            else:
                config[key] = value
    if (
        not isinstance(config["timeout"], (int, float))
        or not 0 < config["timeout"] <= 3600
    ):
        raise StudioError("timeout must be 1–3600 seconds")
    if "blender_mcp" in config:
        _validate_blender_mcp(config["blender_mcp"])
    return config


def executable(config, name):
    explicit = config["executables"].get(name)
    if explicit:
        found = shutil.which(explicit)
        if found:
            return str(Path(found).resolve())
        return None  # An invalid explicit override must not silently use another executable.
    for candidate in {
        "godot": ["godot", "godot4", "godot.exe"],
        "blender": ["blender", "blender.exe"],
    }.get(name, [name]):
        found = shutil.which(candidate)
        if found:
            return str(Path(found).resolve())
    return None


def require_executable(config, name):
    found = executable(config, name)
    if not found:
        raise StudioError(
            f"{name} needs setup: install it and set executables.{name} in the host config"
        )
    return found


def app_path(config, path, tool=None):
    resolved = str(Path(path).resolve())
    if tool and not str(executable(config, tool) or "").lower().endswith(".exe"):
        return resolved
    # WSL interop is opt-in. Longest mapping wins; no guessed /mnt/c translation.
    for mapping in sorted(
        config.get("path_mappings", []), key=lambda m: len(m["from"]), reverse=True
    ):
        source = mapping["from"].rstrip("/\\")
        if resolved == source or resolved.startswith(source + os.sep):
            return mapping["to"].rstrip("/\\") + resolved[len(source) :].replace(
                "/", "\\"
            )
    return resolved


def credential(config, provider):
    name = config["credentials"].get(provider)
    if not name or not os.environ.get(name):
        raise StudioError(
            f"{provider} needs setup: set the configured credential environment variable"
        )
    return os.environ[name]
