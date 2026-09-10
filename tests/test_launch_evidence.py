"""Owned blocking launch, launch inventory and identity manifest receipts (offline)."""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cli, launch, manifest, processes
from studio_tools.common import StudioError, read_json, sha256, write_json
from studio_tools.config import load


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio launch space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)

    def fake_child(self, code):
        def fake_run(args, **kwargs):
            self.last_args = args
            self.last_kwargs = kwargs
            return processes.run([sys.executable, "-c", code], **kwargs)
        return fake_run

    def execute(self, code, **kwargs):
        with patch("studio_tools.launch.run", side_effect=self.fake_child(code)):
            return launch.execute(self.config, self.root, sha256_expected=self.sha, **kwargs)


class OwnedLaunchTests(LaunchCase):
    def test_engine_sha_mismatch_refuses_before_launch(self):
        with patch("studio_tools.launch.run") as run:
            with self.assertRaisesRegex(StudioError, "identity mismatch"):
                launch.execute(self.config, self.root, sha256_expected="0" * 64)
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts").exists())

    def test_completed_launch_writes_receipts_without_argv_or_env(self):
        code = (
            "import os,sys,pathlib;print('private-arg');"
            "print(os.environ['STUDIO_JOB_FIXTURE'],file=sys.stderr);"
            "pathlib.Path('artifacts/out.json').write_text('{}')"
        )
        with patch.dict(os.environ, {"STUDIO_JOB_FIXTURE": "private-env"}):
            result = self.execute(code, label="first", results=["artifacts/out.json"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["verdict"], "completed")
        self.assertEqual(self.last_kwargs["cwd"], str(self.root))
        run_dir = self.root / "artifacts" / "launches" / "first"
        owned = read_json(run_dir / "owned-launch.json")
        exit_record = read_json(run_dir / "exit.json")
        self.assertGreater(owned["pid"], 0)
        self.assertEqual(owned["engine"]["sha256"], self.sha)
        self.assertEqual(owned["status"], "launched")
        self.assertEqual(exit_record["status"], "completed")
        self.assertGreater(exit_record["combined_log_bytes"], 0)
        self.assertTrue(exit_record["result_files"][0]["present"])
        self.assertEqual(exit_record["result_files"][0]["sha256"], sha256(self.root / "artifacts/out.json"))
        self.assertIn("exit zero is not acceptance", exit_record["limits"])
        for name in ("owned-launch.json", "exit.json", "process/process.json", "diagnostics.json"):
            self.assertNotIn("private-", (run_dir / name).read_text())
        self.assertIn("private-arg", (run_dir / "process/stdout.log").read_text())

    def test_timeout_returns_verdict_with_exit_code_instead_of_raising(self):
        with patch("studio_tools.launch.run", side_effect=self.fake_child("import time;print('partial',flush=True);time.sleep(30)")):
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                code = cli.main(["launch", "--project", str(self.root), "--engine", sys.executable, "--sha256", self.sha, "--timeout", "1", "--label", "slow"])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue(), "")
        verdict = json.loads(out.getvalue())
        self.assertEqual(verdict["verdict"], "timed_out")
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["cleanup"], "owned_tree_stopped")
        self.assertIn("partial", Path(verdict["log"]).read_text())
        self.assertEqual(read_json(verdict["process_record"])["status"], "timed_out")

    def test_exit_zero_with_engine_error_is_not_ok(self):
        result = self.execute("import sys;print('SCRIPT ERROR: late');sys.exit(0)", label="late")
        self.assertEqual(result["verdict"], "engine_errors")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["diagnostics"]["error_count"], 1)

    def test_missing_result_and_nonzero_exit_are_reported(self):
        missing = self.execute("print('done')", label="missing", results=["artifacts/never.json"])
        self.assertEqual(missing["verdict"], "results_missing")
        failed = self.execute("import sys;sys.exit(3)", label="failed")
        self.assertEqual(failed["verdict"], "failed")
        self.assertEqual(failed["returncode"], 3)
        self.assertNotIn("SCRIPT", failed["failure"])

    def test_cutoff_already_passed_does_not_launch(self):
        with patch("studio_tools.launch.run") as run:
            result = launch.execute(self.config, self.root, sha256_expected=self.sha, cutoff_utc="2000-01-01T00:00:00Z", label="late-start")
            run.assert_not_called()
        self.assertEqual(result["verdict"], "cutoff_passed")
        self.assertFalse(result["ok"])
        run_dir = self.root / "artifacts/launches/late-start"
        self.assertEqual(read_json(run_dir / "owned-launch.json")["status"], "refused")
        self.assertTrue((run_dir / "exit.json").is_file())

    def test_cutoff_bounds_the_timeout(self):
        cutoff = (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()
        self.execute("print('quick')", label="bounded", timeout=100, cutoff_utc=cutoff)
        self.assertLessEqual(self.last_kwargs["timeout"], 3)
        self.assertGreater(self.last_kwargs["timeout"], 0)
        with self.assertRaisesRegex(StudioError, "UTC offset"):
            launch.execute(self.config, self.root, sha256_expected=self.sha, cutoff_utc="2030-01-01T00:00:00")

    def test_env_scrub_and_profile_isolation(self):
        before = dict(os.environ)
        with patch.dict(os.environ, {"SALVAGE_TOKEN": "secret", "KEEP_ME": "yes"}):
            self.execute("print('env')", label="env", scrub=["SALVAGE_"])
            env = self.last_kwargs["env"]
            self.assertNotIn("SALVAGE_TOKEN", env)
            self.assertEqual(env["KEEP_ME"], "yes")
            run_dir = self.root / "artifacts/launches/env"
            for key in launch.PROFILE_KEYS:
                self.assertEqual(Path(env[key]), (run_dir / "profile").resolve())
            self.assertEqual(os.environ["SALVAGE_TOKEN"], "secret")
        self.assertEqual(dict(os.environ), before)

    def test_mode_flags_match_the_owned_launcher(self):
        native = launch.build_args(self.config, self.root, sys.executable, "native", "res://tests/probe.gd")
        self.assertNotIn("--headless", native)
        self.assertIn("forward_plus", native)
        self.assertEqual(native[-2:], ["--script", "res://tests/probe.gd"])
        imported = launch.build_args(self.config, self.root, sys.executable, "import")
        self.assertEqual(imported[3:], ["--headless", "--audio-driver", "Dummy", "--editor", "--import"])
        check = launch.build_args(self.config, self.root, sys.executable, "check", "res://a.gd", ["--", "x"])
        self.assertIn("--check-only", check)
        self.assertEqual(check[-2:], ["--", "x"])
        for mode in ("test", "check"):
            with self.assertRaisesRegex(StudioError, "needs --script"):
                launch.build_args(self.config, self.root, sys.executable, mode)
        with self.assertRaises(StudioError):
            launch.build_args(self.config, self.root, sys.executable, "smoke")

    def test_label_collision_and_bad_inputs_are_refused_before_launch(self):
        self.execute("print('one')", label="same")
        with patch("studio_tools.launch.run") as run:
            with self.assertRaisesRegex(StudioError, "exists"):
                launch.execute(self.config, self.root, sha256_expected=self.sha, label="same")
            with self.assertRaisesRegex(StudioError, "1–3600"):
                launch.execute(self.config, self.root, sha256_expected=self.sha, timeout=0)
            with self.assertRaises(StudioError):
                launch.execute(self.config, self.root, sha256_expected=self.sha, results=["../escape.json"])
            run.assert_not_called()

    def test_scope_is_persisted_in_receipts_and_invalid_scope_is_refused_before_launch(self):
        result = self.execute("print('scoped')", label="scoped", scope="rung-2")
        self.assertEqual(result["scope"], "rung-2")
        run_dir = self.root / "artifacts/launches/scoped"
        self.assertEqual(read_json(run_dir / "owned-launch.json")["scope"], "rung-2")
        self.assertEqual(read_json(run_dir / "exit.json")["scope"], "rung-2")
        unscoped = self.execute("print('plain')", label="plain")
        self.assertIsNone(unscoped["scope"])
        self.assertIsNone(read_json(self.root / "artifacts/launches/plain/owned-launch.json")["scope"])
        with patch("studio_tools.launch.run") as run:
            with self.assertRaisesRegex(StudioError, "letters, digits"):
                launch.execute(self.config, self.root, sha256_expected=self.sha, label="bad-scope", scope="rung 2/full")
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts/launches/bad-scope").exists())

    def test_cli_launch_passthrough_and_native_visibility(self):
        with patch("studio_tools.launch.run", side_effect=self.fake_child("print('cli')")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = cli.main(["launch", "--project", str(self.root), "--engine", sys.executable, "--sha256", self.sha, "--mode", "native",
                                 "--script", "res://tests/probe.gd", "--label", "cli", "--scope", "rung-1", "--", "--regional", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["verdict"], "completed")
        self.assertEqual(self.last_args[-2:], ["--regional", "1"])
        self.assertFalse(self.last_kwargs["hide_window"])
        owned = read_json(self.root / "artifacts/launches/cli/owned-launch.json")
        self.assertEqual(owned["passthrough_count"], 2)
        self.assertEqual(owned["scope"], "rung-1")
        self.assertNotIn("--regional", json.dumps(owned))


class LaunchInventoryTests(LaunchCase):
    def test_inventory_pairs_launches_and_flags_missing_exit(self):
        self.execute("print('ok')", label="good", scope="rung-1")
        self.execute("import time;time.sleep(30)", label="slow", timeout=1)
        launches = self.root / "artifacts/launches"
        shutil.copytree(launches / "good", launches / "orphan")
        (launches / "orphan/exit.json").unlink()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["evidence", "launches", str(launches)]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["totals"], {"launches": 3, "completed": 1, "not_ok": 2, "timed_out": 1, "missing_exit": 1})
        by_dir = {entry["dir"]: entry for entry in data["launches"]}
        self.assertEqual(by_dir["good"]["verdict"], "completed")
        self.assertEqual(by_dir["good"]["scope"], "rung-1")
        self.assertIsNone(by_dir["slow"]["scope"])
        self.assertEqual(by_dir["slow"]["verdict"], "timed_out")
        self.assertEqual(by_dir["slow"]["cleanup"], "owned_tree_stopped")
        self.assertEqual(by_dir["orphan"]["verdict"], "no_exit_record")
        self.assertIsNone(by_dir["orphan"]["exit"])
        self.assertEqual(by_dir["good"]["launch"]["sha256"], sha256(launches / "good/owned-launch.json"))
        self.assertIn("exit zero is not acceptance", data["limits"])
        self.assertTrue(Path(data["output"]).is_file())
        self.assertEqual(read_json(data["output"])["totals"]["launches"], 3)

    def test_inventory_refuses_empty_root_and_existing_output(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(StudioError, "No owned-launch"):
            launch.inventory(empty)
        self.execute("print('ok')", label="one")
        taken = self.root / "taken.json"
        taken.write_text("{}")
        with self.assertRaisesRegex(StudioError, "exists"):
            launch.inventory(self.root / "artifacts/launches", taken)
        with self.assertRaises(StudioError):
            launch.inventory(self.root / "nowhere")


class IdentityManifestTests(LaunchCase):
    def test_verify_reports_match_mismatch_and_missing_with_receipt(self):
        source = self.root / "source"
        source.mkdir()
        (source / "a.bin").write_bytes(b"alpha")
        (source / "b.bin").write_bytes(b"beta")
        record = {"schema_version": 1, "kind": "identity-manifest", "items": [
            {"id": "engine", "role": "engine", "path": sys.executable, "sha256": self.sha},
            {"id": "a", "role": "source", "path": "source/a.bin", "sha256": sha256(source / "a.bin")},
            {"id": "b", "role": "package", "path": "source/b.bin", "sha256": "0" * 64},
            {"id": "c", "role": "asset", "path": "source/c.bin", "sha256": "1" * 64},
        ]}
        path = self.root / "manifest.json"
        write_json(path, record)
        result = manifest.verify(self.root, path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["verdict"], "mismatch")
        self.assertEqual(result["totals"], {"match": 2, "mismatch": 1, "missing": 1})
        self.assertEqual({i["id"]: i["status"] for i in result["items"]},
                         {"engine": "match", "a": "match", "b": "mismatch", "c": "missing"})
        receipt = read_json(result["receipt"])
        self.assertEqual(receipt["manifest"]["sha256"], sha256(path))
        self.assertTrue(Path(result["receipt"]).is_relative_to(self.root / "artifacts/identity"))
        record["items"] = record["items"][:2]
        write_json(path, record)
        self.assertTrue(manifest.verify(self.root, path)["ok"])
        record["items"][1]["path"] = "../escape.bin"
        write_json(path, record)
        with self.assertRaises(StudioError):
            manifest.verify(self.root, path)
        record["items"][1]["path"] = "source/a.bin"
        record["items"][1]["role"] = "mystery"
        write_json(path, record)
        with self.assertRaisesRegex(StudioError, "role"):
            manifest.verify(self.root, path)

    def test_candidate_operations_keep_new_and_add_verify(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["candidate", "--project", str(self.root)]), 1)
        self.assertIn("--id", err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["candidate", "verify", "--project", str(self.root)]), 1)
        self.assertIn("--manifest", err.getvalue())
        path = self.root / "manifest.json"
        write_json(path, {"schema_version": 1, "kind": "identity-manifest", "items": [
            {"id": "engine", "role": "engine", "path": sys.executable, "sha256": self.sha}]})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["candidate", "verify", "--project", str(self.root), "--manifest", str(path)]), 0)
        self.assertEqual(json.loads(out.getvalue())["verdict"], "match")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["candidate", "--project", str(self.root), "--id", "cand-1"]), 0)
        self.assertEqual(json.loads(out.getvalue())["candidate_id"], "cand-1")

    def test_template_manifest_loads(self):
        kit = Path(__file__).resolve().parents[1]
        loaded = manifest.load(kit / "templates/identity-manifest.json")
        self.assertEqual(loaded["kind"], "identity-manifest")


if __name__ == "__main__":
    unittest.main()
