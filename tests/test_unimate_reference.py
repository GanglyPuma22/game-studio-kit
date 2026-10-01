"""Reference-worker protocol fixtures; fake sampling is never art evidence."""

from copy import deepcopy
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_unimate as fixtures
from studio_tools.adapters import unimate, unimate_reference as reference
from studio_tools import unimate_worker as worker
from studio_tools.common import StudioError, digest, file_record, read_json, sha256, write_json

try:
    import numpy as np
except ImportError:
    np = None


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.UnimateTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root, self.config, self.request = self.fx.root, self.fx.config, self.fx.request
        self.checkpoint = next(a for a in self.config["unimate"]["assets"] if a["role"] == "checkpoint")
        checkpoint_pin = patch.object(reference, "CHECKPOINT_HASH", self.checkpoint["sha256"])
        checkpoint_pin.start()
        self.addCleanup(checkpoint_pin.stop)
        stats_pin = patch.object(reference, "STATISTICS_HASH", self.checkpoint["sha256"])
        stats_pin.start()
        self.addCleanup(stats_pin.stop)
        self.configure("kite18_endpoints")

    def glb(self, filename, parents):
        names = list(parents)
        nodes = [{"name": name, "children": [names.index(n) for n, p in parents.items() if p == name]} for name in names]
        doc = {"asset": {"version": "2.0"}, "meshes": [{}], "nodes": nodes,
               "skins": [{"joints": list(range(len(names)))}], "animations": [{"name": "glide"}]}
        raw = json.dumps(doc).encode()
        raw += b" " * (-len(raw) % 4)
        path = self.root / filename
        path.write_bytes(struct.pack("<III", 0x46546C67, 2, 20 + len(raw)) + struct.pack("<II", len(raw), 0x4E4F534A) + raw)
        return file_record(self.root, path)

    def configure(self, profile):
        names = ["Root"] + sorted(reference.PROFILES[profile] - {"Root"})
        parents = {name: None if name == "Root" else "Root" for name in names}
        cond_parents = dict(parents)
        helpers = []
        if profile == "kite18_endpoints":
            cond_parents.update(reference.HELPERS)
            helpers = [dict(name=n, parent=p, weighted=False, use_deform=False, animated=False)
                       for n, p in reference.HELPERS.items()]
        baseline, prepared = self.glb("source.glb", parents), self.glb("prepared.glb", cond_parents)
        evidence = self.root / "rig-evidence.json"
        write_json(evidence, {"source_names_parents_rest_preserved": True, "mesh_skin_preserved": True,
                             "baseline_sha256": baseline["sha256"], "prepared_baseline_sha256": prepared["sha256"]})
        self.rig = dict(self.fx.rig, profile=profile, subject="chalk_mite" if profile == "mite31" else "kite",
                        preparation="animated_reference", baseline=baseline, prepared_baseline=prepared,
                        source_rest=self.fx.project_file("source-rest.npz"), rig_evidence=file_record(self.root, evidence),
                        source_joints=[{"name": n, "parent": p} for n, p in parents.items()],
                        joints=[{"name": n, "parent": p, "rest_offset": [0.1, 0, 0] if n in reference.HELPERS else [0, 0, 0],
                                 "rest_rotation": [1, 0, 0, 0], "rest_global_rotation": [1, 0, 0, 0]}
                                for n, p in cond_parents.items()], helpers=helpers)
        ref = self.fx.project_file("Fixture-glide-000.npz")
        captions = self.root / "captions.json"
        write_json(captions, {"Fixture-glide-000": "genuine fixture reference"})
        self.rig["reference_motion_clips"] = [ref]
        self.request.update(conditioning={"kind": "animated_reference", "object_type": "Fixture", "start_frame": 0,
                            "reference": ref, "captions": file_record(self.root, captions),
                            "alignment": "Fixture-only aligned 30Hz reference"},
                            generation=dict(reference.GENERATION))
        self.request["clips"] = [{"name": "walk" if profile == "mite31" else "powered_flap",
                                 "sample_id": "fixture-42", "prompt": "flap", "seed": 42, "loop": True,
                                 "root_motion": "raw_preserved", "desired_runtime_root_policy": "controller_owned",
                                 "presentation_compensation": "full_root_view_only"}]
        host = self.config["unimate"]
        leaves = set(cond_parents) - set(cond_parents.values())
        host["capabilities"] = {"independent_rotation_joints": sorted(set(cond_parents) - leaves),
            "unsupported_rotation_joints": sorted(leaves), "unsupported_joint_policy": "source_rest_only",
            "unsupported_translation_joints": sorted(set(cond_parents) - {"Root"}),
            "translation_policy": "fixed_rest_offsets", "conditioning_modes": ["animated_reference"]}
        host["worker_profile"] = reference.WORKER_PROFILE
        host["worker"].update(path=str(Path(worker.__file__).resolve()),
                              sha256=sha256(Path(worker.__file__)))
        host["provenance"].update(code_revision=reference.SOURCE_REVISION, text_revision=reference.TEXT_REVISION,
                                  normalizer_profile="identity_no_normalization")
        # Remove optional inventories from a previous profile fixture.
        host["assets"] = [a for a in host["assets"] if a["role"] in unimate.ASSET_ROLES]
        runtime = {}
        for key, role in (("unimate_root", "provider_source"), ("motion_root", "motion_source"), ("text_root", "text_asset")):
            folder = self.root / key
            folder.mkdir(exist_ok=True)
            filenames = ["fixture.py"] if key != "text_root" else [
                "config.json", "tokenizer_config.json", "special_tokens_map.json", "spiece.model", "model.safetensors"]
            for filename in filenames:
                path = folder / filename
                path.write_text("{}" if filename.endswith(".json") else "fixture only")
                host["assets"].append(dict(self.fx.host_file(key + "-" + filename.replace(".", "-"), path), role=role))
            runtime[key] = str(folder)
        runtime["text_model"] = "google/flan-t5-base"
        host["runtime"] = runtime
        for asset in host["assets"]:
            if asset["role"] in ("encoder_config", "encoder_weights", "tokenizer"):
                filename = {"encoder_config": "config.json", "encoder_weights": "model.safetensors",
                            "tokenizer": "spiece.model"}[asset["role"]]
                asset.update(self.fx.host_file(asset["id"], Path(runtime["text_root"]) / filename))
            if asset["role"] == "normalizer":
                write_json(Path(asset["path"]), {"profile": "identity_no_normalization", "normalize_text": False})
                asset["sha256"] = sha256(Path(asset["path"]))
        lock = self.root / "dependencies.txt"
        lock.write_text("fixture-only==1\n")
        host["assets"].append(dict(self.fx.host_file("dependency-lock", lock), role="dependency_lock"))
        config_asset = next(a for a in host["assets"] if a["role"] == "model_config")
        write_json(Path(config_asset["path"]), {"model": {"text_encoder_type": "t5", "text_encoder_version": "google/flan-t5-base"},
                   "dataset": {"max_motion_length": 60, "feature_len": 12, "topology_condition_type": "tpos",
                               "use_dataset_stats": True, "max_joints": 71, "max_depth": 19},
                   "training": {"diff_model": "flow"}})
        config_asset["sha256"] = sha256(Path(config_asset["path"]))
        self.save()

    def save(self):
        self.fx.rig = self.rig
        self.fx.save()

    def payload(self):
        host = self.config["unimate"]
        return {"schema_version": 1, "request": self.request, "request_digest": digest(self.request), "rig": self.rig,
                "project": str(self.root), "output": str(self.root / "artifacts/unimate/test/output"),
                "assets": [host["python"], host["worker"], *host["assets"]],
                "runtime": host["runtime"], "worker_profile": host["worker_profile"],
                "host_entries": {key: host[key]["id"] for key in ("python", "worker")},
                "capabilities": host["capabilities"], "provenance": host["provenance"],
                "worker_device": "cpu", "offline_policy": {"local_files_only": True, "downloads": False}}

    def fake_sample(self, data, root, output, files, budget, evidence):
        clips = []
        for clip in data["request"]["clips"]:
            item = dict(clip, duration_seconds=59 / 30, sample_rate=30, frame_count=60, loop_validation="unverified")
            for key, suffix in (("raw", ".npy"), ("decoded", ".npz")):
                path = output / (unimate.sample_id(clip) + suffix)
                path.write_bytes(b"FAKE SAMPLING FIXTURE: not array or model evidence")
                item[key] = file_record(root, path)
            clips.append(item)
            evidence["cases"].append({"sample_id": unimate.sample_id(clip),
                                      **{k: clip[k] for k in ("name", "prompt", "seed")}})
        return clips

    def runner(self, mutate=None):
        def launch(args, **kwargs):
            folder = kwargs["job_dir"]
            folder.mkdir()
            write_json(folder / "process.json", {"status": "completed", "returncode": 0, "pid": 123, "windows_ownership": {}})
            data = read_json(Path(args[-3]))
            with patch.dict(os.environ, kwargs["env"], clear=True):
                result = worker.execute(data, Path(args[-1]), sampler=self.fake_sample)
            if mutate:
                mutate(result)
                write_json(Path(args[-1]), result)
        return launch

    def generate(self, mutate=None, label="run"):
        with patch.object(unimate, "prelaunch_baseline", return_value={"status": "ok"}), \
             patch.object(unimate, "run", side_effect=self.runner(mutate)), \
             patch.object(unimate, "stop_survivors", return_value={"status": "ok", "pids": [], "stopped": True, "unverified": []}):
            return self.fx.generate(label)

    def test_profiles_validate_original_and_prepared_identity_without_ml(self):
        for profile in reference.PROFILES:
            self.configure(profile)
            with patch.object(unimate, "run", side_effect=AssertionError("inference")):
                self.assertTrue(unimate.execute(self.config, self.root, "inspect", "request.json")["ok"])

    def test_existing_envelope_produces_raw_primary_portable_export(self):
        result = self.generate()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["production_acceptance"], "pending")
        self.assertEqual(result["offline_execution"], "unverified")
        export = read_json(self.root / "artifacts/unimate/run/output/motion-export.json")
        self.assertTrue(export["raw_playback_primary"])
        self.assertIn("banking", export["presentation_warning"])
        self.assertNotIn("runtime", export)
        self.assertNotIn(str(self.root), json.dumps(export))
        self.assertEqual(export["clips"][0]["root_motion"], "raw_preserved")

    def test_rest_only_does_not_implicitly_select_reference(self):
        self.request["conditioning"]["kind"] = "rest_only"
        self.save()
        self.assertEqual(self.fx.generate()["provider_error"]["code"], "CONDITION_INCOMPATIBLE")
        self.assertFalse((self.root / "artifacts").exists())

    def test_wrong_helper_parent_weight_or_missing_original_bone_refuses(self):
        for mutate in (lambda r: r["helpers"][0].update(parent="Head"),
                       lambda r: r["helpers"][0].update(weighted=True),
                       lambda r: r["helpers"][0].update(use_deform=True),
                       lambda r: r["source_joints"].pop(),
                       lambda r: r["joints"][1].update(parent="Head")):
            old = deepcopy(self.rig)
            mutate(self.rig)
            self.save()
            self.assertFalse(self.fx.generate()["ok"])
            self.rig = old
        self.assertFalse((self.root / "artifacts").exists())

    def test_root_order_zero_helpers_and_extreme_rest_values_refuse_before_inference(self):
        for mutate in (lambda r: r["joints"].reverse(),
                       lambda r: r["joints"][-1].update(rest_offset=[0, 0, 0]),
                       lambda r: r["joints"][0].update(rest_offset=[10**400, 0, 0])):
            old = deepcopy(self.rig)
            mutate(self.rig)
            self.save()
            with patch.object(unimate, "run", side_effect=AssertionError("worker")):
                for operation in ("inspect", "generate"):
                    result = unimate.execute(self.config, self.root, operation, "request.json",
                                             "artifacts/unimate/refused/task.json")
                    self.assertFalse(result["ok"])
                    self.assertFalse(result["provider_error"]["retryable"])
            self.rig = old
        self.assertFalse((self.root / "artifacts").exists())

    def test_reference_hash_frame_alignment_and_generation_profile_are_bound(self):
        for mutate in (lambda r: r["conditioning"]["reference"].update(sha256="0"*64),
                       lambda r: r["conditioning"].update(start_frame=-1),
                       lambda r: r["conditioning"].update(alignment=""),
                       lambda r: r["generation"].update(frames=120),
                       lambda r: r["clips"][0].update(root_motion="in_place")):
            old = deepcopy(self.request)
            mutate(self.request)
            self.save()
            self.assertFalse(self.fx.generate()["ok"])
            self.request.clear()
            self.request.update(old)

    def test_leaf_and_translation_limits_cannot_be_omitted(self):
        caps = self.config["unimate"]["capabilities"]
        for key in ("unsupported_rotation_joints", "unsupported_translation_joints"):
            old = caps[key]
            caps[key] = []
            self.assertEqual(self.fx.generate()["provider_error"]["code"], "CONDITION_INCOMPATIBLE")
            caps[key] = old

    def test_malformed_or_foreign_export_keeps_structured_failed_task(self):
        for mode in ("malformed", "foreign"):
            def mutate(result):
                path = self.root / result["export"]["path"]
                export = [] if mode == "malformed" else read_json(path)
                if mode == "foreign":
                    export["provenance"] = {"model_profile": "foreign"}
                write_json(path, export)
                result["export"] = file_record(self.root, path)
            result = self.generate(mutate, label=mode)
            self.assertEqual(result["status"], "output_invalid")
            self.assertEqual(result["provider_error"]["code"], "OUTPUT_INVALID")
            self.assertEqual(read_json(self.root / f"artifacts/unimate/{mode}/task.json")["status"], "output_invalid")

    def test_evidence_internal_identity_refuses_even_with_updated_hashes_and_export(self):
        changes = (("schema", lambda e: e.update(schema_version=2)),
                   ("request", lambda e: e.update(request_digest="FOREIGN")),
                   ("worker", lambda e: e.update(worker_sha256="0" * 64)),
                   ("inventory", lambda e: e["inventory"][0].update(sha256="0" * 64)),
                   ("missing-cases", lambda e: e.update(cases=[])),
                   ("sample", lambda e: e["cases"][0].update(sample_id="foreign")),
                   ("seed", lambda e: e["cases"][0].update(seed=43)),
                   ("prompt", lambda e: e["cases"][0].update(prompt="foreign")))
        for label, change in changes:
            def mutate(result):
                evidence_path = self.root / result["evidence"]["path"]
                evidence = read_json(evidence_path)
                change(evidence)
                write_json(evidence_path, evidence)
                result["evidence"] = file_record(self.root, evidence_path)
                export_path = self.root / result["export"]["path"]
                export = read_json(export_path)
                export["evidence"] = result["evidence"]
                write_json(export_path, export)
                result["export"] = file_record(self.root, export_path)
            with self.subTest(label=label):
                result = self.generate(mutate, label="evidence-" + label)
                self.assertEqual(result["status"], "output_invalid")
                self.assertEqual(result["provider_error"]["code"], "OUTPUT_INVALID")

    def test_changed_clip_prompt_refuses_even_when_export_echoes_it(self):
        def mutate(result):
            result["clips"][0]["prompt"] = "a different requested behavior"
            path = self.root / result["export"]["path"]
            export = read_json(path)
            export["clips"] = result["clips"]
            write_json(path, export)
            result["export"] = file_record(self.root, path)
        result = self.generate(mutate, label="changed-prompt")
        self.assertEqual(result["status"], "output_invalid")
        self.assertEqual(result["provider_error"]["code"], "OUTPUT_INVALID")

    def test_direct_script_bootstrap_cannot_shadow_stdlib_profile(self):
        code = "\n".join((
            "import pathlib, runpy, sys",
            "worker = pathlib.Path(sys.argv[1])",
            "sys.path.insert(0, str(worker.parent))",
            "sys.argv = [str(worker), '--help']",
            "try:",
            "    runpy.run_path(str(worker), run_name='__main__')",
            "except SystemExit as exc:",
            "    assert exc.code == 0",
            "import cProfile, profile",
            "assert hasattr(cProfile, 'Profile')",
            "assert pathlib.Path(profile.__file__).resolve().parent != worker.parent",
        ))
        result = subprocess.run([sys.executable, "-c", code, str(Path(worker.__file__).resolve())],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unexpected_worker_failure_retains_traceback_and_structured_receipt(self):
        data = self.payload()
        input_path = self.root / "diagnostic-input.json"
        output_path = Path(data["output"]).parent / "result.json"
        write_json(input_path, data)
        errors = io.StringIO()
        with patch.object(worker, "execute", side_effect=RuntimeError("diagnostic fixture error")), redirect_stderr(errors):
            code = worker.main(["--input", str(input_path), "--output", str(output_path)])
        self.assertEqual(code, 1)
        self.assertIn("Traceback", errors.getvalue())
        self.assertIn("RuntimeError: diagnostic fixture error", errors.getvalue())
        failure = read_json(output_path)
        self.assertEqual(failure["request_digest"], data["request_digest"])
        self.assertEqual(failure["provider_error"]["code"], "WORKER_FAILED")
        self.assertNotIn("diagnostic fixture error", failure["provider_error"]["message"])

    def test_incomplete_snapshot_and_uninventoried_source_fail_before_worker(self):
        text = Path(self.config["unimate"]["runtime"]["text_root"])
        path = text / "spiece.model"
        path.unlink()
        with patch.object(unimate, "run", side_effect=AssertionError("worker")):
            self.assertEqual(self.fx.generate()["provider_error"]["code"], "OFFLINE_ASSET_MISSING")
        path.write_text("fixture only")
        (Path(self.config["unimate"]["runtime"]["unimate_root"]) / "unlisted.py").write_text("x=1")
        self.assertEqual(self.fx.generate()["provider_error"]["code"], "OFFLINE_ASSET_MISSING")

    def test_output_digest_root_policy_and_loop_claim_mutations_fail(self):
        for key, value in (("conditioning_digest", "wrong"), ("generation_digest", "wrong"),
                           ("runtime_digest", "wrong"), ("raw_motion", "compensated")):
            result = self.generate(lambda r: r.update({key: value}), label=key.replace("_", "-"))
            self.assertFalse(result["ok"], key)
        # Direct validator cannot accept echoing a changed runtime/view policy.
        data = self.payload()
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": ""}):
            output = worker.execute(data, Path(data["output"]).parent / "result.json", sampler=self.fake_sample)
        output["clips"][0]["desired_runtime_root_policy"] = "in_place"
        with self.assertRaises(unimate.ProviderError):
            reference.validate_result(self.root, Path(data["output"]).parent, self.request, self.config["unimate"], output)
        output["clips"][0]["desired_runtime_root_policy"] = "controller_owned"
        output["clips"][0]["loop_validation"] = "pass"
        with self.assertRaises(unimate.ProviderError):
            reference.validate_result(self.root, Path(data["output"]).parent, self.request, self.config["unimate"], output)

    def test_cutoff_cancel_marker_and_nonzero_device_probe(self):
        data = self.payload()
        budget = worker.Budget(data)
        budget.cancel.parent.mkdir(parents=True)
        write_json(budget.cancel, {"request_digest": data["request_digest"]})
        with self.assertRaises(unimate.ProviderError) as error:
            budget.check()
        self.assertEqual(error.exception.code, "INTERRUPTED")
        budget.cancel.unlink()
        budget.deadline = 0
        with self.assertRaises(unimate.ProviderError) as error:
            budget.check()
        self.assertEqual(error.exception.code, "CUTOFF_PASSED")
        data["request"]["execution"]["device"] = "cuda:3"
        data["worker_device"] = "cuda:0"
        budget = worker.Budget(data)
        with patch.object(worker, "free_ram_mib", return_value=4096), \
             patch.object(worker.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="4096, 0")) as probe:
            evidence = {"resource_checks": []}
            worker.resource_gate(data, budget, evidence, resident=True)
            self.assertEqual(probe.call_args.args[0][1:3], ["-i", "3"])
            self.assertTrue(evidence["resource_checks"][0]["model_resident"])
        with patch.object(worker, "free_ram_mib", return_value=1000):
            with self.assertRaises(unimate.ProviderError):
                worker.resource_gate(data, budget, evidence)

    def test_local_loaders_force_local_files_and_disable_spacy_fallback(self):
        calls = []
        class Tokenizer:
            @staticmethod
            def from_pretrained(path, **kwargs):
                calls.append((path, kwargs))
        class Encoder:
            @staticmethod
            def from_pretrained(path, **kwargs):
                calls.append((path, kwargs))
        class Normalizer:
            pass
        worker.install_local_loaders(Tokenizer, Encoder, Path("local-snapshot"), Normalizer)
        Tokenizer.from_pretrained("google/flan-t5-base")
        Encoder.from_pretrained("google/flan-t5-base")
        self.assertEqual(calls[0], ("local-snapshot", {"local_files_only": True}))
        self.assertEqual(calls[1], calls[0])
        with self.assertRaises(unimate.ProviderError):
            Normalizer()
        with self.assertRaises(unimate.ProviderError):
            Encoder.from_pretrained("unexpected-model")

    def test_dependency_lock_refuses_missing_or_changed_versions_without_installing(self):
        path = self.root / "dependencies.txt"
        with patch.object(worker.metadata, "version", return_value="1"):
            worker.verify_dependencies(path)
        with patch.object(worker.metadata, "version", return_value="2"):
            with self.assertRaises(unimate.ProviderError) as error:
                worker.verify_dependencies(path)
        self.assertEqual(error.exception.code, "DEPENDENCY_MISSING")
        path.write_text("unversioned\n")
        with self.assertRaises(unimate.ProviderError):
            worker.verify_dependencies(path)

    def test_missing_asset_and_foreign_rig_cannot_reach_sampler(self):
        for mode in ("asset", "rig"):
            data = self.payload()
            if mode == "asset":
                data["assets"][-1]["path"] = str(self.root / "absent")
            else:
                data["rig"] = dict(data["rig"], profile="kite14")
            with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": ""}), \
                 patch.object(worker, "sample", side_effect=AssertionError("sampler")):
                with self.assertRaises(unimate.ProviderError):
                    worker.execute(data, self.root / "result.json")

    def test_python_network_guard_refuses_connections_without_contacting_network(self):
        with patch.object(worker.socket, "create_connection"), patch.object(worker.socket.socket, "connect"), \
             patch.object(worker.socket.socket, "connect_ex"), patch.object(worker.socket, "getaddrinfo"):
            worker.disable_network()
            with self.assertRaises(unimate.ProviderError) as error:
                worker.socket.create_connection(("example.invalid", 443))
        self.assertEqual(error.exception.code, "OFFLINE_NETWORK_REFUSED")

    def test_bound_worker_failure_is_preserved_and_cleanup_refusal_takes_priority(self):
        def failed(args, **kwargs):
            folder = kwargs["job_dir"]
            folder.mkdir()
            data = read_json(Path(args[-3]))
            write_json(folder / "process.json", {"status": "failed", "returncode": 1, "pid": 123, "windows_ownership": {}})
            write_json(Path(args[-1]), {"request_digest": data["request_digest"], "status": "failed",
                                       "provider_error": {"code": "RESOURCE_BUSY", "retryable": False}})
            raise StudioError("fixture worker exit")
        for label, cleanup in (("bound-failure", {"status": "ok", "pids": [], "stopped": True, "unverified": []}),
                               ("cleanup-failure", {"status": "unavailable", "pids": [], "stopped": False, "unverified": []})):
            with patch.object(unimate, "prelaunch_baseline", return_value={"status": "ok"}), \
                 patch.object(unimate, "run", side_effect=failed), patch.object(unimate, "stop_survivors", return_value=cleanup):
                result = self.fx.generate(label)
            self.assertFalse(result["ok"])
            self.assertEqual(result["provider_error"]["code"],
                             "RESOURCE_BUSY" if label == "bound-failure" else "CLEANUP_UNVERIFIED")

    @unittest.skipIf(np is None, "Optional NumPy worker environment unavailable")
    def test_actual_array_shapes_order_rest_mapping_and_leaf_recovery(self):
        names = [j["name"] for j in self.rig["joints"]]
        parents = [-1 if j["parent"] is None else names.index(j["parent"]) for j in self.rig["joints"]]
        original = [j["name"] for j in self.rig["source_joints"]]
        entry = {"joint_names": names, "parents": np.array(parents), "scale_factor": 2.7977284418,
                 "tpos_offsets": np.array([j["rest_offset"] for j in self.rig["joints"]]),
                 "tpos_local_rotations": np.tile([1, 0, 0, 0], (18, 1)),
                 "tpos_global_rotations": np.tile([1, 0, 0, 0], (18, 1))}
        rest = {"names": np.array(original), "parents": np.array([-1]+[0]*13),
                "rest_world_bones": np.tile(np.eye(4), (14, 1, 1)), "C": np.eye(4)}
        self.assertEqual(worker.validate_condition(np, self.payload(), entry, rest)[2], entry["scale_factor"])
        rest["rest_world_bones"][1, 0, 0] = 1.0000006  # Real float32 capture roundoff.
        worker.validate_condition(np, self.payload(), entry, rest)
        rest["rest_world_bones"][1, 0, 0] = 1.01
        with self.assertRaises(unimate.ProviderError):
            worker.validate_condition(np, self.payload(), entry, rest)
        rest["rest_world_bones"][1, 0, 0] = 1
        entry["joint_names"] = list(reversed(names))
        with self.assertRaises(unimate.ProviderError):
            worker.validate_condition(np, self.payload(), entry, rest)
        anim = SimpleNamespace(positions=np.zeros((60, 18, 3)), rotations=SimpleNamespace(qs=np.tile([1.,0,0,0], (60,18,1))),
                               orients=SimpleNamespace(qs=np.tile([1.,0,0,0], (60,1))),
                               offsets=np.zeros((18,3)), parents=np.array(parents))
        raw = np.zeros((60,18,12))
        worker.validate_decoded(np, raw, anim, names, parents)
        raw[0,0,0] = np.nan
        with self.assertRaises(unimate.ProviderError):
            worker.validate_decoded(np, raw, anim, names, parents)
        raw[0,0,0] = 0
        anim.rotations.qs[:, names.index("Head")] = [0,1,0,0]
        with self.assertRaises(unimate.ProviderError):
            worker.validate_decoded(np, raw, anim, names, parents)

    @unittest.skipIf(np is None, "Optional NumPy worker environment unavailable")
    def test_nonunit_condition_scale_survives_decoded_and_evidence_serialization(self):
        names = [j["name"] for j in self.rig["joints"]]
        parents = [-1 if j["parent"] is None else names.index(j["parent"]) for j in self.rig["joints"]]
        original = [j["name"] for j in self.rig["source_joints"]]
        entry = {"joint_names": names, "parents": np.array(parents),
                 "tpos_offsets": np.array([j["rest_offset"] for j in self.rig["joints"]]),
                 "tpos_local_rotations": np.tile([1, 0, 0, 0], (18, 1)),
                 "tpos_global_rotations": np.tile([1, 0, 0, 0], (18, 1))}
        rest = {"names": np.array(original), "parents": np.array([-1]+[0]*13),
                "rest_world_bones": np.tile(np.eye(4), (14, 1, 1)), "C": np.eye(4)}
        rest["rest_world_bones"][:, :3, :3] *= 1.15  # Independent captured bone-matrix scale.
        anim = SimpleNamespace(positions=np.zeros((60, 18, 3)),
            rotations=SimpleNamespace(qs=np.tile([1.,0,0,0], (60,18,1))),
            orients=SimpleNamespace(qs=np.tile([1.,0,0,0], (60,1))), offsets=entry["tpos_offsets"],
            parents=np.array(parents))
        for expected in (2.7977284418, 1.7302126414):
            with self.subTest(scale=expected):
                entry["scale_factor"] = expected
                _, _, scale, C = worker.validate_condition(np, self.payload(), entry, rest)
                self.assertEqual(scale, expected)
                evidence = {"canonical_scale_factor": scale, "source_joint_indices": list(range(14))}
                path = self.root / "scale-decoded.npz"
                worker.write_decoded(np, path, anim, entry, C, evidence)
                write_json(self.root / "scale-evidence.json", evidence)
                with np.load(path, allow_pickle=False) as decoded:
                    self.assertEqual(float(decoded["scale_factor"]), expected)
                self.assertEqual(read_json(self.root / "scale-evidence.json")["canonical_scale_factor"], expected)


if __name__ == "__main__":
    unittest.main()
