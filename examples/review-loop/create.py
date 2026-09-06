#!/usr/bin/env python3
"""Original offline recording -> decision -> affected recheck, without paid calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studio_tools.common import file_record, output_root, read_json, sha256, write_json
from studio_tools.config import load
from studio_tools.evidence import new_candidate
from studio_tools import review_media, validation


def create(destination):
    root = output_root(destination)
    if any(root.iterdir()):
        raise ValueError("Choose a new empty example output root")
    config = load()
    fixtures = root / "artifacts/original-media"
    review_media.fixtures(config, fixtures)
    results = {}
    before = None
    for role, case in (("before", "stutter"), ("after", "clean")):
        (root / "scene.txt").write_text("Original moving shoreline fixture: " + case + "\n")
        candidate = new_candidate(root, "original-" + role, "synthetic-raster-v1", "source-checkout")
        candidate_path = root / "artifacts" / (role + "-candidate.json")
        write_json(candidate_path, candidate)
        card = {"schema_version": 1, "work_card_id": "ORIGINAL-REVIEW", "owner": "example operator",
                "candidate_id": candidate["candidate_id"], "content_digest": candidate["content_digest"],
                "duration_seconds": 2, "max_rechecks": 1,
                "settings": {"renderer": "original raster", "resolution": [160, 96], "audio": "original cue"},
                "route_id": "moving-bank", "input_route": "synthetic",
                "launch": {"intent": "human", "entrypoint": "scene.txt", "entrypoint_sha256": sha256(root / "scene.txt"),
                           "delivered_args": [], "effective_audio_backend": "unknown", "import_audio_backend": "not_applicable", "live_services": "disabled"},
                "actions": [{"id": "move", "expected": "Marker moves across bank"}],
                "criteria": [
                    {"id": "TEMP", "dimension": "motion", "kind": "temporal", "action_ids": ["move"], "expected": "No disappearance in reviewed interval", "mandatory": True, "interval": [0, 2], "max_gap_seconds": .0334},
                    {"id": "PERF", "dimension": "performance", "kind": "performance", "action_ids": ["move"], "expected": "Original synthetic timing within declared 40 ms floor; no >=100 ms stall", "mandatory": True, "interval": [0, 2], "p95_ms": 40},
                    {"id": "SOUND", "dimension": "audio", "kind": "audio", "action_ids": ["move"], "expected": "Original cue heard", "mandatory": True, "interval": [0, 2]}]}
        write_json(root / "artifacts" / (role + "-card.json"), card)
        run = validation.prepare_run(root, card, candidate, role=role, previous=before, affected=["PERF"] if before else None)
        profile = {"route": "file", "source": str(fixtures / (case + ".mp4"))}
        write_json(root / "artifacts" / (role + "-profile.json"), profile)
        capture = review_media.capture(config, root, run, profile)
        review_media.dense_frames(config, root, run, [.7, 1.3])
        facts = {"run_id": read_json(root / run / "run.json")["run_id"], "candidate_id": candidate["candidate_id"],
                 "clip_sha256": sha256(root / run / "capture.mp4"), "input_route": "synthetic", "host_interference": False,
                 "actions": [], "timing": {"file": file_record(root, fixtures / (case + "-timing.json")), "method": "wall_frame_time",
                 "interval": [0, 2], "clock_offset_seconds": 0, "clock_uncertainty_seconds": 0},
                 "origin": "synthetic injected timing; not native game measurements"}
        evidence = "artifacts/" + role + "-observations.json"
        write_json(root / evidence, facts)
        assessment = validation.assess(root, run, evidence)
        results[role] = {"run": run, "capture": capture["status"], "criteria": {r["criterion_id"]: r["status"] for r in assessment["results"]}}
        before = run
    results["comparison"] = validation.compare_runs(root, results["before"]["run"], results["after"]["run"])
    results["limits"] = ["File recording only", "Model not called", "No native controls, recording or listening", "Synthetic timing is not game performance", "100ms perception pending"]
    write_json(root / "artifacts/example-result.json", results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    print(json.dumps(create(parser.parse_args().output), indent=2))
