"""Interactive playtest sessions, collection and the emitted launcher (offline)."""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from unittest.mock import patch

from studio_tools import cli, playtest, processes
from studio_tools.common import StudioError, read_json, sha256, write_json
from studio_tools.config import load

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/studio-playtest/SKILL.md"
HARNESS = ROOT / "skills/studio-playtest/references/harness.md"
TEMPLATE = ROOT / "templates/playtest-harness.gd"
# Receipts, never the launcher: the launcher has to reproduce the command line.
RECEIPTS = ("playtest.json", "exit.json", "process/process.json", "diagnostics.json")
# check-package counts the manifest's own skills but cannot read prose, so the
# documents that tell an agent how many entrypoints exist are checked here.
NUMBER_WORDS = {10: "ten", 11: "eleven", 12: "twelve"}
CATALOG_DOCS = ("AGENTS.md", "README.md", "docs/agent-start.md", "docs/setup-windows.md",
                "docs/contributing.md", "references/tool-routing.md")
CATALOG_NOUN = r"(?:skills|entrypoints|folders)"


class PlaytestCase(unittest.TestCase):
    def setUp(self):
        # An attended session is deliberately never waited for, so the
        # interpreter's own warning about an unreaped child is the expected
        # outcome here rather than a leak worth reporting.
        warnings.simplefilter("ignore", ResourceWarning)
        self.addCleanup(warnings.resetwarnings)
        self.tmp = tempfile.TemporaryDirectory(prefix="studio playtest space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        (self.root / "main.tscn").write_text("[gd_scene]\n", encoding="utf-8")
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)
        self.host_config = Path(self.tmp.name) / "host.json"
        write_json(self.host_config, {"executables": {"godot": sys.executable}, "timeout": 5})

    def fake_child(self, code):
        """Stand in for the engine while still exercising the real runner."""
        def fake_run(args, **kwargs):
            self.last_args = args
            self.last_kwargs = kwargs
            return processes.run([sys.executable, "-c", code], **kwargs)
        return fake_run

    def fake_started(self, code):
        def fake_start(args, **kwargs):
            self.last_args = args
            self.last_kwargs = kwargs
            return processes.start([sys.executable, "-c", code], **kwargs)
        return fake_start

    def execute(self, code, **kwargs):
        with patch("studio_tools.playtest.run", side_effect=self.fake_child(code)):
            return playtest.execute(self.config, self.root, sha256_expected=self.sha, **kwargs)

    def attend(self, code, **kwargs):
        with patch("studio_tools.playtest.start", side_effect=self.fake_started(code)):
            return playtest.execute(
                self.config, self.root, sha256_expected=self.sha, session="attended", **kwargs
            )

    def settled(self, pid):
        """Wait for a started child to finish, where this host can observe it.

        `alive` answers None on a host that cannot tell; there is nothing to
        wait for there, and `collect` records the same uncertainty.
        """
        deadline = time.monotonic() + 30
        while processes.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.01)


class SessionTests(PlaytestCase):
    def test_handoff_blocks_and_writes_both_receipts_without_acceptance(self):
        result = self.execute("print('played')", label="first", scene="res://main.tscn")
        self.assertEqual(result["verdict"], "completed")
        self.assertTrue(result["ok"])
        # ok is run health; nothing here may promote a clean exit into acceptance.
        self.assertEqual(result["acceptance"], "not_established")
        self.assertIn("a playtest launch is not acceptance; a human verdict is required", result["limits"])
        self.assertEqual(self.last_kwargs["cwd"], str(self.root))
        run_dir = self.root / "artifacts/playtests/first"
        record = read_json(run_dir / "playtest.json")
        exit_record = read_json(run_dir / "exit.json")
        self.assertEqual(record["kind"], "playtest")
        self.assertEqual(record["session"], "handoff")
        self.assertEqual(record["status"], "launched")
        self.assertGreater(record["pid"], 0)
        self.assertEqual(record["resolution"], "1920x1080")
        self.assertEqual(record["rendering_method"], "forward_plus")
        self.assertEqual(record["scene_sha256"], sha256(self.root / "main.tscn"))
        self.assertEqual(record["engine"]["sha256_after_exit"], self.sha)
        self.assertEqual(exit_record["kind"], "playtest-exit")
        self.assertEqual(exit_record["acceptance"], "not_established")
        self.assertEqual(exit_record["status"], "completed")
        self.assertGreater(exit_record["combined_log_bytes"], 0)

    def test_engine_errors_and_missing_results_are_not_ok(self):
        errors = self.execute("print('SCRIPT ERROR: late')", label="errors")
        self.assertEqual(errors["verdict"], "engine_errors")
        self.assertFalse(errors["ok"])
        self.assertEqual(errors["acceptance"], "not_established")
        missing = self.execute(
            "print('played')", label="driven-miss", session="driven",
            script="res://tests/route.gd", max_minutes=5, results=["artifacts/route.json"],
        )
        self.assertEqual(missing["verdict"], "results_missing")
        self.assertFalse(missing["ok"])
        # A driven harness is judged by assertions and is still not acceptance.
        self.assertEqual(missing["acceptance"], "not_established")

    def test_receipts_hold_no_argv_or_environment_value(self):
        code = (
            "import os,sys;print('private-log');"
            "print(os.environ['STUDIO_JOB_FIXTURE'],file=sys.stderr)"
        )
        with patch.dict(os.environ, {"STUDIO_JOB_FIXTURE": "private-env"}):
            result = self.execute(
                code, label="quiet", scene="res://main.tscn",
                passthrough=["--", "private-passthrough"],
            )
        self.assertTrue(result["ok"])
        run_dir = self.root / "artifacts/playtests/quiet"
        # The separator is not one of the engine's own arguments.
        self.assertEqual(read_json(run_dir / "playtest.json")["passthrough_count"], 1)
        for name in RECEIPTS:
            text = (run_dir / name).read_text()
            self.assertNotIn("private-passthrough", text)
            self.assertNotIn("private-env", text)
        log = (run_dir / "process/stdout.log").read_text()
        self.assertIn("private-log", log)
        self.assertIn("private-env", log)
        # The launcher reproduces the command line, so it carries the
        # passthrough deliberately -- but never the environment.
        launcher = (run_dir / Path(result["launcher"]["path"]).name).read_text()
        self.assertIn("private-passthrough", launcher)
        self.assertNotIn("private-env", launcher)

    def test_attended_returns_and_exactly_one_collect_completes_it(self):
        result = self.attend("print('attended')", label="live")
        self.assertEqual(result["verdict"], "launched")
        self.assertEqual(result["status"], "launched")
        self.assertEqual(result["acceptance"], "not_established")
        self.assertGreater(result["pid"], 0)
        run_dir = self.root / "artifacts/playtests/live"
        self.assertFalse((run_dir / "exit.json").is_file())
        self.assertIn("polling", result["next"])
        self.settled(result["pid"])
        collected = playtest.collect(self.config, self.root, "live")
        self.assertEqual(collected["verdict"], "collected")
        self.assertTrue(collected["ok"])
        self.assertEqual(collected["acceptance"], "not_established")
        # Nobody waited for it, so there is no exit status to report.
        self.assertEqual(collected["status"], "unobserved")
        self.assertIsNone(collected["returncode"])
        self.assertIsNone(collected["elapsed_seconds"])
        self.assertTrue((run_dir / "exit.json").is_file())
        with self.assertRaisesRegex(StudioError, "already collected"):
            playtest.collect(self.config, self.root, "live")

    def test_attended_that_never_started_is_a_receipt_not_an_exception(self):
        with patch("studio_tools.playtest.start", side_effect=StudioError("Could not start python")):
            result = playtest.execute(
                self.config, self.root, sha256_expected=self.sha,
                session="attended", label="stillborn",
            )
        self.assertEqual(result["verdict"], "start_failed")
        self.assertFalse(result["ok"])
        run_dir = self.root / "artifacts/playtests/stillborn"
        self.assertEqual(read_json(run_dir / "playtest.json")["status"], "start_failed")
        # There is no session left to complete, so collect has nothing to add.
        with self.assertRaisesRegex(StudioError, "already collected"):
            playtest.collect(self.config, self.root, "stillborn")

    def test_attended_refuses_a_cap_it_could_not_enforce(self):
        with patch("studio_tools.playtest.start") as started:
            with self.assertRaisesRegex(StudioError, "cannot be capped"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                 session="attended", max_minutes=5, label="capped")
            started.assert_not_called()
        # The receipt records no cap, not even one a cutoff would have implied.
        result = self.attend("print('attended')", label="uncapped-by-default",
                             cutoff_utc=(datetime.now(timezone.utc) + timedelta(minutes=9)).isoformat())
        self.assertIsNone(result["max_minutes_effective"])
        self.assertIsNone(
            read_json(self.root / "artifacts/playtests/uncapped-by-default/playtest.json")["max_minutes_effective"]
        )
        self.settled(result["pid"])

    def test_driven_takes_its_scene_from_the_harness(self):
        with patch("studio_tools.playtest.run") as run:
            with self.assertRaisesRegex(StudioError, "scene from the harness"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha, session="driven",
                                 script="res://tests/route.gd", scene="res://main.tscn",
                                 max_minutes=5, label="two-scenes")
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts/playtests/two-scenes").exists())

    def test_collect_refuses_a_malformed_receipt_and_a_concurrent_claim(self):
        result = self.attend("print('attended')", label="partial")
        self.settled(result["pid"])
        record_path = self.root / "artifacts/playtests/partial/playtest.json"
        truncated = read_json(record_path)
        del truncated["engine"]
        write_json(record_path, truncated)
        # A receipt read back from disk is untrusted input, not a KeyError.
        with self.assertRaisesRegex(StudioError, "incomplete"):
            playtest.collect(self.config, self.root, "partial")
        second = self.attend("print('attended')", label="claimed")
        self.settled(second["pid"])
        (self.root / "artifacts/playtests/claimed/collect.lock").mkdir()
        with self.assertRaisesRegex(StudioError, "Another collect"):
            playtest.collect(self.config, self.root, "claimed")

    def test_collect_without_a_readable_engine_is_not_ok(self):
        result = self.attend("print('attended')", label="no-engine")
        self.settled(result["pid"])
        # An engine that cannot be re-read leaves the session's identity unverified.
        collected = playtest.collect(load(overrides={"timeout": 5}), self.root, "no-engine")
        self.assertEqual(collected["verdict"], "engine_unverified")
        self.assertFalse(collected["ok"])
        self.assertEqual(collected["acceptance"], "not_established")

    def test_collect_refuses_while_the_engine_still_runs_without_spending_it(self):
        result = self.attend("print('attended')", label="still-playing")
        self.settled(result["pid"])
        run_dir = self.root / "artifacts/playtests/still-playing"
        with patch("studio_tools.playtest.alive", return_value=True):
            with self.assertRaisesRegex(StudioError, "still running"):
                playtest.collect(self.config, self.root, "still-playing")
        # Nothing was consumed: no receipt, no lingering claim, so the real
        # collection can still happen once the player quits.
        self.assertFalse((run_dir / "exit.json").exists())
        self.assertFalse((run_dir / "collect.lock").exists())
        self.assertEqual(playtest.collect(self.config, self.root, "still-playing")["verdict"], "collected")

    def test_collect_refuses_a_session_it_does_not_complete(self):
        self.execute("print('played')", label="blocked")
        with self.assertRaisesRegex(StudioError, "completes an attended playtest"):
            playtest.collect(self.config, self.root, "blocked")
        with self.assertRaisesRegex(StudioError, "No playtest receipt"):
            playtest.collect(self.config, self.root, "never-started")

    def test_uncapped_session_needs_a_person_at_the_controls(self):
        result = self.execute("print('played')", label="uncapped", max_minutes=0)
        self.assertTrue(result["ok"])
        # No cap reaches the runner, and the receipt says so rather than
        # recording a ceiling that was never applied.
        self.assertIsNone(self.last_kwargs["timeout"])
        self.assertIsNone(read_json(self.root / "artifacts/playtests/uncapped/playtest.json")["max_minutes_effective"])
        attended = self.attend("print('attended')", label="uncapped-attended")
        self.assertEqual(attended["verdict"], "launched")
        self.settled(attended["pid"])
        with patch("studio_tools.playtest.run") as run:
            with self.assertRaisesRegex(StudioError, "must stay bounded"):
                playtest.execute(
                    self.config, self.root, sha256_expected=self.sha, session="driven",
                    script="res://tests/route.gd", max_minutes=0, label="unbounded-driven",
                )
            with self.assertRaisesRegex(StudioError, "must stay bounded"):
                playtest.execute(
                    self.config, self.root, sha256_expected=self.sha, session="driven",
                    script="res://tests/route.gd", max_minutes=90, label="too-long-driven",
                )
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts/playtests/unbounded-driven").exists())

    def test_bounded_session_caps_the_wait_in_minutes(self):
        self.execute("print('played')", label="bounded", session="driven",
                     script="res://tests/route.gd", max_minutes=2)
        self.assertEqual(self.last_kwargs["timeout"], 120.0)
        self.assertEqual(
            read_json(self.root / "artifacts/playtests/bounded/playtest.json")["max_minutes_effective"], 2.0
        )

    def test_script_belongs_to_driven_only(self):
        with patch("studio_tools.playtest.run") as run:
            with self.assertRaisesRegex(StudioError, "needs --script"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                 session="driven", label="no-script")
            for session in ("handoff", "attended"):
                with self.assertRaisesRegex(StudioError, "belongs to a driven playtest"):
                    playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                     session=session, script="res://tests/route.gd", label="scripted")
            with self.assertRaisesRegex(StudioError, "Unknown playtest session"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                 session="unattended", label="unknown")
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts").exists())

    def test_engine_sha_mismatch_refuses_before_launching(self):
        with patch("studio_tools.playtest.run") as run:
            with self.assertRaisesRegex(StudioError, "identity mismatch"):
                playtest.execute(self.config, self.root, sha256_expected="0" * 64, label="wrong")
            with self.assertRaisesRegex(StudioError, "64 hex characters"):
                playtest.execute(self.config, self.root, sha256_expected="abc", label="short")
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts").exists())

    def test_profile_choice_is_recorded_either_way(self):
        self.execute("print('played')", label="isolated")
        isolated = read_json(self.root / "artifacts/playtests/isolated/playtest.json")
        self.assertEqual(isolated["profile"], "isolated")
        environment = self.last_kwargs["env"]
        for key in playtest.PROFILE_KEYS:
            self.assertEqual(Path(environment[key]), (self.root / "artifacts/playtests/isolated/profile").resolve())
        self.execute("print('played')", label="host-profile", use_host_profile=True)
        hosted = read_json(self.root / "artifacts/playtests/host-profile/playtest.json")
        self.assertEqual(hosted["profile"], "host")
        # A host-profile session leaves the player's real profile alone.
        self.assertFalse((self.root / "artifacts/playtests/host-profile/profile").exists())
        for key in playtest.PROFILE_KEYS:
            self.assertEqual(self.last_kwargs["env"].get(key), os.environ.get(key))

    def test_label_collision_and_contained_results_are_refused(self):
        self.execute("print('played')", label="same")
        with patch("studio_tools.playtest.run") as run:
            with self.assertRaisesRegex(StudioError, "directory exists; choose a new label"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha, label="same")
            # A receipt this launcher writes must never count as engine output.
            with self.assertRaisesRegex(StudioError, "must not be files this playtest writes"):
                playtest.execute(
                    self.config, self.root, sha256_expected=self.sha, session="driven",
                    script="res://tests/route.gd", max_minutes=5, label="owned",
                    results=["artifacts/playtests/owned/exit.json"],
                )
            with self.assertRaisesRegex(StudioError, "res:// path"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                 scene="main.tscn", label="bad-scene")
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts/playtests/owned").exists())

    def test_cutoff_already_passed_does_not_start_the_game(self):
        with patch("studio_tools.playtest.run") as run:
            result = playtest.execute(
                self.config, self.root, sha256_expected=self.sha,
                cutoff_utc="2000-01-01T00:00:00Z", label="late",
            )
            run.assert_not_called()
        self.assertEqual(result["verdict"], "cutoff_passed")
        self.assertFalse(result["ok"])
        self.assertEqual(read_json(self.root / "artifacts/playtests/late/playtest.json")["status"], "refused")

    def test_cutoff_bounds_an_otherwise_uncapped_session(self):
        cutoff = (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()
        self.execute("print('played')", label="windowed", max_minutes=0, cutoff_utc=cutoff)
        self.assertLessEqual(self.last_kwargs["timeout"], 3)
        self.assertGreater(self.last_kwargs["timeout"], 0)

    def test_missing_project_and_godot_project_file_are_refused(self):
        with self.assertRaisesRegex(StudioError, "existing game project directory"):
            playtest.execute(self.config, self.root / "absent", sha256_expected=self.sha)
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(StudioError, "project.godot is missing"):
            playtest.execute(self.config, empty, sha256_expected=self.sha)


class DisplaySettingsTests(PlaytestCase):
    """A playtest shows the game as configured, not as the kit prefers it."""

    def declare(self, body):
        (self.root / "project.godot").write_text(body, encoding="utf-8")

    def test_project_renderer_and_size_are_used_rather_than_the_pinned_default(self):
        self.declare(
            'config_version=5\n\n[application]\n\nconfig/name="Fixture"\n\n'
            '[display]\n\nwindow/size/viewport_width=1280\n'
            'window/size/viewport_height=720\n\n'
            '[rendering]\n\nrenderer/rendering_method="gl_compatibility"\n'
            'renderer/rendering_method.mobile="mobile"\n'
        )
        self.execute("print('played')", label="declared")
        self.assertIn("gl_compatibility", self.last_args)
        self.assertIn("1280x720", self.last_args)
        record = read_json(self.root / "artifacts/playtests/declared/playtest.json")
        self.assertEqual(record["rendering_method"], "gl_compatibility")
        self.assertEqual(record["rendering_method_source"], "project")
        self.assertEqual(record["resolution"], "1280x720")
        self.assertEqual(record["resolution_source"], "project")

    def test_a_platform_override_key_is_not_read_as_the_base_setting(self):
        self.declare('[rendering]\n\nrenderer/rendering_method.mobile="mobile"\n')
        self.execute("print('played')", label="mobile-only")
        record = read_json(self.root / "artifacts/playtests/mobile-only/playtest.json")
        self.assertEqual(record["rendering_method"], "forward_plus")
        self.assertEqual(record["rendering_method_source"], "default")

    def test_a_project_that_declares_nothing_falls_back_and_says_so(self):
        self.execute("print('played')", label="silent")
        record = read_json(self.root / "artifacts/playtests/silent/playtest.json")
        self.assertEqual(record["rendering_method"], "forward_plus")
        self.assertEqual(record["resolution"], "1920x1080")
        self.assertEqual(record["rendering_method_source"], "default")
        self.assertEqual(record["resolution_source"], "default")

    def test_explicit_flags_override_the_project_and_are_recorded_as_override(self):
        self.declare('[rendering]\n\nrenderer/rendering_method="gl_compatibility"\n')
        self.execute("print('played')", label="forced",
                     rendering_method="mobile", resolution="800x600")
        record = read_json(self.root / "artifacts/playtests/forced/playtest.json")
        self.assertEqual(record["rendering_method"], "mobile")
        self.assertEqual(record["rendering_method_source"], "override")
        self.assertEqual(record["resolution"], "800x600")
        self.assertEqual(record["resolution_source"], "override")
        with patch("studio_tools.playtest.run") as run:
            with self.assertRaisesRegex(StudioError, "Rendering method must be"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                 rendering_method="raytraced", label="bad-renderer")
            with self.assertRaisesRegex(StudioError, "WIDTHxHEIGHT"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                 resolution="huge", label="bad-size")
            run.assert_not_called()


class DrivenHarnessReportTests(PlaytestCase):
    """The kit supplies the report path so it cannot disagree with the receipt."""

    def driven(self, code, **kwargs):
        """Run a driven session with the supplied report path reaching the child.

        The ordinary stand-in replaces the whole argument array, so it would
        never see the argument this test is about.
        """
        def forwarding(args, **called):
            self.last_args = args
            self.last_kwargs = called
            supplied = [a for a in args if a.startswith("--studio-playtest=")]
            return processes.run([sys.executable, "-c", code] + supplied, **called)
        with patch("studio_tools.playtest.run", side_effect=forwarding):
            return playtest.execute(
                self.config, self.root, sha256_expected=self.sha, session="driven",
                script="res://tests/route.gd", max_minutes=5, **kwargs
            )

    def write_report(self, ok):
        # The stand-in engine writes where the kit told the harness to write.
        return (
            "import json,sys;"
            "p=[a for a in sys.argv if a.startswith('--studio-playtest=')][0].split('=',1)[1];"
            f"open(p,'w').write(json.dumps({{'kind':'playtest_harness_route','ok':{ok}}}))"
        )

    def test_kit_supplies_the_path_and_reads_the_report_back(self):
        result = self.driven(self.write_report(True), label="reported")
        self.assertEqual(result["verdict"], "completed")
        self.assertTrue(result["ok"])
        self.assertEqual(result["acceptance"], "not_established")
        supplied = [a for a in self.last_args if a.startswith("--studio-playtest=")]
        self.assertEqual(len(supplied), 1)
        run_dir = self.root / "artifacts/playtests/reported"
        self.assertEqual(supplied[0].split("=", 1)[1], str((run_dir / "harness.json").resolve()))
        # The separator has to reach the engine for user args to be visible.
        self.assertIn("--", self.last_args)
        self.assertEqual(
            read_json(run_dir / "playtest.json")["harness_report"],
            "artifacts/playtests/reported/harness.json",
        )
        self.assertEqual(result["harness_report"]["sha256"], sha256(run_dir / "harness.json"))

    def test_a_failing_or_absent_report_is_not_a_completed_run(self):
        failed = self.driven(self.write_report(False), label="route-failed")
        self.assertEqual(failed["verdict"], "harness_failed")
        self.assertFalse(failed["ok"])
        missing = self.driven("print('wrote nothing')", label="route-silent")
        self.assertEqual(missing["verdict"], "harness_report_missing")
        self.assertFalse(missing["ok"])
        self.assertIsNone(missing["harness_report"])
        unreadable = self.driven(
            "import sys;p=[a for a in sys.argv if a.startswith('--studio-playtest=')][0]"
            ".split('=',1)[1];open(p,'w').write('not json')", label="route-garbled")
        self.assertEqual(unreadable["verdict"], "harness_report_unreadable")

    def test_a_hand_passed_report_path_is_refused(self):
        with patch("studio_tools.playtest.run") as run:
            with self.assertRaisesRegex(StudioError, "remove it from the passthrough"):
                playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                 session="driven", script="res://tests/route.gd",
                                 max_minutes=5, label="two-paths",
                                 passthrough=["--", "--studio-playtest=/tmp/elsewhere.json"])
            run.assert_not_called()
        self.assertFalse((self.root / "artifacts/playtests/two-paths").exists())

    def test_a_human_session_is_told_no_report_path(self):
        self.execute("print('played')", label="no-harness")
        self.assertFalse(any(a.startswith("--studio-playtest=") for a in self.last_args))
        self.assertIsNone(read_json(self.root / "artifacts/playtests/no-harness/playtest.json")["harness_report"])


class LauncherTests(PlaytestCase):
    def test_launcher_is_runnable_and_names_the_session_it_documents(self):
        result = self.execute("print('played')", label="relaunch", scene="res://main.tscn")
        run_dir = self.root / "artifacts/playtests/relaunch"
        name = "relaunch.cmd" if playtest.IS_WINDOWS else "relaunch.sh"
        path = run_dir / name
        self.assertTrue(path.is_file())
        self.assertEqual(result["launcher"]["path"], f"artifacts/playtests/{'relaunch'}/{name}")
        self.assertEqual(result["launcher"]["sha256"], sha256(path))
        text = path.read_text()
        self.assertIn(str(Path(sys.executable).resolve()), text)
        self.assertIn("res://main.tscn", text)
        self.assertIn("--rendering-method forward_plus", text)
        self.assertIn(self.sha, text)
        self.assertIn("relaunch", text)
        # It must say which profile the recorded session used, because it
        # cannot recreate an isolated one.
        self.assertIn("profile: isolated", text)
        self.assertIn("accepted by a person", text)
        for key in playtest.PROFILE_KEYS:
            self.assertNotIn(key, text)

    def test_windows_launcher_escapes_percent_expansion(self):
        # cmd.exe expands %NAME% even inside quotes, so an unescaped launcher
        # would run a different argument than the session did.
        self.assertEqual(playtest._cmd_quote("%APPDATA%"), '"%%APPDATA%%"')
        self.assertEqual(playtest._cmd_quote("res://main.tscn"), "res://main.tscn")
        with self.assertRaisesRegex(StudioError, "quotation mark"):
            playtest._cmd_quote('say"what')

    def test_windows_launcher_is_emitted_through_the_real_path(self):
        """Exercise the .cmd branch end to end, not just its quoting helper.

        On this host `_launcher` takes the shlex branch, so `_cmd_quote` is
        reached only by the test above. If the Windows branch stopped calling
        it, every other assertion here would still pass.
        """
        with patch("studio_tools.playtest.IS_WINDOWS", True):
            result = self.execute("print('played')", label="windows-launcher",
                                  scene="res://main.tscn", passthrough=["--", "%REGION%"])
        path = self.root / "artifacts/playtests/windows-launcher/relaunch.cmd"
        self.assertTrue(path.is_file())
        self.assertEqual(result["launcher"]["path"], "artifacts/playtests/windows-launcher/relaunch.cmd")
        text = path.read_text()
        self.assertTrue(text.startswith("@echo off"))
        self.assertIn('"%%REGION%%"', text)
        self.assertIn("REM label: windows-launcher", text)
        self.assertIn("res://main.tscn", text)
        for key in playtest.PROFILE_KEYS:
            self.assertNotIn(key, text)

    def test_no_launcher_leaves_none_behind(self):
        result = self.execute("print('played')", label="bare", emit_launcher=False)
        run_dir = self.root / "artifacts/playtests/bare"
        self.assertIsNone(result["launcher"])
        self.assertIsNone(read_json(run_dir / "playtest.json")["launcher"])
        self.assertEqual(sorted(p.name for p in run_dir.glob("relaunch.*")), [])


class PlaytestCommandTests(PlaytestCase):
    def test_cli_start_and_collect_round_trip(self):
        with patch("studio_tools.playtest.start", side_effect=self.fake_started("print('cli attended')")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = cli.main([
                    "playtest", "start", "--project", str(self.root), "--config", str(self.host_config),
                    "--sha256", self.sha, "--session", "attended", "--label", "cli",
                ])
        self.assertEqual(code, 0)
        started = json.loads(out.getvalue())
        self.assertEqual(started["verdict"], "launched")
        self.settled(started["pid"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main([
                "playtest", "collect", "--project", str(self.root),
                "--config", str(self.host_config), "--label", "cli",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["verdict"], "collected")

    def test_cli_passes_the_separator_to_the_engine(self):
        with patch("studio_tools.playtest.run", side_effect=self.fake_child("print('played')")):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main([
                    "playtest", "start", "--project", str(self.root), "--config", str(self.host_config),
                    "--sha256", self.sha, "--label", "through", "--scene", "res://main.tscn",
                    "--", "--regional-site", "coast",
                ])
        self.assertEqual(code, 0)
        self.assertEqual(self.last_args[-3:], ["--", "--regional-site", "coast"])
        self.assertEqual(read_json(self.root / "artifacts/playtests/through/playtest.json")["passthrough_count"], 2)

    def test_cli_flags_reach_the_session_they_name(self):
        """Every new flag through cli.main, not just through execute().

        --no-launcher is inverted on the way through (emit_launcher=not ...),
        which is the kind of wiring that fails silently when only the function
        underneath is tested.
        """
        with patch("studio_tools.playtest.run", side_effect=self.fake_child("print('played')")):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main([
                    "playtest", "start", "--project", str(self.root), "--config", str(self.host_config),
                    "--sha256", self.sha, "--label", "flags", "--rendering-method", "gl_compatibility",
                    "--resolution", "800x600", "--use-host-profile", "--no-launcher",
                ])
        self.assertEqual(code, 0)
        record = read_json(self.root / "artifacts/playtests/flags/playtest.json")
        self.assertEqual(record["rendering_method"], "gl_compatibility")
        self.assertEqual(record["rendering_method_source"], "override")
        self.assertEqual(record["resolution"], "800x600")
        self.assertEqual(record["resolution_source"], "override")
        self.assertEqual(record["profile"], "host")
        self.assertIsNone(record["launcher"])
        self.assertEqual(sorted((self.root / "artifacts/playtests/flags").glob("relaunch.*")), [])
        self.assertIn("gl_compatibility", self.last_args)
        self.assertIn("800x600", self.last_args)

    def test_cli_reports_a_refusal_without_a_traceback(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main([
                "playtest", "start", "--project", str(self.root), "--config", str(self.host_config),
                "--sha256", "0" * 64, "--label", "refused",
            ])
        self.assertEqual(code, 1)
        reported = json.loads(err.getvalue())
        self.assertFalse(reported["ok"])
        self.assertIn("identity mismatch", reported["error"])


class WindowsLivenessTests(unittest.TestCase):
    """`alive` on Windows, which has no /proc to read."""

    def answer(self, **kwargs):
        completed = subprocess.CompletedProcess(args=[], **kwargs)
        with patch("studio_tools.processes.shutil.which", return_value="pwsh"), \
             patch("studio_tools.processes.subprocess.run", return_value=completed) as run:
            return processes._windows_alive(4321), run

    def test_windows_liveness_reads_the_same_process_table_as_the_descendant_walk(self):
        running, run = self.answer(returncode=0, stdout="1\n")
        self.assertIs(running, True)
        self.assertIn("ProcessId=4321", run.call_args.args[0][-1])
        self.assertIn("Win32_Process", run.call_args.args[0][-1])
        self.assertIs(self.answer(returncode=0, stdout="0\n")[0], False)

    def test_windows_liveness_answers_unknown_rather_than_guessing(self):
        # An unreadable process table must not be reported as "not running".
        self.assertIsNone(self.answer(returncode=1, stdout="")[0])
        self.assertIsNone(self.answer(returncode=0, stdout="not a number")[0])
        with patch("studio_tools.processes.shutil.which", return_value=None):
            self.assertIsNone(processes._windows_alive(4321))
        with patch("studio_tools.processes.shutil.which", return_value="pwsh"), \
             patch("studio_tools.processes.subprocess.run", side_effect=OSError):
            self.assertIsNone(processes._windows_alive(4321))

    def test_alive_actually_dispatches_to_the_windows_probe(self):
        # The probe existing is not the same as alive calling it: unwired, every
        # Windows PID reports unknown and a running session collects as clean.
        with patch("studio_tools.processes.os.name", "nt"), \
             patch("studio_tools.processes._windows_alive", return_value=True) as probe:
            self.assertIs(processes.alive(4321), True)
        probe.assert_called_once_with(4321)

    def test_alive_rejects_a_pid_that_is_not_one(self):
        for value in (None, 0, -1, True, "4321"):
            self.assertIsNone(processes.alive(value))


class PlaytestDocumentationTests(unittest.TestCase):
    """The skill and template are shipped files; check what they promise."""

    def test_skill_names_the_commands_it_routes_to(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        self.assertTrue(re.search(r"^name: studio-playtest$", skill, re.M))
        self.assertTrue(re.search(r"^description: .+", skill, re.M))
        for fragment in ("--session", "handoff", "attended", "driven",
                         "playtest collect --label", "--use-host-profile", "--max-minutes 0"):
            self.assertIn(fragment, skill)
        # It routes to the verdict rather than issuing one.
        self.assertIn("studio-review", skill)
        self.assertIn("not_established", skill)
        self.assertIn("polling", skill)

    def test_harness_reference_keeps_both_rules(self):
        harness = HARNESS.read_text(encoding="utf-8")
        self.assertIn("Drive the game's real input path", harness)
        self.assertIn("Never fork the movement policy", harness)
        self.assertIn("retirement condition", harness)
        self.assertIn("Wiring, and only wiring.", harness)
        self.assertIn("playtest start --project <GAME>", harness)

    def test_template_is_a_scene_tree_runner_with_both_rules(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("extends SceneTree", template)
        self.assertIn("Drive the game's real input path", template)
        self.assertIn("Never fork the movement policy", template)
        for fragment in ("Input.action_press", "Input.action_release", "InputMap.has_action",
                         "Engine.get_physics_frames()", "Time.get_ticks_usec()", "MAX_SECONDS"):
            self.assertIn(fragment, template)
        # Injected input never claims the dimensions it cannot establish.
        for declared in ("ordinary_input_review", "visual_review", "listening"):
            self.assertIn(declared, template)
        # Step state is per step. Deriving it from the currently held action
        # makes a released step fire again on the next frame, so the declared
        # route would loop instead of running once.
        self.assertIn('state["pressed"]', template)
        self.assertIn('state["released"]', template)
        self.assertNotIn("_held", template)
        # A failed assertion has to reach the kit through the log and the exit
        # code, which is what playtest reads; the report file alone would be
        # recorded as a clean completed run.
        self.assertIn("push_error(\"Playtest harness assertions failed", template)
        self.assertIn("quit(1)", template)
        # A ceiling reached mid-route must fail rather than report a passing
        # experiment that never ran its declared route.
        self.assertIn('checks["route_completed"] = _route_complete()', template)
        # Actions reach a game that polls them and a game that reads them as
        # events; driving only the first misreports an event-driven game.
        self.assertIn("Input.parse_input_event(event)", template)
        self.assertIn("InputEventAction.new()", template)

    def test_catalog_count_agrees_with_the_manifest_everywhere(self):
        count = len(read_json(ROOT / "studio-kit.json")["skills"])
        self.assertIn(f"!= {count}", (ROOT / "studio_tools/package.py").read_text(encoding="utf-8"))
        for name in CATALOG_DOCS:
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertRegex(
                text, rf"(?i)\b{NUMBER_WORDS[count]}\b[^.]{{0,40}}?{CATALOG_NOUN}\b",
                f"{name} does not state the shipped catalog size",
            )
            for number, word in NUMBER_WORDS.items():
                if number != count:
                    self.assertNotRegex(
                        text, rf"(?i)\b{word}\b[^.]{{0,40}}?{CATALOG_NOUN}\b",
                        f"{name} still claims {word} entrypoints",
                    )

    def test_plugin_manifest_tracks_the_package_version_and_names_playtesting(self):
        plugin = read_json(ROOT / ".codex-plugin/plugin.json")
        manifest = read_json(ROOT / "studio-kit.json")
        # A marketplace that caches by version would otherwise keep serving a
        # build without the eleventh skill.
        self.assertEqual(plugin["version"], manifest["version"])
        self.assertNotEqual(plugin["version"], "0.1.1")
        self.assertIn("playtesting", plugin["description"])
        self.assertEqual(plugin["skills"], "./skills/")

    def test_shipped_playtest_files_carry_no_host_specific_path(self):
        # A skill that names one host's directories cannot be installed on another.
        host_specific = re.compile(r"[A-Za-z]:\\\\?Users|/home/[a-z]|/Users/[A-Za-z]|/mnt/[a-z]/")
        for path in (SKILL, HARNESS, TEMPLATE):
            found = host_specific.search(path.read_text(encoding="utf-8"))
            self.assertIsNone(found, f"{path.name} names a host-specific path: {found}")


if __name__ == "__main__":
    unittest.main()
