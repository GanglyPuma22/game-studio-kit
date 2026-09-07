"""Adopt named review evidence once, then derive qualification from retained cases.

The host trust list is an explicit checkpoint decision, not cryptographic proof
that a human listened. Hashes bind that decision to bytes and detect later drift.
Test approvals exercise the same path but can never confer production capability.
"""
from pathlib import Path
import uuid
import re
from .common import StudioError, digest, file_record, read_json, relative, sha256, write_json
from .records import required, verify_file, validate_listening, VERDICTS


# Code-owned question contract: the same neutral questions for every corpus role.
# Version independently of media/truth v2. No outcome labels or exact events here.
PROMPT_CONTRACT_ID = "studio-review-neutral-v1"
NEUTRAL_QUESTIONS = {"duration_seconds": 2,
    "actions": [{"id": "move", "expected": "Inspect continuous movement, cue and controlled state change"}],
    "criteria": [
            {"id": "TEMP", "dimension": "motion", "kind": "temporal", "action_ids": ["move"], "expected": "Classify observed disappearance, game stall, or recorder loss with boundaries", "mandatory": True, "interval": [0, 2], "dense_interval": [.7, 1.3], "max_gap_seconds": .0334, "minimum_event_seconds": .1},
            {"id": "INPUT", "dimension": "interaction", "kind": "interaction", "action_ids": ["move"], "expected": "Blue input marker precedes active green state", "expected_state": "active", "mandatory": False, "interval": [0, 2]},
            {"id": "SOUND", "dimension": "audio", "kind": "audio", "action_ids": ["move"], "expected": "Locate the original cue or its absence", "mandatory": True, "interval": [0, 2]},
            {"id": "WORLD", "dimension": "visual", "kind": "visual", "action_ids": ["move"], "expected": "Original scene is legible", "mandatory": True, "interval": [0, 2]}]}

def validate_neutral_run(run):
    card = run["card"]
    if (card.get("prompt_contract_id") != PROMPT_CONTRACT_ID
        or any(card.get(k) != value for k, value in NEUTRAL_QUESTIONS.items())
        or not re.fullmatch(r"[0-9a-f]{32}", run["run_id"])
        or not re.fullmatch(r"[0-9a-f]{32}", run["candidate"]["candidate_id"])):
        raise StudioError("Qualification requires the frozen neutral contract and opaque run/candidate identities")


def approve(config, root, source):
    path = relative(root, source)
    value = read_json(path)
    required(value, ["schema_version", "observer", "role", "scope"])
    policy = config.get("review_trust", {}).get(value["observer"], {})
    if (value["schema_version"] != 1 or value["scope"] not in {"test", "operational"}
        or value["scope"] != policy.get("scope") or value["role"] not in policy.get("roles", [])
        or sha256(path) not in policy.get("approved_sha256", [])):
        raise StudioError("Review record is not approved by the named host review_trust checkpoint")
    return value, {"observer": value["observer"], "role": value["role"], "scope": value["scope"],
                   "approved_sha256": sha256(path), "policy_digest": digest(policy)}


def _save(root, value, authorization, source, kind, extra=None):
    folder = relative(root, "artifacts/review-imports/" + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "review.original.json").write_bytes(relative(root, source).read_bytes())
    write_json(folder / "checkpoint.json", authorization)
    result = {"schema_version": 1, "kind": kind, "review": value, "authorization": authorization,
              "files": [file_record(root, folder / "review.original.json"), file_record(root, folder / "checkpoint.json")], **(extra or {})}
    write_json(folder / "receipt.json", result)
    return file_record(root, folder / "receipt.json")


def ingest(config, root, name, source, *, validate_only=False):
    from .validation import interval, validate_run
    run = validate_run(root, name, current=False, check_assessment=not validate_only, config=config)
    folder = relative(root, name)
    value, authorization = approve(config, root, source)
    capture = read_json(folder / "capture.json")
    expected = {"run_sha256": sha256(folder / "run.json"), "clip_sha256": sha256(folder / "capture.mp4")}
    if value.get("kind") != "observations" or any(value.get(k) != v for k, v in expected.items()):
        raise StudioError("Named observation belongs to a different run/media")
    if value["role"] not in {"independent_reviewer", "listener", "operator"}:
        raise StudioError("Observation needs a reviewer/listener/operator role")
    if value["role"] == "independent_reviewer" and value["observer"] == run["card"]["owner"]:
        raise StudioError("Independent reviewer must differ from the run owner")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise StudioError("Named review needs criterion observations")
    criteria = {c["id"]: c for c in run["card"]["criteria"]}
    for observation in observations:
        required(observation, ["criterion_id", "kind", "status", "interval", "observation", "files"])
        criterion = criteria.get(observation["criterion_id"])
        if not criterion or observation["kind"] != criterion["kind"] or observation["status"] not in VERDICTS:
            raise StudioError("Review criterion/kind/status differs from the card")
        if not isinstance(observation["observation"], str) or not observation["observation"].strip():
            raise StudioError("Named review needs a concrete observation")
        start, end = interval(observation["interval"], run["card"]["duration_seconds"])
        if start > criterion["interval"][0] or end < criterion["interval"][1]:
            raise StudioError("Named review does not cover the criterion interval")
        if not observation["files"]:
            raise StudioError("Named review requires retained source notes/evidence")
        for item in observation["files"]:
            verify_file(root, item)
        if value["role"] == "listener" and observation["kind"] != "audio":
            raise StudioError("Listener role can adopt only audio observations")
        if observation["kind"] == "interaction":
            from .validation import interaction_result, number
            if observation.get("input_route") != run["card"]["input_route"]:
                raise StudioError("Named interaction needs the actual input route")
            actions = observation.get("actions", [])
            checked = interaction_result(criterion, actions)
            uncertainty = number(observation.get("clock_uncertainty_seconds"), "observed action clock uncertainty", 0, 1200)
            if any(a.get("outcome_seconds", 0) - a.get("input_seconds", 0) <= 2 * uncertainty for a in actions):
                checked["status"] = "unverified"
            if checked["status"] != observation["status"]:
                raise StudioError("Named interaction verdict lacks a bounded input/outcome transition")
        if observation["kind"] == "performance":
            from .validation import number
            measured = observation.get("wall_timing", {})
            if measured.get("method") != "wall_frame_time":
                raise StudioError("Named performance review needs wall timing, not encoded/GPU FPS")
            p95 = number(measured.get("p95_ms"), "reviewed p95", .000001, 1200000)
            maximum = number(measured.get("max_ms"), "reviewed max frame time", p95, 1200000)
            uncertainty = number(measured.get("clock_uncertainty_seconds"), "reviewed clock uncertainty", 0, 1200)
            if observation["status"] == "pass" and (p95 > criterion["p95_ms"] or maximum >= 100 or uncertainty > .0334 or measured.get("host_interference") != "none_observed"):
                raise StudioError("Named performance pass contradicts retained timing/host observations")
            if criterion.get("requires_recorder_off"):
                raise StudioError("Recorder overhead criterion needs paired raw on/off timing inputs")
        if observation["kind"] == "temporal":
            coverage = observation.get("temporal_coverage", {})
            if coverage.get("interval") != criterion.get("dense_interval", criterion["interval"]) or type(coverage.get("max_gap_seconds")) not in (int, float) or not 0 < coverage["max_gap_seconds"] <= criterion["max_gap_seconds"]:
                raise StudioError("Temporal named review needs actual bounded dense coverage")
        if observation["kind"] == "audio":
            validate_listening(observation.get("listening"), value["observer"])
            relation = observation.get("audio_relation", {})
            if (relation.get("source_sha256") != expected["clip_sha256"]
                or relation.get("capture_source") != capture["audio_capture_source"]
                or relation.get("mode") not in {"recorded_playback", "live_output"}
                or relation.get("output_route") != observation["listening"]["playback_route"]):
                raise StudioError("Listening must explain the capture-source to playback/output relationship")
            if observation["listening"]["interval_seconds"] != observation["interval"]:
                raise StudioError("Listening interval differs from the named observation")
            if criterion.get("requires_local_output") and relation["mode"] != "live_output":
                raise StudioError("This criterion needs local output listening, not recorded playback")
    if validate_only:
        return value
    return _save(root, value, authorization, source, "review-import")


def imported(root, reference, kind="review-import", *, config=None):
    path = verify_file(root, reference)
    record = read_json(path)
    if record.get("kind") != kind or record.get("schema_version") != 1:
        raise StudioError("Expected an adopted review receipt")
    original, checkpoint = [verify_file(root, f) for f in record["files"][:2]]
    if (read_json(original) != record["review"] or read_json(checkpoint) != record["authorization"]
        or sha256(original) != record["authorization"]["approved_sha256"]):
        raise StudioError("Adopted review/checkpoint identity changed")
    from .config import load
    approve(config or load(), root, original.relative_to(Path(root)).as_posix())
    for observation in record["review"].get("observations", []):
        for item in observation["files"]:
            verify_file(root, item)
    for item in record.get("inputs", []):
        verify_file(root, item)
    return record


def named_result(root, references, run, clip_hash, criterion, *, config=None, run_name=None):
    from .validation import interval
    matches = []
    for reference in references:
        adopted = imported(root, reference, config=config)
        from .config import load
        ingest(config or load(), root, run_name, adopted["files"][0]["path"], validate_only=True)
        review = adopted["review"]
        if review["run_sha256"] != run or review["clip_sha256"] != clip_hash:
            raise StudioError("Named review is stale for this run/media")
        for observation in review["observations"]:
            if observation["criterion_id"] == criterion["id"]:
                start, end = interval(observation["interval"])
                if start > criterion["interval"][0] or end < criterion["interval"][1] or observation["kind"] != criterion["kind"]:
                    raise StudioError("Named review coverage/kind mismatch")
                matches.append({"status": observation["status"], "reason": observation["observation"], "observer": review["observer"],
                    "review_role": review["role"], "evidence_scope": review["scope"], "review_receipt": reference, "temporal_coverage": observation.get("temporal_coverage")})
    if len(matches) > 1:
        raise StudioError("Conflicting/multiple reviews need one explicit checkpoint selection")
    return matches[0] if matches else None


def qualification_data(root, value, *, config=None):
    """Recompute ten role scores; never trust a precomputed qualified boolean."""
    from .validation import interval, validate_run
    from .review_media import CORPUS_ROLES
    if value.get("prompt_contract_id") != PROMPT_CONTRACT_ID:
        raise StudioError("Qualification requires approved neutral prompt contract v1; preserve older receipts")
    corpus_path = verify_file(root, value["corpus"])
    corpus = read_json(corpus_path)
    def corpus_file(reference):
        return file_record(root, verify_file(corpus_path.parent, reference))
    if corpus.get("corpus_id") != "studio-review-acceptance-v2" or set(corpus.get("roles", {})) != {f"M{i:02d}" for i in range(1, 11)}:
        raise StudioError("Qualification requires the versioned ten-role acceptance corpus")
    if corpus.get("schema_version") != 2 or corpus.get("unique_clips") != 8 or corpus.get("acceptance_roles") != 10 or corpus.get("dense_interval") != [.7, 1.3]:
        raise StudioError("Corpus version/counts/dense window differ from frozen acceptance v2")
    for i, (case, status, category, event) in enumerate(CORPUS_ROLES, 1):
        truth = corpus["roles"][f"M{i:02d}"]
        expected = {"case": case, "expected_status": status, "category": category, "event_interval": event,
                    "tolerance_seconds": .1 if i == 8 else 1/60 if i == 3 else .0334}
        if any(truth.get(k) != v for k, v in expected.items()):
            raise StudioError("Corpus ground truth/tolerances differ from frozen acceptance v2")
    hashes = [r["media"]["sha256"] for r in corpus["roles"].values()]
    if len(set(hashes)) != 8 or len({corpus["roles"][r]["media"]["sha256"] for r in ("M01", "M08", "M10")}) != 1:
        raise StudioError("Corpus must contain eight distinct media, with declared clean reuse only")
    cases = value.get("cases", [])
    if len(cases) != 10 or {c["role"] for c in cases} != set(corpus["roles"]):
        raise StudioError("Qualification must retain every required fault/control role")
    inputs = [value["corpus"], corpus_file(corpus["generator"]), corpus_file(corpus["ground_truth"])]
    if corpus.get("prompt_contract_id") != PROMPT_CONTRACT_ID:
        raise StudioError("Corpus requires the neutral prompt contract revision")
    scores, common, runs = [], None, {}
    shared_candidate = None
    for case in cases:
        role = case["role"]
        truth = corpus["roles"][role]
        run_name = case["run"]
        run = validate_run(root, run_name, current=False, check_assessment=False, config=config)
        validate_neutral_run(run)
        if shared_candidate is not None and shared_candidate != run["candidate"]["candidate_id"]:
            raise StudioError("Neutral corpus requires one shared opaque candidate identity")
        shared_candidate = run["candidate"]["candidate_id"]
        if value["observer"] == run["card"]["owner"]:
            raise StudioError("Qualification observer must be independent of corpus run owner")
        folder = relative(root, run_name)
        required(case, ["run_sha256", "analysis_sha256", "capture_sha256"])
        if (case["run_sha256"] != sha256(folder / "run.json") or case["analysis_sha256"] != sha256(folder / "analysis.json")
            or case["capture_sha256"] != sha256(folder / "capture.mp4")):
            raise StudioError("Evaluator case hashes differ from the reviewed run/analysis/media")
        analysis = read_json(folder / "analysis.json")
        capture = read_json(folder / "capture.json")
        if capture["source"].get("sha256") != truth["media"]["sha256"]:
            raise StudioError("Qualification clip differs from the corpus original")
        original_media = corpus_file(truth["media"])
        inputs += [corpus_file(truth["decoded"]), corpus_file(truth["telemetry"])]
        if truth.get("actions"):
            inputs.append(corpus_file(truth["actions"]))
        decoded = read_json(verify_file(corpus_path.parent, truth["decoded"]))
        if capture["media"]["timestamps_seconds"] != decoded["timestamps_seconds"]:
            raise StudioError("Corpus capture PTS differ from original decoded truth")
        if capture["source"]["route"] != "file" or capture["status"] != "completed":
            raise StudioError("Corpus qualification requires complete exact original-file captures")
        if analysis.get("status") != "observations_received" or not analysis.get("ok"):
            raise StudioError("Qualification needs a completed retained analyzer response/usage")
        if value["scope"] == "operational" and analysis.get("execution_scope") != "provider":
            raise StudioError("Test transport cannot qualify operational model capability")
        # validate_run replays target and corpus analysis through the same check.
        identity = analysis["identity"]
        binding = {"model": analysis["model"], "profile": analysis["profile"], "tool_source_digest": analysis["analysis_tool"]["source_digest"]}
        if common is not None and binding != common:
            raise StudioError("Qualification cases use different model/config/tool identities")
        common = binding
        reviewed = case.get("coverage", {})
        required(reviewed, ["interval", "max_gap_seconds", "evidence"])
        interval(reviewed["interval"], run["card"]["duration_seconds"])
        verify_file(root, reviewed["evidence"])
        inputs += [reviewed["evidence"], original_media, file_record(root, folder / "run.json"), file_record(root, folder / "capture.json"), file_record(root, folder / "analysis.json")]
        inputs += analysis["files"]
        findings = analysis["findings"]
        indexes = case.get("finding_indexes", [])
        if any(type(i) is not int or not 0 <= i < len(findings) for i in indexes):
            raise StudioError("Qualification finding index is invalid")
        selected = [findings[i] for i in indexes]
        if role in {"M04", "M05"}:
            from .validation import frame_times, wall_rows
            timing = read_json(verify_file(corpus_path.parent, truth["telemetry"]))
            wall = frame_times(wall_rows(timing, [0, 2], 0, .000001), [0, 2], 40)
            if (wall["status"] != ("fail" if role == "M04" else "pass")
                or role == "M05" and capture["media"]["max_pts_gap_seconds"] <= .1):
                raise StudioError("Game stall/recorder loss must retain distinct wall-timing and PTS controls")
        if role in {"M08", "M09"}:
            validate_listening(case.get("listening"), value["observer"])
            if case["listening"]["interval_seconds"] != [0, 2] or case.get("listened_clip_sha256") != identity["clip_sha256"]:
                raise StudioError("Audio corpus review requires exact clip and full positive/negative listening interval")
        expected_status = truth["expected_status"]
        success = bool(selected) and all(f["status"] == expected_status and f.get("category") == truth["category"] for f in selected)
        if truth.get("event_interval"):
            expected = truth["event_interval"]
            success = success and any(f.get("category") == truth["category"] and all(abs(x-y) <= truth["tolerance_seconds"] for x, y in zip(f["interval"], expected)) for f in selected)
        if role in {"M06", "M07"}:
            action_truth = read_json(verify_file(corpus_path.parent, truth["actions"]))
            def observed_transition(finding):
                action = finding.get("action", {})
                return (type(action.get("input_seconds")) in (int, float) and abs(action["input_seconds"] - action_truth["input_seconds"]) <= .0334
                    and action.get("outcome_window") == action_truth["outcome_window"]
                    and action.get("before_state") == action_truth["before_state"] and action.get("after_state") == action_truth["after_state"]
                    and (action.get("outcome_seconds") is None if role == "M07" else type(action.get("outcome_seconds")) in (int, float) and abs(action["outcome_seconds"] - action_truth["outcome_seconds"]) <= .0334))
            success = success and any(observed_transition(f) for f in selected)
        if role in {"M01", "M10"}:
            success = success and not any(f["status"] == "fail" for f in findings)
        dense = analysis["coverage"]
        if role in {"M01", "M02", "M03", "M10"}:
            max_gap = .016667 if role == "M03" else .0334
            coverage_ok = (reviewed["interval"] == corpus["dense_interval"] and type(reviewed["max_gap_seconds"]) in (int, float)
                and 0 < reviewed["max_gap_seconds"] <= max_gap and dense.get("dense_interval") == corpus["dense_interval"]
                and dense.get("dense_max_gap_seconds") is not None and dense["dense_max_gap_seconds"] <= max_gap
                and dense.get("full_video_submitted") is True)
            success = success and coverage_ok
        outcome = "detected" if expected_status == "fail" else "clean"
        if not success:
            outcome = "unsupported" if not selected or any(f["status"] == "unverified" for f in selected) else "false_positive" if expected_status == "pass" or role == "M09" else "miss_or_mislocalized"
        scores.append({"role": role, "status": outcome, "accepted": success, "mandatory": role != "M03", "finding_indexes": indexes})
        runs[role] = (run, folder)
    if runs["M10"][0].get("previous") != file_record(root, runs["M02"][1] / "run.json") or runs["M10"][0]["run_id"] == runs["M01"][0]["run_id"]:
        raise StudioError("Qualification repair must be a distinct affected recheck of the fault run")
    return {"prompt_contract_id": PROMPT_CONTRACT_ID, "binding": common, "scores": scores, "qualified": all(s["accepted"] for s in scores if s["mandatory"]),
        "max_gap_seconds": .0334, "minimum_event_seconds": .1, "corpus_digest": sha256(verify_file(root, value["corpus"])), "inputs": inputs}


def qualify(config, root, source):
    value, authorization = approve(config, root, source)
    if value.get("kind") != "qualification-evaluation" or value["role"] != "independent_qualifier":
        raise StudioError("Qualification needs an approved independent evaluator record")
    result = qualification_data(root, value, config=config)
    return _save(root, value, authorization, source, "review-qualification", result)


def qualified(root, reference, analysis, *, config=None):
    adopted = imported(root, reference, "review-qualification", config=config)
    recomputed = qualification_data(root, adopted["review"], config=config)
    if any(adopted.get(k) != v for k, v in recomputed.items()):
        raise StudioError("Qualification scores differ from retained corpus evidence")
    expected = {"model": analysis["model"], "profile": analysis["profile"], "tool_source_digest": analysis["analysis_tool"]["source_digest"]}
    if adopted["binding"] != expected:
        raise StudioError("Qualification model/config/tool is stale")
    return {**recomputed, "scope": adopted["review"]["scope"], "observer": adopted["review"]["observer"]}
