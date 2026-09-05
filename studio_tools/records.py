"""Validate minimal production records and their actual artifact identities."""

import math
from .common import StudioError, relative, sha256

STAGES = ["working", "exported", "imported", "reviewed", "accepted"]
VERDICTS = {"pass", "fail", "not_run", "unverified", "not_applicable"}
DIMENSIONS = ["visual", "interaction", "motion", "audio", "performance"]


def required(record, fields):
    for key in fields:
        if key not in record or record[key] is None or record[key] == "":
            raise StudioError("Missing required field: " + key)


def verify_file(root, item):
    required(item, ["path", "sha256"])
    p = relative(root, item["path"])
    if not p.is_file():
        raise StudioError("Missing file: " + item["path"])
    if sha256(p) != item["sha256"]:
        raise StudioError("Hash mismatch: " + item["path"])
    attachments = item.get("attachments", [])
    if not isinstance(attachments, list):
        raise StudioError("Evidence attachments must be a list")
    for attachment in attachments:
        verify_file(root, attachment)
    return p


def validate_listening(listening, observer):
    if not isinstance(listening, dict) or listening.get("performed") is not True:
        raise StudioError("Listening pass requires actual listening evidence")
    required(listening, ["playback_route", "interval_seconds"])
    interval = listening["interval_seconds"]
    if (not isinstance(observer, str) or not observer.strip()
        or not isinstance(listening["playback_route"], str) or not listening["playback_route"].strip()
        or not isinstance(interval, list) or len(interval) != 2
        or any(type(n) not in (int, float) or not math.isfinite(n) for n in interval)
        or not 0 <= interval[0] < interval[1]):
        raise StudioError("Listening needs an observer, playback route and increasing reviewed interval")


def validate(record, root):
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise StudioError("Expected record schema_version 1")
    kind = record.get("kind")
    if kind == "project":
        required(
            record,
            [
                "project_id",
                "engine",
                "target_platform",
                "references",
                "artifact_root",
                "workflow_version",
            ],
        )
        required(record["engine"], ["name", "version"])
        relative(root, record["artifact_root"])
        for ref in record["references"]:
            required(ref, ["id", "version", "status", "file"])
            verify_file(root, ref["file"])
    elif kind == "asset":
        required(
            record,
            [
                "asset_id",
                "stage",
                "source",
                "runtime",
                "units",
                "dimensions_m",
                "pivot",
                "materials",
                "provenance",
                "animated",
            ],
        )
        if record["stage"] not in STAGES:
            raise StudioError("Unknown asset stage")
        dimensions = record["dimensions_m"]
        if (
            not isinstance(dimensions, list)
            or len(dimensions) != 3
            or any(
                not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0
                for x in dimensions
            )
        ):
            raise StudioError("Asset dimensions must be three positive metre values")
        if not record["source"]:
            raise StudioError("Asset needs an editable source record")
        for item in record["source"] + record["runtime"]:
            verify_file(root, item)
        if record["stage"] != "working" and not record["runtime"]:
            raise StudioError("Exported asset requires a runtime export")
        if record["animated"]:
            required(record, ["rig", "clips"])
            if not record["clips"]:
                raise StudioError("Animated asset requires clip metadata")
            for clip in record["clips"]:
                required(
                    clip,
                    ["name", "duration_seconds", "sample_rate", "root_motion", "loop"],
                )
                if clip["duration_seconds"] <= 0 or clip["sample_rate"] <= 0:
                    raise StudioError("Clip duration/sample rate must be positive")
        if STAGES.index(record["stage"]) >= 2:
            verify_file(root, record.get("import_evidence", {}))
        if STAGES.index(record["stage"]) >= 3:
            verify_file(root, record.get("review_evidence", {}))
        if (
            record["stage"] == "accepted"
            and record.get("acceptance", {}).get("decision") != "accepted"
        ):
            raise StudioError("Accepted asset requires an explicit acceptance decision")
    elif kind == "audio-cues":
        required(record, ["cues"])
        for cue in record["cues"]:
            required(
                cue,
                [
                    "event_id",
                    "purpose",
                    "source",
                    "runtime",
                    "loop",
                    "bus",
                    "priority",
                    "provenance",
                    "measured",
                    "listening",
                ],
            )
            verify_file(root, cue["source"])
            verify_file(root, cue["runtime"])
            required(cue["measured"], ["duration_seconds", "sample_rate", "channels"])
            if cue["listening"] not in VERDICTS:
                raise StudioError("Unknown listening verdict")
            for evidence in cue.get("listening_evidence", []):
                verify_file(root, evidence)
            if cue["listening"] == "pass":
                if not cue.get("listening_evidence"):
                    raise StudioError("Listening pass requires actual listening evidence")
                for evidence in cue["listening_evidence"]:
                    validate_listening(evidence.get("listening"), evidence.get("observer"))
            if cue["loop"]:
                required(cue, ["loop_start_seconds", "loop_end_seconds"])
                if (
                    not 0
                    <= cue["loop_start_seconds"]
                    < cue["loop_end_seconds"]
                    <= cue["measured"]["duration_seconds"]
                ):
                    raise StudioError("Audio loop points exceed the measured cue")
    elif kind == "candidate":
        from .evidence import validate_candidate

        validate_candidate(record, root)
    else:
        raise StudioError(
            "Unknown record kind; expected project, asset, audio-cues or candidate"
        )
    return {"ok": True, "kind": kind}
