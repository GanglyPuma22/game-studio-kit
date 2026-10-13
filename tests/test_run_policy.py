"""Offline decision tests; never launch an engine or authenticate acceptance."""

from pathlib import Path
import tempfile
import unittest

from studio_tools.common import StudioError, file_record, write_json
from studio_tools.evidence import new_candidate
from studio_tools.records import validate
from studio_tools.run_policy import compare_baseline

CONDITIONS = {"route": "ordinary", "scope": "coast", "engine": "test-engine",
              "renderer": "forward_plus", "resolution": [1920, 1080],
              "hardware": "synthetic-host", "metric": "frame_ms", "statistic": "p95"}


class RunPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "project.godot").write_text("[application]\n", encoding="utf-8")
        self.artifacts = self.root / "artifacts/run"
        self.artifacts.mkdir(parents=True)
        proof = self.artifacts / "authority.txt"
        proof.write_text("Synthetic test authorization and observation", encoding="utf-8")
        self.proof = file_record(self.root, proof)
        self.policy = {
            "schema_version": 1, "kind": "run-policy", "run_id": "test-run",
            "project_id": "game", "authorization": self.proof,
            "started_utc": "2026-10-03T16:00:00Z", "cutoff_utc": "2026-10-03T18:30:00Z",
            "goals": ["coast"], "lanes": [
                {"id": "integrate", "goal_id": "coast", "scope": "coast", "dependencies": []},
                {"id": "review", "goal_id": "coast", "scope": "coast", "dependencies": []},
            ], "overall_limits": [], "hard_gates": [],
        }
        candidate = new_candidate(self.root, "coast-001", "test-engine", "0.1.6")
        path = self.artifacts / "candidate.json"
        write_json(path, candidate)
        self.decision = {
            "schema_version": 1, "kind": "run-decision", "decision_id": "decision-001",
            "run_id": "test-run", "at_utc": "2026-10-03T17:00:00Z",
            "policy": {}, "candidate": file_record(self.root, path),
            "candidate_id": candidate["candidate_id"], "content_digest": candidate["content_digest"],
            "remaining": {"seconds_until_cutoff": 5400, "explicit_limits": []},
            "lane_inventory": [
                {"id": "integrate", "maturity": "source-ready", "status": "feasible", "next_operation": "Wire coast on canonical route"},
                {"id": "review", "maturity": "integrated", "status": "feasible", "next_operation": "Review authored coast"},
            ], "affected": {"kind": "action", "id": "integrate"},
            "trigger": {"code": "performance_miss", "evidence": [self.proof]},
            "disposition": "continue", "stop_authority": None,
            "selected_lane": "integrate", "selected_operation": "Wire coast on canonical route",
            "rationale": "Pending authorized coast work and remaining budget",
        }

    def authority(self, kind, rule="instruction"):
        return {"type": kind, "reference": self.proof, "rule_id": rule}

    def check(self):
        path = self.artifacts / "policy.json"
        write_json(path, self.policy)
        self.decision["policy"] = file_record(self.root, path)
        return validate(self.decision, self.root)

    def stop(self, kind, rule="instruction"):
        self.decision.update(disposition="handback", stop_authority=self.authority(kind, rule),
                             affected={"kind": "run", "id": "test-run"})

    def block(self, lane, kind="host"):
        lane["status"] = "blocked"
        lane["blocker"] = {"authority": self.authority(kind), "evidence": [self.proof]}

    def select_review(self):
        self.decision.update(selected_lane="review", selected_operation="Review authored coast")

    def test_exact_incident_shortfall_dirty_capture_cannot_end_run(self):
        baseline = {"value_ms": 17, "performance_class": "clean_qualification", "conditions": CONDITIONS}
        candidate = {"value_ms": 17, "performance_class": "diagnostic", "conditions": CONDITIONS}
        finding = compare_baseline(baseline, candidate, 16.67)
        self.assertEqual(finding["baseline_shortfall"], "present")
        self.assertEqual(finding["regression_status"], "unproven")
        self.assertEqual(finding["target_status"], "unverified")
        self.decision["quality_findings"] = [finding]
        result = self.check()
        self.assertFalse(result["stop_authorized"])
        self.assertTrue(result["mandatory_continuation"])
        self.stop("all_lanes_blocked")
        with self.assertRaisesRegex(StudioError, "Denied stop.*integrate"):
            self.check()

    def test_numeric_target_does_not_select_strict_mode(self):
        self.policy["frame_target_ms"] = 16.67
        self.assertEqual(validate(self.policy, self.root)["mode"], "development")

    def test_clean_equal_baseline_misses_target_without_regression(self):
        observation = {"value_ms": 17, "performance_class": "clean_qualification", "conditions": CONDITIONS}
        result = compare_baseline(observation, observation, 16.67)
        self.assertEqual((result["target_status"], result["regression_status"]), ("missed", "not_observed"))

    def test_regression_requires_comparability_and_repeats(self):
        baseline = {"value_ms": 17, "performance_class": "clean_qualification", "conditions": CONDITIONS, "repeat_count": 2}
        candidate = dict(baseline, value_ms=20, tolerance_ms=0.5, required_repeats=2)
        self.assertEqual(compare_baseline(baseline, candidate, 16.67)["regression_status"], "demonstrated")
        candidate["conditions"] = {"scope": "planet"}
        self.assertEqual(compare_baseline(baseline, candidate, 16.67)["regression_status"], "unproven")

    def test_missing_comparison_conditions_never_proves_regression(self):
        observation = {"value_ms": 17, "performance_class": "clean_qualification", "conditions": {"scope": "coast"}}
        self.assertEqual(compare_baseline(observation, observation, 16.67)["regression_status"], "unproven")

    def test_hypothesis_exhaustion_stops_only_experiment(self):
        self.decision.update(disposition="stop_experiment", affected={"kind": "experiment", "id": "shadow-cost"},
                             hypothesis={"stable_family_id": "shadow-cost", "used_trials": 3, "used_seconds": 100})
        self.select_review()
        self.assertFalse(self.check()["stop_authorized"])
        self.stop("experiment_budget")
        with self.assertRaisesRegex(StudioError, "Unknown or denied authority"):
            self.check()

    def test_hypothesis_time_allowance_is_also_local(self):
        self.decision.update(disposition="stop_experiment", affected={"kind": "experiment", "id": "shadow-cost"},
                             hypothesis={"stable_family_id": "shadow-cost", "used_trials": 1, "used_seconds": 900})
        self.assertTrue(self.check()["mandatory_continuation"])

    def test_human_stop_overrides_remaining_budget(self):
        self.stop("human_stop")
        self.decision["trigger"]["code"] = "human_stop"
        self.assertTrue(self.check()["stop_authorized"])
        self.decision.update(disposition="continue", stop_authority=None)
        with self.assertRaisesRegex(StudioError, "prohibits continuation"):
            self.check()

    def test_deadline_exactly_1830_utc(self):
        self.stop("deadline")
        with self.assertRaisesRegex(StudioError, "Denied stop"):
            self.check()
        self.decision["at_utc"] = "2026-10-03T18:30:00Z"
        self.decision["remaining"]["seconds_until_cutoff"] = 0
        self.assertTrue(self.check()["stop_authorized"])

    def test_explicit_overall_budget_exhaustion(self):
        self.policy["overall_limits"] = [{"id": "launch-cap", "unit": "launches", "maximum": 6,
                                           "authority": self.authority("human_instruction")}]
        self.decision["remaining"]["explicit_limits"] = [{"id": "launch-cap", "used": 6}]
        self.stop("overall_budget", "launch-cap")
        self.assertTrue(self.check()["stop_authorized"])
        self.decision["remaining"]["explicit_limits"][0]["used"] = None
        with self.assertRaisesRegex(StudioError, "Unknown overall usage"):
            self.check()

    def test_scope_gate_blocks_only_affected_lane(self):
        self.policy.update(mode="strict_qualification", strict_authority=self.authority("contract"))
        self.policy["lanes"][1]["scope"] = "independent"
        self.policy["hard_gates"] = [{"id": "scope-frame", "effect": "block_scope",
                                     "affected": {"kind": "scope", "id": "coast"},
                                     "authority": self.authority("contract")}]
        lane = self.decision["lane_inventory"][0]
        self.block(lane, "hard_gate")
        lane["blocker"]["gate_id"] = "scope-frame"
        self.select_review()
        self.assertTrue(self.check()["mandatory_continuation"])
        self.stop("hard_gate", "scope-frame")
        self.decision["trigger"].update(code="hard_gate_failed", gate_id="scope-frame")
        with self.assertRaisesRegex(StudioError, "Denied stop"):
            self.check()

    def test_all_lanes_binding_blocked_allows_handback(self):
        for row in self.decision["lane_inventory"]:
            self.block(row)
        self.stop("all_lanes_blocked")
        self.assertTrue(self.check()["stop_authorized"])

    def test_blocked_review_cannot_hide_unaccepted_complete_source_lane(self):
        source, review = self.decision["lane_inventory"]
        source.update(status="complete", completion_evidence=[self.proof])
        self.block(review)
        self.stop("all_lanes_blocked")
        for maturity in ("source-ready", "root-reviewed", "integrated", "native-reviewed"):
            with self.subTest(maturity=maturity):
                source["maturity"] = maturity
                with self.assertRaisesRegex(StudioError, "Denied stop authority: all_lanes_blocked"):
                    self.check()
        source["maturity"] = "user-accepted"
        self.assertTrue(self.check()["stop_authorized"])

    def test_host_block_keeps_independent_source_lane_actionable(self):
        self.block(self.decision["lane_inventory"][1])
        self.assertEqual(self.check()["next_lane"], "integrate")
        self.stop("all_lanes_blocked")
        with self.assertRaisesRegex(StudioError, "Denied stop.*integrate"):
            self.check()

    def test_deferred_unqualified_lane_is_not_all_lanes_blocked(self):
        for row in self.decision["lane_inventory"]:
            row["status"] = "deferred"
        self.stop("all_lanes_blocked")
        with self.assertRaisesRegex(StudioError, "Denied stop"):
            self.check()

    def test_explicit_strict_stop_run_gate_requires_matching_failure(self):
        self.policy.update(mode="strict_qualification", strict_authority=self.authority("contract"))
        self.policy["hard_gates"] = [{"id": "hard-stop", "effect": "stop_run",
                                     "affected": {"kind": "run", "id": "test-run"},
                                     "authority": self.authority("contract")}]
        self.stop("hard_gate", "hard-stop")
        with self.assertRaisesRegex(StudioError, "Denied stop"):
            self.check()
        self.decision["trigger"].update(code="hard_gate_failed", gate_id="hard-stop")
        self.assertTrue(self.check()["stop_authorized"])
        self.decision.update(disposition="continue", stop_authority=None)
        with self.assertRaisesRegex(StudioError, "prohibits continuation"):
            self.check()

    def test_strict_mode_and_gate_effect_need_explicit_authority(self):
        self.policy["mode"] = "strict_qualification"
        with self.assertRaisesRegex(StudioError, "Authority needs"):
            self.check()
        self.policy["strict_authority"] = self.authority("contract")
        self.policy["hard_gates"] = [{"id": "gate", "effect": "stop_stage_twice",
                                     "affected": {"kind": "run", "id": "test-run"},
                                     "authority": self.authority("contract")}]
        with self.assertRaisesRegex(StudioError, "Unknown hard gate effect"):
            self.check()

    def test_unknown_authority_fields_are_not_silently_ignored(self):
        self.stop("human_stop")
        self.decision["stop_authority"]["invented_permission"] = True
        with self.assertRaisesRegex(StudioError, "Authority needs only"):
            self.check()

    def test_global_safety_stop_is_independent_of_quality(self):
        self.stop("global_safety")
        self.decision["trigger"]["code"] = "global_safety"
        self.assertTrue(self.check()["stop_authorized"])

    def test_omitted_source_lane_and_merely_deferred_lane_do_not_authorize_stop(self):
        self.stop("all_lanes_blocked")
        self.decision["lane_inventory"].pop()
        with self.assertRaisesRegex(StudioError, "Incomplete lane inventory"):
            self.check()

    def test_quality_finding_cannot_be_binding_blocker(self):
        self.block(self.decision["lane_inventory"][0], "performance_miss")
        with self.assertRaisesRegex(StudioError, "Unknown or denied authority"):
            self.check()

    def test_unknown_stop_authority_rejected(self):
        self.stop("stage_failed_twice")
        with self.assertRaisesRegex(StudioError, "Unknown or denied authority"):
            self.check()

    def test_goal_done_requires_all_lanes_complete_with_evidence(self):
        self.stop("goal_done")
        with self.assertRaisesRegex(StudioError, "Denied stop"):
            self.check()
        for row in self.decision["lane_inventory"]:
            row.update(status="complete", maturity="user-accepted", completion_evidence=[self.proof])
        self.assertTrue(self.check()["stop_authorized"])

    def test_complete_source_ready_lanes_do_not_authorize_goal_done(self):
        for row in self.decision["lane_inventory"]:
            row.update(status="complete", maturity="source-ready", completion_evidence=[self.proof])
        self.stop("goal_done")
        with self.assertRaisesRegex(StudioError, "Denied stop authority: goal_done"):
            self.check()
        self.stop("all_lanes_blocked")
        with self.assertRaisesRegex(StudioError, "Denied stop authority: all_lanes_blocked"):
            self.check()
        self.stop("human_stop")
        self.decision["trigger"]["code"] = "human_stop"
        self.assertTrue(self.check()["stop_authorized"])

    def test_development_complete_uses_explicit_targets_without_claiming_acceptance(self):
        for lane, row in zip(self.policy["lanes"], self.decision["lane_inventory"]):
            lane["completion_maturity"] = "root-reviewed"
            row.update(status="complete", maturity="root-reviewed", completion_evidence=[self.proof])
        self.stop("development_complete")
        result = self.check()
        self.assertTrue(result["stop_authorized"])
        self.assertEqual(result["pending_human_review"], ["integrate", "review"])
        self.assertFalse(result["human_acceptance_established"])
        self.stop("goal_done")
        with self.assertRaisesRegex(StudioError, "Denied stop authority: goal_done"):
            self.check()

    def test_development_completion_target_is_an_ordered_minimum(self):
        for lane, row in zip(self.policy["lanes"], self.decision["lane_inventory"]):
            lane["completion_maturity"] = "root-reviewed"
            row.update(status="complete", completion_evidence=[self.proof])
        self.stop("development_complete")
        for maturity in ("root-reviewed", "integrated", "native-reviewed", "user-accepted"):
            with self.subTest(maturity=maturity):
                for row in self.decision["lane_inventory"]:
                    row["maturity"] = maturity
                self.assertTrue(self.check()["stop_authorized"])
        for row in self.decision["lane_inventory"]:
            row["maturity"] = "source-ready"
        with self.assertRaisesRegex(StudioError, "Denied stop authority: development_complete"):
            self.check()

    def test_absent_completion_target_retains_user_accepted_threshold(self):
        for row in self.decision["lane_inventory"]:
            row.update(status="complete", maturity="source-ready", completion_evidence=[self.proof])
        self.stop("development_complete")
        with self.assertRaisesRegex(StudioError, "Denied stop authority: development_complete"):
            self.check()
        for row in self.decision["lane_inventory"]:
            row["maturity"] = "user-accepted"
        result = self.check()
        self.assertTrue(result["stop_authorized"])
        self.assertEqual(result["pending_human_review"], [])
        self.assertFalse(result["human_acceptance_established"])

    def test_completion_target_must_be_known_and_beyond_in_progress(self):
        for target in (None, "in-progress", "test-complete", "", [], {}, False, 0):
            with self.subTest(target=target):
                self.policy["lanes"][0]["completion_maturity"] = target
                with self.assertRaisesRegex(StudioError, "completion_maturity.*known maturity"):
                    self.check()

    def test_native_goal_cannot_finish_at_source_ready_or_while_unfinished(self):
        source, native = self.decision["lane_inventory"]
        self.policy["lanes"][0]["completion_maturity"] = "source-ready"
        self.policy["lanes"][1]["completion_maturity"] = "native-reviewed"
        source.update(status="complete", completion_evidence=[self.proof])
        native.update(status="complete", maturity="source-ready", completion_evidence=[self.proof])
        self.stop("development_complete")
        with self.assertRaisesRegex(StudioError, "Denied stop authority: development_complete"):
            self.check()
        native["maturity"] = "native-reviewed"
        for status in ("feasible", "deferred"):
            with self.subTest(status=status):
                native["status"] = status
                with self.assertRaisesRegex(StudioError, "Denied stop authority: development_complete"):
                    self.check()
        native["status"] = "complete"
        self.assertTrue(self.check()["stop_authorized"])

    def test_completion_target_must_exist_in_policy_not_only_inventory(self):
        for row in self.decision["lane_inventory"]:
            row.update(status="complete", maturity="source-ready", completion_evidence=[self.proof],
                       completion_maturity="source-ready")
        self.stop("development_complete")
        with self.assertRaisesRegex(StudioError, "Denied stop authority: development_complete"):
            self.check()

    def test_development_complete_is_denied_in_strict_mode_even_when_accepted(self):
        self.policy.update(mode="strict_qualification", strict_authority=self.authority("contract"))
        for lane, row in zip(self.policy["lanes"], self.decision["lane_inventory"]):
            lane["completion_maturity"] = "root-reviewed"
            row.update(status="complete", maturity="user-accepted", completion_evidence=[self.proof])
        self.stop("development_complete")
        with self.assertRaisesRegex(StudioError, "Denied stop authority: development_complete"):
            self.check()
        self.stop("goal_done")
        self.assertTrue(self.check()["stop_authorized"])

    def test_blocked_native_and_complete_explicit_source_allow_development_handback(self):
        source, native = self.decision["lane_inventory"]
        self.policy["lanes"][0]["completion_maturity"] = "source-ready"
        self.policy["lanes"][1]["completion_maturity"] = "native-reviewed"
        source.update(status="complete", completion_evidence=[self.proof])
        self.block(native)
        self.stop("all_lanes_blocked")
        result = self.check()
        self.assertTrue(result["stop_authorized"])
        self.assertEqual(result["pending_human_review"], ["integrate", "review"])
        self.policy.update(mode="strict_qualification", strict_authority=self.authority("contract"))
        with self.assertRaisesRegex(StudioError, "Denied stop authority: all_lanes_blocked"):
            self.check()

    def test_explicit_target_does_not_hide_feasible_or_deferred_source_work(self):
        source, native = self.decision["lane_inventory"]
        self.policy["lanes"][0]["completion_maturity"] = "source-ready"
        self.block(native)
        self.stop("all_lanes_blocked")
        for status in ("feasible", "deferred"):
            with self.subTest(status=status):
                source["status"] = status
                with self.assertRaisesRegex(StudioError, "Denied stop authority: all_lanes_blocked"):
                    self.check()

    def test_development_completion_requires_nonempty_hashed_evidence(self):
        for lane, row in zip(self.policy["lanes"], self.decision["lane_inventory"]):
            lane["completion_maturity"] = "source-ready"
            row.update(status="complete", maturity="source-ready", completion_evidence=[self.proof])
        self.stop("development_complete")
        row = self.decision["lane_inventory"][0]
        for completion_evidence in (None, [], [dict(self.proof, sha256="0" * 64)]):
            with self.subTest(evidence=completion_evidence):
                row["completion_evidence"] = completion_evidence
                with self.assertRaises(StudioError):
                    self.check()

    def test_continuation_requires_concrete_operation(self):
        self.decision["selected_operation"] = "Maybe improve something"
        with self.assertRaisesRegex(StudioError, "Mandatory continuation"):
            self.check()

    def test_unfinished_lane_operation_must_be_nonempty_text(self):
        lane = self.decision["lane_inventory"][0]
        for operation in ("   ", "\t\n", [], {}, False, 0):
            with self.subTest(operation=operation):
                lane["next_operation"] = operation
                self.decision["selected_operation"] = operation
                with self.assertRaisesRegex(StudioError, "concrete text next operation"):
                    self.check()

    def test_authority_hash_path_number_and_utc_guards(self):
        for value in (True, -1, float("nan"), float("inf")):
            with self.subTest(number=value):
                self.decision["remaining"]["seconds_until_cutoff"] = value
                with self.assertRaises(StudioError):
                    self.check()
        self.decision["remaining"]["seconds_until_cutoff"] = 5400
        for stamp in ("2026-10-03T17:00:00", "2026-13-03T17:00:00Z"):
            self.decision["at_utc"] = stamp
            with self.assertRaises(StudioError):
                self.check()
        self.decision["at_utc"] = "2026-10-03T17:00:00Z"
        self.policy["authorization"] = dict(self.proof, path="../escape")
        with self.assertRaises(StudioError):
            self.check()
        self.policy["authorization"] = dict(self.proof, sha256="0" * 64)
        with self.assertRaisesRegex(StudioError, "Hash mismatch"):
            self.check()

    def test_obsolete_candidate_decision_rejected(self):
        (self.root / "project.godot").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(StudioError, "Hash mismatch"):
            self.check()


if __name__ == "__main__":
    unittest.main()
