"""Identity, stale selection, native admission and publication boundaries."""
import copy
import tempfile
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from studio_tools import qualification as q
from studio_tools.common import StudioError, digest, sha256, write_json


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.asset = self.root / "candidate.glb"
        self.asset.write_bytes(b"immutable selected bytes")
        self.identity = {"attempt_id": "selected", "model_id": "kite", "target": "glide", "sha256": sha256(self.asset)}
        self.attempt = {"id": "selected", "model_id": "kite", "sha256": sha256(self.asset),
                        "targets": ["glide"], "label": "selected take", "session": "pilot"}
        self.review = {"status": "selected", "revision": 1, "ready_for_game": None}
        self.catalog = {"attempts": [self.attempt], "reviews": {"selected:glide": self.review},
                        "baselines": {"kite:glide": "selected"},
                        "models": [{"id": "kite", "current_game_sha256": "b" * 64}],
                        "notes": [{"text": "preserve"}], "model_aliases": [], "cursor": 10}
        self.plan = {"id": "test", "attempt": self.identity, "engine": {"sha256": sha256(sys.executable)}}
        self.record = {"plan": self.plan, "plan_digest": digest(self.plan), "attempt": self.attempt,
                       "review": self.review, "baseline": {"sha256": "b" * 64},
                       "files": [{"path": "candidate.glb", "sha256": sha256(self.asset)}]}
        write_json(self.root / "qualification.json", self.record)

    def test_validation_sample_cannot_replace_selection(self):
        state = copy.deepcopy(self.catalog)
        state["baselines"]["kite:glide"] = "validation"
        with self.assertRaisesRegex(StudioError, "currently selected"):
            q.resolve(state, self.identity)

    def test_wrong_hash_model_target_and_missing_attempt_refused(self):
        for field, value in (("sha256", "c" * 64), ("model_id", "slug"), ("target", "flap"), ("attempt_id", "missing")):
            identity = {**self.identity, field: value}
            with self.subTest(field=field), self.assertRaises(StudioError):
                q.resolve(self.catalog, identity)

    def test_input_mutation_and_traversal_refused(self):
        self.asset.write_bytes(b"changed")
        with self.assertRaisesRegex(StudioError, "input changed"):
            q.verify(self.root)
        self.record["files"][0]["path"] = "../escape.glb"
        write_json(self.root / "qualification.json", self.record)
        with self.assertRaises(StudioError):
            q.verify(self.root)

    def test_plan_mutation_refused(self):
        self.record["plan"]["id"] = "changed"
        write_json(self.root / "qualification.json", self.record)
        with self.assertRaisesRegex(StudioError, "plan changed"):
            q.verify(self.root)

    def test_native_requires_reservation_and_never_launches(self):
        with patch.object(q, "request", return_value=self.catalog), patch.object(q, "launch") as launch:
            with self.assertRaisesRegex(StudioError, "reservation"):
                q.run({"executables": {"godot": sys.executable}}, self.root, "http://local", "native", "native", "2030-01-01T00:00:00Z")
            launch.assert_not_called()

    def test_changed_review_and_game_pin_prevent_launch(self):
        for key in ("review", "pin"):
            catalog = copy.deepcopy(self.catalog)
            if key == "review": catalog["reviews"]["selected:glide"]["revision"] = 2
            else: catalog["models"][0]["current_game_sha256"] = "c" * 64
            with self.subTest(key=key), patch.object(q, "request", return_value=catalog), patch.object(q, "launch") as launch:
                with self.assertRaises(StudioError):
                    q.run({}, self.root, "http://local", "cpu", "cpu", "2030-01-01T00:00:00Z")
                launch.assert_not_called()

    def test_failed_host_preflight_prevents_native_launch(self):
        write_json(self.root / "host.json", {"ready": False})
        window = {"plan_digest": self.record["plan_digest"], "coordinator": "parent",
                  "start_utc": "2000-01-01T00:00:00Z", "end_utc": "2030-01-01T00:00:00Z",
                  "host_preflight": str(self.root / "host.json"),
                  "host_preflight_sha256": sha256(self.root / "host.json")}
        write_json(self.root / "window.json", window)
        with patch.object(q, "request", return_value=self.catalog), patch.object(q, "launch") as launch:
            with self.assertRaisesRegex(StudioError, "passing pinned host preflight"):
                q.run({"executables": {"godot": sys.executable}}, self.root, "http://local", "native", "native",
                      "2029-01-01T00:00:00Z", self.root / "window.json")
            launch.assert_not_called()

    def test_mismatched_window_prevents_native_launch(self):
        write_json(self.root / "host.json", {"ready": True, "window": {
            "start_utc": "2028-01-01T00:00:00Z", "end_utc": "2028-01-02T00:00:00Z"}})
        window = {"plan_digest": self.record["plan_digest"], "coordinator": "parent",
                  "start_utc": "2000-01-01T00:00:00Z", "end_utc": "2030-01-01T00:00:00Z",
                  "host_preflight": str(self.root / "host.json"),
                  "host_preflight_sha256": sha256(self.root / "host.json")}
        write_json(self.root / "window.json", window)
        with patch.object(q, "request", return_value=self.catalog), patch.object(q, "launch") as launch:
            with self.assertRaisesRegex(StudioError, "reserved window"):
                q.run({"executables": {"godot": sys.executable}}, self.root, "http://local", "native", "native",
                      "2029-01-01T00:00:00Z", self.root / "window.json")
            launch.assert_not_called()

    def test_diagnostic_exception_requires_explicit_instruction(self):
        write_json(self.root / "host.json", {"ready": False})
        window = {"plan_digest": self.record["plan_digest"], "coordinator": "parent",
                  "start_utc": "2000-01-01T00:00:00Z", "end_utc": "2030-01-01T00:00:00Z",
                  "host_preflight": str(self.root / "host.json"),
                  "host_preflight_sha256": sha256(self.root / "host.json"),
                  "bounded_diagnostic_authorization": {"source_thread_id": "parent"}}
        write_json(self.root / "window.json", window)
        with patch.object(q, "request", return_value=self.catalog), patch.object(q, "launch") as launch:
            with self.assertRaisesRegex(StudioError, "explicit coordinating instruction"):
                q.run({"executables": {"godot": sys.executable}}, self.root, "http://local", "native", "native",
                      "2029-01-01T00:00:00Z", self.root / "window.json")
            launch.assert_not_called()

    def test_attach_same_attempt_only_preserves_decisions(self):
        receipt = {"kind": "animation-qualification-run", "plan_digest": self.record["plan_digest"],
                   "attempt_id": "selected", "glb_sha256": self.attempt["sha256"], "files": [],
                   "phase": "cpu", "automated_checks": "failed", "performance_qualification": "unverified"}
        write_json(self.root / "receipt.json", receipt)
        calls = []
        def api(url, route, body=None, token=None):
            calls.append((route, body))
            if route == "/api/catalog": return copy.deepcopy(self.catalog)
            if route == "/api/session": return {"token": "local-test"}
            if route == "/api/register": return {"existing": True, "attempt": self.attempt}
            return {"events": [], "cursor": 10, "has_more": False}
        with patch.object(q, "request", side_effect=api):
            result = q.attach(self.root, "http://local", "receipt.json", "kit")
        self.assertTrue(result["decisions_comments_gamepins_preserved"])
        writes = [(route, body) for route, body in calls if body is not None]
        self.assertEqual([r for r, _ in writes], ["/api/register"])
        body = writes[0][1]
        self.assertEqual(body["sha256"], self.attempt["sha256"])
        self.assertEqual(body["targets"], self.attempt["targets"])
        self.assertNotIn("ready_for_game", body)
        self.assertNotIn("status", body)
        initial_audit = (self.root / "receipt.json.publication.json").read_bytes()
        self.catalog["cursor"] = 11
        with patch.object(q, "request", side_effect=api):
            q.attach(self.root, "http://local", "receipt.json", "kit")
        self.assertEqual((self.root / "receipt.json.publication.json").read_bytes(), initial_audit)
        self.assertTrue((self.root / "receipt.json.publication-11-11.json").is_file())

    def test_attach_changed_evidence_refused_before_api(self):
        receipt = {"kind": "animation-qualification-run", "plan_digest": self.record["plan_digest"],
                   "attempt_id": "selected", "glb_sha256": self.attempt["sha256"],
                   "files": [{"path": "candidate.glb", "sha256": "c" * 64}]}
        write_json(self.root / "receipt.json", receipt)
        with patch.object(q, "request") as api, self.assertRaises(StudioError):
            q.attach(self.root, "http://local", "receipt.json", "kit")
        api.assert_not_called()

    def test_timing_requires_rendered_gpu_and_matched_pair(self):
        thresholds = {"frame_p95_ms": 16.67, "gpu_p95_ms": 12, "controller_cpu_p95_ms": 1, "max_relative_frame_cost": 1.2}
        row = {"native_rendered": True, "timing": {"frame_ms": [10] * 120, "controller_cpu_ms": [.1] * 120, "viewport_gpu_ms": [3] * 120}}
        self.assertEqual(q.compare_timing([row, row], thresholds)["verdict"], "passed")
        for bad in ({**row, "native_rendered": False}, {**row, "timing": {**row["timing"], "viewport_gpu_ms": [0] * 120}},
                    {**row, "timing": {**row["timing"], "frame_ms": [float("nan")] * 120}}):
            self.assertEqual(q.compare_timing([row, bad], thresholds)["verdict"], "unverified")
        slow = {**row, "timing": {**row["timing"], "frame_ms": [18] * 120}}
        self.assertEqual(q.compare_timing([row, slow], thresholds)["verdict"], "failed")


if __name__ == "__main__":
    unittest.main()
