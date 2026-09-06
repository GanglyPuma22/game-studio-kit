"""Operational evidence attached to a work card, using existing verdict semantics."""
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from .common import StudioError, digest, file_record, output_root, read_json, relative, safe_id, sha256, write_json
from .evidence import validate_candidate
from .records import DIMENSIONS, VERDICTS, required, verify_file


def number(value, label, minimum=0, maximum=1200):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise StudioError("Invalid " + label)
    return value


def interval(value, duration=1200):
    if not isinstance(value, list) or len(value) != 2:
        raise StudioError("Evidence needs a two-number interval")
    start, end = value
    number(start, "interval start", maximum=duration)
    number(end, "interval end", maximum=duration)
    if end <= start:
        raise StudioError("Evidence interval must increase")
    return start, end


def validate_card(card, candidate, root, *, current=True):
    if not isinstance(card, dict) or card.get("schema_version") != 1:
        raise StudioError("Expected review card schema_version 1")
    required(card, ["work_card_id", "owner", "candidate_id", "content_digest", "settings", "route_id",
                    "input_route", "launch", "duration_seconds", "max_rechecks", "actions", "criteria"])
    safe_id(card["work_card_id"])
    if current:
        validate_candidate(candidate, root)
    if any(card[k] != candidate[k] for k in ("candidate_id", "content_digest")):
        raise StudioError("Card belongs to a different candidate")
    if digest(candidate["content_files"]) != candidate["content_digest"] or digest(candidate["workflow_files"]) != candidate["workflow_digest"]:
        raise StudioError("Candidate inventory identity mismatch")
    duration = number(card["duration_seconds"], "duration_seconds", .01)
    if type(card["max_rechecks"]) is not int or not 0 <= card["max_rechecks"] <= 10:
        raise StudioError("max_rechecks must be an integer from 0 to 10")
    if card["input_route"] not in {"ordinary", "human", "synthetic"}:
        raise StudioError("Declare ordinary/human/synthetic input route")
    if not isinstance(card["settings"], dict) or not card["settings"]:
        raise StudioError("Declare comparison settings")
    launch = card["launch"]
    required(launch, ["intent", "entrypoint", "entrypoint_sha256", "delivered_args",
                      "effective_audio_backend", "import_audio_backend", "live_services"])
    if launch["intent"] not in {"human", "quiet_diagnostic"} or not isinstance(launch["delivered_args"], list):
        raise StudioError("Declare human or quiet_diagnostic launch and delivered argument array")
    if current:
        verify_file(root, {"path": launch["entrypoint"], "sha256": launch["entrypoint_sha256"]})
        wrapper = relative(root, launch["entrypoint"]).read_text(errors="replace") if Path(launch["entrypoint"]).suffix.lower() in {".bat", ".cmd", ".ps1", ".sh", ".txt"} else ""
    else:
        wrapper = ""
    delivered = " ".join(str(a) for a in launch["delivered_args"])
    # Conservative warning gate; dynamic wrapper resolution still needs a launch receipt.
    muted = re.search(r"(?i)(?:--audio-driver[=\s\"']+Dummy\b|-Muted\b)", delivered + " " + wrapper)
    if launch["intent"] == "human" and (muted or launch["effective_audio_backend"].lower() == "dummy"):
        raise StudioError("Human launch contradicts local audio intent; inspect delivered wrapper")
    for key in ("actions", "criteria"):
        if not isinstance(card[key], list) or not card[key]:
            raise StudioError("Card needs nonempty " + key)
    action_ids = [safe_id(a["id"]) for a in card["actions"]]
    criterion_ids = [safe_id(c["id"]) for c in card["criteria"]]
    if len(set(action_ids)) != len(action_ids) or len(set(criterion_ids)) != len(criterion_ids):
        raise StudioError("Duplicate card IDs")
    for action in card["actions"]:
        required(action, ["expected"])
    for criterion in card["criteria"]:
        required(criterion, ["dimension", "action_ids", "expected", "mandatory", "kind", "interval"])
        if criterion["dimension"] not in DIMENSIONS or criterion["kind"] not in {"temporal", "performance", "interaction", "audio", "visual"}:
            raise StudioError("Unknown criterion dimension/kind")
        if type(criterion["mandatory"]) is not bool or not criterion["action_ids"] or not set(criterion["action_ids"]) <= set(action_ids):
            raise StudioError("Criterion needs mandatory boolean and existing actions")
        interval(criterion["interval"], duration)
        if criterion["kind"] == "temporal":
            number(criterion.get("max_gap_seconds"), "temporal sample gap", .00001, 1)
        if criterion["kind"] == "performance":
            number(criterion.get("p95_ms"), "p95 threshold", .01, 1000)
    return {"ok": True, "card_digest": digest(card)}


def tool_identity():
    kit = Path(__file__).resolve().parents[1]
    files = [file_record(kit, p) for p in sorted((kit / "studio_tools").rglob("*.py"))]
    files.append(file_record(kit, kit / "skills/studio-review/SKILL.md"))
    revision = None
    if (kit / ".git").exists():
        try:
            result = subprocess.run(["git", "-C", str(kit), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}\n?", result.stdout):
                revision = result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {"revision": revision, "source_digest": digest(files), "files": files,
            "invocation": "direct_file; registered adoption not inferred"}


def prepare_run(root, card, candidate, *, role="standalone", previous=None, affected=None):
    root = output_root(root)
    validate_card(card, candidate, root)
    if role not in {"before", "after", "standalone"}:
        raise StudioError("Unknown comparison role")
    recheck = 0
    previous_ref = None
    if previous:
        prior = validate_run(root, previous, current=False)
        if card["criteria"] != prior["card"]["criteria"] or card["actions"] != prior["card"]["actions"]:
            raise StudioError("Affected recheck cannot change original criteria/actions")
        recheck = prior["recheck"] + 1
        if recheck > prior["card"]["max_rechecks"] or card["max_rechecks"] != prior["card"]["max_rechecks"]:
            raise StudioError("Affected recheck budget exhausted or changed")
        if not affected or not set(affected) <= {c["id"] for c in prior["card"]["criteria"]}:
            raise StudioError("Affected recheck requires prior criterion IDs")
        previous_ref = file_record(root, relative(root, previous) / "run.json")
    run_id = uuid.uuid4().hex
    folder = relative(root, "artifacts/reviews/" + run_id)
    folder.mkdir(parents=True, exist_ok=False)
    entrypoint = relative(root, card["launch"]["entrypoint"])
    shutil.copyfile(entrypoint, folder / "entrypoint.original")
    record = {"schema_version": 1, "kind": "review-run", "run_id": run_id,
              "created_utc": datetime.now(timezone.utc).isoformat(), "role": role, "analysis_tool": tool_identity(),
              "card": card, "card_digest": digest(card), "candidate": candidate,
              "candidate_digest": digest(candidate), "recheck": recheck,
              "previous": previous_ref, "affected": affected or [],
              "entrypoint": file_record(root, folder / "entrypoint.original")}
    write_json(folder / "run.json", record)
    return folder.relative_to(root).as_posix()


def validate_run(root, name, *, current=True):
    folder = relative(root, name)
    data = read_json(folder / "run.json")
    if data.get("schema_version") != 1 or data.get("kind") != "review-run":
        raise StudioError("Expected review-run schema_version 1")
    if data["card_digest"] != digest(data["card"]) or data["candidate_digest"] != digest(data["candidate"]):
        raise StudioError("Review run identity changed")
    validate_card(data["card"], data["candidate"], root, current=current)
    verify_file(root, data["entrypoint"])
    if data["previous"]:
        verify_file(root, data["previous"])
    for stage in ("capture", "analysis", "assessment"):
        path = folder / (stage + ".json")
        if path.exists():
            stage_data = read_json(path)
            if stage_data.get("run_sha256") != sha256(folder / "run.json"):
                raise StudioError("Stale " + stage + " run identity")
            for item in stage_data.get("files", []):
                verify_file(root, item)
    return data


def temporal_gate(criterion, timestamps, analysis):
    start, end = interval(criterion["interval"])
    pts = sorted(t for t in timestamps if start <= t <= end)
    gaps = [b-a for a, b in zip([start] + pts, pts + [end])]
    gap = max(gaps, default=end-start)
    reason = "Requested sampling and decoded frames do not establish model perception"
    if gap > criterion["max_gap_seconds"]:
        reason = "Decoded temporal coverage exceeds the required gap"
    # This backend has not yet passed independent original-fixture detection.
    # User/model-supplied fixture_detection strings must never unlock a pass.
    return {"status": "unverified", "reason": reason, "decoded_max_gap_seconds": gap,
            "effective_model_gap_seconds": None, "detection_envelope": "not_established"}


def frame_times(rows, selected, p95_ms):
    start, end = interval(selected)
    if not isinstance(rows, list) or not rows:
        raise StudioError("Need complete per-frame timing rows")
    last = -1
    samples = []
    for row in rows:
        t = number(row["time_seconds"], "frame timestamp", maximum=86400)
        ms = number(row["frame_ms"], "frame time", .000001, 60000)
        if t <= last:
            raise StudioError("Per-frame timestamps must increase")
        last = t
        if start <= t < end:
            samples.append((t, ms))
    if not samples:
        raise StudioError("No frame timings in selected interval")
    values = sorted(ms for _, ms in samples)
    result = {"method": "nearest-rank over all selected per-frame wall times", "sample_count": len(values),
              "interval": selected, "max_ms": max(values),
              "stalls": [{"time_seconds": t, "frame_ms": ms} for t, ms in samples if ms >= 100]}
    for percentile in (50, 95, 99):
        result[f"p{percentile}_ms"] = values[math.ceil(len(values)*percentile/100)-1]
    result["status"] = "pass" if result["p95_ms"] <= p95_ms and not result["stalls"] else "fail"
    return result


def compare_runs(root, before, after):
    a, b = [validate_run(root, name, current=False) for name in (before, after)]
    mismatches = [key for key in ("settings", "route_id", "input_route", "criteria", "actions", "duration_seconds") if a["card"][key] != b["card"][key]]
    for key in ("intent", "effective_audio_backend", "live_services"):
        if a["card"]["launch"][key] != b["card"]["launch"][key]:
            mismatches.append("launch." + key)
    if a["candidate"]["engine"] != b["candidate"]["engine"]:
        mismatches.append("engine")
    if a["role"] != "before" or b["role"] != "after":
        mismatches.append("before/after roles")
    assessments = []
    captures = []
    for name in (before, after):
        folder = relative(root, name)
        if not (folder / "capture.json").exists() or read_json(folder / "capture.json")["status"] != "completed":
            mismatches.append("complete capture")
        if (folder / "capture.json").exists():
            captures.append(read_json(folder / "capture.json"))
        if not (folder / "assessment.json").exists():
            mismatches.append("assessment")
        else:
            assessments.append(read_json(folder / "assessment.json"))
    if len(captures) == 2:
        if captures[0]["source"]["route"] != captures[1]["source"]["route"]:
            mismatches.append("recorder route")
        for key in ("requested_fps", "audio_capture_source", "exclusions"):
            if captures[0].get(key) != captures[1].get(key):
                mismatches.append("capture." + key)
        profiles = [[{k: stream.get(k) for k in ("codec_type", "width", "height", "sample_rate", "channels")} for stream in (cap.get("media") or {}).get("streams", [])] for cap in captures]
        if profiles[0] != profiles[1]:
            mismatches.append("capture stream settings")
    return {"comparable": not mismatches, "mismatches": sorted(set(mismatches)),
            "results": assessments if not mismatches else [],
            "decision": "affected_recheck" if mismatches else "compare criterion evidence; human acceptance remains separate"}


def interaction_result(criterion, actions):
    expected = criterion.get("expected_state")
    start, end = interval(criterion["interval"])
    matching = [a for a in actions if a.get("id") in criterion["action_ids"]]
    if not expected or {a["id"] for a in matching} != set(criterion["action_ids"]):
        return {"status": "unverified", "reason": "Missing expected state or action evidence"}
    for action in matching:
        if any(k not in action for k in ("input_seconds", "outcome_seconds", "before_state", "after_state")):
            return {"status": "unverified", "reason": "Input alone does not establish an outcome"}
        t = number(action["input_seconds"], "input timestamp")
        outcome = number(action["outcome_seconds"], "outcome timestamp")
        if not start <= t <= outcome <= end:
            raise StudioError("Action/outcome lies outside the criterion interval")
        if action["after_state"] != expected or action["before_state"] == expected:
            return {"status": "fail", "reason": "Expected state transition did not follow the recorded input", "actions": matching}
    return {"status": "pass", "reason": "Recorded input followed by the expected state transition", "actions": matching}


def assess(root, name, evidence=None):
    """Compute only supported assertions; model proposals never certify perception."""
    data = validate_run(root, name, current=False)
    folder = relative(root, name)
    if (folder / "assessment.json").exists():
        raise StudioError("Assessment is immutable; create an affected recheck")
    capture = read_json(folder / "capture.json") if (folder / "capture.json").exists() else None
    analysis = read_json(folder / "analysis.json") if (folder / "analysis.json").exists() else None
    files = [file_record(root, folder / "capture.json")] if capture else []
    facts = {}
    if analysis:
        files.append(file_record(root, folder / "analysis.json"))
    if evidence:
        source = relative(root, evidence)
        facts = read_json(source)
        expected = {"run_id": data["run_id"], "candidate_id": data["candidate"]["candidate_id"],
                    "clip_sha256": sha256(folder / "capture.mp4") if capture else None}
        if any(facts.get(k) != v for k, v in expected.items()):
            raise StudioError("Timing/action evidence belongs to different run/candidate/media")
        if facts.get("input_route") != data["card"]["input_route"]:
            raise StudioError("Action evidence route differs from the card")
        for item in facts.get("files", []):
            verify_file(root, item)
            files.append(item)
        shutil.copyfile(source, folder / "observations.original.json")
        files.append(file_record(root, folder / "observations.original.json"))
    results = []
    for criterion in data["card"]["criteria"]:
        item = {"criterion_id": criterion["id"], "dimension": criterion["dimension"], "interval": criterion["interval"],
                "status": "not_run", "reason": "Required observation has not been performed", "coverage": data["card"]["input_route"]}
        proposals = [f for f in (analysis or {}).get("findings", []) if f["criterion_id"] == criterion["id"]]
        if not capture or capture["status"] != "completed":
            item.update(status="unverified", reason="Complete finalized capture required")
        elif criterion["kind"] == "temporal":
            item.update(temporal_gate(criterion, capture["media"]["timestamps_seconds"], analysis or {}))
        elif criterion["kind"] == "interaction" and facts:
            item.update(interaction_result(criterion, facts.get("actions", [])))
        elif criterion["kind"] == "performance" and facts.get("timing"):
            timing = facts["timing"]
            required(timing, ["file", "method", "interval", "clock_offset_seconds", "clock_uncertainty_seconds"])
            raw_path = verify_file(root, timing["file"])
            files.append(timing["file"])
            if timing["method"] != "wall_frame_time" or timing["interval"] != criterion["interval"]:
                raise StudioError("Performance needs matching raw wall frame timing interval")
            uncertainty = number(timing["clock_uncertainty_seconds"], "clock uncertainty", 0, 1200)
            offset = number(timing["clock_offset_seconds"], "clock offset", -86400, 86400)
            rows = read_json(raw_path)
            aligned = [{"time_seconds": row["time_seconds"] + offset, "frame_ms": row["frame_ms"]} for row in rows]
            start, end = criterion["interval"]
            if not aligned or abs(aligned[0]["time_seconds"] - start) > .002 or abs(aligned[-1]["time_seconds"] + aligned[-1]["frame_ms"]/1000 - end) > .002:
                raise StudioError("Raw timing rows do not cover the complete declared interval")
            if any(abs(b["time_seconds"] - a["time_seconds"] - a["frame_ms"]/1000) > .002 for a, b in zip(aligned, aligned[1:])):
                raise StudioError("Raw wall timing has missing/inconsistent frame intervals")
            item.update(frame_times(aligned, criterion["interval"], criterion["p95_ms"]))
            item["clock_uncertainty_seconds"] = uncertainty
            if uncertainty > .0334 or facts.get("host_interference") is not False:
                item.update(status="unverified", reason="Clock alignment or host/recorder interference requires recheck")
            else:
                item["reason"] = "Computed from complete raw wall-frame intervals"
        elif criterion["kind"] == "audio":
            item.update(status="unverified", reason="Audio stream/PCM and model text do not demonstrate output listening; record actual named listening review")
        elif proposals:
            item.update(status="unverified", reason="Perceptual proposal requires independent review of the cited video interval")
        for finding in proposals:
            start, end = interval(finding["interval"], data["card"]["duration_seconds"])
            if start < criterion["interval"][0] or end > criterion["interval"][1]:
                raise StudioError("Analyzer finding lies outside the criterion interval")
        if proposals:
            item["observations"] = proposals
            if any(f["status"] == "fail" for f in proposals) and analysis["status"] == "observations_received":
                item.update(status="fail", reason="Analyzer reports a defect in cited video; provisional pending independent confirmation")
        results.append(item)
    mandatory = [r for r, c in zip(results, data["card"]["criteria"]) if c["mandatory"]]
    complete = all(r["status"] == "pass" for r in mandatory) and data["card"]["input_route"] in {"ordinary", "human"}
    failed = [r["criterion_id"] for r in mandatory if r["status"] == "fail"]
    pending = [r["criterion_id"] for r in mandatory if r["status"] not in {"pass", "fail"}]
    result = {"schema_version": 1, "run_sha256": sha256(folder / "run.json"), "results": results,
              "mandatory_failures": failed, "pending": pending, "technical_criteria_complete": complete,
              "production_acceptance": "pending_independent_review", "native_capability": "unverified",
              "next_decision": "repair_and_affected_recheck_before_integrated_expansion" if failed else "complete_missing_evidence" if pending else "independent_review",
              "files": files}
    write_json(folder / "assessment.json", result)
    return result
