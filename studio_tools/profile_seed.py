"""Explicit, hash-bound files prepared in a fresh owned Windows profile.

This guards setup mistakes and detects changed inputs before spawn. It is not
a filesystem sandbox against an actively hostile process racing the checks.
"""

from __future__ import annotations
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time
import unicodedata

from .common import StudioError, outside_package
from .config import require_executable
from .adapters.godot import self_contained

IS_WINDOWS = os.name == "nt"
MAX_FILES = 8
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * MAX_FILE_BYTES
_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$", re.I)


def portable_path(value):
    if (not isinstance(value, str) or not value or PureWindowsPath(value).drive
            or value.startswith("/") or any(c in value for c in '\\:{}<>"|?*')
            or any(unicodedata.category(c) == "Cc" for c in value)):
        raise StudioError("Profile seed paths must be portable relative file paths")
    parts = value.split("/")
    if any(p in ("", ".", "..") or p.endswith((".", " "))
           or _DEVICE.match(p.split(".")[0].rstrip(" "))
           for p in parts):
        raise StudioError("Profile seed path has an unsafe component")
    return value


def declaration(value):
    """Validate only the public declaration; no filesystem or host access."""
    if not isinstance(value, dict) or set(value) != {"platform", "files"}:
        raise StudioError("Profile seed must contain exactly platform and files")
    if value["platform"] != "windows":
        raise StudioError("Profile seed platform must be windows")
    entries = value["files"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
        raise StudioError("Profile seed files must contain 1–8 entries")
    result, targets = [], []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"source", "target", "sha256"}:
            raise StudioError("Profile seed file must contain exactly source, target and sha256")
        source, target = portable_path(entry["source"]), portable_path(entry["target"])
        expected = entry["sha256"]
        if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
            raise StudioError("Profile seed SHA-256 must be 64 hex characters")
        folded = target.casefold()
        if any(folded == other or folded.startswith(other + "/")
               or other.startswith(folded + "/") for other in targets):
            raise StudioError("Profile seed targets duplicate or collide")
        targets.append(folded)
        result.append({"source": source, "target": target, "sha256": expected.lower()})
    return {"platform": "windows", "files": result}


def safe_components(path):
    """Inspect lexical ancestors before resolve, including existing host ancestors."""
    path = Path(path).absolute()
    try:
        for part in (*reversed(path.parents), path):
            try:
                info = part.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise StudioError("Profile seed path contains a link or reparse point")
    except OSError as exc:
        raise StudioError("Profile seed path safety could not be verified") from exc
    return path


def _bytes(path, expected):
    safe_components(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise StudioError("Profile seed requires regular files")
        if info.st_size > MAX_FILE_BYTES:
            raise StudioError("Profile seed file exceeds 1 MiB")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink > 1:
                raise StudioError("Profile seed requires regular files")
            raw = stream.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise StudioError("Profile seed file is missing or unreadable") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise StudioError("Profile seed file exceeds 1 MiB")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise StudioError("Profile seed file SHA-256 mismatch")
    safe_components(path)
    return raw


class Snapshot:
    def __init__(self, root, declared, blobs):
        self.root, self.declared, self.blobs = root, declared, blobs
        self.profile_identity = None
        self.receipt = {
            "platform": "windows", "status": "validated", "setup_seconds": None,
            "files": [{**item, "bytes": len(raw), "actual_sha256": item["sha256"],
                       "copied_sha256": None} for item, raw in zip(declared["files"], blobs)],
        }

    def prepare(self, profile):
        started = time.monotonic()
        self.receipt["status"] = "preparing"
        try:
            safe_components(profile)
            profile.mkdir(exist_ok=False)
            info = profile.stat()
            self.profile_identity = (info.st_dev, info.st_ino)
            for item, raw, receipt in zip(self.declared["files"], self.blobs, self.receipt["files"]):
                target = profile / item["target"]
                safe_components(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                safe_components(target)
                with target.open("xb") as stream:
                    stream.write(raw)
                _bytes(target, item["sha256"])
                receipt["copied_sha256"] = item["sha256"]
            self.receipt["status"] = "prepared"
        except OSError as exc:
            raise StudioError("Profile seed preparation failed; nothing was launched") from exc
        finally:
            self.receipt["setup_seconds"] = round(time.monotonic() - started, 6)

    def recheck(self, profile, launch_profile=None):
        safe_components(profile)
        try:
            info = profile.lstat()
        except OSError as exc:
            raise StudioError("Profile seed owned profile is missing") from exc
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self.profile_identity:
            raise StudioError("Profile seed owned profile changed before launch")
        for item in self.declared["files"]:
            _bytes(self.root / item["source"], item["sha256"])
            _bytes(profile / item["target"], item["sha256"])
        if launch_profile is not None:
            if (not isinstance(launch_profile, dict) or not isinstance(launch_profile.get("sha256"), str)
                    or not re.fullmatch(r"[a-fA-F0-9]{64}", launch_profile["sha256"])):
                raise StudioError("Seeded launch profile identity is invalid")
            path = self.root / portable_path(launch_profile.get("path"))
            safe_components(path)
            try:
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise StudioError("Seeded launch profile must be a regular file")
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise StudioError("Seeded launch profile is missing or unreadable") from exc
            if actual != launch_profile["sha256"].lower():
                raise StudioError("Seeded launch profile changed before launch")
        self.receipt["status"] = "verified_before_spawn"

    def refuse(self):
        self.receipt["status"] = "refused"


def snapshot(config, root, value, *, use_host_profile=False):
    if value is None:
        return None
    declared = declaration(value)
    if use_host_profile:
        raise StudioError("Profile seeds require an isolated profile; --use-host-profile conflicts")
    configured = config.get("executables", {}).get("godot")
    if (not IS_WINDOWS or not isinstance(configured, str) or not configured.lower().endswith(".exe")
            or not require_executable(config, "godot").lower().endswith(".exe")):
        raise StudioError("Profile seeds require native Windows and a configured .exe engine")
    if config.get("path_mappings"):
        raise StudioError("Profile seeds refuse cross-host path mappings")
    if self_contained(Path(require_executable(config, "godot"))):
        raise StudioError("Profile seeds require Godot without a self-contained _sc_ marker")
    root = safe_components(root)
    root = outside_package(root, "Profile seed project")
    blobs = [_bytes(root / item["source"], item["sha256"]) for item in declared["files"]]
    if sum(map(len, blobs)) > MAX_TOTAL_BYTES:
        raise StudioError("Profile seed files exceed 8 MiB total")
    return Snapshot(root, declared, blobs)
