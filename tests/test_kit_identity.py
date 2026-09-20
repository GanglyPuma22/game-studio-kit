"""Which kit wrote a receipt, and whether its results still exist (offline).

A receipt is read months later, often by someone who has since updated the kit.
`kit` records the version and the digest of the Python that produced it, and
`evidence verify` re-hashes the files a receipt claimed rather than trusting
that they are still there.
"""

import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import __version__, cli, launch, processes
from studio_tools.common import StudioError, kit_identity, read_json, sha256, write_json
from studio_tools.config import load
from studio_tools.doctor import inspect
from studio_tools.evidence import new_candidate, verify_receipt

ROOT = Path(__file__).resolve().parents[1]


class KitIdentityTests(unittest.TestCase):
    def test_it_names_this_version_and_digests_this_source_tree(self):
        identity = kit_identity()
        self.assertEqual(identity["version"], __version__)
        self.assertRegex(identity["source_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(identity), {"version", "source_digest"})

    def test_it_is_computed_once_and_handed_out_as_a_copy(self):
        first = kit_identity()
        second = kit_identity()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first["version"] = "tampered"
        self.assertEqual(kit_identity()["version"], __version__)

    def test_the_digest_covers_the_python_under_studio_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "studio_tools"
            (package / "adapters").mkdir(parents=True)
            (package / "adapters" / "one.py").write_text("a = 1\n", encoding="utf-8")
            (package / "two.py").write_text("b = 2\n", encoding="utf-8")
            (package / "notes.md").write_text("not source\n", encoding="utf-8")
            with patch("studio_tools.common._KIT_IDENTITY", None), \
                    patch("studio_tools.common.__file__", str(package / "common.py")):
                before = kit_identity()["source_digest"]
            (package / "two.py").write_text("b = 3\n", encoding="utf-8")
            with patch("studio_tools.common._KIT_IDENTITY", None), \
                    patch("studio_tools.common.__file__", str(package / "common.py")):
                after = kit_identity()["source_digest"]
            (package / "notes.md").write_text("still not source\n", encoding="utf-8")
            with patch("studio_tools.common._KIT_IDENTITY", None), \
                    patch("studio_tools.common.__file__", str(package / "common.py")):
                ignored = kit_identity()["source_digest"]
        self.assertNotEqual(before, after)
        self.assertEqual(after, ignored)


class ReceiptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio kit space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)
        self.host_config = Path(self.tmp.name) / "host.json"
        write_json(self.host_config, {"executables": {"godot": sys.executable}, "timeout": 5})

    def execute(self, code, **kwargs):
        def fake_run(args, **call):
            return processes.run([sys.executable, "-c", code], **call)
        with patch("studio_tools.launch.run", side_effect=fake_run):
            return launch.execute(self.config, self.root, sha256_expected=self.sha, **kwargs)


class ReceiptKitTests(ReceiptCase):
    def test_a_launch_records_the_kit_in_both_of_its_receipts(self):
        self.execute("print('ran')", label="kit")
        run_dir = self.root / "artifacts/launches/kit"
        for name in ("owned-launch.json", "exit.json"):
            with self.subTest(receipt=name):
                self.assertEqual(read_json(run_dir / name)["kit"], kit_identity())

    def test_a_candidate_and_the_doctor_report_record_the_kit(self):
        (self.root / "scene.gd").write_text("original scene", encoding="utf-8")
        self.assertEqual(new_candidate(self.root, "candidate", "4.5.1", "test")["kit"], kit_identity())
        self.assertEqual(inspect(self.config)["kit"], kit_identity())

    def test_the_kit_block_carries_no_host_paths_or_environment(self):
        self.execute("print('ran')", label="portable")
        text = json.dumps(read_json(self.root / "artifacts/launches/portable/exit.json")["kit"])
        self.assertNotIn(str(self.root), text)
        self.assertNotIn(os.sep + "home", text)


class VerifyTests(ReceiptCase):
    def launch_with_result(self, label="verify"):
        code = "import pathlib;pathlib.Path('artifacts/out.json').write_text('{\"frames\": 1}')"
        self.execute(code, label=label, results=["artifacts/out.json"])
        return self.root / f"artifacts/launches/{label}/exit.json"

    def test_unchanged_results_verify_and_the_receipt_is_not_copied(self):
        receipt = self.launch_with_result()
        result = verify_receipt(receipt)
        self.assertTrue(result["ok"])
        self.assertEqual([f["state"] for f in result["files"]], ["current"])
        self.assertEqual(result["files"][0]["current_sha256"],
                         result["files"][0]["recorded_sha256"])
        self.assertEqual(result["totals"], {"current": 1, "changed": 0, "missing": 0})
        self.assertEqual(result["project"], str(self.root))
        self.assertEqual(result["kit"], kit_identity())

    def test_changed_bytes_are_reported_as_changed(self):
        receipt = self.launch_with_result("changed")
        (self.root / "artifacts/out.json").write_text('{"frames": 2}', encoding="utf-8")
        result = verify_receipt(receipt)
        self.assertFalse(result["ok"])
        self.assertEqual(result["files"][0]["state"], "changed")
        self.assertNotEqual(result["files"][0]["current_sha256"],
                            result["files"][0]["recorded_sha256"])

    def test_a_deleted_result_is_reported_as_missing(self):
        receipt = self.launch_with_result("gone")
        (self.root / "artifacts/out.json").unlink()
        result = verify_receipt(receipt)
        self.assertFalse(result["ok"])
        self.assertEqual(result["files"][0]["state"], "missing")
        self.assertIsNone(result["files"][0]["current_sha256"])

    def test_a_receipt_with_nothing_recorded_is_not_ok(self):
        self.execute("print('ran')", label="empty")
        result = verify_receipt(self.root / "artifacts/launches/empty/exit.json")
        self.assertFalse(result["ok"])
        self.assertEqual(result["files"], [])

    def test_a_result_the_run_never_produced_is_listed_as_unrecorded(self):
        self.execute("print('ran')", label="never", results=["artifacts/never.json"])
        result = verify_receipt(self.root / "artifacts/launches/never/exit.json")
        self.assertEqual(result["unrecorded"], ["artifacts/never.json"])
        self.assertEqual(result["files"], [])
        self.assertFalse(result["ok"])

    def test_the_project_is_derived_from_the_run_directory_or_given(self):
        receipt = self.launch_with_result("derived")
        self.assertEqual(verify_receipt(receipt, project=str(self.root))["project"], str(self.root))
        loose = Path(self.tmp.name) / "copied-exit.json"
        loose.write_text(receipt.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(StudioError, "--project"):
            verify_receipt(loose)
        self.assertTrue(verify_receipt(loose, project=str(self.root))["ok"])

    def test_a_receipt_without_result_files_is_refused(self):
        other = Path(self.tmp.name) / "notes.json"
        write_json(other, {"kind": "something-else"})
        with self.assertRaisesRegex(StudioError, "result_files"):
            verify_receipt(other, project=str(self.root))

    def test_the_command_line_reports_the_same_verdict(self):
        receipt = self.launch_with_result("cli")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["evidence", "verify", "--receipt", str(receipt)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        (self.root / "artifacts/out.json").write_text("moved on", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["evidence", "verify", "--receipt", str(receipt)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["files"][0]["state"], "changed")

    def test_verify_needs_a_receipt_and_launches_still_needs_a_run_root(self):
        for argv, message in (
            (["evidence", "verify"], "--receipt"),
            (["evidence", "launches"], "run root"),
        ):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(cli.main(argv), 1)
                self.assertIn(message, json.loads(err.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
