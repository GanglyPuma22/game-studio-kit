"""Doctor telling the truth about where a key would come from (offline).

`credential` has always fallen back to a declared file, but `doctor` only ever
looked at the environment, so a correctly configured host was told its
providers needed setup. These tests pin the honest answer and pin that no value
from a file or a variable is ever reported.
"""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools.config import credential, credential_file_report, credential_source, load
from studio_tools.doctor import inspect

SECRET = "sk-should-never-be-printed"


class CredentialCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio doctor space ")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for name in ("MESHY_API_KEY", "ELEVENLABS_API_KEY", "FISH_AUDIO_API_KEY", "GEMINI_API_KEY"):
            os.environ.pop(name, None)

    def keyfile(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)


class CredentialSourceTests(CredentialCase):
    def test_no_key_anywhere_is_none(self):
        self.assertEqual(credential_source(load(), "meshy"), "none")

    def test_an_exported_variable_is_the_environment(self):
        os.environ["MESHY_API_KEY"] = SECRET
        self.assertEqual(credential_source(load(), "meshy"), "environment")

    def test_a_declared_file_is_the_file(self):
        config = load(overrides={"credential_files": [self.keyfile("keys.env", f"MESHY_API_KEY={SECRET}\n")]})
        self.assertEqual(credential_source(config, "meshy"), "file")
        # Reading the file never exports it, so nothing this kit starts inherits it.
        self.assertNotIn("MESHY_API_KEY", os.environ)

    def test_the_source_follows_the_same_order_the_credential_resolves_in(self):
        config = load(overrides={"credential_files": [self.keyfile("keys.env", "MESHY_API_KEY=from-file\n")]})
        os.environ["MESHY_API_KEY"] = "from-environment"
        self.assertEqual(credential_source(config, "meshy"), "environment")
        self.assertEqual(credential(config, "meshy"), "from-environment")

    def test_an_empty_value_is_not_a_source(self):
        config = load(overrides={"credential_files": [self.keyfile("keys.env", "MESHY_API_KEY=\n")]})
        self.assertEqual(credential_source(config, "meshy"), "none")

    def test_a_provider_with_no_configured_variable_name_is_none(self):
        self.assertEqual(credential_source(load(), "nobody"), "none")


class CredentialFileReportTests(CredentialCase):
    def test_a_present_readable_file_lists_its_names_and_no_values(self):
        path = self.keyfile("keys.env", f"# comment\nexport MESHY_API_KEY={SECRET}\nFISH_AUDIO_API_KEY='{SECRET}'\n")
        report = credential_file_report(load(overrides={"credential_files": [path]}))
        self.assertEqual(len(report), 1)
        self.assertTrue(report[0]["present"])
        self.assertTrue(report[0]["readable"])
        self.assertEqual(report[0]["keys"], ["FISH_AUDIO_API_KEY", "MESHY_API_KEY"])
        self.assertNotIn(SECRET, json.dumps(report))

    def test_a_missing_file_is_reported_rather_than_hidden(self):
        missing = str(self.dir / "absent.env")
        report = credential_file_report(load(overrides={"credential_files": [missing]}))
        self.assertEqual(report, [{"index": 0, "name": "absent.env", "present": False,
                                   "readable": False, "keys": []}])

    def test_only_the_basename_and_position_identify_a_declared_file(self):
        first = self.keyfile("meshy.env", f"MESHY_API_KEY={SECRET}\n")
        second = self.keyfile("fish.env", f"FISH_AUDIO_API_KEY={SECRET}\n")
        report = credential_file_report(load(overrides={"credential_files": [first, second]}))
        self.assertEqual([entry["index"] for entry in report], [0, 1])
        self.assertEqual([entry["name"] for entry in report], ["meshy.env", "fish.env"])
        text = json.dumps(report)
        # The directory a host keeps its keys in is host layout, not evidence.
        self.assertNotIn(str(self.dir), text)
        self.assertNotIn("path", text)

    def test_a_windows_spelled_entry_still_reports_a_bare_name(self):
        from studio_tools.config import _credential_file_name

        for item, name in (
            ("/home/someone/.keys/meshy.env", "meshy.env"),
            ("C:\\Users\\someone\\keys\\meshy.env", "meshy.env"),
            ("\\\\server\\share\\keys.env", "keys.env"),
            ("keys.env", "keys.env"),
        ):
            with self.subTest(item=item):
                self.assertEqual(_credential_file_name(item), name)

    def test_a_file_this_process_cannot_read_is_present_but_not_readable(self):
        path = Path(self.keyfile("locked.env", f"MESHY_API_KEY={SECRET}\n"))
        path.chmod(0o000)
        self.addCleanup(path.chmod, 0o600)
        if os.access(path, os.R_OK):
            self.skipTest("this host reads a mode 000 file anyway")
        report = credential_file_report(load(overrides={"credential_files": [str(path)]}))
        self.assertTrue(report[0]["present"])
        self.assertFalse(report[0]["readable"])
        self.assertEqual(report[0]["keys"], [])


class DoctorReportTests(CredentialCase):
    def test_a_file_backed_host_is_unverified_rather_than_needing_setup(self):
        path = self.keyfile("keys.env", f"MESHY_API_KEY={SECRET}\nGEMINI_API_KEY={SECRET}\n")
        report = inspect(load(overrides={"credential_files": [path]}))
        meshy = report["capabilities"]["meshy"]
        self.assertEqual(meshy["credential_source"], "file")
        self.assertTrue(meshy["credential_present"])
        self.assertEqual(meshy["status"], "unverified")
        # A key that is present is still not a probed, entitled account.
        self.assertFalse(meshy["network_probed"])
        video = report["capabilities"]["review_video_analysis"]
        self.assertEqual(video["credential_source"], "file")
        self.assertEqual(video["status"], "unverified")

    def test_a_host_with_nothing_configured_still_needs_setup(self):
        report = inspect(load())
        for provider in ("meshy", "elevenlabs", "fish"):
            with self.subTest(provider=provider):
                entry = report["capabilities"][provider]
                self.assertEqual(entry["credential_source"], "none")
                self.assertEqual(entry["status"], "needs_setup")
        self.assertEqual(report["credential_files"], [])

    def test_the_environment_is_reported_as_the_environment(self):
        os.environ["ELEVENLABS_API_KEY"] = SECRET
        entry = inspect(load())["capabilities"]["elevenlabs"]
        self.assertEqual(entry["credential_source"], "environment")
        self.assertEqual(entry["status"], "unverified")

    def test_the_report_never_carries_a_key_value(self):
        path = self.keyfile("keys.env", f"MESHY_API_KEY={SECRET}\n")
        os.environ["FISH_AUDIO_API_KEY"] = SECRET
        report = inspect(load(overrides={"credential_files": [path]}))
        text = json.dumps(report)
        self.assertNotIn(SECRET, text)
        self.assertIn("MESHY_API_KEY", json.dumps(report["credential_files"]))

    def test_the_setup_plan_still_reads_the_reported_statuses(self):
        from studio_tools.doctor import setup

        path = self.keyfile("keys.env", f"MESHY_API_KEY={SECRET}\n")
        report = inspect(load(overrides={"credential_files": [path]}))
        actions = {entry["capability"]: entry["status"] for entry in setup(report)["actions"]}
        self.assertEqual(actions["meshy"], "unverified")
        self.assertEqual(actions["fish"], "needs_setup")


if __name__ == "__main__":
    unittest.main()
