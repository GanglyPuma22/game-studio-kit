"""Verify a manifest of expected file identities and write a dated receipt."""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import uuid
from .common import StudioError, outside_package, relative, safe_id, sha256, write_json
from .config import executable
from .records import required

ROLES = ("engine", "helper", "source", "package", "asset", "other")
# Which spelling of an absolute path this host can actually open. Tests set it;
# patching os.name instead would change how pathlib itself parses every path.
IS_WINDOWS = os.name == "nt"
# An engine lives at a host path that must stay in ignored host config, so an
# engine item may name the configured executable instead of a path.
SOURCES = ("host-config",)


def _read(path):
    """Read the manifest bytes once; the record and its recorded hash come from the same bytes."""
    try:
        raw = Path(path).read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise StudioError(f"Cannot read JSON record: {Path(path).name}") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != "identity-manifest":
        raise StudioError("Expected an identity-manifest record")
    if manifest.get("schema_version") != 1:
        raise StudioError("Identity manifest schema_version must be 1")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise StudioError("Identity manifest needs a non-empty items list")
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise StudioError("Identity manifest items must be objects")
        required(item, ["id", "role", "sha256"])
        safe_id(item["id"])
        if item["id"] in seen:
            raise StudioError("Duplicate identity manifest id: " + item["id"])
        seen.add(item["id"])
        if item["role"] not in ROLES:
            raise StudioError("Identity manifest role must be one of: " + ", ".join(ROLES))
        source = item.get("source")
        if source is not None:
            if source not in SOURCES:
                raise StudioError("Identity manifest source must be one of: " + ", ".join(SOURCES))
            if item["role"] != "engine":
                raise StudioError("Only an engine item may take its location from the host config")
            if item.get("path") is not None:
                raise StudioError("A host-config engine item must not also carry a path")
        elif not isinstance(item.get("path"), str) or not item["path"]:
            raise StudioError("Identity manifest path must be a non-empty string")
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise StudioError("Identity manifest sha256 must be 64 lowercase hex characters")
    return manifest, hashlib.sha256(raw).hexdigest()


def load(path):
    return _read(path)[0]


def _target(root, path):
    windows = PureWindowsPath(path)
    if windows.drive and not windows.root:
        # C:engine.exe depends on the per-drive working directory; it names no fixed file.
        raise StudioError("Identity manifest path must be relative to the project or fully absolute")
    windows_absolute = windows.is_absolute()
    posix_absolute = PurePosixPath(path).is_absolute()
    native, foreign = (
        (windows_absolute, posix_absolute) if IS_WINDOWS
        else (posix_absolute, windows_absolute)
    )
    if foreign and not native:
        # `C:\tools\asset.bin` names no file on POSIX and `/opt/asset.bin` names
        # none on Windows: hashing it here would report a foreign host's file as
        # missing instead of admitting this host cannot check the manifest.
        raise StudioError("Identity manifest path is absolute for another host")
    return Path(path) if native else relative(root, path)


def verify(project, manifest_path, output=None, config=None):
    root = Path(project).resolve()
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest, manifest_digest = _read(manifest_path)
    items = []
    totals = {"match": 0, "mismatch": 0, "missing": 0}
    for item in manifest["items"]:
        source = item.get("source")
        if source == "host-config":
            # The resolved host path never reaches the receipt: an unconfigured
            # or absent engine is reported as missing, like any other item.
            found = executable(config, "godot") if config else None
            target = Path(found) if found else None
        else:
            target = _target(root, item["path"])
        if target is None or not target.is_file():
            status, actual = "missing", None
        else:
            actual = sha256(target)
            status = "match" if actual == item["sha256"] else "mismatch"
        totals[status] += 1
        items.append({
            "id": item["id"], "role": item["role"],
            "path": None if source else item["path"], "source": source,
            "expected": item["sha256"], "actual": actual, "status": status,
        })
    verdict = "match" if totals["mismatch"] == 0 and totals["missing"] == 0 else (
        "mismatch" if totals["mismatch"] else "missing"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # The default receipt is contained like any other declared output: a
    # symlinked artifacts/ must not write it outside the project or into the kit.
    receipt_path = (
        Path(output).expanduser().resolve() if output
        else outside_package(
            relative(root, f"artifacts/identity/verify-{stamp}-{uuid.uuid4().hex[:8]}.json")
        )
    )
    if receipt_path.exists():
        raise StudioError("Identity receipt exists; choose a new filename")
    receipt = {
        "schema_version": 1,
        "kind": "identity-receipt",
        "manifest": {"path": str(manifest_path), "sha256": manifest_digest},
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "totals": totals,
        "verdict": verdict,
        "ok": verdict == "match",
        "limits": ["byte identity only; a matching hash is not acceptance or entitlement"],
    }
    write_json(receipt_path, receipt)
    return {**receipt, "receipt": str(receipt_path)}
