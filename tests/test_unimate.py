"""Offline foundation checks. Fixture bytes are not model or art evidence."""

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools.adapters import unimate
from studio_tools.cli import main, parser, dispatch
from studio_tools.common import digest, file_record, read_json, sha256, write_json
from studio_tools.doctor import inspect as doctor


WORKER = '''import argparse, hashlib, json, os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args()
data=json.loads(Path(a.input).read_text());root=Path(data['project']);out=Path(data['output']);out.mkdir()
assert os.environ['HF_HUB_OFFLINE']=='1' and os.environ['TRANSFORMERS_OFFLINE']=='1'
assert os.environ['CUDA_VISIBLE_DEVICES']==''
assert 'UNIMATE_TEST_SECRET' not in os.environ
assert data['offline_policy']=={'local_files_only':True,'downloads':False}
clips=[]
for c in data['request']['clips']:
    item=dict(c,duration_seconds=1.0,sample_rate=30)
    for kind,suffix in [('raw','.npy'),('decoded','.npz')]:
        f=out/(c.get('sample_id',c['name'])+suffix);f.write_bytes(b'fake-worker-fixture')
        item[kind]={'path':f.relative_to(root).as_posix(),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
    clips.append(item)
Path(a.output).write_text(json.dumps({'schema_version':1,'request_digest':data['request_digest'],
'rig_sha256':data['request']['rig_manifest']['sha256'],'provenance_digest':hashlib.sha256(json.dumps(data['provenance'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
'capabilities_digest':hashlib.sha256(json.dumps(data['capabilities'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),'clips':clips}))
'''


class UnimateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="unimate contract space ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        names = ["Root"] + sorted(unimate.MITE_NAMES - {"Root"})
        nodes = [{"name": name} for name in names]
        nodes[0]["children"] = list(range(1, 31))
        doc = {"asset": {"version": "2.0"}, "meshes": [{}], "nodes": nodes,
               "skins": [{"joints": list(range(31))}],
               "animations": [{"name": name} for name in unimate.ROLES]}
        raw = json.dumps(doc).encode()
        raw += b" " * (-len(raw) % 4)
        baseline = self.root / "baseline.glb"
        baseline.write_bytes(struct.pack("<III", 0x46546C67, 2, 20 + len(raw))
                             + struct.pack("<II", len(raw), 0x4E4F534A) + raw)
        self.rig = {"schema_version": 1, "subject": "chalk_mite", "preparation": "rest_only",
                    "reference_motion_clips": [], "baseline": file_record(self.root, baseline),
                    "source": self.project_file("source.blend"), "condition": self.project_file("cond.npy"),
                    "joints": [{"name": name, "parent": None if name == "Root" else "Root"} for name in names],
                    "canonical_from_source": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
                    "canonical_axes": "Y_up_Z_forward"}
        self.request = {"schema_version": 1, "provider": "unimate", "work_card": "fixture",
                        "experimental": True, "mode": "text_tpos", "model_profile": "fake-pinned",
                        "clips": [{"name": "walk", "prompt": "walk", "seed": 42, "loop": True, "root_motion": "in_place"}],
                        "limits": {"batch_size": 1, "maximum_attempts": 1, "maximum_samples": 1, "timeout_seconds": 30},
                        "execution": {"resource_owner": "fixture", "device": "cpu",
                                      "cutoff_utc": (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}}
        worker = self.root / "worker.py"
        worker.write_text(WORKER)
        host = {"protocol_version": 1, "python": self.host_file("python", Path(sys.executable)),
                "worker": self.host_file("worker", worker),
                "provenance": {"code_revision": "1"*40, "bridge_revision": "2"*40, "model_revision": "3"*40,
                               "model_profile": "fake-pinned", "normalizer_profile": "fake-local-normalizer", "license": "fixture-only"},
                "capabilities": {"independent_rotation_joints": sorted(unimate.MITE_NAMES - unimate.STOCK_UNSUPPORTED_ROTATIONS),
                                 "unsupported_rotation_joints": sorted(unimate.STOCK_UNSUPPORTED_ROTATIONS),
                                 "unsupported_joint_policy": "source_rest_only"},
                "assets": []}
        for role in sorted(unimate.ASSET_ROLES):
            path = self.root / (role + ".cache")
            path.write_bytes(b"offline-fixture")
            host["assets"].append(dict(self.host_file(role, path), role=role))
        self.config = {"unimate": host, "executables": {}, "credentials": {}, "credential_files": []}
        self.save()

    def project_file(self, name):
        path = self.root / name
        path.write_bytes(b"fixture")
        return file_record(self.root, path)

    def host_file(self, name, path):
        return {"id": name, "path": str(path), "sha256": sha256(path)}

    def save(self):
        write_json(self.root / "rig.json", self.rig)
        self.request["rig_manifest"] = file_record(self.root, self.root / "rig.json")
        write_json(self.root / "request.json", self.request)

    def generate(self, label="run"):
        return unimate.execute(self.config, self.root, "generate", "request.json",
                               f"artifacts/unimate/{label}/task.json")

    def test_inspect_is_read_only_and_lazy_cli_does_not_import_provider(self):
        code = "import sys;from studio_tools.cli import parser;parser().parse_args(['unimate','inspect','--project','x','--request','r']);assert 'studio_tools.adapters.unimate' not in sys.modules;assert 'torch' not in sys.modules"
        subprocess.run([sys.executable, "-c", code], check=True)
        before = set(self.root.rglob("*"))
        with patch("socket.create_connection", side_effect=AssertionError("network")), patch.object(unimate, "run", side_effect=AssertionError("worker")):
            result = unimate.execute(self.config, self.root, "inspect", "request.json")
        self.assertTrue(result["ok"])
        self.assertEqual(result["offline_execution"], "unverified")
        self.assertEqual(set(result["capabilities"]["unsupported_rotation_joints"]), unimate.STOCK_UNSUPPORTED_ROTATIONS)
        self.assertEqual(set(self.root.rglob("*")), before)

    def test_every_missing_cache_including_normalizer_fails_without_execution_or_network(self):
        for asset in self.config["unimate"]["assets"]:
            with self.subTest(role=asset["role"]):
                path = Path(asset["path"])
                data = path.read_bytes();path.unlink()
                try:
                    with patch.object(unimate, "run", side_effect=AssertionError("worker")), patch("socket.create_connection", side_effect=AssertionError("network")):
                        result = self.generate(asset["id"])
                    self.assertEqual(result["provider_error"]["code"], "OFFLINE_ASSET_MISSING")
                    self.assertFalse((self.root / "artifacts").exists())
                finally:
                    path.write_bytes(data)

    def test_rest_only_exact_names_parents_and_immutable_baseline(self):
        baseline = self.root / "baseline.glb"
        before = baseline.read_bytes()
        for mutation in (lambda r: r.update(preparation="animated"),
                         lambda r: r.update(reference_motion_clips=["walk"]),
                         lambda r: r["joints"].pop(),
                         lambda r: r["joints"][1].update(parent="L_Mandible"),
                         lambda r: r["joints"][1].update(name="lost")):
            original = deepcopy(self.rig)
            mutation(self.rig);self.save()
            result = unimate.execute(self.config, self.root, "inspect", "request.json")
            self.assertEqual(result["provider_error"]["code"], "RIG_UNSUPPORTED")
            self.rig = original
        self.assertEqual(baseline.read_bytes(), before)

    def test_fake_worker_runs_through_owned_runner_and_success_is_not_acceptance(self):
        with patch.dict(os.environ, {"UNIMATE_TEST_SECRET": "private"}):
            result = self.generate()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["support"], "experimental_foundation")
        self.assertEqual(result["production_acceptance"], "pending")
        self.assertEqual(result["offline_execution"], "unverified")
        self.assertEqual(len(result["outputs"]), 2)
        self.assertTrue((self.root / result["process"]["path"]).exists())
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(self.generate()["provider_error"]["code"], "RUN_EXISTS")

    def fake_runner(self, mode):
        def worker(args, **kwargs):
            folder = kwargs["job_dir"]
            folder.mkdir()
            write_json(folder / "process.json", {"status": "completed", "returncode": 0, "pid": 123, "windows_ownership": {}})
            data = read_json(Path(args[-3]))
            out = Path(data["output"]);out.mkdir()
            c = dict(self.request["clips"][0], duration_seconds=1, sample_rate=30)
            for key, suffix in (("raw", ".npy"), ("decoded", ".npz")):
                path = out / ("walk"+suffix);path.write_bytes(b"fixture")
                c[key] = file_record(self.root, path)
            result = {"schema_version": 1, "request_digest": data["request_digest"],
                      "rig_sha256": self.request["rig_manifest"]["sha256"],
                      "provenance_digest": digest(data["provenance"]), "clips": [c]}
            result["capabilities_digest"] = digest(data["capabilities"])
            if mode == "skipped":result["clips"] = []
            if mode == "seed":c["seed"] += 1
            if mode == "digest":result["request_digest"] = "wrong"
            if mode == "model":result["provenance_digest"] = "wrong"
            if mode == "capabilities":result["capabilities_digest"] = "wrong"
            if mode == "timing":c["duration_seconds"] = float("nan")
            if mode == "old":c["raw"] = self.rig["condition"]
            if mode == "changed":(self.root / "source.blend").write_bytes(b"changed")
            if mode == "missing_process":(folder / "process.json").unlink()
            if mode == "invalid_process":(folder / "process.json").write_text("broken")
            if mode == "wrong_exit":write_json(folder / "process.json", {"status": "failed", "returncode": 9, "pid": 123})
            write_json(Path(args[-1]), result) if mode != "timing" else Path(args[-1]).write_text(json.dumps(result))
        return worker

    def test_missing_changed_or_misattributed_outputs_cannot_succeed(self):
        for mode in ("skipped", "seed", "digest", "model", "capabilities", "timing", "old", "changed"):
            with self.subTest(mode=mode), patch.object(unimate, "prelaunch_baseline", return_value={"status":"ok"}), patch.object(unimate, "run", side_effect=self.fake_runner(mode)), patch.object(unimate, "stop_survivors", return_value={"status":"ok","pids":[],"stopped":True,"unverified":[]}):
                result = self.generate(mode)
            self.assertFalse(result["ok"], mode)
            self.assertEqual(result["status"], "output_invalid")
            self.assertTrue((self.root / f"artifacts/unimate/{mode}/task.json").exists())

    def test_cutoff_and_unreserved_gpu_do_not_start_worker(self):
        self.request["execution"]["cutoff_utc"] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();self.save()
        with patch.object(unimate, "run", side_effect=AssertionError("worker")):
            self.assertEqual(self.generate()["provider_error"]["code"], "CUTOFF_PASSED")
        self.assertFalse((self.root / "artifacts").exists())
        self.request["execution"]["device"] = "cuda:0";self.save()
        self.assertEqual(self.generate()["provider_error"]["code"], "RESOURCE_BUSY")

    def test_multiple_seeds_have_distinct_sample_identity_and_same_named_clip_role(self):
        self.request["clips"][0]["sample_id"] = "walk-42"
        self.request["clips"].append(dict(self.request["clips"][0], seed=43, sample_id="walk-43"))
        self.request["limits"]["maximum_samples"] = 2;self.save()
        result = self.generate()
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["outputs"]), 4)

    def test_invalid_paths_modes_duplicate_samples_and_cleanup_cannot_succeed(self):
        for mutation in (lambda r: r.update(mode="motion_edit"),
                         lambda r: r["rig_manifest"].update(path="../outside.json"),
                         lambda r: r["clips"].append(dict(r["clips"][0]))):
            original = deepcopy(self.request);mutation(self.request)
            write_json(self.root / "request.json", self.request)
            self.assertFalse(self.generate()["ok"])
            self.request = original
        self.save()
        with patch.object(unimate, "prelaunch_baseline", return_value={"status":"ok"}), patch.object(unimate, "run", side_effect=self.fake_runner("valid")), patch.object(unimate, "stop_survivors", return_value={"status":"unavailable","pids":[],"stopped":False,"unverified":[]}):
            result = self.generate()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "cleanup_unverified")

    def test_process_evidence_failure_retains_task_receipt_without_success(self):
        for mode in ("missing_process", "invalid_process", "wrong_exit", "cleanup_error"):
            with self.subTest(mode=mode), patch.object(unimate, "prelaunch_baseline", return_value={"status":"ok"}), patch.object(unimate, "run", side_effect=self.fake_runner(mode)), patch.object(unimate, "stop_survivors", side_effect=OSError("fixture cleanup error")):
                result = self.generate(mode)
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "cleanup_unverified")
            self.assertEqual(result["provider_error"]["code"], "CLEANUP_UNVERIFIED")
            self.assertEqual(read_json(self.root / f"artifacts/unimate/{mode}/task.json")["status"], "cleanup_unverified")

    def test_malformed_object_sections_refuse_without_launch(self):
        for key in ("limits", "execution"):
            original = self.request[key]
            self.request[key] = [];self.save()
            with patch.object(unimate, "run", side_effect=AssertionError("worker")):
                result = self.generate(key)
            self.assertEqual(result["provider_error"]["code"], "REQUEST_INVALID")
            self.request[key] = original
        self.save()
        self.config["unimate"]["provenance"] = []
        self.assertEqual(self.generate()["provider_error"]["code"], "IDENTITY_MISMATCH")

    def test_leaf_capability_disclosure_cannot_claim_full_dof_or_borrow_original_motion(self):
        original = deepcopy(self.config["unimate"]["capabilities"])
        for mutation in (lambda c: c.update(independent_rotation_joints=sorted(unimate.MITE_NAMES), unsupported_rotation_joints=[]),
                         lambda c: c.update(independent_rotation_joints=sorted(unimate.MITE_NAMES-unimate.JAW_NAMES), unsupported_rotation_joints=sorted(unimate.JAW_NAMES)),
                         lambda c: c.update(unsupported_joint_policy="original_clip"),
                         lambda c: c["unsupported_rotation_joints"].append("Unknown")):
            capabilities = deepcopy(original);mutation(capabilities)
            self.config["unimate"]["capabilities"] = capabilities
            with patch.object(unimate, "run", side_effect=AssertionError("worker")):
                result = self.generate()
            self.assertEqual(result["provider_error"]["code"], "CONDITION_INCOMPATIBLE")
        self.config["unimate"]["capabilities"] = original
        result = unimate.execute(self.config, self.root, "inspect", "request.json")
        self.assertEqual(result["capabilities"], original)
        self.assertEqual(result["capability_validation"], "declared_only")

    def test_changed_worker_missing_revision_and_invalid_limits_refuse(self):
        worker = Path(self.config["unimate"]["worker"]["path"])
        worker.write_text("changed")
        self.assertEqual(self.generate()["provider_error"]["code"], "IDENTITY_MISMATCH")
        self.config["unimate"]["provenance"]["model_revision"] = "main"
        self.assertEqual(self.generate()["provider_error"]["code"], "IDENTITY_MISMATCH")
        self.request["limits"]["maximum_attempts"] = 2;self.save()
        self.assertEqual(self.generate()["provider_error"]["code"], "REQUEST_INVALID")

    def test_worker_failure_receipt_no_automatic_retry(self):
        worker = Path(self.config["unimate"]["worker"]["path"])
        worker.write_text("raise SystemExit(9)")
        self.config["unimate"]["worker"]["sha256"] = sha256(worker)
        result = self.generate()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "worker_failed")
        self.assertEqual(read_json(self.root / result["process"]["path"])["returncode"], 9)
        self.assertEqual(self.generate()["provider_error"]["code"], "RUN_EXISTS")

    def test_doctor_presence_only_and_cli_no_model_import(self):
        with patch("studio_tools.doctor.executable", return_value=None), patch("studio_tools.doctor.run", side_effect=AssertionError("probe")):
            result = doctor(self.config)["capabilities"]["unimate"]
        self.assertEqual(result["status"], "unverified")
        args = parser().parse_args(["unimate", "inspect", "--project", str(self.root), "--request", "request.json"])
        with patch("studio_tools.cli.load", return_value=self.config):
            self.assertTrue(dispatch(args)["ok"])

    def test_cli_missing_root_has_no_mutation(self):
        root = self.root / "absent"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["unimate", "inspect", "--project", str(root), "--request", "request.json"]), 1)
        self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
