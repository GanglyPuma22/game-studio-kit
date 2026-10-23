"""CPU-only factory safety tests; native measurements and publishing are mocked."""
import copy
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from studio_tools import model_factory as factory
from studio_tools.common import StudioError, digest, file_record, read_json, sha256, write_json
from studio_tools.model_qa import __main__ as qa_main
from studio_tools.model_qa.report import CHECKS


def _hold_lock(path, entered, release):
    with factory.writer_lock(path):
        entered.set()
        release.wait(10)


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.brief = {
            "schema_version": 1, "id": "specimen", "version": "v1",
            "concept": self.ref("concept.txt", "exact concept"),
            "policy": {"reference": self.ref("policy.txt", "project policy"),
                       "allow_nonliving_na": True, "allow_clump_info": False},
            "ecology": {"living": False, "reference": None, "reason": "Manufactured test object"},
            "size_m": [1, 2, 3], "tolerance_m": 0.01, "structure": "assembly",
            "lods": [{"level": 0, "maximum_triangles": 100, "switch_distance_m": 2},
                     {"level": 1, "maximum_triangles": 50, "switch_distance_m": 10}],
            "build": {"mode": "reuse", "models": [
                {"level": i, **self.ref(f"input-lod{i}.glb", f"mock model {i}")} for i in range(2)]},
        }
        self.save()
        self.qa_change = lambda report, execution: None
        self.qa_code = 0
        self.dimensions = [1, 3, 2]  # Blender Z-up, distinct axes make conversion observable.
        self.bounds_pose = "armature_rest"
        self.qa_calls = []
        self.preflight = self.start_patch("studio_tools.model_factory.host.preflight", side_effect=self.fake_preflight)
        self.qa = self.start_patch("studio_tools.model_factory.model_qa.main", side_effect=self.fake_qa)
        self.inspect = self.start_patch("studio_tools.model_factory.blender.inspect", side_effect=self.fake_inspect)
        self.build = self.start_patch("studio_tools.model_factory.blender.script_run", side_effect=self.fake_build)

    def start_patch(self, target, **kwargs):
        p = patch(target, **kwargs)
        result = p.start()
        self.addCleanup(p.stop)
        return result

    def ref(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return file_record(self.root, path)

    def save(self):
        write_json(self.root / "brief.json", self.brief)

    def run_factory(self, **kwargs):
        return factory.execute(self.root, "brief.json", "run", **kwargs)

    def fake_preflight(self, config, *, output):
        result = {"ready": True, "host_kind": "windows", "reasons": []}
        write_json(output, result)
        return result

    def fake_qa(self, argv):
        args = qa_main.parser().parse_args(argv)
        self.qa_calls.append(args)
        out = Path(args.out)
        out.mkdir(exist_ok=False)
        report = {"schema_version": 2, "result": "PASS", "errors": [], "models": []}
        for i, path in enumerate(args.inputs):
            checks = [{"check": check, "result": "PASS", "details": {}, "numbers": "mock measurement"} for check in CHECKS]
            checks[3]["details"] = {"triangles": 80 if i == 0 else 40, "maximum": args.budget_tris}
            if not self.brief["ecology"]["living"]:
                checks[4]["result"] = "N/A"
            if self.brief["structure"] == "clump":
                checks[1]["result"] = "INFO"
            report["models"].append({"lod": i, "file": Path(path).name, "sha256": sha256(path), "checks": checks})
        execution = {"result": "PASS", "process": {"returncode": 0}}
        self.qa_change(report, execution)
        write_json(out / "report.json", report)
        write_json(out / "execution.json", execution)
        (out / "capture.png").write_bytes(b"mock capture")
        return self.qa_code

    def fake_inspect(self, config, source, output, *, rest_pose=False):
        self.assertTrue(rest_pose)
        info = {"dimensions_m": self.dimensions}
        if self.bounds_pose is not None:
            info["bounds_pose"] = self.bounds_pose
        write_json(output, info)
        return info

    def fake_build(self, config, project, **kwargs):
        for index, result in enumerate(kwargs["results"]):
            (Path(project) / result).write_bytes(f"fresh mock model {index}".encode())
        return {"ok": True, "results": kwargs["results"]}

    def approvals(self, result=None):
        result = result or self.run_factory()
        subject = {"concept": self.brief["concept"]["sha256"], "policy": factory.policy_subject(self.brief),
                   "model": result["group_sha256"]}
        if self.brief["ecology"]["living"]:
            subject["ecology"] = digest(self.brief["ecology"])
        evidence = self.ref("approval-original.txt", "Original human attestation, synthetic fixture only")
        capture = self.ref("review-capture.png", "synthetic captured evidence fixture")
        manifest = read_json(self.root / result["manifest"]["path"])
        metadata = {"schema_version": 1, "capture_sha256": capture["sha256"], "group_sha256": result["group_sha256"],
                    "models": [{k: m[k] for k in ("level", "sha256")} for m in manifest["models"]],
                    "camera": {"name": "front", "position_m": [0, 1, 3]}, "viewport": [1920, 1080],
                    "lighting": "Studio neutral", "pose": "rest", "renderer": "Workbench"}
        write_json(self.root / "capture-metadata.json", metadata)
        capture["metadata"] = file_record(self.root, self.root / "capture-metadata.json")
        bundle = {"schema_version": 1, "approvals": [
            {"kind": kind, "authority": "human", "decision": "approved", "subject_sha256": value,
             "reviewer": "Fixture reviewer", "evidence": [evidence]} for kind, value in subject.items()],
            "review": {"verdict": "pass", "group_sha256": subject["model"], "concept_sha256": subject["concept"],
                       "brief_sha256": sha256(self.root / "brief.json"), "observer": "Fixture observer",
                       "method": "capture_comparison", "captures": [capture],
                       "observations": ["Synthetic test observation; no real model was reviewed."]}}
        write_json(self.root / "approvals.json", bundle)
        return bundle

    def publisher(self, manifest, key):
        return {"published": True, "idempotency_key": key, "group_sha256": manifest["group_sha256"], "remote_ref": "fixture:group"}

    def test_reuse_preserves_label_and_dry_run_does_not_call_callback(self):
        callback = Mock(side_effect=self.publisher)
        first = self.run_factory(publication_callback=callback)
        self.assertEqual(first["status"], "blocked")
        self.assertEqual(first["operation"], "reused")
        self.approvals(first)
        result = self.run_factory(approvals="approvals.json", publication_callback=callback)
        self.assertEqual(result["status"], "ready")
        callback.assert_not_called()
        self.assertFalse((self.root / "artifacts/model-factory/run/publication").exists())
        self.qa.assert_called_once()
        self.assertEqual(self.inspect.call_count, 2)
        self.preflight.assert_called_once()

    def test_publish_once_after_exact_human_review(self):
        self.approvals()
        callback = Mock(side_effect=self.publisher)
        first = self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        second = self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        self.assertEqual(first["status"], "published")
        self.assertEqual(second["publication_receipt"], first["publication_receipt"])
        callback.assert_called_once()
        self.assertEqual(len(callback.call_args.args[0]["models"]), 2)

    def test_publish_requires_boolean_true_not_truthy_text(self):
        callback = Mock()
        with self.assertRaisesRegex(StudioError, "explicit booleans"):
            self.run_factory(publish="false", publication_callback=callback)
        callback.assert_not_called()
        self.qa.assert_not_called()

    def test_crash_after_intent_or_before_confirmation_does_not_resend(self):
        self.approvals()
        publication = self.root / "artifacts/model-factory/run/publication"
        publication.mkdir()
        write_json(publication / "intent.json", {"status": "sending", "idempotency_key": "preserved"})
        callback = Mock(side_effect=self.publisher)
        self.assertEqual(self.run_factory(approvals="approvals.json", publish=True,
                                         publication_callback=callback)["status"], "publication_uncertain")
        callback.assert_not_called()

    def test_ambiguous_send_exception_and_crash_intent_never_retry(self):
        self.approvals()
        callback = Mock(side_effect=RuntimeError("transport lost after sending"))
        first = self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        second = self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback, retry_failed=True)
        self.assertEqual(first["status"], "publication_uncertain")
        self.assertEqual(second["status"], "publication_uncertain")
        callback.assert_called_once()

    def test_wrong_receipt_identity_is_uncertain(self):
        self.approvals()
        callback = Mock(return_value={"published": True, "idempotency_key": "wrong", "group_sha256": "wrong", "remote_ref": "fixture"})
        result = self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        self.assertEqual(result["status"], "publication_uncertain")
        self.assertFalse((self.root / "artifacts/model-factory/run/publication/receipt.json").exists())

    def test_confirmed_publication_receipt_tampering_is_refused(self):
        self.approvals()
        self.run_factory(approvals="approvals.json", publish=True, publication_callback=self.publisher)
        receipt = self.root / "artifacts/model-factory/run/publication/receipt.json"
        altered = read_json(receipt)
        altered["remote_ref"] = "changed-service-reference"
        write_json(receipt, altered)
        callback = Mock()
        with self.assertRaisesRegex(StudioError, "changed referenced"):
            self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        callback.assert_not_called()

    def test_policy_approval_does_not_transfer_to_new_numeric_policy(self):
        bundle = self.approvals()
        prior = next(a["subject_sha256"] for a in bundle["approvals"] if a["kind"] == "policy")
        for field, value in (("size_m", [2, 2, 3]), ("tolerance_m", 1), ("structure", "clump"), ("ground_y_m", 1)):
            changed = copy.deepcopy(self.brief)
            changed[field] = value
            self.assertNotEqual(factory.policy_subject(changed), prior)
        for field, value in (("maximum_triangles", 90), ("switch_distance_m", 3)):
            changed = copy.deepcopy(self.brief)
            changed["lods"][0][field] = value
            self.assertNotEqual(factory.policy_subject(changed), prior)
        self.brief["lods"][0]["maximum_triangles"] = 90
        self.save()
        # Even if a new review explicitly binds the new brief, an old policy
        # attestation remains invalid rather than transferring by file hash.
        bundle["review"]["brief_sha256"] = sha256(self.root / "brief.json")
        write_json(self.root / "approvals.json", bundle)
        result = factory.execute(self.root, "brief.json", "new-policy", approvals="approvals.json")
        self.assertEqual(result["review"]["gates"]["policy"]["status"], "invalid")

    def test_predictive_review_and_capture_metadata_cannot_qualify(self):
        bundle = self.approvals()
        original_metadata = read_json(self.root / "capture-metadata.json")
        bundle["review"]["method"] = "predictive_model"
        write_json(self.root / "approvals.json", bundle)
        self.assertEqual(self.run_factory(approvals="approvals.json")["status"], "blocked")
        bundle["review"]["method"] = "capture_comparison"
        for field, value in (("capture_sha256", "f" * 64), ("group_sha256", "f" * 64), ("models", []),
                             ("camera", "unknown"), ("viewport", [0, 1080]), ("lighting", "predicted"),
                             ("pose", None), ("renderer", "N/A")):
            with self.subTest(field=field):
                metadata = {**original_metadata, field: value}
                write_json(self.root / "capture-metadata.json", metadata)
                bundle["review"]["captures"][0]["metadata"] = file_record(self.root, self.root / "capture-metadata.json")
                write_json(self.root / "approvals.json", bundle)
                self.assertEqual(self.run_factory(approvals="approvals.json")["status"], "blocked")

    def test_unknown_values_run_diagnostics_without_guessed_policy(self):
        self.brief["concept"] = None
        self.brief["policy"]["reference"] = None
        self.brief["size_m"] = None
        self.brief["tolerance_m"] = None
        self.brief["lods"][1].update(maximum_triangles=None, switch_distance_m=None)
        self.save()
        result = self.run_factory()
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(self.qa_calls[0].budget_tris)
        self.assertIsNone(self.qa_calls[0].switch_distances)
        self.assertTrue(any("NOT SET" in r for r in result["reasons"]))
        self.assertEqual(self.inspect.call_count, 2)

    def test_exact_per_lod_cap_overrides_runner_maximum(self):
        self.brief["lods"][1]["maximum_triangles"] = 30
        self.save()
        result = self.run_factory()
        self.assertEqual(self.qa_calls[0].budget_tris, 100)
        manifest = read_json(self.root / result["manifest"]["path"])
        self.assertEqual(manifest["qa"]["budgets"][1]["result"], "FAIL")
        raw = read_json(self.root / "artifacts/model-factory/run/attempt-1/qa/report.json")
        self.assertEqual(raw["models"][1]["checks"][3]["result"], "PASS")

    def test_completed_failing_qa_is_quality_failure_not_execution_failure(self):
        def fail_quality(report, execution):
            report["result"] = "FAIL"
            report["models"][0]["checks"][0]["result"] = "FAIL"
            execution["result"] = "FAIL"
        self.qa_change = fail_quality
        self.qa_code = 1  # QA CLI quality verdict, while native process exits 0.
        result = self.run_factory()
        manifest = read_json(self.root / result["manifest"]["path"])
        self.assertFalse(manifest["qa"]["ok"])
        self.assertIn("QA measurements failed quality checks", manifest["qa"]["reasons"])
        self.assertIn("LOD0 M12: FAIL", manifest["qa"]["reasons"])
        self.assertFalse(any("execution" in reason or "incomplete" in reason for reason in manifest["qa"]["reasons"]))
        self.assertEqual(result["status"], "blocked")
        # An inconsistent runner exit still blocks; broadening execution success
        # to accept quality exit 1 must not hide an invalid success report.
        self.qa_change = lambda report, execution: None
        result = factory.execute(self.root, "brief.json", "inconsistent-qa-exit")
        manifest = read_json(self.root / result["manifest"]["path"])
        self.assertFalse(manifest["qa"]["ok"])
        self.assertIn("QA runner exit code is inconsistent with its report verdict", manifest["qa"]["reasons"])

    def test_unknown_fail_and_incomplete_qa_rows_block(self):
        cases = ["UNKNOWN", "FAIL", "UNMEASURED", "NOT SET", "N/A", "INFO"]
        for state in cases:
            with self.subTest(state=state):
                def change(report, execution):
                    report["models"][0]["checks"][0]["result"] = state
                self.qa_change = change
                result = factory.execute(self.root, "brief.json", "state-" + state.replace(" ", "-").replace("/", "-"))
                self.assertTrue(any("M12" in r for r in result["reasons"]))
        for name, change in (
            ("missing-row", lambda r, e: r["models"][0]["checks"].pop()),
            ("missing-lod", lambda r, e: r["models"].pop()),
            ("wrong-hash", lambda r, e: r["models"][0].update(sha256="f" * 64)),
            ("errors", lambda r, e: r["errors"].append("measurement failed")),
            ("execution", lambda r, e: e.pop("process")),
        ):
            with self.subTest(case=name):
                self.qa_change = change
                result = factory.execute(self.root, "brief.json", name)
                manifest = read_json(self.root / result["manifest"]["path"])
                self.assertFalse(manifest["qa"]["ok"])

    def test_nonliving_na_and_clump_info_require_explicit_policy(self):
        self.brief["structure"] = "clump"
        self.brief["policy"]["allow_nonliving_na"] = False
        self.save()
        result = self.run_factory()
        self.assertTrue(any("ecology: N/A" in r for r in result["reasons"]))
        self.assertTrue(any("M13: INFO" in r for r in result["reasons"]))
        self.brief["policy"].update(allow_nonliving_na=True, allow_clump_info=True)
        self.save()
        result = factory.execute(self.root, "brief.json", "explicit-policy")
        manifest = read_json(self.root / result["manifest"]["path"])
        self.assertTrue(manifest["qa"]["ok"])
        raw = read_json(self.root / "artifacts/model-factory/explicit-policy/attempt-1/qa/report.json")
        self.assertEqual(raw["models"][0]["checks"][1]["result"], "INFO")
        self.assertEqual(raw["models"][0]["checks"][4]["result"], "N/A")

    def test_size_converts_z_up_and_rejects_mismatch_or_unknown(self):
        result = self.run_factory()
        manifest = read_json(self.root / result["manifest"]["path"])
        self.assertEqual(manifest["size"][0]["dimensions_m_gltf_y_up"], [1, 2, 3])
        self.assertEqual(manifest["size"][0]["result"], "PASS")
        self.assertEqual(manifest["size"][0]["bounds_pose"], "armature_rest")
        for name, dimensions, expected in (("wrong-size", [1, 2, 3], "FAIL"), ("unknown-size", None, "UNMEASURED")):
            self.dimensions = dimensions
            result = factory.execute(self.root, "brief.json", name)
            self.assertTrue(any(f"size: {expected}" in r for r in result["reasons"]))

    def test_size_requires_explicit_armature_rest_pose_marker(self):
        for name, marker in (("missing-pose", None), ("imported-pose", "imported")):
            self.bounds_pose = marker
            result = factory.execute(self.root, "brief.json", name)
            manifest = read_json(self.root / result["manifest"]["path"])
            self.assertTrue(all(row["result"] == "UNMEASURED" for row in manifest["size"]))
            self.assertEqual(manifest["size"][0]["dimensions_m_gltf_y_up"], [1, 2, 3])
            self.assertTrue(all(call.kwargs["rest_pose"] is True for call in self.inspect.call_args_list))

    def test_predictions_and_identity_mismatch_do_not_approve(self):
        bundle = self.approvals()
        variants = [
            ("authority", "agent"), ("decision", "predicted"), ("reviewer", "unknown"),
            ("subject_sha256", "f" * 64), ("evidence", []),
        ]
        for key, value in variants:
            with self.subTest(field=key):
                changed = copy.deepcopy(bundle)
                changed["approvals"][0][key] = value
                write_json(self.root / "approvals.json", changed)
                result = self.run_factory(approvals="approvals.json")
                self.assertEqual(result["status"], "blocked")
        for key, value in (("verdict", "predicted"), ("observer", "N/A"), ("method", "unknown"),
                           ("group_sha256", "f" * 64), ("brief_sha256", "f" * 64),
                           ("concept_sha256", "f" * 64), ("captures", []), ("observations", [])):
            changed = copy.deepcopy(bundle)
            changed["review"][key] = value
            write_json(self.root / "approvals.json", changed)
            self.assertEqual(self.run_factory(approvals="approvals.json")["status"], "blocked")

    def test_living_ecology_approval_is_distinct_from_metadata(self):
        self.brief["ecology"] = {"living": True, "reference": self.ref("ecology.md", "Habitat and traits; proposed"), "reason": None}
        self.save()
        result = self.run_factory()
        manifest = read_json(self.root / result["manifest"]["path"])
        self.assertTrue(manifest["qa"]["ok"])
        self.assertEqual(result["review"]["gates"]["ecology"]["status"], "pending")
        self.approvals(result)
        self.assertEqual(self.run_factory(approvals="approvals.json")["status"], "ready")

    def test_review_evidence_rehashed_on_resume(self):
        self.approvals()
        (self.root / "review-capture.png").write_text("changed capture")
        callback = Mock()
        result = self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        self.assertEqual(result["status"], "blocked")
        callback.assert_not_called()

    def test_successful_outputs_and_evidence_are_rehashed(self):
        result = self.run_factory()
        model = read_json(self.root / result["manifest"]["path"])["models"][0]
        path = self.root / model["path"]
        original = path.read_bytes()
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(StudioError, "changed referenced"):
            self.run_factory()
        path.write_bytes(original)
        report = self.root / "artifacts/model-factory/run/attempt-1/qa/report.json"
        report.write_text("{}")
        with self.assertRaisesRegex(StudioError, "changed referenced"):
            self.run_factory()

    def test_finish_tampering_alone_cannot_publish(self):
        self.dimensions = [9, 9, 9]
        result = self.run_factory()
        self.approvals(result)
        finish_path = self.root / "artifacts/model-factory/run/attempt-1/finish.json"
        finish = read_json(finish_path)
        finish["qualified"] = True
        for row in finish["candidate"]["size"]:
            row["result"] = "PASS"
        finish["candidate"]["qa"].update(ok=True, reasons=[])
        write_json(finish_path, finish)
        callback = Mock(side_effect=self.publisher)
        with self.assertRaisesRegex(StudioError, "changed referenced"):
            self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        callback.assert_not_called()

    def test_reconfirmed_cached_candidate_must_match_verified_raw_evidence(self):
        result = self.run_factory()
        self.approvals(result)
        attempt = self.root / "artifacts/model-factory/run/attempt-1"
        original = read_json(attempt / "finish.json")
        variants = [
            lambda f: f["candidate"].update(group_sha256="f" * 64),
            lambda f: f["candidate"].update(operation="exported"),
            lambda f: f["candidate"]["qa"].update(reasons=["changed cached gate"]),
            lambda f: f["candidate"]["size"][0].update(result="FAIL"),
            lambda f: f["candidate"]["models"][0].update(sha256="f" * 64),
            lambda f: f.update(evidence=[r for r in f["evidence"] if not r["path"].endswith("qa-gate.json")]),
        ]
        callback = Mock()
        for mutate in variants:
            finish = copy.deepcopy(original)
            mutate(finish)
            write_json(attempt / "finish.json", finish)
            write_json(attempt / "finish-confirmation.json", {"schema_version": 1, "checkpoint": file_record(self.root, attempt / "finish.json")})
            with self.assertRaises(StudioError):
                self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        callback.assert_not_called()

    def test_missing_finish_confirmation_requires_retry_and_reuses_verified_build(self):
        result = self.run_factory()
        self.approvals(result)
        confirmation = self.root / "artifacts/model-factory/run/attempt-1/finish-confirmation.json"
        confirmation.unlink()
        callback = Mock()
        blocked = self.run_factory(approvals="approvals.json", publish=True, publication_callback=callback)
        self.assertEqual(blocked["status"], "retry_required")
        callback.assert_not_called()
        retry = self.run_factory(approvals="approvals.json", retry_failed=True)
        self.assertEqual(retry["status"], "ready")
        self.assertEqual(retry["operation"], "reused_build")
        self.assertEqual(self.qa.call_count, 2)

    def test_unconfirmed_build_is_not_reused_after_interruption(self):
        self.inspect.side_effect = StudioError("inspection failed")
        self.run_factory()
        (self.root / "artifacts/model-factory/run/attempt-1/build-confirmation.json").unlink()
        with self.assertRaisesRegex(StudioError, "unconfirmed"):
            self.run_factory(retry_failed=True)

    def test_deleted_recorded_build_never_reruns_builder_on_retry(self):
        self.brief["build"] = {"mode": "blender", "source": self.ref("source.blend", "mock source"),
                               "builder": self.ref("builder.py", "# mock only"), "dependencies": []}
        self.save()
        def quality_failure(report, execution):
            report["result"] = execution["result"] = "FAIL"
            report["models"][0]["checks"][0]["result"] = "FAIL"
        for run_id, failed_inspection in (("failed-inspection", True), ("failed-quality", False)):
            with self.subTest(run_id=run_id):
                self.build.reset_mock()
                self.inspect.side_effect = StudioError("inspection failed") if failed_inspection else self.fake_inspect
                self.qa_change = (lambda report, execution: None) if failed_inspection else quality_failure
                self.qa_code = 0 if failed_inspection else 1
                result = factory.execute(self.root, "brief.json", run_id)
                self.assertEqual(result["status"], "failed" if failed_inspection else "blocked")
                (self.root / f"artifacts/model-factory/{run_id}/attempt-1/build.json").unlink()
                with self.assertRaisesRegex(StudioError, "checkpoint is missing"):
                    factory.execute(self.root, "brief.json", run_id, retry_failed=True)
                self.build.assert_called_once()

    def test_changed_brief_policy_builder_and_ecology_refuse_resume(self):
        self.brief["ecology"] = {"living": True, "reference": self.ref("ecology.md", "ecology"), "reason": None}
        self.brief["build"] = {"mode": "blender", "source": self.ref("source.blend", "mock source"),
                               "builder": self.ref("builder.py", "# mock only"), "dependencies": []}
        self.save()
        self.run_factory()
        for name in ("policy.txt", "ecology.md", "builder.py"):
            with self.subTest(input=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(b"changed")
                with self.assertRaises(StudioError):
                    self.run_factory()
                path.write_bytes(original)
        self.brief["version"] = "v2"
        self.save()
        with self.assertRaisesRegex(StudioError, "new run id"):
            self.run_factory()

    def test_workflow_config_change_requires_new_run_id(self):
        self.run_factory()
        with self.assertRaisesRegex(StudioError, "workflow changed"):
            self.run_factory(config={"timeout": 120})

    def test_failed_retry_is_explicit_and_preserves_attempt(self):
        self.inspect.side_effect = StudioError("native inspection failed")
        result = self.run_factory()
        self.assertEqual(result["status"], "failed")
        old = self.root / "artifacts/model-factory/run/attempt-1/finish.json"
        before = sha256(old)
        self.assertEqual(self.run_factory()["status"], "retry_required")
        self.inspect.side_effect = self.fake_inspect
        result = self.run_factory(retry_failed=True)
        self.assertEqual(result["attempt"], "attempt-2")
        self.assertEqual(sha256(old), before)
        self.assertEqual(self.qa.call_count, 2)

    def test_downstream_failure_reuses_verified_build_without_rerunning_builder(self):
        self.brief["build"] = {"mode": "blender", "source": self.ref("source.blend", "mock source"),
                               "builder": self.ref("builder.py", "# mock only"), "dependencies": []}
        self.save()
        self.inspect.side_effect = StudioError("inspection unavailable after successful export")
        first = self.run_factory()
        self.assertEqual(first["status"], "failed")
        before = sha256(self.root / "artifacts/model-factory/run/attempt-1/build.json")
        self.inspect.side_effect = self.fake_inspect
        result = self.run_factory(retry_failed=True)
        self.assertEqual(result["operation"], "reused_build")
        self.assertEqual(before, sha256(self.root / "artifacts/model-factory/run/attempt-1/build.json"))
        self.build.assert_called_once()
        checkpoint = read_json(self.root / "artifacts/model-factory/run/attempt-2/build.json")
        self.assertEqual(checkpoint["original_operation"], "exported")
        self.run_factory()
        self.build.assert_called_once()

    def test_tampered_successful_build_cannot_be_reused_after_failure(self):
        self.inspect.side_effect = StudioError("inspection failed")
        self.run_factory()
        path = self.root / "artifacts/model-factory/run/attempt-1/build/specimen-lod0.glb"
        path.write_bytes(b"changed build")
        with self.assertRaisesRegex(StudioError, "changed referenced"):
            self.run_factory(retry_failed=True)

    def test_interrupted_attempt_requires_explicit_retry(self):
        self.run_factory()
        # Simulate a process dying before its final checkpoint was committed.
        (self.root / "artifacts/model-factory/run/attempt-1/finish.json").unlink()
        self.assertEqual(self.run_factory()["status"], "retry_required")
        self.assertEqual(self.run_factory(retry_failed=True)["attempt"], "attempt-2")

    def test_blender_contract_uses_adapter_unique_attempt_and_request(self):
        self.brief["build"] = {"mode": "blender", "source": self.ref("source.blend", "mock source"),
                               "builder": self.ref("builder.py", "# mock only"), "dependencies": [self.ref("dependency.txt", "input")]}
        self.save()
        result = self.run_factory()
        self.assertEqual(result["operation"], "exported")
        kwargs = self.build.call_args.kwargs
        self.assertEqual(kwargs["source"], "source.blend")
        self.assertEqual(kwargs["passthrough"][0], "--factory-request")
        request = read_json(self.root / kwargs["passthrough"][1])
        self.assertEqual([m["path"] for m in request["outputs"]], kwargs["results"])
        self.assertEqual(request["brief"], self.brief)
        self.run_factory()
        self.build.assert_called_once()

    def test_cutoff_and_host_block_before_native(self):
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        result = self.run_factory(cutoff_utc=past)
        self.assertEqual(result["status"], "failed")
        self.qa.assert_not_called()
        self.inspect.assert_not_called()
        self.preflight.assert_not_called()
        self.preflight.side_effect = lambda config, output: {"ready": False, "host_kind": "windows", "reasons": ["CBS reboot pending"]}
        result = self.run_factory(retry_failed=True)
        self.assertEqual(result["status"], "failed")
        self.qa.assert_not_called()

    def test_cutoff_checked_between_operations(self):
        times = [180, 180, 180, 180, StudioError("Factory cutoff exhausted")]
        with patch.object(factory, "_timeout", side_effect=times):
            result = self.run_factory()
        self.assertEqual(result["status"], "failed")
        self.inspect.assert_not_called()

    def test_schema_rejects_unsafe_and_ambiguous_metadata(self):
        variants = [
            lambda b: b.update(unrecognized=True), lambda b: b.update(size_m=[1, float("nan"), 2]),
            lambda b: b["lods"][1].update(level=3), lambda b: b["lods"][1].update(maximum_triangles=0),
            lambda b: b["lods"][1].update(switch_distance_m=1), lambda b: b["concept"].update(path="../escape"),
        ]
        for mutate in variants:
            brief = copy.deepcopy(self.brief)
            mutate(brief)
            with self.assertRaises(StudioError):
                factory.validate_brief(self.root, brief)

    def test_os_lock_blocks_another_process_and_leaves_lock_file(self):
        context = multiprocessing.get_context("spawn")
        entered, release = context.Event(), context.Event()
        path = self.root / "writer.lock"
        process = context.Process(target=_hold_lock, args=(str(path), entered, release))
        process.start()
        try:
            self.assertTrue(entered.wait(10))
            with self.assertRaisesRegex(StudioError, "already has a writer"):
                with factory.writer_lock(path):
                    self.fail("concurrent writer entered")
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
        self.assertEqual(process.exitcode, 0)
        self.assertTrue(path.is_file())
        with factory.writer_lock(path):
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
