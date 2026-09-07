"""Operational evidence attached to a work card, using existing verdict semantics."""
from datetime import datetime, timezone
import math
import hashlib
import json
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
    # Effective game args take precedence; do not execute or flatten wrapper branches.
    game_lines = [line for line in wrapper.splitlines() if line.strip() and
                  not line.lstrip().startswith(("#", "REM ", "rem ", "::")) and
                  "--import" not in line and "--headless" not in line and
                  not re.search(r"(?i)\b(if|else|elif|case)\b", line)]
    scanned = delivered if delivered else " ".join(game_lines)
    muted = re.search(r"(?i)(?:--audio-driver[=\s\"']+Dummy\b|-Muted\b)", scanned)
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
        if criterion["dimension"] not in DIMENSIONS or {"temporal": "motion", "performance": "performance", "interaction": "interaction", "audio": "audio", "visual": "visual"}.get(criterion["kind"]) != criterion["dimension"]:
            raise StudioError("Unknown criterion dimension/kind")
        if type(criterion["mandatory"]) is not bool or not criterion["action_ids"] or not set(criterion["action_ids"]) <= set(action_ids):
            raise StudioError("Criterion needs mandatory boolean and existing actions")
        interval(criterion["interval"], duration)
        if criterion["kind"] == "interaction":
            required(criterion, ["expected_state"])
        if criterion["kind"] == "temporal":
            number(criterion.get("max_gap_seconds"), "temporal sample gap", .00001, 1)
            if "dense_interval" in criterion:
                ds, de = interval(criterion["dense_interval"], duration)
                if ds < criterion["interval"][0] or de > criterion["interval"][1]:
                    raise StudioError("Dense interval must be inside its criterion")
            number(criterion.get("minimum_event_seconds", .1), "minimum detectable event duration", .00001, duration)
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


def prepare_run(root, card, candidate, *, role="standalone", previous=None, affected=None, config=None):
    root = output_root(root)
    validate_card(card, candidate, root)
    if role not in {"before", "after", "standalone"}:
        raise StudioError("Unknown comparison role")
    if affected and not previous:
        raise StudioError("Affected criteria require a previous run")
    recheck = 0
    previous_ref = None
    lineage = None
    if previous:
        prior = validate_run(root, previous, current=False, config=config)
        if card["criteria"] != prior["card"]["criteria"] or card["actions"] != prior["card"]["actions"]:
            raise StudioError("Affected recheck cannot change original criteria/actions")
        lineage = prior.get("lineage") or prior["run_id"]
        recheck = prior["recheck"] + 1
        if recheck > prior["card"]["max_rechecks"] or card["max_rechecks"] != prior["card"]["max_rechecks"]:
            raise StudioError("Affected recheck budget exhausted or changed")
        if not affected or not set(affected) <= {c["id"] for c in prior["card"]["criteria"]}:
            raise StudioError("Affected recheck requires prior criterion IDs")
        previous_ref = file_record(root, relative(root, previous) / "run.json")
    run_id = uuid.uuid4().hex
    if lineage:
        ledger = relative(root, "artifacts/review-lineages/" + lineage)
        ledger.mkdir(parents=True, exist_ok=True)
        try:
            lock = (ledger / "reserve.lock").open("x")
        except FileExistsError:
            raise StudioError("Recheck budget reservation is busy or interrupted; preserve its attempts") from None
        try:
            with lock:
                attempts = list(ledger.glob("attempt-*.json"))
                if len(attempts) >= card["max_rechecks"]:
                    raise StudioError("Recheck budget exhausted across lineage attempts")
                recheck = len(attempts) + 1
                write_json(ledger / ("attempt-" + run_id + ".json"), {"run_id": run_id, "previous": previous_ref, "attempt": recheck})
        finally:
            (ledger / "reserve.lock").unlink(missing_ok=True)
    folder = relative(root, "artifacts/reviews/" + run_id)
    folder.mkdir(parents=True, exist_ok=False)
    entrypoint = relative(root, card["launch"]["entrypoint"])
    shutil.copyfile(entrypoint, folder / "entrypoint.original")
    record = {"schema_version": 1, "kind": "review-run", "run_id": run_id,
              "created_utc": datetime.now(timezone.utc).isoformat(), "role": role, "analysis_tool": tool_identity(),
              "card": card, "card_digest": digest(card), "candidate": candidate,
              "candidate_digest": digest(candidate), "recheck": recheck, "lineage": lineage or run_id,
              "previous": previous_ref, "affected": affected or [],
              "entrypoint": file_record(root, folder / "entrypoint.original")}
    write_json(folder / "run.json", record)
    return folder.relative_to(root).as_posix()


def validate_run(root, name, *, current=True, check_assessment=True, config=None):
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
    if (folder / "capture.json").exists():
        from .review_media import validate_capture
        from .config import load
        validate_capture(config or load(), root, name, data)
    if (folder / "analysis.json").exists():
        from .review_video import validate_analysis
        validate_analysis(root, name, data, read_json(folder / "analysis.json"))
    if check_assessment and (folder / "assessment.json").exists():
        saved = read_json(folder / "assessment.json")
        recomputed = assess(root, name, _recompute=True, config=config)
        if saved != recomputed:
            raise StudioError("Assessment decisions differ from retained bound inputs")
    return data


def temporal_gate(criterion, timestamps, analysis, *, qualification=None, review=None):
    selected = criterion.get("dense_interval", criterion["interval"])
    start, end = interval(selected)
    pts = sorted(t for t in timestamps if start <= t <= end)
    gap = max((b-a for a, b in zip([start] + pts, pts + [end])), default=end-start)
    result = {"status": "unverified", "reason": "Independent qualification and bounded reviewed coverage required",
              "decoded_max_gap_seconds": gap, "effective_model_gap_seconds": None, "detection_envelope": "not_established"}
    if review and review["status"] == "fail":
        return {**result, **review}
    if gap > criterion["max_gap_seconds"]:
        result["reason"] = "Decoded temporal coverage exceeds the required gap"
        return result
    if not qualification or not qualification["qualified"] or not review or review["status"] != "pass":
        return result
    coverage = analysis.get("coverage", {})
    reviewed = review.get("temporal_coverage", {})
    dense = coverage.get("dense_interval")
    if (analysis.get("status") != "observations_received" or not analysis.get("ok") or not dense
        or dense[0] > start or dense[1] < end or not coverage.get("full_video_submitted")
        or qualification["max_gap_seconds"] > criterion["max_gap_seconds"]
        or qualification["minimum_event_seconds"] > criterion.get("minimum_event_seconds", .1)
        or coverage.get("dense_max_gap_seconds", 1200) > criterion["max_gap_seconds"]
        or reviewed.get("interval") != selected or reviewed.get("max_gap_seconds", 1200) > criterion["max_gap_seconds"]):
        return result
    if analysis.get("execution_scope") not in {"test", "provider"}:
        result["reason"] = "Target analyzer execution scope is not established"
        return result
    result.update(status="pass", reason="Qualified fault/control envelope and named review cover the declared interval",
                  submitted_max_gap_seconds=reviewed["max_gap_seconds"], detection_envelope=qualification["minimum_event_seconds"],
                  evidence_scope="test" if "test" in {analysis["execution_scope"], qualification["scope"], review["evidence_scope"]} else "operational",
                  observer=review["observer"], review_receipt=review["review_receipt"])
    return result


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


def compare_runs(root, before, after, *, config=None):
    a, b = [validate_run(root, name, current=False, config=config) for name in (before, after)]
    mismatches = []
    if b.get("previous") != file_record(root, relative(root, before) / "run.json"):
        mismatches.append("after run does not reference selected before")
    for card in (a["card"], b["card"]):
        needed = set(["renderer", "resolution", "audio"] + card.get("comparison_fields", []))
        def known(value):
            if value is None or isinstance(value, str) and value.strip().lower() in {"", "unknown", "unverified", "not_defined"}:
                return False
            if isinstance(value, (list, dict)):
                return bool(value) and all(known(v) for v in (value.values() if isinstance(value, dict) else value))
            return True
        if not needed or not all(k in card["settings"] and known(card["settings"][k]) for k in needed):
            mismatches.append("effective comparison settings unknown")
    mismatches += [key for key in ("settings", "route_id", "input_route", "criteria", "actions", "duration_seconds") if a["card"][key] != b["card"][key]]
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
        for key in ("requested_fps", "audio_capture_source", "exclusions", "encoder", "fps_mode"):
            if captures[0].get(key) != captures[1].get(key):
                mismatches.append("capture." + key)
        profiles = [[{k: stream.get(k) for k in ("codec_type", "codec_name", "profile", "width", "height", "sample_rate", "channels", "r_frame_rate", "time_base")} for stream in (cap.get("media") or {}).get("streams", [])] for cap in captures]
        for cap, streams in zip(captures, profiles):
            video = [stream for stream in streams if stream.get("codec_type") == "video"]
            if len(video) != 1 or not all(video[0].get(k) for k in ("codec_name", "profile", "r_frame_rate", "time_base", "width", "height")):
                mismatches.append("capture acquisition profile unknown")
            elif cap.get("requested_fps") is not None:
                from fractions import Fraction
                try:
                    if Fraction(video[0]["r_frame_rate"]) != cap["requested_fps"]:
                        mismatches.append("requested and recorded cadence differ")
                except (ValueError, ZeroDivisionError):
                    mismatches.append("recorded cadence invalid")
            if cap.get("encoder") in {None, "unknown"} or cap.get("fps_mode") in {None, "unknown"}:
                mismatches.append("capture encoder/cadence mode unknown")
        if profiles[0] != profiles[1]:
            mismatches.append("capture stream settings")
    return {"comparable": not mismatches, "mismatches": sorted(set(mismatches)),
            "results": assessments if not mismatches else [],
            "criterion_changes": [{"criterion_id": old["criterion_id"], "before": old["status"], "after": new["status"], "affected": old["criterion_id"] in b["affected"]}
                for old, new in zip(assessments[0]["results"], assessments[1]["results"])] if len(assessments) == 2 else [],
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


def wall_rows(rows, selected, offset, precision):
    """Validate complete wall coverage before deriving any percentile."""
    start, end = interval(selected)
    if not isinstance(rows, list) or not rows:
        raise StudioError("Need complete raw wall timing rows")
    aligned = [{"time_seconds": number(row["time_seconds"], "frame timestamp", -86400, 86400) + offset,
                "frame_ms": number(row["frame_ms"], "frame duration", .000001, 1200000)} for row in rows]
    if abs(sum(row["frame_ms"] for row in aligned)/1000 - (end-start)) > precision * 2:
        raise StudioError("Total raw frame durations leave missing wall time")
    if abs(aligned[0]["time_seconds"] - start) > precision or abs(aligned[-1]["time_seconds"] + aligned[-1]["frame_ms"]/1000 - end) > precision:
        raise StudioError("Raw timing rows do not cover the complete declared interval")
    if any(abs(b["time_seconds"] - a["time_seconds"] - a["frame_ms"]/1000) > precision * 2 for a, b in zip(aligned, aligned[1:])):
        raise StudioError("Raw wall timing has missing/inconsistent frame intervals")
    return aligned


def action_trace(root, reference, run, clip_hash, criterion):
    path = verify_file(root, reference)
    trace = read_json(path)
    required(trace, ["run_sha256", "clip_sha256", "observer", "provenance", "input_route", "clock", "source_evidence", "actions"])
    if trace["run_sha256"] != run["sha256"] or trace["clip_sha256"] != clip_hash or trace["input_route"] != run["input_route"]:
        raise StudioError("Raw action source needs matching run/media/input route")
    clock = trace["clock"]
    offset = number(clock.get("offset_seconds"), "action clock offset", -86400, 86400)
    uncertainty = number(clock.get("uncertainty_seconds"), "action clock uncertainty", 0, 1200)
    precision = number(clock.get("precision_seconds"), "action clock precision", .000000001, .001)
    if trace["provenance"] not in {"synthetic", "operator_reported"}:
        raise StudioError("Action provenance must be synthetic or operator_reported")
    verify_file(root, trace["source_evidence"])
    actions = [{**a, "input_seconds": a["input_seconds"] + offset, "outcome_seconds": a["outcome_seconds"] + offset} for a in trace["actions"] if a["id"] in criterion["action_ids"]]
    result = interaction_result(criterion, actions)
    if any(a["outcome_seconds"] - a["input_seconds"] <= 2 * (uncertainty + precision) + 1e-12 for a in actions):
        result.update(status="unverified", reason="Clock precision and uncertainty cannot establish input before outcome")
    result.update(observer=trace["observer"], evidence_scope="test" if trace["provenance"] == "synthetic" else "operator_reported")
    return result, trace["source_evidence"]


def criterion_timings(facts, criteria):
    """Map raw measurements only to their declared, applicable criterion."""
    performance = {c["id"]: c for c in criteria if c["kind"] == "performance"}
    if "timings" in facts and "timing" in facts:
        raise StudioError("Select timings by criterion ID or one legacy timing object, not both")
    if "timings" in facts:
        selected = facts["timings"]
        if not isinstance(selected, dict) or not set(selected) <= set(performance):
            raise StudioError("Timing collection requires existing performance criterion IDs")
        for key, timing in selected.items():
            if not isinstance(timing, dict) or timing.get("interval") != performance[key]["interval"]:
                raise StudioError("Timing collection interval differs from its criterion")
        return selected
    timing = facts.get("timing")
    if timing is None:
        return {}
    if not isinstance(timing, dict):
        raise StudioError("Legacy timing must be an object")
    matches = [key for key, c in performance.items() if timing.get("interval") == c["interval"]]
    if len(matches) != 1:
        raise StudioError("Legacy timing requires one matching criterion; use timings by criterion ID")
    return {matches[0]: timing}


def reserve_assessment(root, folder, evidence):
    """Local once-per-run reservation; not protection against replacing all originals."""
    marker = folder / "assessment-attempt.json"
    if (folder / "assessment.json").exists() or (folder / "observations.original.json").exists():
        raise StudioError("Assessment inputs already retained or immutable; create an affected recheck")
    try:
        stream = marker.open("x", encoding="utf-8")
    except FileExistsError:
        raise StudioError("Assessment attempt already retained; preserve it and create an affected recheck") from None
    except OSError as exc:
        raise StudioError("Cannot reserve assessment attempt in the run directory") from exc
    attempt = {"schema_version": 1, "kind": "assessment-attempt", "input_supplied": evidence is not None,
               "run_sha256": None, "input_sha256": None, "input_state": "unreadable" if evidence is not None else "not_supplied"}
    raw = None
    with stream:
        try:
            attempt["run_sha256"] = sha256(folder / "run.json")
            if evidence is not None:
                raw = relative(root, evidence).read_bytes()
                attempt.update(input_sha256=hashlib.sha256(raw).hexdigest(), input_state="snapshotted")
        except OSError as exc:
            raise StudioError("Assessment input/run cannot be retained; attempt reserved") from exc
        finally:
            json.dump(attempt, stream, indent=2, allow_nan=False)
            stream.write("\n")
    if raw is not None:
        try:
            with (folder / "observations.original.json").open("xb") as retained:
                retained.write(raw)
        except OSError as exc:
            raise StudioError("Cannot retain reserved assessment input; attempt remains") from exc


def assessment_input(root, folder):
    """Check a new attempt's snapshot; legacy read-only recompute stays unchanged."""
    marker = folder / "assessment-attempt.json"
    if not marker.exists():
        return None
    attempt = read_json(marker)
    if (attempt.get("schema_version") != 1 or attempt.get("kind") != "assessment-attempt"
        or attempt.get("run_sha256") != sha256(folder / "run.json")
        or type(attempt.get("input_supplied")) is not bool):
        raise StudioError("Assessment attempt identity changed")
    retained = folder / "observations.original.json"
    if attempt["input_supplied"]:
        if attempt.get("input_state") != "snapshotted" or not retained.is_file() or sha256(retained) != attempt.get("input_sha256"):
            raise StudioError("Reserved assessment input is missing or changed; preserve the failed attempt")
    elif retained.exists() or attempt.get("input_sha256") is not None or attempt.get("input_state") != "not_supplied":
        raise StudioError("No-input assessment attempt differs from retained input")
    return file_record(root, marker)

def assess(root, name, evidence=None, *, _recompute=False, config=None):
    """Compute only supported assertions; model proposals never certify perception."""
    folder = relative(root, name)
    if not _recompute:
        reserve_assessment(root, folder, evidence)
    attempt_ref = assessment_input(root, folder)
    data = validate_run(root, name, current=False, check_assessment=False, config=config)
    capture = read_json(folder / "capture.json") if (folder / "capture.json").exists() else None
    analysis = read_json(folder / "analysis.json") if (folder / "analysis.json").exists() else None
    files = [file_record(root, folder / "capture.json")] if capture else []
    if attempt_ref:
        files.append(attempt_ref)
    facts = {}
    if analysis:
        files.append(file_record(root, folder / "analysis.json"))
    if (folder / "observations.original.json").exists():
        evidence = (folder / "observations.original.json").relative_to(Path(root)).as_posix()
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
        files.append(file_record(root, folder / "observations.original.json"))
    reviews = facts.get("reviews", [])
    for reference in reviews:
        verify_file(root, reference)
        files.append(reference)
    qualification = None
    if facts.get("qualification"):
        if not analysis:
            raise StudioError("Qualification needs retained analysis for this run")
        from .review_records import qualified
        qualification = qualified(root, facts["qualification"], analysis, config=config)
        files.append(facts["qualification"])
    timings = criterion_timings(facts, data["card"]["criteria"])
    results = []
    for criterion in data["card"]["criteria"]:
        item = {"criterion_id": criterion["id"], "dimension": criterion["dimension"], "interval": criterion["interval"],
                "status": "not_run", "reason": "Required observation has not been performed", "coverage": data["card"]["input_route"]}
        from .review_records import named_result
        named = named_result(root, reviews, sha256(folder / "run.json"), sha256(folder / "capture.mp4") if capture else None, criterion, config=config, run_name=name)
        proposals = [f for f in (analysis or {}).get("findings", []) if f["criterion_id"] == criterion["id"]]
        if data["previous"] and criterion["id"] not in data["affected"]:
            item.update(status="not_run", reason="Unaffected prior evidence is not rebound to this candidate")
            results.append(item)
            continue
        if not capture or capture["status"] != "completed":
            item.update(status="unverified", reason="Complete finalized capture required")
        elif criterion["kind"] == "temporal":
            item.update(temporal_gate(criterion, capture["media"]["timestamps_seconds"], analysis or {}, qualification=qualification, review=named))
        elif criterion["kind"] == "interaction" and facts:
            if named:
                item.update(named)
            elif facts.get("action_source"):
                action, source = action_trace(root, facts["action_source"], {"sha256": sha256(folder / "run.json"), "input_route": data["card"]["input_route"]}, sha256(folder / "capture.mp4"), criterion)
                files += [facts["action_source"], source]
                item.update(action)
            else:
                item.update(status="unverified", reason="State strings need linked raw action provenance or a named adopted review")
        elif criterion["kind"] == "performance" and criterion["id"] in timings:
            timing = timings[criterion["id"]]
            required(timing, ["file", "method", "interval", "clock_offset_seconds", "clock_uncertainty_seconds"])
            raw_path = verify_file(root, timing["file"])
            files.append(timing["file"])
            if timing["method"] != "wall_frame_time" or timing["interval"] != criterion["interval"]:
                raise StudioError("Performance needs matching raw wall frame timing interval")
            uncertainty = number(timing["clock_uncertainty_seconds"], "clock uncertainty", 0, 1200)
            offset = number(timing["clock_offset_seconds"], "clock offset", -86400, 86400)
            rows = read_json(raw_path)
            precision = number(timing.get("clock_precision_seconds", .000001), "clock precision", .000000001, .001)
            start, end = criterion["interval"]
            aligned = wall_rows(rows, criterion["interval"], offset, precision)
            item.update(frame_times(aligned, criterion["interval"], criterion["p95_ms"]))
            item["clock_uncertainty_seconds"] = uncertainty
            context_ref = timing.get("context")
            context = read_json(verify_file(root, context_ref)) if context_ref else {}
            if context_ref:
                files.append(context_ref)
                required(context, ["observer", "provenance", "clock", "host_evidence", "run_sha256", "timing_sha256", "settings", "host_interference", "clock_evidence"])
                if context["run_sha256"] != sha256(folder / "run.json") or context["timing_sha256"] != timing["file"]["sha256"] or context["settings"] != data["card"]["settings"]:
                    raise StudioError("Timing provenance/context mismatch")
                if context["clock"] != {"offset_seconds": offset, "uncertainty_seconds": uncertainty, "precision_seconds": precision}:
                    raise StudioError("Timing clock differs from retained provenance")
                for source in (context["host_evidence"], context["clock_evidence"]):
                    verify_file(root, source)
                    files.append(source)
                if context["provenance"] not in {"synthetic", "operator_reported"}:
                    raise StudioError("Timing provenance must be synthetic or operator_reported")
                item.update(observer=context["observer"], evidence_scope="test" if context["provenance"] == "synthetic" else "operator_reported")
            if uncertainty > .0334 or context.get("host_interference") != "none_observed":
                item.update(status="unverified", reason="Clock alignment or host/recorder interference requires recheck")
            else:
                item["reason"] = "Computed from complete raw wall-frame intervals with retained observer/clock/host context"
            if timing.get("recorder_off"):
                reference = timing["recorder_off"]
                if reference.get("settings") != data["card"]["settings"] or reference.get("route_id") != data["card"]["route_id"] or reference.get("candidate_digest") != data["candidate"]["content_digest"]:
                    raise StudioError("Recorder-off reference is not a matched candidate/settings/route")
                off_context = read_json(verify_file(root, reference["context"]))
                files.append(reference["context"])
                required(off_context, ["measurement_id", "recording_active", "observer", "clock", "clock_evidence", "host_evidence", "timing_sha256", "settings", "route_id", "candidate_digest", "provenance", "host_interference"])
                if (context.get("recording_active") is not True or not context.get("measurement_id")
                    or off_context["recording_active"] is not False or off_context["measurement_id"] == context["measurement_id"]
                    or reference["file"]["sha256"] == timing["file"]["sha256"]
                    or off_context["timing_sha256"] != reference["file"]["sha256"]
                    or any(off_context[k] != reference[k] for k in ("settings", "route_id", "candidate_digest"))):
                    raise StudioError("Recorder-off measurement must be distinct, matched and recorded as off at source")
                for source in (off_context["host_evidence"], off_context["clock_evidence"]):
                    verify_file(root, source)
                    files.append(source)
                off_clock = off_context["clock"]
                off_offset = number(off_clock.get("offset_seconds"), "off clock offset", -86400, 86400)
                off_precision = number(off_clock.get("precision_seconds"), "off clock precision", .000000001, .001)
                if number(off_clock.get("uncertainty_seconds"), "off clock uncertainty", 0, 1200) > .0334:
                    raise StudioError("Recorder-off clock mapping is insufficient")
                off_rows = wall_rows(read_json(verify_file(root, reference["file"])), criterion["interval"], off_offset, off_precision)
                files.append(reference["file"])
                off = frame_times(off_rows, criterion["interval"], criterion["p95_ms"])
                if off_context["provenance"] not in {"synthetic", "operator_reported"}:
                    raise StudioError("Recorder-off provenance must be synthetic or operator_reported")
                if off_context["provenance"] == "synthetic":
                    item["evidence_scope"] = "test"
                comparison_valid = uncertainty <= .0334 and all(c.get("host_interference") == "none_observed" for c in (context, off_context))
                item["recorder_on"] = {"context": context_ref, "observer": context["observer"], "provenance": context["provenance"], "measurement_id": context["measurement_id"]}
                item["recorder_off"] = {"measurement": off, "context": reference["context"], "observer": off_context["observer"],
                    "provenance": off_context["provenance"], "measurement_id": off_context["measurement_id"], "host_interference": off_context["host_interference"],
                    "comparison_valid": comparison_valid, "p95_delta_ms": item["p95_ms"] - off["p95_ms"] if comparison_valid else None}
                if not comparison_valid and criterion.get("requires_recorder_off"):
                    item.update(status="unverified", reason="Host interference invalidates the required recorder-on/off comparison")
            elif criterion.get("requires_recorder_off"):
                item.update(status="unverified", reason="Matched recorder-off reference required")
        elif criterion["kind"] in {"audio", "visual", "performance"} and named:
            item.update(named)
        elif criterion["kind"] == "audio":
            item.update(status="unverified", reason="Adopt a named listening review with capture/output relationship")
        elif proposals:
            item.update(status="unverified", reason="Perceptual proposal requires independent review of the cited video interval")
        for finding in proposals:
            start, end = interval(finding["interval"], data["card"]["duration_seconds"])
            if start < criterion["interval"][0] or end > criterion["interval"][1]:
                raise StudioError("Analyzer finding lies outside the criterion interval")
        if proposals:
            item["observations"] = proposals
            if criterion["kind"] in {"temporal", "visual", "audio"} and any(f["status"] == "fail" for f in proposals) and analysis["status"] == "observations_received":
                item.update(status="fail", reason="Analyzer reports a defect in cited video; provisional pending independent confirmation")
        results.append(item)
    mandatory = [r for r, c in zip(results, data["card"]["criteria"]) if c["mandatory"]]
    complete = all(r["status"] == "pass" and r.get("evidence_scope") != "test" for r in mandatory) and data["card"]["input_route"] in {"ordinary", "human"}
    failed = [r["criterion_id"] for r in mandatory if r["status"] == "fail"]
    pending = [r["criterion_id"] for r in mandatory if r["status"] not in {"pass", "fail"}]
    result = {"schema_version": 1, "run_sha256": sha256(folder / "run.json"), "results": results,
              "mandatory_failures": failed, "pending": pending, "technical_criteria_complete": complete,
              "production_acceptance": "pending_independent_review", "native_capability": "unverified",
              "next_decision": "repair_and_affected_recheck_before_integrated_expansion" if failed else "complete_missing_evidence" if pending else "independent_review",
              "files": files}
    if not _recompute:
        write_json(folder / "assessment.json", result)
    return result
