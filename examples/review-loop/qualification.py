#!/usr/bin/env python3
"""Executable TEST contract: eight originals, ten roles, zero provider/listening calls.

Simulated responses deliberately read the separate oracle. The actual request
builder sees only neutral identities/media/criteria. This tests ingestion and
scoring reachability, never model perception or actual human observations.
"""
import argparse
import copy
import uuid
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studio_tools import review_media, review_video, review_records, validation
from studio_tools.common import file_record, output_root, read_json, sha256, write_json
from studio_tools.config import load
from studio_tools.evidence import new_candidate


def create(destination):
    root = output_root(destination)
    if any(root.iterdir()):
        raise ValueError("Choose a new empty output root")
    config = load(overrides={"review_trust": {}})
    fixtures = root / "artifacts/originals"
    review_media.fixtures(config, fixtures)
    corpus = read_json(fixtures / "acceptance-roles.json")
    (root / "scene.txt").write_text("Original synthetic acceptance scene\n")
    candidate = new_candidate(root, uuid.uuid4().hex, "raster-v2", "synthetic")
    card = {"schema_version": 1, "work_card_id": "CONTRACT", "owner": "test generator",
        "candidate_id": candidate["candidate_id"], "content_digest": candidate["content_digest"],
        "duration_seconds": 2, "max_rechecks": 1, "settings": {"renderer": "raster", "resolution": [160, 96], "audio": "original cue"},
        "route_id": "original", "input_route": "synthetic",
        "launch": {"intent": "human", "entrypoint": "scene.txt", "entrypoint_sha256": sha256(root / "scene.txt"),
                   "delivered_args": [], "effective_audio_backend": "unknown", "import_audio_backend": "not_applicable", "live_services": "disabled"},
        "prompt_contract_id": review_records.PROMPT_CONTRACT_ID,
        **copy.deepcopy(review_records.NEUTRAL_QUESTIONS)}
    runs = {}
    for role, truth in corpus["roles"].items():
        previous = runs.get("M02") if role == "M10" else None
        run = validation.prepare_run(root, card, candidate, role="after" if previous else "before" if role == "M02" else "standalone",
            previous=previous, affected=["TEMP", "SOUND", "WORLD"] if previous else None)
        source = fixtures / truth["media"]["path"]
        capture = review_media.capture(config, root, run, {"route": "file", "source": str(source)})
        if not capture["ok"]:
            raise ValueError("Original fixture capture incomplete")
        review_media.dense_frames(config, root, run, corpus["dense_interval"])
        runs[role] = run
    budget = {"authorization_id": "offline-test-contract", "upload_authorized": True,
        "approved_media_sha256": [sha256(root / run / "capture.mp4") for run in runs.values()],
        "model": "gemini-3.7-flash", "max_requests": 10, "max_total_usd": 20, "reserve_per_request_usd": 2,
        "max_request_bytes": 1000000, "max_output_tokens": 4096, "rate_verified_utc": datetime.now(timezone.utc).isoformat(),
        "rates_model": "gemini-3.7-flash", "rates_profile": "standard-all-context",
        "rates_usd_per_million": {"input": .75, "output": 3.75, "thought": 3.75}}
    cases = []
    for role, run in runs.items():
        truth = corpus["roles"][role]
        def simulate(body, secret, timeout):
            request = json.loads(body)
            prompt = request["input"][-1]["text"]
            if any(word in prompt for word in ("ground-truth", "acceptance-roles", "missing_frame_indexes", '"M02"')):
                raise ValueError("Evaluator truth leaked into analyzer prompt")
            identity = {"run_id": read_json(root / run / "run.json")["run_id"], "candidate_id": candidate["candidate_id"],
                        "clip_sha256": sha256(root / run / "capture.mp4")}
            # This explicit test oracle is not a detector. M03 intentionally misses.
            finding = {"criterion_id": "SOUND" if role in {"M08", "M09"} else "INPUT" if role in {"M06", "M07"} else "TEMP",
                "status": "unverified" if role == "M03" else truth["expected_status"], "category": truth["category"],
                "interval": truth["event_interval"] or [0, 2], "observation": "SIMULATED test oracle; no model or human perception performed",
                "severity": "test", "hypothesis": "", "next_check": "Separate authorized actual evaluation"}
            if role in {"M06", "M07"}:
                finding["action"] = read_json(fixtures / truth["actions"]["path"])
                finding["action"].pop("source")
            return json.dumps({"id": "test-" + role, "model": budget["model"], "status": "completed", "usage": {"total_tokens": 100},
                "steps": [{"type": "model_output", "content": [{"type": "text", "text": json.dumps({**identity, "findings": [finding]})}]}]}).encode()
        result = review_video.analyze(config, root, run, budget, dense=run + "/dense-0/frames.json", transport=simulate)
        if not result["ok"]:
            raise ValueError("Simulated response contract failed")
        notes = root / run / "review-notes.txt"
        notes.write_text("TEST ONLY: original input and expected output inspected by deterministic example; no actual independent human/model evaluation.\n")
        cases.append({"role": role, "run": run, "run_sha256": sha256(root / run / "run.json"), "analysis_sha256": sha256(root / run / "analysis.json"), "capture_sha256": sha256(root / run / "capture.mp4"), "finding_indexes": [0], "coverage": {"interval": corpus["dense_interval"],
                      "max_gap_seconds": read_json(root / run / "dense-0/frames.json")["max_gap_seconds"], "evidence": file_record(root, notes)}})
        if role in {"M08", "M09"}:
            cases[-1].update(listening={"performed": True, "playback_route": "simulated original-file playback", "interval_seconds": [0, 2]}, listened_clip_sha256=sha256(root / run / "capture.mp4"))
    evaluator = {"schema_version": 1, "kind": "qualification-evaluation", "observer": "simulated independent reviewer",
        "role": "independent_qualifier", "scope": "test", "prompt_contract_id": review_records.PROMPT_CONTRACT_ID, "corpus": file_record(root, fixtures / "acceptance-roles.json"), "cases": cases}
    evaluation_path = root / "artifacts/test-evaluation.json"
    write_json(evaluation_path, evaluator)
    config["review_trust"][evaluator["observer"]] = {"scope": "test", "roles": ["independent_qualifier", "independent_reviewer"], "approved_sha256": [sha256(evaluation_path)]}
    qualification = review_records.qualify(config, root, evaluation_path.relative_to(root).as_posix())
    target = runs["M10"]
    notes = file_record(root, root / target / "review-notes.txt")
    observations = []
    for criterion in card["criteria"]:
        if criterion["id"] == "INPUT":
            continue
        observed = {"criterion_id": criterion["id"], "kind": criterion["kind"], "status": "pass", "interval": [0, 2],
            "observation": "SIMULATED bounded test review; no human inspection/listening", "files": [notes]}
        if criterion["kind"] == "temporal":
            observed["temporal_coverage"] = {"interval": [.7, 1.3], "max_gap_seconds": read_json(root / target / "dense-0/frames.json")["max_gap_seconds"]}
        if criterion["kind"] == "audio":
            observed["listening"] = {"performed": True, "playback_route": "simulated speakers", "interval_seconds": [0, 2]}
            observed["audio_relation"] = {"source_sha256": sha256(root / target / "capture.mp4"), "capture_source": "source file",
                "mode": "recorded_playback", "output_route": "simulated speakers"}
        observations.append(observed)
    review = {"schema_version": 1, "kind": "observations", "observer": evaluator["observer"], "role": "independent_reviewer", "scope": "test",
        "run_sha256": sha256(root / target / "run.json"), "clip_sha256": sha256(root / target / "capture.mp4"), "observations": observations}
    review_path = root / "artifacts/test-observations.json"
    write_json(review_path, review)
    config["review_trust"][review["observer"]]["approved_sha256"].append(sha256(review_path))
    adopted = review_records.ingest(config, root, target, review_path.relative_to(root).as_posix())
    facts = {"run_id": read_json(root / target / "run.json")["run_id"], "candidate_id": candidate["candidate_id"],
        "clip_sha256": sha256(root / target / "capture.mp4"), "input_route": "synthetic", "reviews": [adopted], "qualification": qualification}
    write_json(root / "artifacts/test-facts.json", facts)
    result = validation.assess(root, target, "artifacts/test-facts.json", config=config)
    validation.validate_run(root, target, current=False, config=config)
    write_json(root / "artifacts/test-host-config.json", config)
    result = {"scope": "test_contract_only", "unique_original_clips": 8, "acceptance_roles": 10, "runs": runs,
        "qualification": qualification, "review": adopted, "assessment": result,
        "actual_provider_calls": 0, "actual_listening": 0, "native_operations": 0,
        "limits": ["M03 intentionally unsupported", "Effective internal model sampling unknown", "M10 file recheck does not qualify native capture", "Test scope cannot confer production capability"]}
    write_json(root / "artifacts/qualification-example.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    print(json.dumps(create(parser.parse_args().output), indent=2))
