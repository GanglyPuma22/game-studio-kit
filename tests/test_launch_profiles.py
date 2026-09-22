"""Project-owned launch and playtest profiles (offline).

Six wrapper scripts around one project were the same thirty lines with a
different worktree and different feature flags; three more read a project's
accepted arguments and appended an output path and a content digest. A profile
is that declaration as a file the kit reads, so nothing here needs a Python
wrapper to verify assets and then launch. Small Python child processes stand in
for the engine; no engine, provider or desktop is involved.
"""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cli, launch, playtest, processes, profile
from studio_tools.common import StudioError, read_json, sha256, write_json

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates/launch-profile.json"
OK = "print('ran')"


class ProfileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio profile space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        (self.root / "tools").mkdir(parents=True)
        (self.root / "project.godot").touch()
        (self.root / "asset.bin").write_bytes(b"asset bytes")
        self.sha = sha256(sys.executable)
        self.host_config = Path(self.tmp.name) / "host.json"
        write_json(self.host_config, {"executables": {"godot": sys.executable}, "timeout": 5})

    def manifest(self, name="tools/identity.json", digest=None):
        write_json(self.root / name, {
            "schema_version": 1, "kind": "identity-manifest",
            "items": [{"id": "asset", "role": "asset", "path": "asset.bin",
                       "sha256": digest or sha256(self.root / "asset.bin")}],
        })
        return name

    def profile(self, name="tools/play.json", **fields):
        record = {"schema_version": 1, "kind": "launch-profile", **fields}
        write_json(self.root / name, record)
        return name

    def invoke(self, argv, code=OK, module="playtest"):
        def fake(args, **kwargs):
            self.last_args = args
            return processes.run([sys.executable, "-c", code], **kwargs)

        with patch(f"studio_tools.{module}.run", side_effect=fake):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    status = cli.main(argv)
        return status, out.getvalue(), err.getvalue()

    def playtest_argv(self, *extra):
        return ["playtest", "start", "--project", str(self.root), "--config",
                str(self.host_config), "--sha256", self.sha, *extra]

    def launch_argv(self, *extra):
        return ["launch", "--project", str(self.root), "--config",
                str(self.host_config), "--sha256", self.sha, *extra]


class ProfileResolutionTests(ProfileCase):
    def test_a_playtest_profile_supplies_every_field_the_flags_would(self):
        name = self.profile(
            command="playtest", session="handoff", scene="res://scenes/entry.tscn",
            rendering_method="mobile", resolution="1280x720", max_minutes=1,
            passthrough=["--wetland-pocket"], feature_flags=["--wetland-kite"],
            identity_manifest=self.manifest(),
        )
        status, out, err = self.invoke(self.playtest_argv("--profile", name, "--label", "declared"))
        self.assertEqual(err, "")
        self.assertEqual(status, 0)
        record = read_json(self.root / "artifacts/playtests/declared/playtest.json")
        self.assertEqual(record["scene"], "res://scenes/entry.tscn")
        self.assertEqual(record["rendering_method"], "mobile")
        self.assertEqual(record["resolution"], "1280x720")
        self.assertEqual(record["session"], "handoff")
        # The separator itself reaches the engine, and the feature flags are
        # appended to the passthrough rather than replacing it.
        self.assertEqual(self.last_args[-3:], ["--", "--wetland-pocket", "--wetland-kite"])
        self.assertEqual(record["passthrough_count"], 2)

    def test_a_launch_profile_supplies_mode_script_timeout_scope_and_results(self):
        name = self.profile(
            command="launch", mode="native", script="res://tests/probe.gd", timeout=30,
            scope="accepted-population", results=["artifacts/out.json"],
            passthrough=["--encounter-output"],
        )
        code = "import pathlib;pathlib.Path('artifacts').mkdir(exist_ok=True);" \
               "pathlib.Path('artifacts/out.json').write_text('{}')"
        status, out, err = self.invoke(
            self.launch_argv("--profile", name, "--label", "probe"), code=code, module="launch"
        )
        self.assertEqual(err, "")
        self.assertEqual(status, 0)
        record = read_json(self.root / "artifacts/launches/probe/owned-launch.json")
        self.assertEqual(record["mode"], "native")
        self.assertEqual(record["script"], "res://tests/probe.gd")
        self.assertEqual(record["scope"], "accepted-population")
        self.assertEqual(record["expected_results"], ["artifacts/out.json"])

    def test_an_explicit_flag_overrides_the_single_field_it_names(self):
        name = self.profile(
            command="playtest", session="handoff", scene="res://scenes/entry.tscn",
            rendering_method="mobile", resolution="1280x720", max_minutes=1,
            passthrough=["--from-profile"],
        )
        self.invoke(self.playtest_argv(
            "--profile", name, "--label", "overridden",
            "--rendering-method", "forward_plus", "--scene", "res://scenes/other.tscn",
        ))
        record = read_json(self.root / "artifacts/playtests/overridden/playtest.json")
        self.assertEqual(record["rendering_method"], "forward_plus")
        self.assertEqual(record["scene"], "res://scenes/other.tscn")
        # Everything the caller did not type still comes from the profile.
        self.assertEqual(record["resolution"], "1280x720")
        self.assertIn("--from-profile", self.last_args)

    def test_an_explicit_passthrough_replaces_the_profiles_own_but_not_its_flags(self):
        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["--from-profile"], feature_flags=["--flag"])
        self.invoke(self.playtest_argv("--profile", name, "--label", "typed", "--", "--typed"))
        # passthrough and feature_flags are two fields: typing one replaces
        # that one, and the flags this profile exists to turn on stay on.
        self.assertEqual(self.last_args[-3:], ["--", "--typed", "--flag"])
        self.assertNotIn("--from-profile", self.last_args)

    def test_a_profile_for_the_other_command_is_refused(self):
        name = self.profile(command="launch", mode="native")
        status, out, err = self.invoke(self.playtest_argv("--profile", name))
        self.assertEqual(status, 1)
        self.assertIn("launch profile", json.loads(err)["error"])

    def test_a_field_that_belongs_to_the_other_parser_is_named_rather_than_ignored(self):
        name = self.profile(command="playtest", scope="macro-terrain")
        status, _, err = self.invoke(self.playtest_argv("--profile", name))
        self.assertEqual(status, 1)
        message = json.loads(err)["error"]
        self.assertIn('"scope"', message)
        self.assertIn("belongs to launch", message)

    def test_a_malformed_profile_is_refused_before_anything_starts(self):
        for fields, fragment in (
            ({"command": "bench"}, "launch\" or \"playtest"),
            ({"command": "playtest", "scene": ""}, "nonempty"),
            ({"command": "playtest", "passthrough": "--one"}, "wrong type"),
            ({"command": "playtest", "passthrough": ["", "x"]}, "nonempty strings"),
            ({"command": "playtest", "max_minutes": "1"}, "wrong type"),
            ({"command": "playtest", "unknown_field": "x"}, "not a playtest field"),
        ):
            name = self.profile(name="tools/bad.json", **fields)
            with self.subTest(fields=fields):
                status, _, err = self.invoke(self.playtest_argv("--profile", name))
                self.assertEqual(status, 1)
                self.assertIn(fragment, json.loads(err)["error"])
                self.assertFalse((self.root / "artifacts/playtests").exists())

    def test_a_profile_outside_the_project_is_refused(self):
        outside = Path(self.tmp.name) / "play.json"
        write_json(outside, {"schema_version": 1, "kind": "launch-profile", "command": "playtest"})
        status, _, err = self.invoke(self.playtest_argv("--profile", str(outside)))
        self.assertEqual(status, 1)
        self.assertIn("belongs to the project", json.loads(err)["error"])


class ProfileIdentityTests(ProfileCase):
    def test_a_mismatched_manifest_refuses_with_identity_mismatch_and_no_launch(self):
        name = self.profile(command="playtest", max_minutes=1,
                            identity_manifest=self.manifest(digest="0" * 64))
        with patch("studio_tools.playtest.run") as run:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    status = cli.main(self.playtest_argv("--profile", name, "--label", "blocked"))
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(status, 1)
        run.assert_not_called()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["verdict"], "identity_mismatch")
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["launched"])
        self.assertEqual(payload["identity"]["totals"]["mismatch"], 1)
        # The receipt that lists the items is the identity receipt, named
        # project-relative like every other path a receipt carries.
        self.assertTrue((self.root / payload["identity"]["receipt"]).is_file())
        self.assertFalse((self.root / "artifacts/playtests").exists())

    def test_a_missing_manifest_item_also_refuses(self):
        (self.root / "asset.bin").unlink()
        name = self.profile(command="playtest", max_minutes=1, identity_manifest=self.manifest(
            digest="a" * 64))
        status, out, _ = self.invoke(self.playtest_argv("--profile", name))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(out)["verdict"], "identity_mismatch")

    def test_a_matching_manifest_reaches_the_receipt_as_a_verdict(self):
        name = self.profile(command="playtest", max_minutes=1,
                            identity_manifest=self.manifest())
        self.invoke(self.playtest_argv("--profile", name, "--label", "verified"))
        record = read_json(self.root / "artifacts/playtests/verified/playtest.json")
        self.assertEqual(record["launch_profile"]["identity_verdict"], "match")
        self.assertEqual(record["launch_profile"]["path"], name)
        self.assertEqual(record["launch_profile"]["sha256"], sha256(self.root / name))
        self.assertEqual(
            read_json(self.root / "artifacts/playtests/verified/exit.json")
            ["launch_profile"]["identity_verdict"], "match")

    def test_a_profile_without_a_manifest_says_so_rather_than_claiming_a_match(self):
        name = self.profile(command="playtest", max_minutes=1)
        self.invoke(self.playtest_argv("--profile", name, "--label", "undeclared"))
        record = read_json(self.root / "artifacts/playtests/undeclared/playtest.json")
        self.assertEqual(record["launch_profile"]["identity_verdict"], "not_declared")
        self.assertIsNone(record["launch_profile"]["identity_receipt"])


class ProfilePlaceholderTests(ProfileCase):
    def candidate(self, digest=None):
        """Write a candidate record carrying the project's current digest.

        Called after every project file the test writes, because the digest is
        a claim about the files that exist when it is made -- which is exactly
        what the stale check re-reads. The record itself lives under
        `artifacts/`, which the inventory excludes, so writing it cannot move
        the number it stores.
        """
        from studio_tools.common import digest as hash_record
        from studio_tools.evidence import inventory

        value = digest or hash_record(inventory(self.root))
        write_json(self.root / "artifacts/candidate.json",
                   {"kind": "candidate", "content_digest": value})
        return value

    def test_the_three_placeholders_are_substituted_in_passthrough_and_flags(self):
        name = self.profile(
            command="playtest", max_minutes=1,
            passthrough=["--evidence", "{project}/artifacts/run/{label}"],
            feature_flags=["--candidate-hash", "{content_digest}"],
        )
        current = self.candidate()
        self.invoke(self.playtest_argv("--profile", name, "--label", "substituted"))
        self.assertIn(f"{self.root}/artifacts/run/substituted", self.last_args)
        self.assertIn(current, self.last_args)

    def test_a_generated_label_is_the_one_the_run_directory_uses(self):
        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["--evidence", "{label}"])
        status, out, _ = self.invoke(self.playtest_argv("--profile", name))
        self.assertEqual(status, 0)
        label = json.loads(out)["label"]
        self.assertIn(label, self.last_args)
        self.assertTrue((self.root / "artifacts/playtests" / label).is_dir())

    def test_the_content_digest_placeholder_is_refused_without_a_candidate(self):
        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["--hash", "{content_digest}"])
        status, _, err = self.invoke(self.playtest_argv("--profile", name))
        self.assertEqual(status, 1)
        message = json.loads(err)["error"]
        self.assertIn("artifacts/candidate.json", message)
        self.assertFalse((self.root / "artifacts/playtests").exists())

    def test_a_stale_candidate_record_refuses_rather_than_naming_an_old_build(self):
        # A stored digest is a claim about files, and the files moved. Handing
        # the engine the identity of a build that no longer exists is exactly
        # the confusion the digest was added to prevent.
        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["--hash", "{content_digest}"])
        recorded = self.candidate()
        (self.root / "asset.bin").write_bytes(b"different asset bytes")
        with patch("studio_tools.playtest.run") as run:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    status = cli.main(self.playtest_argv("--profile", name, "--label", "stale"))
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(status, 1)
        run.assert_not_called()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["verdict"], "candidate_stale")
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["launched"])
        self.assertEqual(payload["candidate"]["recorded_content_digest"], recorded)
        self.assertNotEqual(payload["candidate"]["current_content_digest"], recorded)
        self.assertIn("studio candidate new", payload["failure"])
        self.assertFalse((self.root / "artifacts/playtests").exists())

    def test_a_candidate_record_without_a_hex_content_digest_is_refused(self):
        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["--hash", "{content_digest}"])
        for record in ({"kind": "candidate"},
                       {"kind": "candidate", "content_digest": ""},
                       {"kind": "candidate", "content_digest": "not-a-digest"},
                       {"kind": "candidate", "content_digest": "C" * 64},
                       {"kind": "candidate", "content_digest": "a" * 63},
                       {"kind": "candidate", "content_digest": 7}):
            write_json(self.root / "artifacts/candidate.json", record)
            with self.subTest(record=record):
                status, _, err = self.invoke(self.playtest_argv("--profile", name))
                self.assertEqual(status, 1)
                message = json.loads(err)["error"]
                self.assertIn("64 lowercase hexadecimal", message)
                self.assertFalse((self.root / "artifacts/playtests").exists())

    def test_a_stale_candidate_is_only_consulted_when_the_placeholder_is_used(self):
        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["--no-placeholder-here"])
        self.candidate()
        (self.root / "asset.bin").write_bytes(b"different asset bytes")
        status, out, err = self.invoke(
            self.playtest_argv("--profile", name, "--label", "unaffected")
        )
        self.assertEqual(err, "")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["verdict"], "completed")

    def test_a_passthrough_brace_that_is_not_a_placeholder_is_left_alone(self):
        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["--json", '{"a": 1}'])
        self.invoke(self.playtest_argv("--profile", name, "--label", "braces"))
        self.assertIn('{"a": 1}', self.last_args)


class ProfileCheckTests(ProfileCase):
    def test_check_verifies_the_manifest_and_launches_nothing(self):
        from studio_tools.common import digest as hash_record
        from studio_tools.evidence import inventory

        name = self.profile(
            command="playtest", max_minutes=1, scene="res://scenes/entry.tscn",
            identity_manifest=self.manifest(),
            passthrough=["--secret-flag", "{content_digest}"],
            feature_flags=["--another-secret"],
        )
        # Written last: the digest describes the files that exist now.
        self.candidate_digest = hash_record(inventory(self.root))
        write_json(self.root / "artifacts/candidate.json",
                   {"kind": "candidate", "content_digest": self.candidate_digest})
        with patch("studio_tools.playtest.run") as run:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    status = cli.main(self.playtest_argv("--profile", name, "--check"))
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(status, 0)
        run.assert_not_called()
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["launched"])
        self.assertEqual(payload["identity"]["verdict"], "match")
        self.assertEqual(payload["passthrough_count"], 3)
        self.assertEqual(payload["resolved_fields"], ["max_minutes", "scene"])
        # A count and a set of field names; never a passthrough value.
        for secret in ("--secret-flag", "--another-secret", self.candidate_digest):
            self.assertNotIn(secret, out.getvalue())
        self.assertFalse((self.root / "artifacts/playtests").exists())

    def test_check_refuses_a_stale_candidate_too(self):
        from studio_tools.common import digest as hash_record
        from studio_tools.evidence import inventory

        name = self.profile(command="playtest", max_minutes=1,
                            passthrough=["{content_digest}"])
        write_json(self.root / "artifacts/candidate.json",
                   {"kind": "candidate", "content_digest": hash_record(inventory(self.root))})
        (self.root / "asset.bin").write_bytes(b"moved on")
        status, out, _ = self.invoke(self.playtest_argv("--profile", name, "--check"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(out)["verdict"], "candidate_stale")

    def test_check_reports_a_mismatch_as_a_refusal_rather_than_a_pass(self):
        name = self.profile(command="playtest", max_minutes=1,
                            identity_manifest=self.manifest(digest="0" * 64))
        status, out, _ = self.invoke(self.playtest_argv("--profile", name, "--check"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(out)["verdict"], "identity_mismatch")

    def test_check_works_for_launch_too_and_needs_a_profile(self):
        name = self.profile(command="launch", mode="native", script="res://t.gd",
                            identity_manifest=self.manifest())
        with patch("studio_tools.launch.run") as run:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()):
                    status = cli.main(self.launch_argv("--profile", name, "--check"))
        self.assertEqual(status, 0)
        run.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["command"], "launch")

        status, _, err = self.invoke(self.launch_argv("--check"), module="launch")
        self.assertEqual(status, 1)
        self.assertIn("name one with --profile", json.loads(err)["error"])


class ProfileReceiptContainmentTests(ProfileCase):
    def test_no_receipt_carries_a_passthrough_value(self):
        from studio_tools.common import digest as hash_record
        from studio_tools.evidence import inventory

        name = self.profile(
            command="playtest", max_minutes=1, identity_manifest=self.manifest(),
            passthrough=["--private-passthrough-value", "{content_digest}"],
            feature_flags=["--private-feature-flag"],
        )
        current = hash_record(inventory(self.root))
        write_json(self.root / "artifacts/candidate.json",
                   {"kind": "candidate", "content_digest": current})
        self.invoke(self.playtest_argv("--profile", name, "--label", "contained"),
                 code="print('private-passthrough-value seen')")
        run_dir = self.root / "artifacts/playtests/contained"
        for receipt in ("playtest.json", "exit.json", "diagnostics.json", "process/process.json"):
            text = (run_dir / receipt).read_text(encoding="utf-8")
            with self.subTest(receipt=receipt):
                for secret in ("--private-passthrough-value", "--private-feature-flag"):
                    self.assertNotIn(secret, text)
        # The content digest is not a passthrough value that leaked: the
        # session receipt records which build was played on its own account,
        # and this profile happens to hand the engine the same number.
        record = read_json(run_dir / "playtest.json")
        self.assertEqual(record["content_digest"], current)
        self.assertNotIn(current, json.dumps(record["launch_profile"]))
        # The log still holds what the child printed; that is what it is for.
        self.assertIn("private-passthrough-value",
                      (run_dir / "process/stdout.log").read_text(encoding="utf-8"))

    def test_commands_without_a_profile_record_none_and_behave_as_before(self):
        self.invoke(self.playtest_argv("--label", "plain", "--max-minutes", "1"))
        record = read_json(self.root / "artifacts/playtests/plain/playtest.json")
        self.assertIsNone(record["launch_profile"])
        self.assertEqual(record["session"], "handoff")
        self.invoke(self.launch_argv("--label", "plain"), module="launch")
        owned = read_json(self.root / "artifacts/launches/plain/owned-launch.json")
        self.assertIsNone(owned["launch_profile"])
        self.assertEqual(owned["mode"], "import")


class ProfileTemplateTests(unittest.TestCase):
    def test_the_shipped_template_is_a_valid_profile_that_names_every_placeholder(self):
        record = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(record["kind"], "launch-profile")
        self.assertEqual(record["schema_version"], 1)
        self.assertIn(record["command"], profile.COMMANDS)
        text = TEMPLATE.read_text(encoding="utf-8")
        for placeholder in profile.PLACEHOLDERS:
            self.assertIn(placeholder, text)
        self.assertIn("identity_mismatch", record["$comment"])
        self.assertIn("templates/launch-profile.json",
                      read_json(ROOT / "studio-kit.json")["resources"])

    def test_the_template_loads_through_the_real_resolver(self):
        with tempfile.TemporaryDirectory(prefix="studio template space ") as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "tools/play.json").write_bytes(TEMPLATE.read_bytes())
            record, file_record = profile.load(root, "tools/play.json")
            self.assertEqual(record["command"], "playtest")
            self.assertEqual(file_record["path"], "tools/play.json")


if __name__ == "__main__":
    unittest.main()
