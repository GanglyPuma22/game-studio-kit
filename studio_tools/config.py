"""No implicit credential files or shell profiles: only declared ones."""

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
    "credential_files": [],
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


DEFAULT_BLENDER_MCP_PORT = 9876
# Below 1024 is the privileged range Windows reserves for services, and 65535
# is the last TCP port; a supervised loopback listener lives strictly between.
MIN_BLENDER_MCP_PORT = 1024
MAX_BLENDER_MCP_PORT = 65535


def blender_mcp_port(block):
    """The TCP port this host's supervised Blender MCP listener binds.

    Declared as a string in `server.env.BLENDER_PORT`, because that is what the
    upstream server reads from its environment; absent means the historical
    default. A value that is not a plain decimal integer in range is refused
    here rather than forwarded to a PowerShell script that would bind whatever
    `[int]` made of it.
    """
    env = (block.get("server") or {}).get("env") or {}
    raw = env.get("BLENDER_PORT")
    if raw is None:
        return DEFAULT_BLENDER_MCP_PORT
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,5}", raw.strip()):
        raise StudioError(
            "blender_mcp.server.env.BLENDER_PORT must be a decimal port number "
            f"between {MIN_BLENDER_MCP_PORT} and {MAX_BLENDER_MCP_PORT}"
        )
    port = int(raw.strip())
    if not MIN_BLENDER_MCP_PORT <= port <= MAX_BLENDER_MCP_PORT:
        raise StudioError(
            "blender_mcp.server.env.BLENDER_PORT must be a decimal port number "
            f"between {MIN_BLENDER_MCP_PORT} and {MAX_BLENDER_MCP_PORT}"
        )
    return port


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
    # The host, not the port, is the safety property: the add-on must listen on
    # loopback and telemetry must be off. The port itself is a host fact — a
    # Windows box that reserved 9806-9905 for Hyper-V cannot bind the historical
    # 9876 at all, and hard-coding it blocked every live session on such a host.
    required_env = {
        "BLENDER_HOST": "127.0.0.1",
        "DISABLE_TELEMETRY": "true",
        "BLENDER_MCP_DISABLE_TELEMETRY": "true",
    }
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise StudioError("blender_mcp.server.env must be a string-to-string object")
    for key, value in required_env.items():
        if env.get(key) != value:
            raise StudioError(
                "blender_mcp.server.env must bind the loopback host 127.0.0.1 with "
                f"telemetry disabled; {key} is not {value!r}"
            )
    blender_mcp_port(block)
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
    files = config["credential_files"]
    if not isinstance(files, list) or not all(
        isinstance(item, str) and item.strip() for item in files
    ):
        raise StudioError("credential_files must be a list of host file paths")
    config["credential_files"] = _resolve_credential_files(files, path)
    if "blender_mcp" in config:
        _validate_blender_mcp(config["blender_mcp"])
    return config


def _resolve_credential_files(files, config_path):
    """Anchor relative entries to the host config file, never to the caller's CWD.

    A host config is a file an agent passes from wherever it happens to be
    standing, so a relative entry that resolved against the current directory
    would name a different file — usually none at all — for every working
    directory the same config is used from. A drive-qualified or UNC entry is
    left alone even when this host parses POSIX paths, so a Windows config
    read on another host is not turned into nonsense.
    """
    base = Path(config_path).expanduser().resolve().parent if config_path else Path.cwd()
    resolved = []
    for item in files:
        candidate = Path(item).expanduser()
        absolute = candidate.is_absolute() or PureWindowsPath(item).is_absolute()
        resolved.append(item if absolute else str(base / candidate))
    return resolved


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


def _credential_entries(text):
    """Yield every `(name, value)` a credential file body declares.

    One parser, so what `credential` reads and what `doctor` reports can never
    describe two different files.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        yield key.strip(), value


def _credential_file_text(path):
    """The body of one declared credential file, or None when it cannot be read."""
    try:
        # utf-8-sig: a file written by a Windows editor starts with a byte-order
        # mark, and a BOM in front of the first name is part of that name.
        return Path(path).expanduser().read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _credential_file_value(path, name):
    """Read `name` out of one declared `KEY=VALUE` file, or None.

    A file that is absent or unreadable is skipped: a host may list the file it
    uses on another machine. The value is returned to the one caller that asked
    for it and is never put into `os.environ`, so nothing this kit starts
    inherits a key it was not given deliberately.
    """
    text = _credential_file_text(path)
    if text is None:
        return None
    for key, value in _credential_entries(text):
        if key == name and value:
            return value
    return None


def credential_source(config, provider):
    """Where this provider's key would actually come from: environment, file or nowhere.

    The same order `credential` resolves in, so a report cannot name a source
    the next call would not use. No value is returned or logged — only which
    of the two places holds one.
    """
    name = config["credentials"].get(provider)
    if not name:
        return "none"
    if os.environ.get(name):
        return "environment"
    for path in config.get("credential_files", []):
        if _credential_file_value(path, name):
            return "file"
    return "none"


def _credential_file_name(item):
    """The declared file's own name, never the directory holding it.

    A doctor report is pasted into issues and handed to other agents, and the
    directory of a key file is host layout: an account name, a mounted share, a
    deployment root. The zero-based position in `credential_files` is enough to
    say which entry is meant. The Windows form is applied after the host form
    so a config written on Windows and read here still yields a bare name
    rather than a whole backslash path; a POSIX filename that actually contains
    a backslash is trimmed too, which errs towards saying less.
    """
    return PureWindowsPath(Path(item).name).name


def credential_file_report(config):
    """Per declared credential file: present, readable, and the names it declares.

    Names only, in two senses. The file is identified by its own basename and
    its position in the configured list, never by the path it sits at. And the
    keys are names: one appearing here says the file mentions it, not that it
    carries a usable value and not that any provider is entitled to use it;
    `credential_source` is the answer to that question.
    """
    report = []
    for index, item in enumerate(config.get("credential_files", [])):
        entry = {"index": index, "name": _credential_file_name(item),
                 "present": False, "readable": False, "keys": []}
        try:
            entry["present"] = Path(item).expanduser().is_file()
        except OSError:
            entry["present"] = False
        if entry["present"]:
            text = _credential_file_text(item)
            if text is not None:
                entry["readable"] = True
                entry["keys"] = sorted({key for key, _ in _credential_entries(text) if key})
        report.append(entry)
    return report


def credential(config, provider):
    """The provider key from the environment, else from a declared credential file.

    The environment still wins, so nothing that works today changes. A host that
    keeps its keys in a file lists it in `credential_files` instead of teaching
    every agent to parse that file into the environment by hand.
    """
    name = config["credentials"].get(provider)
    if name:
        value = os.environ.get(name)
        if value:
            return value
        for path in config.get("credential_files", []):
            value = _credential_file_value(path, name)
            if value:
                return value
    raise StudioError(
        f"{provider} needs setup: set the configured credential environment variable "
        "or list a credential file"
    )
