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
from studio_tools.adapters.godot import (
    FIRST_ERROR_LIMIT, UNRECOGNIZED, classify_log, error_signature,
)
from studio_tools.common import read_json, sha256, write_json
from studio_tools.config import load

# Real two-line logs: the message, then the frame Godot prints under it. The
# newline is written as a joined literal so a fixture can never quietly become
# one line and stop exercising the continuation rule at all.
PARSE_ERROR = "\n".join([
    'SCRIPT ERROR: Parse Error: Identifier "missing" not declared in the current scope.',
    "   at: GDScript::reload (modules/gdscript/gdscript.cpp:2831)",
])
RUNTIME_ERROR = "\n".join([
    "SCRIPT ERROR: Invalid get index 'x' (on base: 'Nil').",
    "   at: _ready (res://main.gd:12)",
])


class ClassifierTests(unittest.TestCase):
    def test_the_fixtures_are_the_two_line_logs_they_claim_to_be(self):
        for fixture in (PARSE_ERROR, RUNTIME_ERROR):
            with self.subTest(fixture=fixture.splitlines()[0]):
                self.assertEqual(len(fixture.splitlines()), 2)
                self.assertTrue(fixture.splitlines()[1].strip().startswith("at:"))

    def test_load_signatures_are_reported_as_the_load_phase(self):
        for line, signature in (
            ("SCRIPT ERROR: Parse Error: something", "SCRIPT ERROR: Parse Error"),
            ("ERROR: Failed to load script res://main.gd with error 'Parse error'",
             "ERROR: Failed to load script res://main.gd"),
            ("ERROR: Failed loading resource: res://main.tscn",
             "ERROR: Failed loading resource res://main.tscn"),
            ("ERROR: Cannot open file 'res://main.tscn'",
             "ERROR: Cannot open file res://main.tscn"),
            ("ERROR: Could not load the project settings", "ERROR: Could not load"),
            ("ERROR: Failed to instantiate scene res://main.tscn",
             "ERROR: Failed to instantiate scene res://main.tscn"),
            ("ERROR: Unable to load addon script", "ERROR: Unable to load"),
            ("ERROR: res://main.gd:1: Error parsing this file",
             "ERROR: " + UNRECOGNIZED + " res://main.gd:1"),
        ):
            with self.subTest(line=line):
                result = classify_log(line + "\n")
                self.assertEqual(result["phase"], "load")
                self.assertEqual(result["first_error"], signature)

    def test_a_runtime_callback_is_reported_as_the_runtime_phase(self):
        result = classify_log(RUNTIME_ERROR + "\n")
        self.assertEqual(result["phase"], "runtime")
        self.assertEqual(result["first_error"], "SCRIPT ERROR: Invalid get index")

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

    def test_terminal_escapes_never_reach_the_signature(self):
        result = classify_log("\x1b[31mSCRIPT ERROR: Parse Error: broken\x1b[0m\n")
        self.assertNotIn("\x1b", result["first_error"])
        self.assertEqual(result["first_error"], "SCRIPT ERROR: Parse Error")

    def test_any_project_frame_means_the_game_was_executing(self):
        # The frame's function name is not an allowlist: a handler a project
        # named itself is the game running just as much as _process is.
        for function in ("_on_button_pressed", "_unhandled_input", "spawn_wave", "_process"):
            with self.subTest(function=function):
                log = ("ERROR: Failed loading resource: res://wave.tscn\n"
                       f"   at: {function} (res://arena.gd:88)\n")
                self.assertEqual(classify_log(log)["phase"], "runtime")

    def test_an_engine_frame_under_a_load_signature_stays_load(self):
        for frame in (
            "   at: GDScript::reload (modules/gdscript/gdscript.cpp:2831)\n",
            "   at: ResourceLoader::_load (core/io/resource_loader.cpp:283)\n",
            "   at: load_source_code (core/object/script_language.h:104)\n",
            "",
        ):
            with self.subTest(frame=frame):
                log = "SCRIPT ERROR: Parse Error: Identifier not declared\n" + frame
                self.assertEqual(classify_log(log)["phase"], "load")

    def test_a_frame_in_neither_form_does_not_prove_the_game_ran(self):
        log = "ERROR: Could not load res://main.tscn\n   at: somewhere\n"
        self.assertEqual(classify_log(log)["phase"], "load")

    def test_the_original_counts_and_status_are_unchanged(self):
        result = classify_log("WARNING: first\nOrphan StringName: X\n ERROR: late\n")
        self.assertEqual(result["status"], "errors")
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["warning_count"], 2)


class SignatureTests(unittest.TestCase):
    """The signature is rebuilt from an allowlist, so only three pieces survive."""

    def test_only_the_prefix_category_and_resource_survive(self):
        line = (
            "ERROR: Failed to load script res://ui/menu.gd:41 from "
            "C:\\Users\\someone\\projects\\game\\ui\\menu.gd and "
            "https://cdn.example.com/build/patch.pck and /home/someone/.keys/id"
        )
        self.assertEqual(error_signature(line),
                         "ERROR: Failed to load script res://ui/menu.gd:41")

    def test_a_token_and_an_address_in_the_message_do_not_survive(self):
        line = (
            "SCRIPT ERROR: Invalid call to fetch with token=sk-secret-9f2a "
            "reported by someone@example.com at res://net/client.gd:88"
        )
        signature = error_signature(line)
        self.assertEqual(signature, "SCRIPT ERROR: Invalid call res://net/client.gd:88")
        for secret in ("sk-secret", "token=", "someone@example.com", "@"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, signature)

    def test_a_player_save_path_leaves_nothing_behind(self):
        self.assertEqual(
            error_signature("ERROR: Could not load user://saves/player-someone-2026.save"),
            "ERROR: Could not load",
        )

    def test_every_allowlisted_phrase_reports_its_own_words(self):
        for phrase, category in (
            ("Parse Error: x", "Parse Error"),
            ("Failed to load script x", "Failed to load script"),
            ("Failed loading resource: x", "Failed loading resource"),
            ("Cannot open file x", "Cannot open file"),
            ("Could not load x", "Could not load"),
            ("Failed to instantiate scene x", "Failed to instantiate scene"),
            ("Unable to load x", "Unable to load"),
            ("Resource file not found: x", "Resource file not found"),
            ("Script inherits from native type X", "Script inherits from native type"),
            ("Invalid call to function f", "Invalid call"),
            ("Invalid get index 'x'", "Invalid get index"),
            ("Invalid set index 'x'", "Invalid set index"),
            ("Nonexistent function 'f'", "Nonexistent function"),
            ("Division by zero in operator", "Division by zero"),
            ("Out of bounds get index", "Out of bounds"),
            ("Assertion failed: nope", "Assertion failed"),
            ('Condition "p->data == this" is true.', "Condition is true"),
            ('Condition "p->ready" is false.', "Condition is false"),
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(error_signature("ERROR: " + phrase), "ERROR: " + category)

    def test_a_phrase_nobody_listed_is_reported_as_unrecognized(self):
        signature = error_signature("ERROR: the renderer said something new about someone")
        self.assertEqual(signature, "ERROR: " + UNRECOGNIZED)
        self.assertNotIn("someone", signature)

    def test_the_signature_is_capped(self):
        self.assertEqual(FIRST_ERROR_LIMIT, 200)
        signature = error_signature("ERROR: Parse Error res://" + "a" * 400 + ".gd")
        self.assertEqual(len(signature), FIRST_ERROR_LIMIT)


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

    def test_a_host_path_in_the_log_never_reaches_a_receipt(self):
        message = (
            "ERROR: Cannot open file C:\\Users\\someone\\game\\main.tscn "
            "listed at https://cdn.example.com/manifest.json with token=sk-secret-9f2a "
            "for someone@example.com"
        )
        result = self.execute(self.child(message), label="paths")
        self.assertEqual(result["verdict"], "startup_failure")
        self.assertEqual(result["diagnostics"]["phase"], "load")
        self.assertEqual(result["diagnostics"]["first_error"], "ERROR: Cannot open file")
        run_dir = self.root / "artifacts/launches/paths"
        for name in ("exit.json", "diagnostics.json"):
            text = (run_dir / name).read_text(encoding="utf-8")
            for secret in ("C:", "someone", "cdn.example.com", "sk-secret", "@example.com"):
                with self.subTest(receipt=name, secret=secret):
                    self.assertNotIn(secret, text)
        # The raw line stays where the raw output always was: the log.
        self.assertIn("cdn.example.com", (run_dir / "process/stdout.log").read_text(encoding="utf-8"))

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
