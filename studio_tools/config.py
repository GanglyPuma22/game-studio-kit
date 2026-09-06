"""No implicit credential files or shell profiles."""

from pathlib import Path
import os
import shutil
from .common import StudioError, read_json

DEFAULTS = {
    "executables": {},
    "credentials": {"meshy": "MESHY_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY", "fish": "FISH_AUDIO_API_KEY", "gemini": "GEMINI_API_KEY"},
    "timeout": 180,
    "path_mappings": [],
}


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
