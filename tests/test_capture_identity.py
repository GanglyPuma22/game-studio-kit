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
    IDENTITIES,
    attach_evidence,
    new_candidate,
    performance_rollup,
    receipt_identity,
    refresh_rollups,
    row_identity,
    validate_candidate,
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

    def test_a_bench_row_binds_the_measurement_the_bench_receipt_cannot(self):
        # cleanroom.json records a window and a project, never a candidate, so
        # the digest comes from the row written beside it.
        candidate = self.candidate()
        bench = {"schema_version": 1, "kind": "cleanroom-bench", "label": "settled-01",
                 "attributable": True, "ok": True,
                 "performance_class": "clean_qualification"}
        self.assertNotIn("content_digest", bench)
        entry = self.capture(candidate, name="bench.txt", method="profiler_measurement")
        attached = attach_evidence(candidate, "performance", entry, receipt=bench)
        self.assertEqual(attached["identity"], "current")
        self.assertEqual(attached["performance_class"], "clean_qualification")
        verdict = candidate["verdicts"]["performance"]
        self.assertEqual(verdict["evidence_current"], 1)
        self.assertEqual(verdict["performance_class"], "clean_qualification")
        validate_candidate(candidate, self.root)

    def test_a_receipt_digest_still_wins_over_the_row(self):
        candidate = self.candidate()
        entry = self.capture(candidate, method="profiler_measurement")
        attached = attach_evidence(
            candidate, "performance", entry,
            receipt={"kind": "capture", "content_digest": "an earlier build"},
        )
        self.assertEqual(attached["identity"], "historical")

    def test_evidence_with_no_digest_anywhere_is_unknown(self):
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


class ValidationTests(CaptureIdentityCase):
    """A verdict may not rest on evidence that no longer describes the build."""

    METHODS = {"visual": "native_visual", "motion": "native_visual",
               "interaction": "ordinary_input", "audio": "listening",
               "performance": "profiler_measurement"}

    def passing(self, candidate, dimension):
        entry = self.capture(candidate, name=dimension + ".txt", method=self.METHODS[dimension])
        if dimension == "audio":
            entry["listening"] = {"performed": True, "playback_route": "offline fixture route",
                                  "interval_seconds": [0, 4]}
        receipt = {"content_digest": candidate["content_digest"]}
        if dimension == "performance":
            receipt["performance_class"] = "clean_qualification"
        attach_evidence(candidate, dimension, entry, receipt=receipt)
        candidate["verdicts"][dimension]["status"] = "pass"
        return candidate["verdicts"][dimension]["evidence"][-1]

    def test_a_pass_backed_by_current_evidence_validates(self):
        candidate = self.candidate()
        self.passing(candidate, "visual")
        validate_candidate(candidate, self.root)

    def test_a_pass_with_no_current_row_is_refused(self):
        for identity in (None, "historical", "unknown"):
            with self.subTest(identity=identity):
                candidate = self.candidate()
                entry = self.passing(candidate, "visual")
                if identity is None:
                    entry.pop("identity")
                else:
                    entry["identity"] = identity
                refresh_rollups(candidate)
                with self.assertRaisesRegex(StudioError, "identity=current"):
                    validate_candidate(candidate, self.root)

    def test_a_historical_row_may_name_the_build_it_came_from(self):
        candidate = self.candidate()
        self.passing(candidate, "visual")
        older = self.capture(candidate, name="older.txt", method="native_visual")
        older["content_digest"] = digest([{"path": "scene.gd", "sha256": "0" * 64}])
        older["identity"] = "historical"
        candidate["verdicts"]["visual"]["evidence"].append(older)
        refresh_rollups(candidate)
        self.assertEqual(candidate["verdicts"]["visual"]["evidence_total"], 2)
        self.assertEqual(candidate["verdicts"]["visual"]["evidence_current"], 1)
        # Keeping what was measured before does not invalidate the record, and
        # does not help the pass either: the current row is still doing that.
        validate_candidate(candidate, self.root)

    def test_a_current_row_must_name_this_candidates_digest(self):
        candidate = self.candidate()
        entry = self.passing(candidate, "visual")
        entry["content_digest"] = digest([{"path": "scene.gd", "sha256": "0" * 64}])
        with self.assertRaisesRegex(StudioError, "different candidate"):
            validate_candidate(candidate, self.root)

    def test_an_unknown_or_unlabelled_row_must_also_name_it(self):
        for identity in ("unknown", None):
            with self.subTest(identity=identity):
                candidate = self.candidate()
                self.passing(candidate, "visual")
                other = self.capture(candidate, name="other.txt", method="native_visual")
                other["content_digest"] = digest([{"path": "scene.gd", "sha256": "0" * 64}])
                if identity is not None:
                    other["identity"] = identity
                candidate["verdicts"]["visual"]["evidence"].append(other)
                refresh_rollups(candidate)
                with self.assertRaisesRegex(StudioError, "different candidate"):
                    validate_candidate(candidate, self.root)

    def test_a_historical_row_alone_still_cannot_carry_a_pass(self):
        candidate = self.candidate()
        entry = self.passing(candidate, "visual")
        entry["content_digest"] = digest([{"path": "scene.gd", "sha256": "0" * 64}])
        entry["identity"] = "historical"
        refresh_rollups(candidate)
        with self.assertRaisesRegex(StudioError, "identity=current"):
            validate_candidate(candidate, self.root)

    def test_an_identity_this_kit_does_not_know_is_refused_by_name(self):
        for spelling in ("currnet", "CURRENT", "recent", "", True):
            with self.subTest(spelling=spelling):
                candidate = self.candidate()
                entry = self.passing(candidate, "visual")
                entry["identity"] = spelling
                with self.assertRaisesRegex(StudioError, "must be current, historical or unknown"):
                    validate_candidate(candidate, self.root)

    def test_the_refusal_names_the_row_it_found(self):
        candidate = self.candidate()
        entry = self.passing(candidate, "visual")
        entry["identity"] = "currnet"
        with self.assertRaises(StudioError) as failure:
            validate_candidate(candidate, self.root)
        self.assertIn(entry["path"], str(failure.exception))

    def test_a_row_with_no_label_is_legacy_and_counts_as_unknown(self):
        candidate = self.candidate()
        entry = self.passing(candidate, "visual")
        entry.pop("identity")
        self.assertEqual(row_identity(entry), "unknown")
        self.assertIn(row_identity(entry), IDENTITIES)
        refresh_rollups(candidate)
        self.assertEqual(candidate["verdicts"]["visual"]["evidence_current"], 0)
        self.assertEqual(candidate["verdicts"]["visual"]["evidence_total"], 1)
        # Legacy is not invalid; it simply cannot carry a pass.
        candidate["verdicts"]["visual"]["status"] = "unverified"
        validate_candidate(candidate, self.root)

    def test_a_stored_rollup_that_disagrees_with_its_own_rows_is_refused(self):
        for key, value in (("evidence_total", 5), ("evidence_current", 0)):
            with self.subTest(key=key):
                candidate = self.candidate()
                self.passing(candidate, "visual")
                candidate["verdicts"]["visual"][key] = value
                with self.assertRaisesRegex(StudioError, key + " disagrees"):
                    validate_candidate(candidate, self.root)

    def test_a_stored_performance_class_that_disagrees_is_refused(self):
        candidate = self.candidate()
        self.passing(candidate, "performance")
        candidate["verdicts"]["performance"]["performance_class"] = "subjective_acceptance"
        with self.assertRaisesRegex(StudioError, "performance_class disagrees"):
            validate_candidate(candidate, self.root)

    def test_a_record_storing_no_rollups_at_all_still_validates(self):
        # A legacy candidate has nothing to disagree with, and every rule above
        # reads the rows rather than the summary.
        candidate = self.candidate()
        self.passing(candidate, "visual")
        for verdict in candidate["verdicts"].values():
            for key in ("evidence_total", "evidence_current", "performance_class"):
                verdict.pop(key, None)
        validate_candidate(candidate, self.root)

    def accepted(self):
        candidate = self.candidate()
        for dimension in self.METHODS:
            self.passing(candidate, dimension)
        candidate["settings"] = {"renderer": "gl_compatibility", "viewport": [1280, 720]}
        candidate["input_route"] = "offline fixture route"
        candidate["acceptance"] = {"decision": "accepted", "reviewer": "offline fixture",
                                   "rationale": "offline fixture"}
        return candidate

    def test_acceptance_needs_every_mandatory_dimension_passing_on_current_evidence(self):
        validate_candidate(self.accepted(), self.root)
        for dimension in self.METHODS:
            with self.subTest(dimension=dimension):
                candidate = self.accepted()
                candidate["verdicts"][dimension]["evidence"][0]["identity"] = "historical"
                refresh_rollups(candidate)
                with self.assertRaises(StudioError):
                    validate_candidate(candidate, self.root)

    def test_a_dimension_marked_not_applicable_still_needs_only_a_reason(self):
        candidate = self.accepted()
        candidate["verdicts"]["audio"] = {"status": "not_applicable", "reason": "silent fixture",
                                          "evidence": [], "evidence_current": 0, "evidence_total": 0}
        validate_candidate(candidate, self.root)


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
