"""Evidence that says which content it still describes (offline).

A candidate's verdicts collect receipts over time, and the project underneath
them keeps changing. Without a label on each row, a verdict that was argued
from yesterday's capture looks exactly like one argued from today's.
"""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from studio_tools.common import StudioError, digest, file_record
from studio_tools.evidence import (
    attach_evidence,
    new_candidate,
    performance_rollup,
    receipt_identity,
    refresh_rollups,
)

ROOT = Path(__file__).resolve().parents[1]


class CaptureIdentityCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio identity space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scene.gd").write_text("original scene", encoding="utf-8")
        (self.root / "artifacts").mkdir()

    def candidate(self):
        return new_candidate(self.root, "candidate", "4.5.1", "test")

    def capture(self, candidate, name="review.txt", method="native_capture_review"):
        path = self.root / "artifacts" / name
        path.write_text("Original review fixture, no perceptual claim", encoding="utf-8")
        return {
            **file_record(self.root, path),
            "content_digest": candidate["content_digest"],
            "method": method,
            "observer": "offline fixture",
        }


class IdentityLabelTests(CaptureIdentityCase):
    def test_a_receipt_from_this_content_is_current(self):
        candidate = self.candidate()
        self.assertEqual(receipt_identity(self.capture(candidate), candidate), "current")

    def test_a_receipt_from_other_content_is_historical(self):
        candidate = self.candidate()
        entry = self.capture(candidate)
        entry["content_digest"] = digest([{"path": "scene.gd", "sha256": "0" * 64}])
        self.assertEqual(receipt_identity(entry, candidate), "historical")

    def test_a_receipt_with_no_digest_is_unknown_not_historical(self):
        # A launch exit or a cleanroom bench knows a project, never a candidate.
        candidate = self.candidate()
        for receipt in ({"kind": "launch-exit"}, {"content_digest": None}, {"content_digest": ""}):
            with self.subTest(receipt=receipt):
                self.assertEqual(receipt_identity(receipt, candidate), "unknown")

    def test_archived_capture_labels_itself_against_the_candidate_it_came_from(self):
        from studio_tools.evidence import archive_capture

        candidate = self.candidate()
        source = self.root / "artifacts/raw.txt"
        source.write_text("capture fixture", encoding="utf-8")
        archived = archive_capture(self.root, source, candidate, "arrival")
        self.assertEqual(archived["identity"], "current")
        self.assertEqual(archived["content_digest"], candidate["content_digest"])
        self.assertEqual(json.loads((self.root / archived["path"]).parent.parent.joinpath(
            "capture.json").read_text(encoding="utf-8"))["identity"], "current")


class AttachTests(CaptureIdentityCase):
    def test_attaching_labels_the_row_and_leaves_its_hashes_alone(self):
        candidate = self.candidate()
        entry = self.capture(candidate)
        original = copy.deepcopy(entry)
        attached = attach_evidence(candidate, "visual", entry)
        self.assertEqual(attached["identity"], "current")
        self.assertEqual(attached["sha256"], original["sha256"])
        self.assertEqual(attached["content_digest"], original["content_digest"])
        # The caller's own dictionary is not mutated into the record.
        self.assertEqual(entry, original)
        self.assertEqual(candidate["verdicts"]["visual"]["evidence"], [attached])

    def test_rollups_are_recomputed_on_every_attach(self):
        candidate = self.candidate()
        self.assertEqual(candidate["verdicts"]["visual"]["evidence_total"], 0)
        self.assertEqual(candidate["verdicts"]["visual"]["evidence_current"], 0)
        attach_evidence(candidate, "visual", self.capture(candidate))
        stale = self.capture(candidate, name="older.txt")
        stale["content_digest"] = digest([{"path": "scene.gd", "sha256": "0" * 64}])
        attach_evidence(candidate, "visual", stale)
        verdict = candidate["verdicts"]["visual"]
        self.assertEqual(verdict["evidence_total"], 2)
        self.assertEqual(verdict["evidence_current"], 1)
        self.assertEqual([e["identity"] for e in verdict["evidence"]], ["current", "historical"])

    def test_a_bench_receipt_supplies_the_identity_the_entry_cannot(self):
        candidate = self.candidate()
        entry = self.capture(candidate, method="profiler_measurement")
        entry.pop("content_digest")
        attached = attach_evidence(candidate, "performance", entry, receipt={"kind": "cleanroom-bench"})
        self.assertEqual(attached["identity"], "unknown")
        self.assertEqual(candidate["verdicts"]["performance"]["evidence_current"], 0)

    def test_an_unknown_dimension_is_refused(self):
        candidate = self.candidate()
        with self.assertRaisesRegex(StudioError, "dimension"):
            attach_evidence(candidate, "framerate", self.capture(candidate))

    def test_refresh_recounts_rows_attached_by_hand(self):
        candidate = self.candidate()
        entry = self.capture(candidate)
        entry["identity"] = "current"
        candidate["verdicts"]["audio"]["evidence"] = [entry, dict(entry, identity="historical")]
        refresh_rollups(candidate)
        self.assertEqual(candidate["verdicts"]["audio"]["evidence_total"], 2)
        self.assertEqual(candidate["verdicts"]["audio"]["evidence_current"], 1)
        # Empty verdicts stay at zero rather than gaining a claim.
        self.assertEqual(candidate["verdicts"]["motion"]["evidence_total"], 0)
        self.assertEqual(performance_rollup([]), "unverified")


class TemplateTests(unittest.TestCase):
    def test_the_candidate_template_ships_the_new_rollup_keys(self):
        template = json.loads((ROOT / "templates/candidate.json").read_text(encoding="utf-8"))
        for name, verdict in template["verdicts"].items():
            with self.subTest(dimension=name):
                self.assertEqual(verdict["evidence"], [])
                self.assertEqual(verdict["evidence_current"], 0)
                self.assertEqual(verdict["evidence_total"], 0)
        self.assertEqual(template["verdicts"]["performance"]["performance_class"], "unverified")


if __name__ == "__main__":
    unittest.main()
