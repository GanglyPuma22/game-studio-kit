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


def output_root(path):
    root = Path(path).expanduser().resolve()
    package = Path(__file__).resolve().parents[1]
    if root == package or root.is_relative_to(package):
        raise StudioError(
            "Output must be outside the toolkit/package cache; choose a game project directory"
        )
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
