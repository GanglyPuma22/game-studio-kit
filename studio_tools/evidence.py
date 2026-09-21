"""Tie separate review verdicts to an immutable content inventory."""

from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import re
import shutil
import uuid
from .common import (
    digest, file_record, kit_identity, StudioError, read_json, safe_id, sha256, write_json,
    relative,
)
from .records import required, verify_file, DIMENSIONS, VERDICTS

EXCLUDED = {".git", ".godot", "artifacts", "__pycache__", ".studio"}


def inventory(project, *, portable=True):
    root = Path(project).resolve()
    files = [
        file_record(root, p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and not p.is_symlink()
        and not any(x in EXCLUDED for x in p.relative_to(root).parts)
        and p.name not in {".studio-local.json"}
    ]

    return canonical_inventory(files, portable=portable)


def canonical_inventory(files, *, portable=True):
    """Reject aliases; apply Windows portability only to version 2 inventories."""
    seen = set()
    spellings = {}
    for item in files:
        path = item["path"]
        parts = PurePosixPath(path).parts
        if not parts or PurePosixPath(path).is_absolute() or ":" in path or "/".join(parts) != path or "\\" in path or ".." in parts:
            raise StudioError("Inventory needs canonical POSIX relative paths")
        if path in seen:
            raise StudioError("Duplicate inventory path")
        seen.add(path)
        if not portable:
            continue
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(prefix + n for prefix in ("COM", "LPT") for n in "123456789¹²³")
        for part in parts:
            if (part.endswith((".", " ")) or part.split(".")[0].upper() in reserved
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
                raise StudioError("Inventory path is not portable to Windows: " + path)
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            folded = prefix.casefold()
            if folded in spellings and spellings[folded] != prefix:
                raise StudioError("Case collision in portable inventory: " + prefix)
            spellings[folded] = prefix
    return sorted(files, key=lambda item: item["path"])


# What an evidence entry still describes: the candidate as it is now, a
# candidate whose files have since changed, or a receipt that never recorded
# which content it was taken from.
IDENTITIES = ("current", "historical", "unknown")
# Methods by which a person states a verdict rather than a tool measuring one.
HUMAN_METHODS = {"native_visual", "native_capture_review", "listening", "ordinary_input"}
VERIFY_LIMITS = [
    "re-hashing shows the declared results still have the bytes the receipt recorded; "
    "it does not show they are correct, complete or acceptable",
    "only files the receipt itself recorded a digest for are checked",
]


def receipt_identity(receipt, candidate):
    """Whether a receipt still describes this candidate's content, by digest alone.

    The comparison is between two recorded digests: the one the capture, bench
    or cleanroom receipt wrote down when it was taken and the one the candidate
    carries now. Nothing is re-hashed here, so `current` means the receipt was
    taken from the same inventory the candidate names — not that the files on
    disk match it today, which is `validate_candidate`'s job.

    A receipt that never recorded a content digest — a launch exit or a
    cleanroom bench, which know a project but not a candidate — is `unknown`.
    That is weaker than `historical`: it says nothing was recorded, not that
    something was and has moved on.
    """
    recorded = receipt.get("content_digest") if isinstance(receipt, dict) else None
    if not isinstance(recorded, str) or not recorded:
        return "unknown"
    return "current" if recorded == candidate.get("content_digest") else "historical"


def _row_class(entry):
    """The performance class one evidence row argues for."""
    declared = entry.get("performance_class")
    if isinstance(declared, str) and declared:
        return declared
    # A row with no class that records a person's own review is a subjective
    # acceptance; anything else unclassified stays unclassified and will pull
    # the rollup to mixed rather than quietly counting as either.
    return "subjective_acceptance" if entry.get("method") in HUMAN_METHODS else "unclassified"


def performance_rollup(entries):
    """One word for what the performance evidence on a verdict adds up to.

    Only rows still describing the current content are counted: a number taken
    from a build whose files have since changed cannot qualify this one.
    """
    current = [entry for entry in entries if entry.get("identity") == "current"]
    if not current:
        return "unverified"
    classes = {_row_class(entry) for entry in current}
    if classes == {"clean_qualification"}:
        return "clean_qualification"
    if classes == {"subjective_acceptance"}:
        return "subjective_acceptance"
    if classes == {"diagnostic"}:
        # Honest about what it is: numbers taken on a busy host, from a plain
        # launch, that were never meant to qualify anything.
        return "diagnostic"
    return "mixed"


def refresh_rollups(candidate, dimension=None):
    """Recompute the per-verdict evidence counts, and the performance class.

    Counts, not judgements: `evidence_total` is how many rows are attached and
    `evidence_current` how many of them still describe this candidate. A
    verdict whose two numbers differ is resting partly on older content.
    """
    verdicts = candidate.get("verdicts") or {}
    for name in ([dimension] if dimension is not None else list(verdicts)):
        verdict = verdicts.get(name)
        if not isinstance(verdict, dict):
            continue
        entries = verdict.get("evidence") or []
        verdict["evidence_total"] = len(entries)
        verdict["evidence_current"] = sum(entry.get("identity") == "current" for entry in entries)
        if name == "performance":
            verdict["performance_class"] = performance_rollup(entries)
    return candidate


def attach_evidence(candidate, dimension, evidence, receipt=None):
    """Attach one capture, bench or cleanroom receipt to a verdict, labelled.

    The entry keeps every hash it arrived with; this only adds what the entry
    could not know on its own — whether it still describes the candidate it is
    being attached to, and, for performance, which class of number it is. The
    verdict's rollups are recomputed here, so they can never be stale with
    respect to the list beside them.
    """
    if dimension not in DIMENSIONS:
        raise StudioError("Unknown verdict dimension: " + str(dimension))
    if not isinstance(evidence, dict):
        raise StudioError("Evidence entry must be a JSON object")
    verdicts = candidate.setdefault("verdicts", {})
    verdict = verdicts.setdefault(dimension, {"status": "not_run", "evidence": []})
    entries = verdict.setdefault("evidence", [])
    if not isinstance(entries, list):
        raise StudioError("Verdict evidence must be a list")
    # The receipt is the record the digest and class were written into; an
    # archived capture carries both on the entry itself.
    source = receipt if isinstance(receipt, dict) else evidence
    entry = dict(evidence)
    entry["identity"] = receipt_identity(source, candidate)
    performance_class = source.get("performance_class")
    if isinstance(performance_class, str) and performance_class:
        entry["performance_class"] = performance_class
    entries.append(entry)
    refresh_rollups(candidate, dimension)
    return entry


def _receipt_root(receipt, project=None):
    """The project root a receipt's recorded relative paths are anchored to.

    Every receipt this kit writes lands under `<project>/artifacts/...`, so the
    root is the parent of the `artifacts` directory above it. An explicit
    project wins, because a receipt copied out of its run directory has nothing
    left to derive from.
    """
    if project is not None:
        root = Path(project).expanduser().resolve()
        if not root.is_dir():
            raise StudioError("Receipt verification needs an existing project directory")
        return root
    for parent in Path(receipt).resolve().parents:
        if parent.name == "artifacts":
            return parent.parent
    raise StudioError(
        "Cannot tell which project this receipt belongs to; pass --project"
    )


def verify_receipt(receipt, project=None):
    """Re-hash the result files a receipt recorded, and say what changed.

    Reads a receipt written by `launch` or `blender run`, takes every declared
    result it recorded a digest for, and hashes that file as it is now. No
    bytes are copied anywhere. `ok` is true only when every recorded file is
    still exactly what the receipt said, which is a statement about bytes and
    about nothing else.

    Nothing in `result_files` is silently dropped. An element that is not an
    object with a string path, or whose digest is neither absent nor a 64
    character hex string, is reported under `malformed` with its index and
    makes the whole verification not ok: a receipt this reader cannot fully
    account for has not been checked, and saying so beats reporting the rows
    that happened to parse.
    """
    path = Path(receipt).expanduser().resolve()
    record = read_json(path)
    if not isinstance(record, dict):
        raise StudioError("Receipt is not a JSON object")
    root = _receipt_root(path, project)
    declared = record.get("result_files")
    if not isinstance(declared, list):
        raise StudioError("Receipt has no result_files list to verify")
    files = []
    unrecorded = []
    malformed = []
    for index, item in enumerate(declared):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            # The path is not echoed: it is not known to be a string, and a
            # receipt this reader cannot parse is not one to quote from.
            malformed.append({"index": index,
                              "reason": "entry is not an object with a string path"})
            continue
        recorded = item.get("sha256")
        if recorded is None:
            # The run itself recorded no digest for this path, so there is
            # nothing here to compare against and saying "changed" would be a
            # claim about a file this receipt never vouched for.
            unrecorded.append(item["path"])
            continue
        if not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded):
            malformed.append({"index": index, "path": item["path"],
                              "reason": "sha256 is not a 64 character hex digest"})
            continue
        entry = {"path": item["path"], "recorded_sha256": recorded,
                 "current_sha256": None, "state": "missing"}
        try:
            target = relative(root, item["path"])
        except StudioError:
            # A path that no longer resolves inside the project names no file
            # this receipt can be checked against.
            files.append(entry)
            continue
        if target.is_file():
            try:
                entry["current_sha256"] = sha256(target)
            except OSError:
                # Present but unreadable cannot be shown to still match.
                entry["state"] = "changed"
                files.append(entry)
                continue
            entry["state"] = "current" if entry["current_sha256"] == recorded else "changed"
        files.append(entry)
    return {
        "schema_version": 1,
        "kind": "evidence-verify",
        "kit": kit_identity(),
        "receipt": {"path": str(path), "kind": record.get("kind"), "label": record.get("label")},
        "project": str(root),
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "unrecorded": unrecorded,
        "malformed": malformed,
        "totals": {
            "current": sum(entry["state"] == "current" for entry in files),
            "changed": sum(entry["state"] == "changed" for entry in files),
            "missing": sum(entry["state"] == "missing" for entry in files),
            "malformed": len(malformed),
        },
        # A receipt that recorded no digests proves nothing by being re-read,
        # and one this reader could not fully parse has not been checked.
        "ok": bool(files) and not malformed
        and all(entry["state"] == "current" for entry in files),
        "limits": VERIFY_LIMITS,
    }


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
    # Taken from this candidate's inventory a moment ago, so it describes the
    # current content; the label is computed rather than asserted so the two
    # can never drift apart.
    result["identity"] = receipt_identity(result, candidate)
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
        "kit": kit_identity(),
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
        "verdicts": {
            d: {
                "status": "not_run",
                "evidence": [],
                "evidence_current": 0,
                "evidence_total": 0,
                **({"performance_class": "unverified"} if d == "performance" else {}),
            }
            for d in DIMENSIONS
        },
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
    ordered = canonical_inventory(files, portable=version == 2)
    workflow_ordered = canonical_inventory(record["workflow_files"], portable=version == 2)
    if version == 2 and (files != ordered or record["workflow_files"] != workflow_ordered):
        raise StudioError("Version 2 inventories must use canonical path order")
    for item in files:
        verify_file(root, item)
    current = inventory(root, portable=version == 2)
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
        # The rollups are a summary of the rows beside them and are recomputed
        # here rather than trusted. A record whose stored numbers disagree with
        # its own evidence is describing a list it no longer holds. A record
        # that stores none is legacy: there is nothing to disagree with, and
        # every rule below reads the rows themselves.
        current_rows = sum(item.get("identity") == "current" for item in evidence_items)
        rolled_class = performance_rollup(evidence_items) if dimension == "performance" else None
        for key, recomputed in (("evidence_total", len(evidence_items)),
                                ("evidence_current", current_rows),
                                ("performance_class", rolled_class)):
            stored = verdict.get(key)
            if stored is not None and recomputed is not None and stored != recomputed:
                raise StudioError(
                    f"Verdict {key} disagrees with its own evidence: " + dimension
                )
        if status == "pass" and not current_rows:
            # Every row here already had to name this candidate's content
            # digest; this adds that the row must say so. A pass argued only
            # from evidence labelled historical or unknown is a pass for a
            # build that no longer exists.
            raise StudioError(
                "Pass needs at least one evidence row marked identity=current: " + dimension
            )
        if status == "pass" and dimension == "performance" and rolled_class != "clean_qualification":
            # A frame time measured while something else had the machine, or a
            # number nobody classified, cannot carry a performance pass. Only a
            # cleanroom window qualifies one.
            raise StudioError(
                "Performance pass needs clean_qualification evidence; this verdict rolls up as "
                + str(rolled_class)
            )
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
