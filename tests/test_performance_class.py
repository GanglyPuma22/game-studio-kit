"""What a performance number is allowed to settle (offline).

A frame time measured while a browser was transcoding is a diagnostic reading.
The same number measured inside an attributable cleanroom window is the only
kind this kit lets qualify anything, and a person's own verdict is a third
thing again. These tests check that each receipt says which it is and that a
verdict never rolls a mixture up into the strongest of them.
"""

import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_cleanroom_host import proc, snap, stub_sampler

from studio_tools import cleanroom, launch, processes
from studio_tools.common import StudioError, digest, file_record, read_json, sha256
from studio_tools.config import load
from studio_tools.evidence import (
    attach_evidence, new_candidate, performance_rollup, validate_candidate,
)


class CleanroomClassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio class bench ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        self.config = load(overrides={"timeout": 5})

    def bench(self, capture, label, **kwargs):
        return cleanroom.execute(self.config, self.root, capture, label=label,
                                 sampler_factory=stub_sampler(), self_pid=os.getpid(), **kwargs)

    def test_an_attributable_window_around_a_completed_capture_qualifies(self):
        reader = lambda: snap([proc(1, "idle")])
        result = self.bench([sys.executable, "-c", "print('{}')"], "clean", snapshot_reader=reader)
        self.assertTrue(result["attributable"])
        self.assertEqual(result["capture"]["status"], "completed")
        self.assertEqual(result["performance_class"], "clean_qualification")
        self.assertEqual(
            read_json(self.root / "artifacts/bench/clean/cleanroom.json")["performance_class"],
            "clean_qualification",
        )

    def test_a_contended_window_is_only_a_diagnostic(self):
        snapshots = [
            snap([proc(1, "idle")]),
            snap([proc(1, "idle"), proc(4, "browser", ws=900 * 1024 * 1024)],
                 at="2026-09-10T10:05:02+00:00"),
        ]
        calls = []

        def reader():
            calls.append(len(calls))
            return snapshots[len(calls) - 1]

        result = self.bench([sys.executable, "-c", "print('{}')"], "busy", snapshot_reader=reader)
        self.assertFalse(result["attributable"])
        self.assertEqual(result["performance_class"], "diagnostic")

    def test_a_capture_that_did_not_finish_is_only_a_diagnostic(self):
        reader = lambda: snap([proc(1, "idle")])
        result = self.bench([sys.executable, "-c", "import time;time.sleep(30)"], "slow",
                            snapshot_reader=reader, timeout=1)
        self.assertTrue(result["attributable"])
        self.assertEqual(result["capture"]["status"], "timed_out")
        self.assertEqual(result["performance_class"], "diagnostic")


class LaunchClassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio class launch ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)

    def execute(self, code, **kwargs):
        def fake_run(args, **call):
            return processes.run([sys.executable, "-c", code], **call)
        with patch("studio_tools.launch.run", side_effect=fake_run):
            return launch.execute(self.config, self.root, sha256_expected=self.sha, **kwargs)

    def test_a_native_launch_that_captured_a_file_is_labelled_diagnostic(self):
        code = "import pathlib;pathlib.Path('artifacts/frames.json').write_text('{}')"
        result = self.execute(code, mode="native", label="native",
                              results=["artifacts/frames.json"])
        self.assertEqual(result["performance_class"], "diagnostic")
        self.assertEqual(
            read_json(self.root / "artifacts/launches/native/exit.json")["performance_class"],
            "diagnostic",
        )

    def test_a_launch_that_captured_nothing_claims_no_class_at_all(self):
        native = self.execute("print('ran')", mode="native", label="bare")
        self.assertNotIn("performance_class", native)
        headless = self.execute(
            "import pathlib;pathlib.Path('artifacts/out.json').write_text('{}')",
            mode="import", label="headless", results=["artifacts/out.json"],
        )
        self.assertNotIn("performance_class", headless)
        self.assertNotIn(
            "performance_class",
            read_json(self.root / "artifacts/launches/headless/exit.json"),
        )


class RollupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio class rollup ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scene.gd").write_text("original scene", encoding="utf-8")
        (self.root / "artifacts").mkdir()
        self.candidate = new_candidate(self.root, "candidate", "4.5.1", "test")

    def row(self, name, method="profiler_measurement"):
        path = self.root / "artifacts" / name
        path.write_text("Original fixture", encoding="utf-8")
        return {
            **file_record(self.root, path),
            "content_digest": self.candidate["content_digest"],
            "method": method,
            "observer": "offline fixture",
        }

    def verdict(self):
        return self.candidate["verdicts"]["performance"]

    def test_a_fresh_candidate_has_qualified_nothing(self):
        self.assertEqual(self.verdict()["performance_class"], "unverified")

    def test_a_clean_bench_row_carries_its_class_onto_the_entry_and_the_rollup(self):
        entry = attach_evidence(
            self.candidate, "performance", self.row("bench.json"),
            receipt={"content_digest": self.candidate["content_digest"],
                     "performance_class": "clean_qualification"},
        )
        self.assertEqual(entry["performance_class"], "clean_qualification")
        self.assertEqual(entry["identity"], "current")
        self.assertEqual(self.verdict()["performance_class"], "clean_qualification")
        self.assertEqual(self.verdict()["evidence_current"], 1)

    def test_a_human_verdict_alone_is_a_subjective_acceptance(self):
        attach_evidence(self.candidate, "performance",
                        self.row("review.json", method="native_capture_review"))
        self.assertEqual(self.verdict()["performance_class"], "subjective_acceptance")

    def test_classes_that_differ_roll_up_to_mixed(self):
        attach_evidence(
            self.candidate, "performance", self.row("bench.json"),
            receipt={"content_digest": self.candidate["content_digest"],
                     "performance_class": "clean_qualification"},
        )
        attach_evidence(
            self.candidate, "performance", self.row("launch.json"),
            receipt={"content_digest": self.candidate["content_digest"],
                     "performance_class": "diagnostic"},
        )
        self.assertEqual(self.verdict()["performance_class"], "mixed")

    def test_a_diagnostic_on_its_own_never_qualifies(self):
        attach_evidence(
            self.candidate, "performance", self.row("launch.json"),
            receipt={"content_digest": self.candidate["content_digest"],
                     "performance_class": "diagnostic"},
        )
        self.assertEqual(self.verdict()["performance_class"], "diagnostic")

    def test_a_qualification_taken_from_other_content_does_not_count(self):
        stale = self.row("bench.json")
        stale["content_digest"] = digest([{"path": "scene.gd", "sha256": "0" * 64}])
        attach_evidence(self.candidate, "performance", stale,
                        receipt={**stale, "performance_class": "clean_qualification"})
        self.assertEqual(self.verdict()["evidence_total"], 1)
        self.assertEqual(self.verdict()["evidence_current"], 0)
        self.assertEqual(self.verdict()["performance_class"], "unverified")

    def test_only_a_clean_qualification_can_carry_a_performance_pass(self):
        for performance_class, expected in (
            ("clean_qualification", None),
            ("diagnostic", "diagnostic"),
        ):
            with self.subTest(performance_class=performance_class):
                candidate = new_candidate(self.root, "candidate", "4.5.1", "test")
                self.candidate = candidate
                attach_evidence(
                    candidate, "performance", self.row("bench.json"),
                    receipt={"content_digest": candidate["content_digest"],
                             "performance_class": performance_class},
                )
                candidate["verdicts"]["performance"]["status"] = "pass"
                if expected is None:
                    validate_candidate(candidate, self.root)
                else:
                    with self.assertRaisesRegex(StudioError, "clean_qualification"):
                        validate_candidate(candidate, self.root)

    def test_a_human_review_alone_cannot_carry_a_performance_pass(self):
        candidate = new_candidate(self.root, "candidate", "4.5.1", "test")
        self.candidate = candidate
        attach_evidence(candidate, "performance",
                        self.row("review.json", method="native_capture_review"))
        candidate["verdicts"]["performance"]["status"] = "pass"
        self.assertEqual(candidate["verdicts"]["performance"]["performance_class"],
                         "subjective_acceptance")
        with self.assertRaisesRegex(StudioError, "clean_qualification"):
            validate_candidate(candidate, self.root)

    def test_a_mixture_cannot_carry_a_performance_pass(self):
        candidate = new_candidate(self.root, "candidate", "4.5.1", "test")
        self.candidate = candidate
        for name, performance_class in (("bench.json", "clean_qualification"),
                                        ("launch.json", "diagnostic")):
            attach_evidence(
                candidate, "performance", self.row(name),
                receipt={"content_digest": candidate["content_digest"],
                         "performance_class": performance_class},
            )
        candidate["verdicts"]["performance"]["status"] = "pass"
        with self.assertRaisesRegex(StudioError, "clean_qualification"):
            validate_candidate(candidate, self.root)

    def test_the_rollup_of_nothing_is_unverified(self):
        self.assertEqual(performance_rollup([]), "unverified")
        self.assertEqual(performance_rollup([{"identity": "unknown"}]), "unverified")


if __name__ == "__main__":
    unittest.main()
