"""Small offline regressions from production: no Blender/Godot/Gaea launch."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from studio_tools import processes
from studio_tools.adapters import gaea, godot
from studio_tools.common import StudioError, read_json, sha256, write_json
from studio_tools.config import load


class ProductionReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio job space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_python(self, code, name="job", **kwargs):
        return processes.run(
            [sys.executable, "-c", code],
            job_dir=self.root / name,
            hide_window=True,
            **kwargs,
        )

    def test_job_preserves_success_and_nonzero_output_without_secret_metadata(self):
        before = dict(os.environ)
        environment = {**os.environ, "STUDIO_JOB_FIXTURE": "private-env"}
        for name, exit_code in (("success", 0), ("failure", 3)):
            code = (
                "import os,sys;print('private-arg');"
                "print(os.environ['STUDIO_JOB_FIXTURE'], file=sys.stderr);"
                f"sys.exit({exit_code})"
            )
            if exit_code:
                with self.assertRaises(StudioError) as failure:
                    self.run_python(code, name=name, env=environment)
                self.assertNotIn("private-", str(failure.exception))
            else:
                result = self.run_python(code, name=name, env=environment)
                self.assertIn("private-arg", result["stdout"])
                self.assertEqual(Path(result["process_record"]).name, "process.json")
            folder = self.root / name
            record = read_json(folder / "process.json")
            self.assertEqual(record["status"], "failed" if exit_code else "completed")
            self.assertEqual(record["returncode"], exit_code)
            self.assertGreater(record["pid"], 0)
            self.assertGreaterEqual(record["elapsed_seconds"], 0)
            self.assertGreaterEqual(record["finished_utc"], record["started_utc"])
            self.assertNotIn("private-", json.dumps(record))
            output = (folder / "stdout.log").read_text()
            self.assertIn("private-arg", output)
            self.assertIn("private-env", output)
        self.assertEqual(dict(os.environ), before)

    def test_timeout_preserves_flushed_output_and_final_record(self):
        with self.assertRaisesRegex(StudioError, "owned process stopped"):
            self.run_python(
                "import time;print('before timeout',flush=True);time.sleep(30)",
                timeout=1,
            )
        self.assertIn("before timeout", (self.root / "job/stdout.log").read_text())
        record = read_json(self.root / "job/process.json")
        self.assertEqual(record["status"], "timed_out")
        self.assertEqual(record["cleanup"], "owned_tree_stopped")
        self.assertIsNotNone(record["returncode"])
    def test_timeout_stops_descendant_without_stopping_unrelated_process(self):
        child = self.root / "child.py"
        heartbeat = self.root / "heartbeat"
        child.write_text(
            "from pathlib import Path\nimport sys,time\n"
            "path=Path(sys.argv[1])\n"
            "for n in range(80):\n path.write_text(str(n));time.sleep(.05)\n"
        )
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(10)"],
            **processes._creation_options(True),
        )
        try:
            code = (
                "import subprocess,sys,time,os;"
                "subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],"
                "creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0);"
                "time.sleep(30)"
            )
            with self.assertRaisesRegex(StudioError, "owned process stopped"):
                processes.run(
                    [sys.executable, "-c", code, str(child), str(heartbeat)],
                    timeout=2, job_dir=self.root / "tree", hide_window=True,
                )
            self.assertTrue(heartbeat.exists(), "Descendant must run before testing cleanup")
            before = heartbeat.read_bytes()
            time.sleep(.2)
            self.assertEqual(heartbeat.read_bytes(), before)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_legacy_log_also_survives_timeout(self):
        log = self.root / "legacy.log"
        with self.assertRaisesRegex(StudioError, "timed out"):
            processes.run(
                [sys.executable, "-c", "import time;print('saved',flush=True);time.sleep(30)"],
                timeout=1, log=log, hide_window=True,
            )
        self.assertIn("saved", log.read_text())

    def test_start_failure_and_existing_job_do_not_erase_evidence(self):
        folder = self.root / "missing"
        with self.assertRaisesRegex(StudioError, "Could not start"):
            processes.run([self.root / "missing-program"], job_dir=folder, hide_window=True)
        record = (folder / "process.json").read_bytes()
        self.assertEqual(json.loads(record)["status"], "start_failed")
        self.assertIsNone(json.loads(record)["pid"])
        self.assertEqual((folder / "stdout.log").read_bytes(), b"")
        with patch("studio_tools.processes.subprocess.Popen") as launch:
            with self.assertRaisesRegex(StudioError, "new run identity"):
                processes.run([sys.executable], job_dir=folder)
            launch.assert_not_called()
        self.assertEqual((folder / "process.json").read_bytes(), record)

    def test_cleanup_failure_is_not_reported_as_stopped(self):
        # No live process is deliberately left behind by this failure fixture.
        with patch("studio_tools.processes.subprocess.Popen") as launch:
            child = launch.return_value
            child.pid = 123
            child.poll.return_value = None
            child.wait.side_effect = subprocess.TimeoutExpired(["fixture"], 1)
            with patch("studio_tools.processes._stop_owned", side_effect=OSError):
                with self.assertRaisesRegex(StudioError, "cleanup unverified"):
                    self.run_python("unused")
        record = read_json(self.root / "job/process.json")
        self.assertEqual(record["cleanup"], "unverified")
        self.assertIsNone(record["returncode"])

    def test_receipt_write_failure_after_launch_stops_owned_job(self):
        def fail_running_receipt(path, record):
            if record["status"] == "running":
                raise OSError("fixture receipt failure")
            write_json(path, record)

        with (
            patch("studio_tools.processes.subprocess.Popen") as launch,
            patch("studio_tools.processes.write_json", side_effect=fail_running_receipt),
            patch("studio_tools.processes._stop_owned", return_value=True) as stop,
        ):
            child = launch.return_value
            child.pid = 123
            child.poll.return_value = -1
            with self.assertRaisesRegex(OSError, "fixture receipt failure"):
                self.run_python("unused")
            stop.assert_called_once_with(child, True)
        record = read_json(self.root / "job/process.json")
        self.assertEqual(record["status"], "interrupted")
        self.assertEqual(record["cleanup"], "owned_tree_stopped")

    @unittest.skipUnless(os.name == "nt", "Native Windows console visibility check")
    def test_windows_hidden_child_has_no_console_window(self):
        result = self.run_python(
            "import ctypes;print(ctypes.windll.kernel32.GetConsoleWindow())"
        )
        self.assertEqual(result["stdout"].strip(), "0")

    def test_platform_creation_flags_are_explicit(self):
        with patch("studio_tools.processes.os.name", "nt"), \
             patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
             patch.object(subprocess, "CREATE_NO_WINDOW", 134217728, create=True):
            self.assertEqual(processes._creation_options(False), {"creationflags": 512})
            self.assertEqual(
                processes._creation_options(True), {"creationflags": 512 | 134217728}
            )
        with patch("studio_tools.processes.os.name", "posix"):
            self.assertEqual(processes._creation_options(True), {"start_new_session": True})

    def test_godot_completed_logs_keep_two_runs_and_reject_exit_zero_error(self):
        (self.root / "project.godot").touch()
        config = load(overrides={"executables": {"godot": sys.executable}})
        runs = []

        def fake_run(args, **kwargs):
            self.assertTrue(kwargs["hide_window"])
            result = processes.run(
                [sys.executable, "-c",
                 "import sys;print('finished');print("
                 + repr("WARNING: shutdown warning" if not runs else "SCRIPT ERROR: late error")
                 + ",file=sys.stderr)"],
                **kwargs,
            )
            runs.append(Path(result["log"]))
            return result

        with patch("studio_tools.adapters.godot.run", side_effect=fake_run):
            first = godot.execute(config, self.root)
            first_bytes = runs[0].read_bytes()
            self.assertEqual(first["process_evidence"]["diagnostics"]["status"], "warnings")
            self.assertEqual(first["native_review"], "not_run")
            with self.assertRaisesRegex(StudioError, "reported an error"):
                godot.execute(config, self.root)
        self.assertNotEqual(runs[0], runs[1])
        self.assertEqual(runs[0].read_bytes(), first_bytes)
        self.assertEqual(read_json(runs[1].parent / "diagnostics.json")["error_count"], 1)
        # Process success is distinct from engine diagnostics.
        self.assertEqual(read_json(runs[1].parent / "process.json")["status"], "completed")

    def test_godot_classifier_counts_warnings_orphans_and_colored_errors(self):
        self.assertEqual(godot.classify_log("scene complete\n")["status"], "clean")
        result = godot.classify_log("WARNING: first\nOrphan StringName: X\n ERROR: late\n")
        self.assertEqual(result, {"status": "errors", "error_count": 1, "warning_count": 2})
        self.assertEqual(godot.classify_log("\x1b[31mSCRIPT ERROR: late\x1b[0m")["error_count"], 1)

    def test_native_godot_run_does_not_request_console_hiding(self):
        (self.root / "project.godot").touch()
        config = load(overrides={"executables": {"godot": sys.executable}})
        with patch("studio_tools.adapters.godot.run", return_value={"stdout": "", "elapsed_seconds": 0}) as run:
            godot.execute(config, self.root, "run")
        self.assertFalse(run.call_args.kwargs["hide_window"])

    def recipe(self):
        graph = self.root / "graph.terrain"
        graph.write_text("offline fixture")
        return {
            "version": "fixture",
            "entitlement_confirmed": True,
            "ui_build_verified": True,
            "graph": str(graph),
            "graph_sha256": sha256(graph),
            "arguments": [],
            "outputs": ["height.raw"],
            "variables": {},
        }

    def test_gaea_unattended_requires_separate_verification_before_writes(self):
        for mode, verified in (("unattended", None), ("unattended", "true"),
                               ("background", True), ([], True)):
            recipe = {**self.recipe(), "execution_mode": mode, "unattended_verified": verified}
            output = self.root / "build"
            with patch("studio_tools.adapters.gaea.run") as run:
                with self.assertRaises(StudioError):
                    gaea.build({}, recipe, output)
                run.assert_not_called()
            self.assertFalse(output.exists())

    def test_gaea_legacy_native_and_verified_unattended_are_distinct(self):
        config = load(overrides={"executables": {"gaea": sys.executable}})
        for mode in ("native", "unattended"):
            recipe = self.recipe()
            if mode == "unattended":
                recipe.update(execution_mode=mode, unattended_verified=True)
            output = self.root / mode

            def fake_run(args, **kwargs):
                self.assertEqual(kwargs["hide_window"], mode == "unattended")
                (output / "height.raw").write_bytes(b"fixture, not terrain acceptance")
                return {"elapsed_seconds": 0}

            with patch("studio_tools.adapters.gaea.run", side_effect=fake_run):
                result = gaea.build(config, recipe, output)
            self.assertEqual(result["execution_mode"], mode)
            self.assertEqual(result["unattended_verified"], mode == "unattended")
            self.assertEqual(result["terrain_contract"], "required")
            self.assertEqual(result["visual_verdict"], "not_run")
