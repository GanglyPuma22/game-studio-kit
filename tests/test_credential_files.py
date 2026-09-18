"""Optional `credential_files`: a declared host file instead of an exported variable.

This exists because an agent on a real host wrote a wrapper whose only real job
was parsing `KEY=VALUE` out of a file into the environment before every run.
"""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools.adapters import meshy
from studio_tools.common import StudioError, read_json, write_json
from studio_tools.config import credential, load

ROOT = Path(__file__).resolve().parents[1]


class FakeTransport:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class CredentialCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio credential space ")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("MESHY_API_KEY", None)

    def keyfile(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)


class CredentialFileTests(CredentialCase):
    def test_the_environment_still_wins_over_a_declared_file(self):
        config = load(overrides={"credential_files": [self.keyfile("keys.env", "MESHY_API_KEY=file-secret\n")]})
        os.environ["MESHY_API_KEY"] = "env-secret"
        self.assertEqual(credential(config, "meshy"), "env-secret")

    def test_a_declared_file_answers_when_the_environment_does_not(self):
        config = load(overrides={"credential_files": [self.keyfile("keys.env", "MESHY_API_KEY=file-secret\n")]})
        self.assertEqual(credential(config, "meshy"), "file-secret")
        # Reading a key is not the same as handing it to every child process.
        self.assertNotIn("MESHY_API_KEY", os.environ)

    def test_export_prefix_quotes_comments_and_blank_lines_are_parsed(self):
        for name, text, expected in (
            ("export.env", "export MESHY_API_KEY=plain-secret\n", "plain-secret"),
            ("double.env", 'MESHY_API_KEY="double-secret"\n', "double-secret"),
            ("single.env", "MESHY_API_KEY='single-secret'\n", "single-secret"),
            ("both.env", 'export  MESHY_API_KEY = "spaced-secret" \n', "spaced-secret"),
            ("noise.env", "\n# MESHY_API_KEY=commented-secret\n\n   \n"
                          "OTHER_KEY=not-this-one\nMESHY_API_KEY=real-secret\n", "real-secret"),
        ):
            with self.subTest(file=name):
                config = load(overrides={"credential_files": [self.keyfile(name, text)]})
                self.assertEqual(credential(config, "meshy"), expected)

    def test_only_commented_or_empty_values_are_not_a_credential(self):
        for name, text in (("comment.env", "# MESHY_API_KEY=commented\n"),
                           ("empty.env", "MESHY_API_KEY=\n"),
                           ("other.env", "ELEVENLABS_API_KEY=other-secret\n")):
            with self.subTest(file=name):
                config = load(overrides={"credential_files": [self.keyfile(name, text)]})
                with self.assertRaisesRegex(StudioError, "or list a credential file"):
                    credential(config, "meshy")

    def test_missing_files_are_skipped_and_the_first_declared_hit_wins(self):
        config = load(overrides={"credential_files": [
            str(self.dir / "absent.env"),
            self.keyfile("first.env", "MESHY_API_KEY=first-secret\n"),
            self.keyfile("second.env", "MESHY_API_KEY=second-secret\n"),
        ]})
        self.assertEqual(credential(config, "meshy"), "first-secret")

    def test_the_missing_key_message_still_names_the_environment_variable(self):
        with self.assertRaises(StudioError) as caught:
            credential(load(), "meshy")
        self.assertEqual(
            str(caught.exception),
            "meshy needs setup: set the configured credential environment variable "
            "or list a credential file",
        )

    def test_a_malformed_declaration_is_refused_when_the_host_config_loads(self):
        for value in ("C:/keys/meshy.env", [""], [3], {"meshy": "keys.env"}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(StudioError, "credential_files"):
                    load(overrides={"credential_files": value})

    def test_a_file_sourced_key_never_reaches_a_meshy_task_record(self):
        record = self.dir / "task.json"
        config = load(overrides={"credential_files": [self.keyfile("keys.env", "MESHY_API_KEY=file-secret\n")]})
        transport = FakeTransport({"result": "file-key-task"})
        meshy.submit(config, "preview", {"prompt": "A ceramic bell"}, record, {
            "authorized": True, "work_card": "fixture", "rate_checked_at": "2026-09-05",
            "units": "test units", "estimated": 1, "maximum": 1,
        }, transport=transport)
        self.assertEqual(transport.calls[0][0][2]["Authorization"], "Bearer file-secret")
        self.assertNotIn("file-secret", record.read_text(encoding="utf-8"))


class CredentialFileReviewTests(CredentialCase):
    """Round one of review: a byte-order mark, a working directory and a rotation."""

    def test_a_byte_order_mark_is_not_part_of_the_variable_name(self):
        path = self.dir / "bom.env"
        path.write_text('export MESHY_API_KEY="bom-secret"\n', encoding="utf-8-sig")
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        config = load(overrides={"credential_files": [str(path)]})
        self.assertEqual(credential(config, "meshy"), "bom-secret")

    def test_a_relative_entry_follows_the_host_config_not_the_working_directory(self):
        (self.dir / "keys").mkdir()
        (self.dir / "keys/meshy.env").write_text("MESHY_API_KEY=beside-the-config\n", encoding="utf-8")
        host = self.dir / "host.json"
        write_json(host, {"credential_files": ["keys/meshy.env"]})
        elsewhere = self.dir / "somewhere else"
        elsewhere.mkdir()
        # The same host config, read from two working directories, names one file.
        found = []
        origin = os.getcwd()
        try:
            for where in (self.dir, elsewhere):
                os.chdir(where)
                config = load(str(host))
                found.append((config["credential_files"], credential(config, "meshy")))
        finally:
            os.chdir(origin)
        self.assertEqual(found[0], found[1])
        self.assertEqual(found[0][1], "beside-the-config")
        self.assertEqual(found[0][0], [str(self.dir / "keys/meshy.env")])
        # A decoy of the same relative name in the working directory is not read.
        (elsewhere / "keys").mkdir()
        (elsewhere / "keys/meshy.env").write_text("MESHY_API_KEY=beside-the-caller\n", encoding="utf-8")
        try:
            os.chdir(elsewhere)
            self.assertEqual(credential(load(str(host)), "meshy"), "beside-the-config")
        finally:
            os.chdir(origin)

    def test_an_absolute_entry_is_left_exactly_as_the_host_wrote_it(self):
        host = self.dir / "host.json"
        write_json(host, {"credential_files": [str(self.dir / "keys.env"), "C:\\Studio Host\\keys.env"]})
        self.assertEqual(load(str(host))["credential_files"],
                         [str(self.dir / "keys.env"), "C:\\Studio Host\\keys.env"])

    def test_a_rotation_between_two_reads_cannot_leave_the_sent_key_in_the_record(self):
        path = self.dir / "keys.env"
        path.write_text("MESHY_API_KEY=first-secret\n", encoding="utf-8")
        config = load(overrides={"credential_files": [str(path)]})
        record = self.dir / "task.json"
        meshy.submit(config, "preview", {"prompt": "A ceramic bell"}, record, {
            "authorized": True, "work_card": "fixture", "rate_checked_at": "2026-09-05",
            "units": "test units", "estimated": 1, "maximum": 1,
        }, transport=FakeTransport({"result": "rotating-task"}))

        class RotatingTransport(FakeTransport):
            def request(self, *args, **kwargs):
                # The host rotates the key while this request is in flight.
                path.write_text("MESHY_API_KEY=second-secret\n", encoding="utf-8")
                return super().request(*args, **kwargs)

        transport = RotatingTransport({
            "id": "rotating-task", "status": "FAILED",
            "task_error": {"message": "rejected key first-secret"},
        })
        observed = meshy.observe(config, record, transport)
        self.assertEqual(transport.calls[0][0][2]["Authorization"], "Bearer first-secret")
        # The key that was sent is the key redacted, not the one now on disk.
        self.assertNotIn("first-secret", json.dumps(observed))
        self.assertNotIn("first-secret", record.read_text(encoding="utf-8"))
        self.assertEqual(read_json(record)["status"], "FAILED")
        self.assertEqual(credential(config, "meshy"), "second-secret")


class CredentialFileDiscoverabilityTests(unittest.TestCase):
    """A host cannot declare what no document says exists."""

    def test_every_document_a_host_reads_names_the_declaration(self):
        for name in ("skills/studio-meshy/SKILL.md", "docs/setup-windows.md",
                     "docs/setup-linux.md", "docs/provider-setup.md"):
            with self.subTest(document=name):
                self.assertIn("credential_files", (ROOT / name).read_text(encoding="utf-8"))

    def test_the_documents_a_host_writes_the_file_from_spell_its_format(self):
        for name in ("skills/studio-meshy/SKILL.md", "docs/setup-windows.md",
                     "docs/setup-linux.md"):
            with self.subTest(document=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("`KEY=VALUE`", text)
                self.assertIn("export ", text)
        # The limit that makes this safe to document at all.
        windows = (ROOT / "docs/setup-windows.md").read_text(encoding="utf-8")
        self.assertIn("never written into `os.environ`", windows)
        # A relative entry is only unambiguous because the anchor is written down.
        for name in ("skills/studio-meshy/SKILL.md", "docs/setup-windows.md",
                     "docs/setup-linux.md", "docs/provider-setup.md"):
            with self.subTest(document=name):
                self.assertIn("host config file", (ROOT / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
