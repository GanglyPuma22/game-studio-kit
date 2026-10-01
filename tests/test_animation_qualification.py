"""Identity, stale selection, native admission and publication boundaries."""
import copy
import json
import struct
import tempfile
import sys
import zlib
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

    def test_multiclip_target_resolves_generated_flap_instead_of_authored_glide(self):
        attempt = {"targets": ["glide", "powered-flap"],
                   "clips": [{"name": "glide"}, {"name": "derived_selected_flap_original14"}]}
        self.assertEqual(q.clip_name(attempt, "powered-flap"), "derived_selected_flap_original14")
        self.assertEqual(q.clip_name(attempt, "glide"), "glide")

    def test_ambiguous_or_missing_embedded_clip_mapping_is_refused(self):
        for clips in (None, [], [{"name": ""}], [{"name": "glide"}, {"name": "glide"}]):
            with self.subTest(clips=clips), self.assertRaises(StudioError):
                q.clip_name({"targets": ["glide"], "clips": clips}, "glide")

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

    def complete_evidence(self, native=True):
        plan = {"attempt": self.identity, "baseline": {**self.identity, "attempt_id": "baseline"},
                "replay": {"frames": 3, "capture_frames": [1]}, "settings": {"resolution": [1920, 1080]}}
        identity = {"role": "candidate", "attempt_id": "selected", "glb_sha256": self.identity["sha256"], "plan_digest": "d"*64}
        folder = self.root / "evidence"
        folder.mkdir()
        replay = folder / "replay.jsonl"
        replay.write_text("".join(json.dumps({"frame": i, "identity": identity})+'\n' for i in range(3)))
        observed = {"identity": identity, "native_rendered": native,
                    "replay": {"path": "evidence/replay.jsonl", "sha256": sha256(replay), "frames": 3}, "captures": []}
        if native:
            def chunk(kind, data):
                return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data)&0xffffffff)
            png = folder / "frame-0001.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB",1920,1080,8,2,0,0,0))
                            +chunk(b"IDAT", zlib.compress(bytes(1080*(1+1920*3))))+chunk(b"IEND",b""))
            observed["captures"] = [{"frame":1,"path":"evidence/frame-0001.png","sha256":sha256(png),"dimensions":[1920,1080]}]
        return plan, identity, folder, observed

    def test_complete_identity_bound_evidence_is_required(self):
        plan,identity,folder,observed = self.complete_evidence()
        self.assertTrue(q.validate_evidence(self.root,plan,"d"*64,"candidate",observed,folder,True)["ok"])
        for case in ("missing_capture", "wrong_dimensions", "truncated_png", "invalid_idat", "wrong_hash", "missing_frame", "duplicate_frame", "wrong_identity"):
            with self.subTest(case=case):
                damaged = copy.deepcopy(observed)
                replay = folder / "replay.jsonl"
                original = replay.read_bytes()
                png = folder / "frame-0001.png"
                original_png = png.read_bytes()
                if case == "missing_capture": damaged["captures"] = []
                elif case == "wrong_dimensions": damaged["captures"][0]["dimensions"] = [1,1]
                elif case == "truncated_png":
                    png.write_bytes(original_png[:-12]); damaged["captures"][0]["sha256"] = sha256(png)
                elif case == "invalid_idat":
                    def chunk(kind, data):
                        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
                    png.write_bytes(original_png[:33]+chunk(b"IDAT",b"not a compressed image")+chunk(b"IEND",b""))
                    damaged["captures"][0]["sha256"] = sha256(png)
                elif case == "wrong_hash": damaged["replay"]["sha256"] = "a"*64
                elif case == "wrong_identity": damaged["identity"]["attempt_id"] = "other"
                else:
                    frames = [json.loads(line) for line in replay.read_text().splitlines()]
                    if case == "missing_frame": frames.pop()
                    else: frames[1]["frame"] = 0
                    replay.write_text("".join(json.dumps(frame)+'\n' for frame in frames))
                    damaged["replay"]["sha256"] = sha256(replay)
                self.assertFalse(q.validate_evidence(self.root,plan,"d"*64,"candidate",damaged,folder,True)["ok"])
                replay.write_bytes(original); png.write_bytes(original_png)

    def test_adapter_pass_without_replay_cannot_qualify(self):
        self.plan.update({"baseline": {**self.identity,"attempt_id":"baseline"},"script":"adapter.gd",
                          "replay":{"frames":3,"capture_frames":[1]},"settings":{"resolution":[1920,1080]}})
        self.record["plan_digest"] = digest(self.plan)
        write_json(self.root / "qualification.json",self.record)
        def fake_launch(config, root, **kwargs):
            write_json(root / kwargs["results"][0], {"automated_checks":"passed","native_rendered":False,
                       "performance_qualification":"passed","captures":[]})
            return {"ok":True}
        with patch.object(q,"request",return_value=self.catalog), patch.object(q,"launch",side_effect=fake_launch):
            result = q.run({"executables":{"godot":sys.executable}},self.root,"http://local","cpu","no-evidence","2030-01-01T00:00:00Z")
        self.assertFalse(result["ok"])
        self.assertFalse(result["evidence_complete"])
        self.assertEqual(result["automated_checks"],"failed")
        self.assertEqual(result["performance_qualification"],"unverified")

    def test_attach_cannot_publish_a_pass_with_no_capture_or_replay(self):
        receipt = {"kind":"animation-qualification-run","plan_digest":self.record["plan_digest"],
                   "attempt_id":"selected","glb_sha256":self.attempt["sha256"],"files":[],"phase":"native",
                   "automated_checks":"passed","performance_qualification":"passed","evidence_complete":True}
        write_json(self.root / "forged-pass.json",receipt)
        with patch.object(q,"request") as api, self.assertRaisesRegex(StudioError,"complete capture/replay"):
            q.attach(self.root,"http://local","forged-pass.json","kit")
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
