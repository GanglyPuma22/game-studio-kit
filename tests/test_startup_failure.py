"""A game that never started, told apart from one that failed while playing (offline).

`sys.executable` stands in for Godot; the engine log is whatever the stand-in
prints. Nothing here consults elapsed time: a slow host is not a startup
failure, and a fast one is not proof the game came up.
"""

import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import launch, playtest, processes
from studio_tools.adapters.godot import FIRST_ERROR_LIMIT, classify_log
from studio_tools.common import read_json, sha256, write_json
from studio_tools.config import load

PARSE_ERROR = (
    "SCRIPT ERROR: Parse Error: Identifier \\\"missing\\\" not declared in the current scope.\\n"
    "   at: GDScript::reload (res://main.gd:3)"
)
RUNTIME_ERROR = (
    "SCRIPT ERROR: Invalid access to property or key 'x' on a base object of type 'Nil'.\\n"
    "   at: _ready (res://main.gd:12)"
)


class ClassifierTests(unittest.TestCase):
    def test_load_signatures_are_reported_as_the_load_phase(self):
        for line in (
            "SCRIPT ERROR: Parse Error: something",
            "ERROR: Failed to load script res://main.gd with error 'Parse error'",
            "ERROR: Failed loading resource: res://main.tscn",
            "ERROR: Cannot open file 'res://main.tscn'",
            "ERROR: Could not load the project settings",
            "ERROR: Failed to instantiate scene res://main.tscn",
            "ERROR: Unable to load addon script",
            "ERROR: res://main.gd:1: Error parsing this file",
        ):
            with self.subTest(line=line):
                result = classify_log(line + "\n")
                self.assertEqual(result["phase"], "load")
                self.assertEqual(result["first_error"], line)

    def test_a_runtime_callback_is_reported_as_the_runtime_phase(self):
        result = classify_log(RUNTIME_ERROR + "\n")
        self.assertEqual(result["phase"], "runtime")
        self.assertIn("Invalid access", result["first_error"])

    def test_a_load_error_that_names_a_running_callback_is_runtime(self):
        # A resource the game failed to load from inside _process is a runtime
        # fault, whatever the wording of the message.
        log = "ERROR: Failed loading resource: res://late.tscn\n   at: _process (res://main.gd:40)\n"
        self.assertEqual(classify_log(log)["phase"], "runtime")

    def test_only_the_first_error_decides_the_phase(self):
        both = RUNTIME_ERROR + "\n" + "ERROR: Failed loading resource: res://late.tscn\n"
        self.assertEqual(classify_log(both)["phase"], "runtime")
        reversed_order = "ERROR: Could not load res://main.tscn\n" + RUNTIME_ERROR + "\n"
        self.assertEqual(classify_log(reversed_order)["phase"], "load")

    def test_no_error_means_no_phase_and_no_first_error(self):
        for text in ("", " \n", "scene complete\n", "WARNING: slow\n"):
            with self.subTest(text=text):
                result = classify_log(text)
                self.assertIsNone(result["phase"])
                self.assertIsNone(result["first_error"])

    def test_the_first_error_is_stripped_of_escapes_and_truncated(self):
        long = "ERROR: " + "detail " * 100
        result = classify_log("\x1b[31m" + long + "\x1b[0m\n")
        self.assertNotIn("\x1b", result["first_error"])
        self.assertEqual(len(result["first_error"]), FIRST_ERROR_LIMIT)
        self.assertTrue(result["first_error"].startswith("ERROR: detail"))

    def test_the_original_counts_and_status_are_unchanged(self):
        result = classify_log("WARNING: first\nOrphan StringName: X\n ERROR: late\n")
        self.assertEqual(result["status"], "errors")
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["warning_count"], 2)


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio startup space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        (self.root / "main.tscn").write_text("[gd_scene]\n", encoding="utf-8")
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)

    def fake_child(self, code):
        def fake_run(args, **kwargs):
            return processes.run([sys.executable, "-c", code], **kwargs)
        return fake_run

    def child(self, message, code=1):
        return f"import sys;print({message!r});sys.exit({code})"


class LaunchVerdictTests(LaunchCase):
    def execute(self, code, **kwargs):
        with patch("studio_tools.launch.run", side_effect=self.fake_child(code)):
            return launch.execute(self.config, self.root, sha256_expected=self.sha, **kwargs)

    def test_a_load_error_with_a_nonzero_exit_is_a_startup_failure(self):
        result = self.execute(self.child(PARSE_ERROR), label="load")
        self.assertEqual(result["verdict"], "startup_failure")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["diagnostics"]["phase"], "load")
        self.assertIn("Parse Error", result["diagnostics"]["first_error"])
        exit_record = read_json(self.root / "artifacts/launches/load/exit.json")
        self.assertEqual(exit_record["verdict"], "startup_failure")
        self.assertEqual(exit_record["diagnostics"]["phase"], "load")

    def test_a_runtime_error_with_a_nonzero_exit_is_not_a_startup_failure(self):
        result = self.execute(self.child(RUNTIME_ERROR), label="runtime")
        self.assertEqual(result["verdict"], "failed")
        self.assertEqual(result["diagnostics"]["phase"], "runtime")

    def test_a_load_error_that_still_exits_zero_stays_engine_errors(self):
        result = self.execute(self.child(PARSE_ERROR, code=0), label="zero")
        self.assertEqual(result["verdict"], "engine_errors")
        self.assertEqual(result["diagnostics"]["phase"], "load")

    def test_a_timeout_is_still_a_timeout_however_the_log_reads(self):
        code = f"import sys,time;print({PARSE_ERROR!r},flush=True);time.sleep(30)"
        with patch("studio_tools.launch.run", side_effect=self.fake_child(code)):
            result = launch.execute(self.config, self.root, sha256_expected=self.sha,
                                    label="slow", timeout=1)
        self.assertEqual(result["verdict"], "timed_out")
        self.assertEqual(result["diagnostics"]["phase"], "load")


class PlaytestVerdictTests(LaunchCase):
    def playtest(self, code, **kwargs):
        with patch("studio_tools.playtest.run", side_effect=self.fake_child(code)):
            return playtest.execute(self.config, self.root, sha256_expected=self.sha,
                                    emit_launcher=False, **kwargs)

    def test_a_session_that_never_reached_the_game_is_a_startup_failure(self):
        result = self.playtest(self.child(PARSE_ERROR), label="load", session="handoff")
        self.assertEqual(result["verdict"], "startup_failure")
        self.assertFalse(result["ok"])
        self.assertEqual(result["acceptance"], "not_established")
        self.assertEqual(result["diagnostics"]["phase"], "load")

    def test_a_runtime_fault_keeps_the_process_status_as_its_verdict(self):
        result = self.playtest(self.child(RUNTIME_ERROR), label="runtime", session="handoff")
        self.assertEqual(result["verdict"], "failed")
        self.assertEqual(result["diagnostics"]["phase"], "runtime")


if __name__ == "__main__":
    unittest.main()
