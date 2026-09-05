"""Tie separate review verdicts to an immutable content inventory."""

from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import shutil
import uuid
from .common import digest, file_record, StudioError, read_json, safe_id, write_json, relative
from .records import required, verify_file, DIMENSIONS, VERDICTS

EXCLUDED = {".git", ".godot", "artifacts", "__pycache__", ".studio"}


def inventory(project):
    root = Path(project).resolve()
    files = [
        file_record(root, p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and not p.is_symlink()
        and not any(x in EXCLUDED for x in p.relative_to(root).parts)
        and p.name not in {".studio-local.json"}
    ]

    return canonical_inventory(files)


def canonical_inventory(files):
    """Portable exact spelling/order; reject aliases before a Windows transfer."""
    seen = set()
    spellings = {}
    for item in files:
        path = item["path"]
        parts = PurePosixPath(path).parts
        if not parts or PurePosixPath(path).is_absolute() or ":" in path or "/".join(parts) != path or "\\" in path or ".." in parts:
            raise StudioError("Inventory needs canonical POSIX relative paths")
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(prefix + n for prefix in ("COM", "LPT") for n in "123456789¹²³")
        for part in parts:
            if (part.endswith((".", " ")) or part.split(".")[0].upper() in reserved
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
                raise StudioError("Inventory path is not portable to Windows: " + path)
        if path in seen:
            raise StudioError("Duplicate inventory path")
        seen.add(path)
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            folded = prefix.casefold()
            if folded in spellings and spellings[folded] != prefix:
                raise StudioError("Case collision in portable inventory: " + prefix)
            spellings[folded] = prefix
    return sorted(files, key=lambda item: item["path"])


def archive_capture(project, source, candidate, label):
    """Archive already captured bytes; this does not perform or attest review."""
    validate_candidate(candidate, project)
    label = safe_id(label)
    safe_id(candidate["candidate_id"])
    source = Path(source)
    if not source.is_file():
        raise StudioError("Capture source is missing")
    capture_id = uuid.uuid4().hex
    folder = relative(project, "artifacts/captures/" + capture_id)
    folder.mkdir(parents=True, exist_ok=False)
    payload = folder / "payload"
    payload.mkdir()
    target = payload / (label + source.suffix)
    shutil.copyfile(source, target)
    result = {
        **file_record(project, target),
        "capture_id": capture_id,
        "candidate_id": candidate["candidate_id"],
        "content_digest": candidate["content_digest"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "review": "not_run",
    }
    write_json(folder / "capture.json", result)
    return result


def new_candidate(project, candidate_id, engine_version, workflow):
    files = inventory(project)
    kit = Path(__file__).resolve().parents[1]
    workflow_files = [
        file_record(kit, p)
        for folder in (
            "skills",
            "references",
            "templates",
            "studio_tools",
            "scripts",
            ".codex-plugin",
        )
        for p in sorted((kit / folder).rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]
    workflow_files = canonical_inventory(workflow_files)
    project_record = (
        read_json(Path(project) / "project.json")
        if (Path(project) / "project.json").is_file()
        else {}
    )

    return {
        "schema_version": 1,
        "inventory_version": 2,
        "kind": "candidate",
        "candidate_id": candidate_id,
        "content_files": files,
        "content_digest": digest(files),
        "workflow_version": workflow,
        "workflow_files": workflow_files,
        "workflow_digest": digest(workflow_files),
        "engine": {
            "name": "Godot",
            "version": engine_version,
            "version_origin": "declared; match to actual import/build evidence",
        },
        "settings": project_record.get("settings", {"status": "unverified"}),
        "input_route": project_record.get("input_route", "not_defined"),
        "verdicts": {d: {"status": "not_run", "evidence": []} for d in DIMENSIONS},
        "defects": [],
        "acceptance": {"decision": "pending", "reviewer": None},
    }


def validate_candidate(record, root):
    required(
        record,
        [
            "candidate_id",
            "content_files",
            "content_digest",
            "workflow_version",
            "workflow_files",
            "workflow_digest",
            "engine",
            "settings",
            "input_route",
            "verdicts",
            "defects",
            "acceptance",
        ],
    )
    if (
        not record["workflow_files"]
        or digest(record["workflow_files"]) != record["workflow_digest"]
    ):
        raise StudioError("Workflow inventory/digest is missing or inconsistent")
    files = record["content_files"]
    if not files or digest(files) != record["content_digest"]:
        raise StudioError(
            "Candidate content inventory/digest is missing or inconsistent"
        )
    version = record.get("inventory_version", 1)
    if version not in {1, 2}:
        raise StudioError("Unsupported inventory version")
    ordered = canonical_inventory(files)
    workflow_ordered = canonical_inventory(record["workflow_files"])
    if version == 2 and (files != ordered or record["workflow_files"] != workflow_ordered):
        raise StudioError("Version 2 inventories must use canonical path order")
    for item in files:
        verify_file(root, item)
    current = inventory(root)
    if {item["path"]: item["sha256"] for item in current} != {item["path"]: item["sha256"] for item in ordered}:
        raise StudioError(
            "Candidate content changed: added, removed or modified project file"
        )
    accepted = record["acceptance"].get("decision") == "accepted"
    for dimension in DIMENSIONS:
        verdict = record["verdicts"].get(dimension, {})
        status = verdict.get("status")
        if status not in VERDICTS:
            raise StudioError("Missing/invalid verdict: " + dimension)
        if status == "not_applicable" and not verdict.get("reason"):
            raise StudioError("Not-applicable verdict needs a reason: " + dimension)
        evidence_items = verdict.get("evidence", [])
        if not isinstance(evidence_items, list):
            raise StudioError("Verdict evidence must be a list")
        if status in {"pass", "fail"} and not evidence_items:
            raise StudioError("Verdict needs evidence: " + dimension)
        for evidence in evidence_items:
            required(evidence, ["content_digest", "method", "observer"])
            verify_file(root, evidence)
            if evidence["content_digest"] != record["content_digest"]:
                raise StudioError("Evidence belongs to a different candidate: " + dimension)
            methods = {
                "visual": {"native_visual", "native_capture_review"},
                "audio": {"listening", "native_capture_review"},
                "motion": {"native_visual", "native_capture_review"},
                "interaction": {"ordinary_input", "native_capture_review"},
                "performance": {"profiler_measurement", "native_capture_review"},
            }
            if status == "pass" and evidence["method"] not in methods[dimension]:
                raise StudioError(
                    "Perceptual pass or runtime acceptance requires the appropriate review method: " + dimension
                )
            if status == "pass" and dimension == "audio":
                from .records import validate_listening
                validate_listening(evidence.get("listening"), evidence.get("observer"))
        if accepted and status not in {"pass", "not_applicable"}:
            raise StudioError("Acceptance blocked by verdict: " + dimension)
    if accepted and (
        record["settings"].get("status") == "unverified"
        or record["input_route"] == "not_defined"
    ):
        raise StudioError(
            "Acceptance needs declared settings and an ordinary input route"
        )
    if accepted:
        required(record["acceptance"], ["reviewer", "rationale"])
        if any(d.get("status") != "resolved" for d in record["defects"]):
            raise StudioError("Acceptance blocked by unresolved defects")
