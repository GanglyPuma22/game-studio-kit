"""Small file and identity utilities shared by the CLI and adapters."""

from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath


class StudioError(ValueError):
    """An actionable, safe-to-display failure."""


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StudioError(f"Cannot read JSON record: {Path(path).name}") from exc


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(data):
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def relative(root, name):
    """Reject cross-platform absolute paths, traversal and escaping symlinks."""
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or PureWindowsPath(name).drive
        or Path(name).is_absolute()
    ):
        raise StudioError("Record paths must be nonempty portable relative paths")
    root = Path(root).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root) or ".." in Path(name).parts:
        raise StudioError("Path escapes the declared project root")
    return target


PACKAGE = Path(__file__).resolve().parents[1]


def outside_package(path, subject="Output"):
    """Resolve `path` and reject it if it is, or lies inside, the installed
    toolkit/package cache. Does not touch the filesystem otherwise, so it is
    safe to use on a file (e.g. a receipt) as well as a directory.
    """
    resolved = Path(path).expanduser().resolve()
    if resolved == PACKAGE or resolved.is_relative_to(PACKAGE):
        raise StudioError(
            f"{subject} must be outside the installed kit (outside the toolkit/package cache); "
            "choose a game project directory"
        )
    return resolved


def output_root(path):
    root = outside_package(path, "Output")
    root.mkdir(parents=True, exist_ok=True)
    return root


def file_record(root, path):
    path = Path(path).resolve()
    return {
        "path": path.relative_to(Path(root).resolve()).as_posix(),
        "sha256": sha256(path),
    }


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value
    ):
        raise StudioError(
            "ID must contain only letters, digits, hyphens or underscores"
        )
    return value


_KIT_IDENTITY = None


def kit_identity():
    """Which kit wrote a receipt: its declared version and its own source digest.

    The version alone names a release, not the bytes that ran: a working tree
    between releases, a half-applied update or a local patch all keep it. The
    digest is taken over every `studio_tools/**/*.py` file, sorted by its
    POSIX-relative path, with the path and the byte length mixed in so that
    moving code between two files changes the digest. It says nothing about
    skills, references or templates, and nothing about whether the kit was
    installed from a release.

    Computed once per process: the files cannot change under a running
    interpreter without the modules already loaded from them disagreeing with
    whatever a later read would report.
    """
    global _KIT_IDENTITY
    if _KIT_IDENTITY is None:
        from . import __version__

        package = Path(__file__).resolve().parent
        h = hashlib.sha256()
        for path in sorted(package.rglob("*.py")):
            name = path.relative_to(package).as_posix()
            try:
                data = path.read_bytes()
            except OSError:
                # A source file this process cannot read is still part of the
                # tree; recording it as unreadable beats silently omitting it.
                h.update(name.encode("utf-8") + b"\0unreadable\0")
                continue
            h.update(name.encode("utf-8") + b"\0" + str(len(data)).encode("ascii") + b"\0")
            h.update(data)
        _KIT_IDENTITY = {"version": __version__, "source_digest": h.hexdigest()}
    # A copy, so a receipt that is edited afterwards cannot change the cache.
    return dict(_KIT_IDENTITY)
