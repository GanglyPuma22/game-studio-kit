"""Verify a manifest of expected file identities and write a dated receipt."""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import uuid
from .common import StudioError, relative, safe_id, sha256, write_json
from .records import required

ROLES = ("engine", "helper", "source", "package", "asset", "other")


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
        required(item, ["id", "role", "path", "sha256"])
        safe_id(item["id"])
        if item["id"] in seen:
            raise StudioError("Duplicate identity manifest id: " + item["id"])
        seen.add(item["id"])
        if item["role"] not in ROLES:
            raise StudioError("Identity manifest role must be one of: " + ", ".join(ROLES))
        if not isinstance(item["path"], str) or not item["path"]:
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
    absolute = Path(path).is_absolute() or windows.is_absolute()
    return Path(path) if absolute else relative(root, path)


def verify(project, manifest_path, output=None):
    root = Path(project).resolve()
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest, manifest_digest = _read(manifest_path)
    items = []
    totals = {"match": 0, "mismatch": 0, "missing": 0}
    for item in manifest["items"]:
        target = _target(root, item["path"])
        if not target.is_file():
            status, actual = "missing", None
        else:
            actual = sha256(target)
            status = "match" if actual == item["sha256"] else "mismatch"
        totals[status] += 1
        items.append({
            "id": item["id"], "role": item["role"], "path": item["path"],
            "expected": item["sha256"], "actual": actual, "status": status,
        })
    verdict = "match" if totals["mismatch"] == 0 and totals["missing"] == 0 else (
        "mismatch" if totals["mismatch"] else "missing"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_path = (
        Path(output).expanduser().resolve() if output
        else root / "artifacts" / "identity" / f"verify-{stamp}-{uuid.uuid4().hex[:8]}.json"
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
