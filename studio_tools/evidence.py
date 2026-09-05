"""Tie separate review verdicts to an immutable content inventory."""

from pathlib import Path
from .common import digest, file_record, StudioError, read_json
from .records import required, verify_file, DIMENSIONS, VERDICTS

EXCLUDED = {".git", ".godot", "artifacts", "__pycache__", ".studio"}


def inventory(project):
    root = Path(project).resolve()
    return [
        file_record(root, p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and not p.is_symlink()
        and not any(x in EXCLUDED for x in p.relative_to(root).parts)
        and p.name not in {".studio-local.json"}
    ]


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
    workflow_files.sort(key=lambda item: item["path"])
    project_record = (
        read_json(Path(project) / "project.json")
        if (Path(project) / "project.json").is_file()
        else {}
    )

    return {
        "schema_version": 1,
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
    paths = [f["path"] for f in files]
    if len(paths) != len(set(paths)):
        raise StudioError("Duplicate candidate content path")
    for item in files:
        verify_file(root, item)
    current = inventory(root)
    if current != files:
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
        if status in {"pass", "fail"}:
            if not verdict.get("evidence"):
                raise StudioError("Verdict needs evidence: " + dimension)
            for evidence in verdict["evidence"]:
                required(evidence, ["content_digest", "method", "observer"])
                verify_file(root, evidence)
                if evidence["content_digest"] != record["content_digest"]:
                    raise StudioError(
                        "Evidence belongs to a different candidate: " + dimension
                    )
                methods = {
                    "visual": {"native_visual", "native_capture_review"},
                    "audio": {"listening", "native_capture_review"},
                    "motion": {"native_visual", "native_capture_review"},
                    "interaction": {"ordinary_input", "native_capture_review"},
                    "performance": {"profiler_measurement", "native_capture_review"},
                }
                if status == "pass" and evidence["method"] not in methods[dimension]:
                    raise StudioError(
                        "Perceptual pass or runtime acceptance requires the appropriate review method: "
                        + dimension
                    )
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
