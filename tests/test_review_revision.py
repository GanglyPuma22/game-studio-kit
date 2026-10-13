"""Pure Python structural controls; every observation is a synthetic attestation."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools.common import StudioError, digest, file_record, write_json
from studio_tools.review_revision import assess


class RevisionReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.notes = self.root / "synthetic-notes.txt"
        self.notes.write_text("TEST ONLY. No real model, video, native inspection or human acceptance.")
        self.before = self.candidate("before", "before bytes")
        self.after = self.candidate("after", "revised bytes")
        self.value = {
            "schema_version": 1, "kind": "review-revision", "builder": "builder",
            "candidates": [self.before[0], self.after[0]],
            "criteria": [{"id": "CONTACT", "kind": "visual", "subjects": ["pocket-1"],
                          "required_scope": ["close", "reverse"], "environment": "native"}],
            "evidence": [self.evidence("before-close", self.before[1]), self.evidence("after-close", self.after[1])],
            "defects": [{"defect_id": "pocket-1/CONTACT-01", "criterion_id": "CONTACT", "subjects": ["pocket-1"],
                         "candidate_before": self.before[1], "before_evidence": ["before-close"],
                         "observed_defect": "Synthetic floating root", "requested_outcome": "Synthetic rooted contact",
                         "candidate_after": self.after[1], "change_summary": "Synthetic revision",
                         "after_evidence": ["after-close"], "critic_recheck": self.recheck("critic"),
                         "root_recheck": self.recheck("builder"), "root_decision": "closed"}],
            "human_acceptance": "accepted",  # The report must never adopt this assertion.
        }

    def candidate(self, name, text):
        path = self.root / (name + "-source.txt")
        path.write_text("TEST ONLY " + text)
        files = [file_record(self.root, path)]
        record = {"schema_version": 1, "kind": "candidate", "inventory_version": 2,
                  "candidate_id": name, "content_files": files, "content_digest": digest(files),
                  "workflow_files": files, "workflow_digest": digest(files)}
        target = self.root / (name + "-candidate.json")
        write_json(target, record)
        return file_record(self.root, target), {k: record[k] for k in ("candidate_id", "content_digest")}

    def evidence(self, eid, candidate):
        return {"id": eid, **candidate, "criterion_id": "CONTACT", "subjects": ["pocket-1"],
                "method": "still", "environment": "native", "observer": "synthetic observer",
                "inspection": "performed", "capability": "supported", "inspected_scope": ["close", "reverse"],
                "unknowns": ["unexamined inland area"], "location": "synthetic close/reverse notes",
                "files": [file_record(self.root, self.notes)]}

    def recheck(self, observer):
        return {"observer": observer, "status": "performed", "verdict": "met", **self.after[1],
                "evidence": ["after-close"], "inspected_scope": ["close", "reverse"],
                "unknowns": ["inland not inspected"], "observation": "Synthetic criterion rechecked"}

    def report(self):
        write_json(self.root / "review.json", self.value)
        return assess(self.root, "review.json")

    def test_sufficient_local_attestations_support_only_record_closure(self):
        report = self.report()
        self.assertTrue(report["defects"][0]["closure_supported_by_record"])
        self.assertEqual(report["human_acceptance"], "not_established")
        self.assertEqual(report["authority"], "local_named_attestation")
        self.assertIn("not independently established", report["limitation"])
        self.assertEqual(report["coverage"][1]["subjects"][0]["unknowns"], ["unexamined inland area"])
        self.assertNotIn("accepted", report)

    def test_successful_visual_revision_preserves_separate_open_access_defect(self):
        criterion = {"id": "ACCESS", "kind": "interaction", "subjects": ["pocket-1"],
                     "required_scope": ["approach"], "environment": "native"}
        self.value["criteria"].append(criterion)
        defect = copy.deepcopy(self.value["defects"][0])
        defect.update(defect_id="pocket-1/ACCESS-01", criterion_id="ACCESS", root_decision="open",
                      before_evidence=[], candidate_after=None, after_evidence=[], critic_recheck=None,
                      root_recheck=None, change_summary=None)
        self.value["defects"].append(defect)
        report = self.report()
        self.assertTrue(report["defects"][0]["closure_supported_by_record"])
        self.assertEqual(report["open_defects"], ["pocket-1/ACCESS-01"])
        self.assertEqual(report["coverage"][-1]["subjects"][0]["status"], "unobserved")

    def test_hero_image_does_not_cover_reverse_or_other_new_pockets(self):
        self.value["criteria"][0]["subjects"] += ["pocket-2", "pocket-3", "pocket-4", "pocket-5", "pocket-6"]
        self.value["evidence"][1]["inspected_scope"] = ["close"]
        report = self.report()
        rows = report["coverage"][1]["subjects"]
        self.assertEqual(rows[0]["status"], "partial")
        self.assertEqual(rows[0]["missing_scope"], ["reverse"])
        self.assertTrue(all(r["status"] == "unobserved" for r in rows[1:]))
        self.assertFalse(report["defects"][0]["closure_supported_by_record"])

    def test_stills_cannot_close_temporal_shimmer(self):
        self.value["criteria"][0]["kind"] = "temporal"
        report = self.report()
        self.assertEqual(report["unsupported_closure_claims"], ["pocket-1/CONTACT-01"])
        self.assertIn("temporal criterion", " ".join(report["defects"][0]["reasons"]))

    def temporal_live(self):
        self.value["criteria"][0]["kind"] = "temporal"
        for evidence in self.value["evidence"]:
            evidence.update(method="scene_inspection", interval=[0, 2], duration_seconds=2,
                            temporal_inspection=True, context="Synthetic declared native scene",
                            actions=["synthetic lateral walk"])

    def test_bounded_live_temporal_notes_do_not_require_a_recorded_video(self):
        self.temporal_live()
        self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])

    def test_clip_needs_retained_media_and_actual_temporal_inspection(self):
        self.temporal_live()
        for evidence in self.value["evidence"]:
            evidence["method"] = "clip"
        self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])
        media_path = self.root / "synthetic-clip.dat"
        media_path.write_bytes(b"NOT A VIDEO. Test-only retained byte identity.")
        media = file_record(self.root, media_path)
        for evidence in self.value["evidence"]:
            evidence.update(media=media, files=evidence["files"] + [media])
        # This validates declarations only. It does not decode or qualify media.
        self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])
        self.value["evidence"][1]["temporal_inspection"] = False
        self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])

    def test_unknown_live_interval_or_capability_cannot_close(self):
        for field, value in (("interval", None), ("capability", "unknown"), ("duration_seconds", True), ("context", "")):
            with self.subTest(field=field):
                self.temporal_live()
                self.value["evidence"][1][field] = value
                self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])
                self.value["evidence"][1] = self.evidence("after-close", self.after[1])

    def test_model_render_cannot_close_gameplay(self):
        self.value["criteria"][0]["kind"] = "interaction"
        self.value["evidence"][1].update(method="model_inspection", environment="blender")
        self.assertIn("native ordinary-input", " ".join(self.report()["defects"][0]["reasons"]))

    def test_native_ordinary_interaction_is_allowed_but_synthetic_is_not(self):
        self.value["criteria"][0]["kind"] = "interaction"
        for evidence in self.value["evidence"]:
            evidence.update(method="live_interaction", context="Synthetic scene", actions=["walk then step"], input_route="ordinary")
        self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])
        self.value["evidence"][1]["input_route"] = "synthetic"
        self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])

    def test_before_content_can_be_historical(self):
        (self.root / "before-source.txt").unlink()
        self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])

    def test_wrong_after_candidate_or_unchanged_content_cannot_close(self):
        self.value["evidence"][1].update(self.before[1])
        self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])
        self.value["evidence"][1].update(self.after[1])
        self.value["defects"][0]["candidate_after"] = self.before[1]
        self.assertIn("changed candidate content", " ".join(self.report()["defects"][0]["reasons"]))

    def test_rechecks_need_independent_critic_and_revised_evidence(self):
        original = copy.deepcopy(self.value["defects"][0])
        for replacement in (None, {**self.recheck("builder")}, {**self.recheck("critic"), **self.before[1]},
                            {**self.recheck("critic"), "evidence": ["before-close"]},
                            {**self.recheck("critic"), "verdict": "partial"}):
            with self.subTest(replacement=replacement):
                self.value["defects"][0] = copy.deepcopy(original)
                self.value["defects"][0]["critic_recheck"] = replacement
                self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])

    def test_drift_or_missing_files_preserves_partial_report(self):
        self.notes.write_text("Changed test evidence")
        report = self.report()
        self.assertFalse(report["defects"][0]["closure_supported_by_record"])
        self.assertIn("Hash mismatch", report["evidence_issues"][0]["reasons"][0])
        self.notes.unlink()
        self.assertIn("Missing file", self.report()["evidence_issues"][0]["reasons"][0])

    def test_interrupted_exclusive_handoff_is_an_operational_finding(self):
        self.value["evidence"][1]["handoff"] = {"control_mode": "exclusive", "released": False, "state_reconciled": False}
        report = self.report()
        self.assertTrue(report["operational_findings"])
        self.assertFalse(report["defects"][0]["closure_supported_by_record"])
        self.value["evidence"][1]["handoff"].update(released=True, state_reconciled=True)
        self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])

    def test_explicit_reference_rejection_is_separate_from_revision_closure(self):
        defect = self.value["defects"][0]
        defect.update(root_decision="rejected", decision_reason="Named reference intentionally exposes this root", decision_basis="reference")
        report = self.report()
        self.assertFalse(report["defects"][0]["closure_supported_by_record"])
        self.assertEqual(report["rejected_findings"], [defect["defect_id"]])
        self.assertEqual(report["open_defects"], [])
        defect["decision_reason"] = ""
        self.assertEqual(self.report()["open_defects"], [defect["defect_id"]])

    def test_optional_existing_lineage_must_bind_affected_before_after(self):
        before_path, after_path = self.root / "before/run.json", self.root / "after/run.json"
        write_json(before_path, {"test": True})
        write_json(after_path, {"test": True})
        before_ref, after_ref = file_record(self.root, before_path), file_record(self.root, after_path)
        self.value["defects"][0].update(before_run=before_ref, after_run=after_ref)
        runs = [{"candidate": self.before[1], "role": "before"},
                {"candidate": self.after[1], "role": "after", "previous": before_ref, "affected": ["CONTACT"]}]
        with patch("studio_tools.validation.validate_run", side_effect=runs):
            self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])
        runs[1]["affected"] = []
        with patch("studio_tools.validation.validate_run", side_effect=runs):
            self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])

    def test_malformed_lists_duplicate_ids_and_candidate_identity_fail_explicitly(self):
        original = copy.deepcopy(self.value)
        for change in (lambda: self.value.update(evidence={}),
                       lambda: self.value["evidence"].append(copy.deepcopy(self.value["evidence"][0])),
                       lambda: self.value["candidates"][0].update(sha256="0" * 64)):
            with self.subTest(change=change):
                self.value = copy.deepcopy(original)
                change()
                with self.assertRaises(StudioError):
                    self.report()


    def test_visual_live_inspection_needs_context_and_actions(self):
        item = self.value["evidence"][1]
        item["method"] = "live_interaction"
        self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])
        item.update(context="Synthetic shore", actions=["orbit the shelf"])
        self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])

    def test_interaction_clip_needs_time_bounds_and_temporal_observation(self):
        self.value["criteria"][0]["kind"] = "interaction"
        for item in self.value["evidence"]:
            item.update(method="clip", media=item["files"][0], context="Synthetic shore",
                        actions=["ordinary walk"], input_route="ordinary")
        self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])
        for item in self.value["evidence"]:
            item.update(interval=[0, 2], duration_seconds=2, temporal_inspection=True)
        self.assertTrue(self.report()["defects"][0]["closure_supported_by_record"])

    def test_named_critic_independence_normalizes_whitespace_and_case(self):
        for name in ("builder ", " Builder", "BUILDER"):
            self.value["defects"][0]["critic_recheck"]["observer"] = name
            self.assertFalse(self.report()["defects"][0]["closure_supported_by_record"])

    def test_malformed_enum_and_lookup_types_raise_studio_error(self):
        original = copy.deepcopy(self.value)
        for group, key, invalid in (("evidence", "method", {}),
                                    ("evidence", "criterion_id", []),
                                    ("criteria", "kind", []),
                                    ("defects", "root_decision", {})):
            self.value = copy.deepcopy(original)
            self.value[group][0][key] = invalid
            with self.assertRaises(StudioError):
                self.report()

    def test_cli_does_not_create_a_missing_project(self):
        import contextlib
        import io
        from studio_tools.cli import main
        missing = self.root / "mistyped-project"
        with contextlib.redirect_stderr(io.StringIO()):
            result = main(["review", "revision", "--project", str(missing), "--evidence", "review.json"])
        self.assertEqual(result, 1)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
