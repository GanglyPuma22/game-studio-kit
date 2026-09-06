"""Original file/process tests; fake provider responses never prove perception."""
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio_tools.common import StudioError, read_json, write_json, sha256
from studio_tools.config import load
from studio_tools.evidence import new_candidate


class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scene.txt").write_text("original scene")
        self.candidate = new_candidate(self.root, "sample", "fixture", "test")
        self.card = {
            "schema_version": 1, "work_card_id": "W1", "owner": "reviewer",
            "candidate_id": "sample", "content_digest": self.candidate["content_digest"],
            "duration_seconds": 2, "max_rechecks": 1,
            "settings": {"renderer": "fixture", "resolution": [160, 96], "audio": "PCM"},
            "route_id": "bank", "input_route": "synthetic",
            "launch": {"intent": "human", "entrypoint": "scene.txt", "entrypoint_sha256": sha256(self.root / "scene.txt"),
                       "delivered_args": [], "effective_audio_backend": "unknown", "import_audio_backend": "Dummy", "live_services": "disabled"},
            "actions": [{"id": "walk", "expected": "move continuously"}],
            "criteria": [{"id": "TEMP", "dimension": "motion", "action_ids": ["walk"],
                          "expected": "No disappearance", "mandatory": True, "kind": "temporal",
                          "interval": [0, 2], "max_gap_seconds": .0334}],
        }
        self.config = load()

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("studio_tools.validation"), "review run implementation missing")
        from studio_tools import validation
        return validation



class ValidationLoop(ReviewFixture):
    def test_valid_card_and_hidden_dummy_launch_failure(self):
        api = self.api()
        self.assertTrue(api.validate_card(self.card, self.candidate, self.root)["ok"])
        for mutation in ({"delivered_args": ["--audio-driver", "Dummy"]}, {"delivered_args": ["-Muted"]}, {"effective_audio_backend": "Dummy"}):
            card = copy.deepcopy(self.card)
            card["launch"].update(mutation)
            with self.assertRaisesRegex(StudioError, "human.*audio|Human.*audio"):
                api.validate_card(card, self.candidate, self.root)

    def test_invalid_cards_reject_before_operations(self):
        api = self.api()
        for field, value in [("duration_seconds", float("nan")), ("duration_seconds", 0), ("max_rechecks", -1), ("criteria", []), ("candidate_id", "stale")]:
            card = copy.deepcopy(self.card)
            card[field] = value
            with self.subTest(field=field), self.assertRaises(StudioError):
                api.validate_card(card, self.candidate, self.root)
        card = copy.deepcopy(self.card)
        card["criteria"][0]["action_ids"] = ["missing"]
        with self.assertRaises(StudioError):
            api.validate_card(card, self.candidate, self.root)

    def test_original_card_run_unique_and_stale_candidate_rejected(self):
        api = self.api()
        before = copy.deepcopy(self.card)
        one = api.prepare_run(self.root, self.card, self.candidate, role="before")
        two = api.prepare_run(self.root, self.card, self.candidate, role="after")
        self.assertNotEqual(one, two)
        self.assertEqual(self.card, before)
        (self.root / "scene.txt").write_text("changed")
        with self.assertRaises(StudioError):
            api.validate_run(self.root, one)

    def test_requested_sampling_cannot_pass_temporal(self):
        api = self.api()
        result = api.temporal_gate(self.card["criteria"][0], [n / 30 for n in range(60)], {"requested_fps": 30, "effective_max_gap_seconds": None, "fixture_detection": "not_run"})
        self.assertEqual(result["status"], "unverified")
        result = api.temporal_gate(self.card["criteria"][0], [0, 1], {"requested_fps": 1})
        self.assertEqual(result["status"], "unverified")

    def test_performance_uses_full_raw_intervals(self):
        api = self.api()
        result = api.frame_times([{"time_seconds": i * .02, "frame_ms": 20 if i != 8 else 120} for i in range(10)], [0, .2], 33.3)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["max_ms"], 120)
        self.assertEqual(len(result["stalls"]), 1)


class RecorderLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_owned(self, script, **kwargs):
        from studio_tools import processes
        self.assertTrue(hasattr(processes, "record"), "graceful recorder lifecycle missing")
        return processes.record([sys.executable, "-u", "-c", script], job_dir=self.root / "job", duration=.15, grace=.5, **kwargs)

    def test_normal_stop_finalizes_and_preserves_unique_job(self):
        r = self.run_owned("import sys; print('started'); sys.stdin.readline(); print('finalized')")
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["stop_reason"], "duration")
        self.assertIn("finalized", (self.root / "job/stdout.log").read_text())
        with self.assertRaises(StudioError):
            self.run_owned("pass")

    def test_cancel_retains_graceful_but_incomplete_status(self):
        r = self.run_owned("import sys; sys.stdin.readline()", cancelled=lambda: True)
        self.assertEqual(r["status"], "cancelled")
        self.assertTrue(r["graceful"])

    def test_timeout_forces_only_owned_tree(self):
        r = self.run_owned("import time; time.sleep(30)")
        self.assertEqual(r["status"], "timed_out")
        self.assertFalse(r["graceful"])
        self.assertEqual(r["cleanup"], "owned_tree_stopped")

    def test_failed_start_receipt_survives(self):
        from studio_tools import processes
        self.assertTrue(hasattr(processes, "record"), "graceful recorder lifecycle missing")
        r = processes.record([str(self.root / "absent")], job_dir=self.root / "job", duration=.1)
        self.assertEqual(r["status"], "start_failed")
        self.assertTrue((self.root / "job/process.json").is_file())


class MediaRoundtrip(ReviewFixture):
    def media(self):
        self.assertIsNotNone(importlib.util.find_spec("studio_tools.review_media"), "real recorder/media adapter missing")
        from studio_tools import review_media
        return review_media

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "installed media tools required")
    def test_real_original_media_record_finalize_dense_frames(self):
        media = self.media()
        source = self.root / "artifacts/original"
        fixture = media.fixtures(self.config, source)
        original = source / "brief.mp4"
        original_hash = sha256(original)
        run = self.api().prepare_run(self.root, self.card, self.candidate)
        capture = media.capture(self.config, self.root, run, {"route": "file", "source": str(original)})
        self.assertEqual(capture["status"], "completed")
        self.assertEqual(capture["media"]["frame_count"], 60)
        self.assertTrue(capture["media"]["has_audio"])
        self.assertEqual(sha256(original), original_hash)
        dense = media.dense_frames(self.config, self.root, run, [0.7, 1.3])
        self.assertGreaterEqual(len(dense["frames"]), 18)
        self.assertLess(dense["max_gap_seconds"], .0334)
        self.assertEqual(fixture["perception"], "not_run")
        self.api().validate_run(self.root, run)
        with self.assertRaises(StudioError):
            media.capture(self.config, self.root, run, {"route": "file", "source": str(original)})
        (self.root / run / "capture.mp4").write_bytes(b"altered")
        with self.assertRaises(StudioError):
            self.api().validate_run(self.root, run)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "installed media tools required")
    def test_incomplete_container_rejected(self):
        media = self.media()
        broken = self.root / "broken.mp4"
        broken.write_bytes(b"incomplete")
        with self.assertRaises(StudioError):
            media.inspect_media(self.config, broken)

    def test_native_denied_route_never_starts_process(self):
        media = self.media()
        run = self.api().prepare_run(self.root, self.card, self.candidate)
        with patch("studio_tools.review_media.record") as recorder:
            with self.assertRaises(StudioError):
                media.capture(self.config, self.root, run, {"route": "windows_ddagrab"})
            recorder.assert_not_called()


class VideoBackend(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("studio_tools.review_video"), "video analysis backend missing")
        from studio_tools import review_video
        return review_video

    def test_zero_budget_denies_before_network(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as root, patch("urllib.request.urlopen") as request:
            with self.assertRaises(StudioError):
                api.reserve(Path(root), {"upload_authorized": False}, "run", "clip")
            request.assert_not_called()

    def test_reservation_ambiguous_outcome_blocks_other_submissions(self):
        api = self.api()
        budget = {"authorization_id": "original", "upload_authorized": True, "approved_media_sha256": ["clip"],
                  "model": "gemini-3.7-flash", "max_requests": 8, "max_total_usd": 2, "reserve_per_request_usd": .25,
                  "max_request_bytes": 1000000, "max_output_tokens": 4096, "rate_verified_utc": "2026-09-06"}
        with tempfile.TemporaryDirectory() as root:
            slot = api.reserve(Path(root), budget, "run", "clip")
            self.assertEqual(read_json(slot)["status"], "reserved")
            with self.assertRaisesRegex(StudioError, "ambiguous|unresolved"):
                api.reserve(Path(root), budget, "another", "clip")
            state = read_json(slot)
            state["status"] = "completed"
            write_json(slot, state)
            self.assertNotEqual(api.reserve(Path(root), budget, "another", "clip"), slot)

    def test_result_identity_and_intervals_are_not_model_assertions(self):
        api = self.api()
        expected = {"run_id": "run", "clip_sha256": "clip", "candidate_id": "candidate"}
        finding = {"criterion_id": "TEMP", "status": "pass", "interval": [0, 2], "observation": "No defect observed", "severity": "none", "hypothesis": "", "next_check": "dense check"}
        result = {**expected, "findings": [finding]}
        self.assertEqual(api.validate_findings(result, expected, ["TEMP"], 2), result)
        for mutation in ({"candidate_id": "stale"}, {"clip_sha256": "other"}):
            with self.assertRaises(StudioError):
                api.validate_findings({**result, **mutation}, expected, ["TEMP"], 2)
        finding["interval"] = [1, 3]
        with self.assertRaises(StudioError):
            api.validate_findings(result, expected, ["TEMP"], 2)


class DecisionTests(ReviewFixture):
    def test_interaction_checks_transition_not_input(self):
        api = self.api()
        self.assertTrue(hasattr(api, "interaction_result"), "action outcome evaluator missing")
        criterion = {"action_ids": ["board"], "expected_state": "boarded", "interval": [0, 2]}
        action = {"id": "board", "input_seconds": .4, "outcome_seconds": .6, "before_state": "walking", "after_state": "boarded"}
        self.assertEqual(api.interaction_result(criterion, [action])["status"], "pass")
        action["after_state"] = "walking"
        self.assertEqual(api.interaction_result(criterion, [action])["status"], "fail")
        del action["outcome_seconds"]
        self.assertEqual(api.interaction_result(criterion, [action])["status"], "unverified")

    def test_incompatible_comparison_and_recheck_budget(self):
        api = self.api()
        before = api.prepare_run(self.root, self.card, self.candidate, role="before")
        other = copy.deepcopy(self.card)
        other["settings"]["resolution"] = [320, 192]
        after = api.prepare_run(self.root, other, self.candidate, role="after", previous=before, affected=["TEMP"])
        result = api.compare_runs(self.root, before, after)
        self.assertFalse(result["comparable"])
        self.assertIn("settings", result["mismatches"])
        with self.assertRaisesRegex(StudioError, "budget"):
            api.prepare_run(self.root, other, self.candidate, role="after", previous=after, affected=["TEMP"])


class EndToEndFiles(ReviewFixture):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "installed media tools required")
    def test_full_backend_request_mock_preserves_raw_and_does_not_pass(self):
        from studio_tools import review_media, review_video, validation
        review_media.fixtures(self.config, self.root / "artifacts/original")
        original = self.root / "artifacts/original/brief.mp4"
        run = validation.prepare_run(self.root, self.card, self.candidate, role="before")
        review_media.capture(self.config, self.root, run, {"route": "file", "source": str(original)})
        review_media.dense_frames(self.config, self.root, run, [.7, 1.3])
        budget = {"authorization_id": "unit-test-only", "upload_authorized": True,
                  "approved_media_sha256": [sha256(self.root / run / "capture.mp4")],
                  "model": "gemini-3.7-flash", "max_requests": 1, "max_total_usd": .25,
                  "reserve_per_request_usd": .25, "max_request_bytes": 1000000,
                  "max_output_tokens": 4096, "rate_verified_utc": "2026-09-06", "rates_usd_per_million": {"input": .75, "output": 3.75}}
        preserved = []
        def transport(body, secret, timeout):
            payload = json.loads(body)
            self.assertEqual(payload["input"][0]["type"], "video")
            self.assertFalse(payload["store"])
            self.assertTrue(any(p["type"] == "image" for p in payload["input"]))
            prompt = payload["input"][-1]["text"]
            self.assertNotIn("ground-truth", prompt)
            binding = {"run_id": read_json(self.root / run / "run.json")["run_id"], "candidate_id": "sample", "clip_sha256": budget["approved_media_sha256"][0]}
            finding = {"criterion_id": "TEMP", "status": "pass", "interval": [0, 2], "observation": "Mock clean response is not perception", "severity": "none", "hypothesis": "", "next_check": "Actual model fixture run"}
            raw = json.dumps({"id": "unit-only", "model": budget["model"], "status": "completed", "usage": {"total_tokens": 100}, "steps": [{"type": "model_output", "content": [{"type": "text", "text": json.dumps({**binding, "findings": [finding]})}]}]}).encode()
            preserved.append(raw)
            return raw
        with patch.dict("os.environ", {"GEMINI_API_KEY": "unit-test-no-network"}):
            analyzed = review_video.analyze(self.config, self.root, run, budget, dense=run+"/dense-0/frames.json", transport=transport)
        self.assertEqual(analyzed["status"], "observations_received")
        self.assertEqual((self.root / run / "analysis-request/response.original.json").read_bytes(), preserved[0])
        decision = validation.assess(self.root, run)
        self.assertEqual(decision["results"][0]["status"], "unverified")
        self.assertFalse(decision["technical_criteria_complete"])
        self.assertEqual(sha256(original), read_json(self.root / run / "capture.json")["source"]["sha256"])
        with self.assertRaises(StudioError):
            review_video.analyze(self.config, self.root, run, budget, transport=transport)
        (self.root / run / "analysis-request/response.original.json").write_bytes(b"changed")
        with self.assertRaises(StudioError):
            validation.validate_run(self.root, run)

    def test_temporal_self_declared_detection_flag_never_unlocks_pass(self):
        result = self.api().temporal_gate(self.card["criteria"][0], [n/30 for n in range(60)], {"fixture_detection": "pass", "effective_max_gap_seconds": .001})
        self.assertEqual(result["status"], "unverified")


class AdversarialEvidence(ReviewFixture):
    def test_changed_entrypoint_wrapper_and_recheck_criteria_rejected(self):
        api = self.api()
        first = api.prepare_run(self.root, self.card, self.candidate, role="before")
        changed = copy.deepcopy(self.card)
        changed["criteria"][0]["max_gap_seconds"] = 1
        with self.assertRaisesRegex(StudioError, "original criteria"):
            api.prepare_run(self.root, changed, self.candidate, previous=first, affected=["TEMP"])
        (self.root / first / "entrypoint.original").write_text("replacement")
        with self.assertRaisesRegex(StudioError, "Hash mismatch"):
            api.validate_run(self.root, first)

    def test_human_wrapper_scan_separates_headless_import_intent(self):
        api = self.api()
        self.assertTrue(api.validate_card(self.card, self.candidate, self.root)["ok"])
        (self.root / "scene.txt").write_text('godot --audio-driver Dummy')
        candidate = new_candidate(self.root, "sample", "fixture", "test")
        card = copy.deepcopy(self.card)
        card["content_digest"] = candidate["content_digest"]
        card["launch"]["entrypoint_sha256"] = sha256(self.root / "scene.txt")
        with self.assertRaisesRegex(StudioError, "Human launch"):
            api.validate_card(card, candidate, self.root)
        card["launch"]["intent"] = "quiet_diagnostic"
        self.assertTrue(api.validate_card(card, candidate, self.root)["ok"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "installed media tools required")
    def test_real_recorder_loss_cadence_and_stale_telemetry(self):
        from studio_tools import review_media, validation
        fixture = self.root / "artifacts/fixtures"
        review_media.fixtures(self.config, fixture)
        dropped = review_media.inspect_media(self.config, fixture / "recorder_drop.mp4")
        self.assertEqual(dropped["frame_count"], 57)
        self.assertGreater(dropped["max_pts_gap_seconds"], .1)
        challenge = review_media.inspect_media(self.config, fixture / "single.mp4")
        self.assertEqual(challenge["frame_count"], 120)
        card = copy.deepcopy(self.card)
        card["criteria"] = [{"id": "PERF", "dimension": "performance", "kind": "performance", "action_ids": ["walk"], "expected": "below floor", "mandatory": True, "interval": [0, 2], "p95_ms": 40}]
        run = validation.prepare_run(self.root, card, self.candidate)
        review_media.capture(self.config, self.root, run, {"route": "file", "source": str(fixture / "clean.mp4")})
        from studio_tools.common import file_record
        timing = file_record(self.root, fixture / "clean-timing.json")
        facts = {"run_id": read_json(self.root / run / "run.json")["run_id"], "candidate_id": "sample", "clip_sha256": sha256(self.root / run / "capture.mp4"), "input_route": "synthetic", "host_interference": False,
                 "timing": {"file": timing, "method": "wall_frame_time", "interval": [0, 2], "clock_offset_seconds": 0, "clock_uncertainty_seconds": 0}}
        write_json(self.root / "artifacts/facts.json", facts)
        assessment = validation.assess(self.root, run, "artifacts/facts.json")
        self.assertEqual(assessment["results"][0]["status"], "pass")
        self.assertFalse(assessment["technical_criteria_complete"])
        (fixture / "clean-timing.json").write_text('[]')
        with self.assertRaisesRegex(StudioError, "Hash mismatch"):
            validation.validate_run(self.root, run)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "installed media tools required")
    def test_ambiguous_transport_is_preserved_and_never_retried(self):
        from studio_tools import review_media, review_video, validation
        fixture = self.root / "artifacts/fixtures"
        review_media.fixtures(self.config, fixture)
        run = validation.prepare_run(self.root, self.card, self.candidate)
        review_media.capture(self.config, self.root, run, {"route": "file", "source": str(fixture / "clean.mp4")})
        budget = {"authorization_id": "test-timeout", "upload_authorized": True, "approved_media_sha256": [sha256(self.root / run / "capture.mp4")], "model": "gemini-3.7-flash", "max_requests": 1, "max_total_usd": .25, "reserve_per_request_usd": .25, "max_request_bytes": 1000000, "max_output_tokens": 4096, "rate_verified_utc": "2026-09-06"}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "unit-test-no-network"}), patch("studio_tools.review_video._submit", side_effect=TimeoutError) as submit:
            result = review_video.analyze(self.config, self.root, run, budget)
            self.assertEqual(result["status"], "ambiguous")
            self.assertFalse(result["ok"])
            with self.assertRaises(StudioError):
                review_video.analyze(self.config, self.root, run, budget)
            self.assertEqual(submit.call_count, 1)
        state = read_json(self.root / "artifacts/review-budgets/test-timeout/request-1.json")
        self.assertEqual(state["status"], "ambiguous")
        self.assertNotIn("unit-test-no-network", json.dumps(state))
        self.assertTrue((self.root / run / "analysis-request/outcome.json").is_file())


if __name__ == "__main__":
    unittest.main()
