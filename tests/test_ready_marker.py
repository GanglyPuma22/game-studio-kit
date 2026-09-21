"""The optional ready marker: how long a child took to say it was up (offline).

A `python -c` child stands in for the engine and prints the marker after a
short sleep. The number this produces is load-time timing and nothing else; the
tests below check that the receipts say so and that a project which declares no
marker has its log left alone while it runs.
"""

import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import launch, playtest, processes
from studio_tools.common import StudioError, read_json, sha256, write_json
from studio_tools.config import load

MARKER = "STUDIO-CHILD-READY"
LIMIT = "ready_seconds is a load-time measurement, never acceptance"


def child(delay=0.4, marker=MARKER, after=0.3, code=0):
    return (
        "import sys,time;"
        f"time.sleep({delay});"
        f"print({marker!r},flush=True);"
        f"time.sleep({after});"
        f"sys.exit({code})"
    )


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio ready space ")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_the_marker_is_timed_from_popen_and_recorded_in_the_process_receipt(self):
        job = self.dir / "job"
        result = processes.run([sys.executable, "-c", child()], timeout=20,
                               job_dir=job, ready_marker=MARKER)
        self.assertIsNotNone(result["ready_seconds"])
        self.assertGreaterEqual(result["ready_seconds"], 0.4)
        self.assertLess(result["ready_seconds"], result["elapsed_seconds"])
        self.assertEqual(read_json(job / "process.json")["ready_seconds"], result["ready_seconds"])
        # Rounded to milliseconds, like every other elapsed time in a receipt.
        self.assertEqual(round(result["ready_seconds"], 3), result["ready_seconds"])

    def test_a_child_that_never_prints_the_marker_records_null(self):
        job = self.dir / "quiet"
        result = processes.run([sys.executable, "-c", "print('nothing to declare')"],
                               timeout=20, job_dir=job, ready_marker=MARKER)
        self.assertIsNone(result["ready_seconds"])
        self.assertIsNone(read_json(job / "process.json")["ready_seconds"])

    def test_a_marker_printed_just_before_exit_is_still_seen(self):
        job = self.dir / "late"
        result = processes.run([sys.executable, "-c", child(delay=0.3, after=0.0)],
                               timeout=20, job_dir=job, ready_marker=MARKER)
        self.assertIsNotNone(result["ready_seconds"])

    def test_a_marker_on_an_unterminated_line_counts(self):
        code = f"import sys,time;time.sleep(0.3);sys.stdout.write({MARKER!r});sys.stdout.flush();time.sleep(0.4)"
        result = processes.run([sys.executable, "-c", code], timeout=20,
                               job_dir=self.dir / "partial", ready_marker=MARKER)
        self.assertIsNotNone(result["ready_seconds"])

    def test_a_run_without_a_marker_never_reads_the_log_while_it_waits(self):
        with patch("studio_tools.processes._scan_ready") as scan:
            result = processes.run([sys.executable, "-c", child()], timeout=20,
                                   job_dir=self.dir / "unwatched")
        scan.assert_not_called()
        self.assertIsNone(result["ready_seconds"])

    def test_a_watched_run_reads_no_more_often_than_four_times_a_second(self):
        self.assertEqual(processes.READY_POLL_SECONDS, 0.25)
        with patch("studio_tools.processes._scan_ready", side_effect=processes._scan_ready) as scan:
            processes.run([sys.executable, "-c", child(delay=0.4, after=0.4)], timeout=20,
                          job_dir=self.dir / "paced", ready_marker=MARKER)
        # Roughly 0.8 s of child life, plus the read after the child is reaped.
        self.assertLessEqual(scan.call_count, 8)

    def test_a_watched_run_still_times_out_and_is_cleaned_up(self):
        job = self.dir / "slow"
        with self.assertRaisesRegex(StudioError, "timed out"):
            processes.run([sys.executable, "-c", "import time;time.sleep(30)"],
                          timeout=1, job_dir=job, ready_marker=MARKER)
        record = read_json(job / "process.json")
        self.assertEqual(record["status"], "timed_out")
        self.assertEqual(record["cleanup"], "owned_tree_stopped")
        self.assertIsNone(record["ready_seconds"])

    def test_a_run_that_came_up_and_then_hung_keeps_its_load_time(self):
        job = self.dir / "hung"
        code = f"import time,sys;time.sleep(0.3);print({MARKER!r},flush=True);time.sleep(30)"
        with self.assertRaisesRegex(StudioError, "timed out"):
            processes.run([sys.executable, "-c", code], timeout=1,
                          job_dir=job, ready_marker=MARKER)
        record = read_json(job / "process.json")
        self.assertEqual(record["status"], "timed_out")
        self.assertEqual(record["cleanup"], "owned_tree_stopped")
        # The engine did come up; the timeout says what happened next, not that
        # the load never happened.
        self.assertIsNotNone(record["ready_seconds"])
        self.assertGreaterEqual(record["ready_seconds"], 0.3)

    def test_a_marker_spanning_a_line_break_is_refused(self):
        for bad in (MARKER + "\nREADY", MARKER + "\rREADY", "\n"):
            with self.subTest(marker=bad):
                with self.assertRaisesRegex(StudioError, "one line"):
                    processes.run([sys.executable, "-c", "pass"], timeout=5,
                                  job_dir=self.dir / f"line{len(bad)}{bad.strip()}",
                                  ready_marker=bad)

    def test_a_marker_without_anywhere_to_read_from_is_refused(self):
        with self.assertRaisesRegex(StudioError, "log file"):
            processes.run([sys.executable, "-c", "pass"], timeout=5, ready_marker=MARKER)
        for bad in ("", 7):
            with self.subTest(marker=bad), self.assertRaisesRegex(StudioError, "nonempty"):
                processes.run([sys.executable, "-c", "pass"], timeout=5,
                              job_dir=self.dir / f"bad{bad!r}", ready_marker=bad)


class Tick:
    """A monotonic clock this test advances by hand."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class ScriptedChild:
    """A child that times out for a while and records every timeout it was asked for."""

    def __init__(self, tick, waits=None):
        self.tick = tick
        self.waits = waits
        self.asked = []

    def wait(self, timeout=None):
        self.asked.append(timeout)
        self.tick.now += timeout
        if self.waits is None or len(self.asked) < self.waits:
            raise subprocess.TimeoutExpired(cmd=[], timeout=timeout)
        return 0


class ReadyClockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio ready clock ")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def log(self, text=""):
        path = self.dir / f"log{len(list(self.dir.iterdir()))}.log"
        path.write_bytes(text.encode("utf-8"))
        return path

    def test_watching_for_a_marker_never_shortens_the_granted_window(self):
        # The deadline is taken when the wait begins, exactly as an unwatched
        # `process.wait(timeout=...)` would take it, so a child that spent a
        # second being prepared is not charged for that second.
        tick = Tick(1000.0)
        child = ScriptedChild(tick)
        record = {"ready_seconds": None}
        with patch("studio_tools.processes.time.monotonic", tick):
            with self.assertRaises(subprocess.TimeoutExpired):
                processes._wait_for_marker(child, 1.0, self.log(), MARKER, 900.0, record)
        self.assertAlmostEqual(sum(child.asked), 1.0, places=6)
        self.assertEqual(tick.now, 1001.0)

    def test_the_marker_is_measured_from_the_spawn_instant(self):
        for spawned, expected in ((999.0, 1.25), (1000.0, 0.25)):
            with self.subTest(spawned=spawned):
                tick = Tick(1000.0)
                child = ScriptedChild(tick, waits=2)
                record = {"ready_seconds": None}
                with patch("studio_tools.processes.time.monotonic", tick):
                    processes._wait_for_marker(
                        child, 5.0, self.log(MARKER + "\n"), MARKER, spawned, record
                    )
                self.assertEqual(record["ready_seconds"], expected)

    def test_a_marker_written_in_the_last_moment_is_read_before_the_timeout(self):
        # The child printed it between the final poll and the deadline; the
        # scan at the deadline is the only chance to see it.
        tick = Tick(1000.0)
        child = ScriptedChild(tick)
        log = self.log()
        record = {"ready_seconds": None}

        def wait(timeout=None):
            child.asked.append(timeout)
            tick.now += timeout
            if len(child.asked) == 4:
                log.write_bytes((MARKER + "\n").encode("utf-8"))
            raise subprocess.TimeoutExpired(cmd=[], timeout=timeout)

        child.wait = wait
        with patch("studio_tools.processes.time.monotonic", tick):
            with self.assertRaises(subprocess.TimeoutExpired):
                processes._wait_for_marker(child, 1.0, log, MARKER, 1000.0, record)
        self.assertEqual(record["ready_seconds"], 1.0)


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio ready project ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        (self.root / "main.tscn").write_text("[gd_scene]\n", encoding="utf-8")
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 20})
        self.sha = sha256(sys.executable)

    def declare(self, marker):
        write_json(self.root / "project.json", {
            "schema_version": 1, "kind": "project", "project_id": "ready",
            "settings": {"ready_marker": marker},
        })

    def fake_child(self, code):
        def fake_run(args, **kwargs):
            self.last_kwargs = kwargs
            return processes.run([sys.executable, "-c", code], **kwargs)
        return fake_run


class LaunchReadyTests(ProjectCase):
    def test_a_declared_marker_reaches_the_runner_and_the_exit_receipt(self):
        self.declare(MARKER)
        with patch("studio_tools.launch.run", side_effect=self.fake_child(child())):
            result = launch.execute(self.config, self.root, sha256_expected=self.sha,
                                    mode="native", label="ready")
        self.assertEqual(self.last_kwargs["ready_marker"], MARKER)
        exit_record = read_json(self.root / "artifacts/launches/ready/exit.json")
        self.assertIsNotNone(exit_record["ready_seconds"])
        self.assertEqual(exit_record["ready_seconds"], result["ready_seconds"])
        self.assertGreaterEqual(exit_record["ready_seconds"], 0.4)
        self.assertIn(LIMIT, exit_record["limits"])

    def test_a_project_that_declares_nothing_gets_a_null_and_no_marker(self):
        for declared in (None, "absent"):
            with self.subTest(declared=declared):
                if declared == "absent":
                    (self.root / "project.json").unlink(missing_ok=True)
                else:
                    self.declare(None)
                with patch("studio_tools.launch.run", side_effect=self.fake_child(child())):
                    launch.execute(self.config, self.root, sha256_expected=self.sha,
                                   label="none" + str(declared))
                self.assertIsNone(self.last_kwargs["ready_marker"])
                record = read_json(self.root / f"artifacts/launches/none{declared}/exit.json")
                self.assertIsNone(record["ready_seconds"])

    def test_a_marker_that_is_not_a_line_substring_is_refused_before_a_label_exists(self):
        self.declare(["not", "a", "substring"])
        with patch("studio_tools.launch.run") as run:
            with self.assertRaisesRegex(StudioError, "ready_marker"):
                launch.execute(self.config, self.root, sha256_expected=self.sha, label="bad")
        run.assert_not_called()
        self.assertFalse((self.root / "artifacts/launches/bad").exists())

    def test_a_project_declaring_a_multiline_marker_is_refused(self):
        for bad in (MARKER + "\nREADY", MARKER + "\r\nREADY"):
            with self.subTest(marker=bad):
                self.declare(bad)
                with patch("studio_tools.launch.run") as run:
                    with self.assertRaisesRegex(StudioError, "one line"):
                        launch.execute(self.config, self.root,
                                       sha256_expected=self.sha, label="multiline")
                run.assert_not_called()
                self.assertFalse((self.root / "artifacts/launches/multiline").exists())

    def test_the_timing_never_becomes_an_acceptance_claim(self):
        self.declare(MARKER)
        with patch("studio_tools.launch.run", side_effect=self.fake_child(child(code=1))):
            result = launch.execute(self.config, self.root, sha256_expected=self.sha, label="failing")
        self.assertIsNotNone(result["ready_seconds"])
        self.assertFalse(result["ok"])
        self.assertIn(LIMIT, launch.LIMITS)

    def test_no_receipt_carries_an_argv_or_environment_value(self):
        self.declare(MARKER)
        code = (
            "import os,sys,time;print('private-arg');"
            "print(os.environ['STUDIO_READY_FIXTURE'],file=sys.stderr);"
            f"time.sleep(0.3);print({MARKER!r},flush=True)"
        )
        with patch.dict(os.environ, {"STUDIO_READY_FIXTURE": "private-env"}):
            with patch("studio_tools.launch.run", side_effect=self.fake_child(code)):
                launch.execute(self.config, self.root, sha256_expected=self.sha, label="private")
        run_dir = self.root / "artifacts/launches/private"
        for name in ("owned-launch.json", "exit.json", "process/process.json", "diagnostics.json"):
            with self.subTest(receipt=name):
                self.assertNotIn("private-", (run_dir / name).read_text(encoding="utf-8"))
        self.assertIn("private-arg", (run_dir / "process/stdout.log").read_text(encoding="utf-8"))
        self.assertIsNotNone(read_json(run_dir / "exit.json")["ready_seconds"])


class PlaytestReadyTests(ProjectCase):
    def test_a_driven_session_carries_the_same_marker_and_limit(self):
        self.declare(MARKER)
        harness = "res://tests/playtest.gd"
        with patch("studio_tools.playtest.run", side_effect=self.fake_child(child())):
            result = playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                      session="driven", script=harness, label="driven",
                                      emit_launcher=False, max_minutes=1)
        self.assertEqual(self.last_kwargs["ready_marker"], MARKER)
        record = read_json(self.root / "artifacts/playtests/driven/exit.json")
        self.assertEqual(record["ready_seconds"], result["ready_seconds"])
        self.assertIsNotNone(record["ready_seconds"])
        self.assertIn(LIMIT, record["limits"])
        self.assertEqual(record["acceptance"], "not_established")


if __name__ == "__main__":
    unittest.main()
