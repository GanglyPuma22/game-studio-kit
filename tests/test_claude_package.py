"""Shared package guard; actual Claude discovery is a separate host check."""
from pathlib import Path
import unittest
from unittest.mock import patch

from studio_tools import package
from studio_tools.evidence import new_candidate

ROOT = Path(__file__).resolve().parents[1]


class ClaudePackageTests(unittest.TestCase):
    def test_shared_package_validates(self):
        self.assertEqual(package.check(ROOT), {"ok": True, "errors": []})

    def altered(self, mutation):
        original = package.read_json
        def read(path):
            value = original(path)
            if Path(path) == ROOT / ".claude-plugin/plugin.json":
                mutation(value)
            return value
        with patch("studio_tools.package.read_json", side_effect=read):
            return package.check(ROOT)

    def test_stale_claude_version_is_rejected(self):
        result = self.altered(lambda value: value.update(version="0.0.0"))
        self.assertFalse(result["ok"])
        self.assertIn("Claude plugin name/version disagree with package", result["errors"])

    def test_different_claude_skill_tree_is_rejected(self):
        result = self.altered(lambda value: value.update(skills="./alternate/"))
        self.assertFalse(result["ok"])
        self.assertIn("Claude plugin must load the shared skills directory", result["errors"])

    def test_old_package_without_claude_manifest_remains_supported(self):
        original = Path.is_file
        read_original = package.read_json
        def is_file(path):
            return False if path == ROOT / ".claude-plugin/plugin.json" else original(path)
        def read(path):
            value = read_original(path)
            if Path(path) == ROOT / "studio-kit.json":
                value["resources"] = [name for name in value["resources"] if not name.startswith(".claude-plugin/")]
            return value
        with patch.object(Path, "is_file", is_file), patch("studio_tools.package.read_json", side_effect=read):
            self.assertTrue(package.check(ROOT)["ok"])

    def test_claude_manifest_is_bound_into_workflow_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "scene.gd").write_text("pass\n")
            candidate = new_candidate(project, "claude-workflow-test", "not-run", "test")
            paths = {item["path"] for item in candidate["workflow_files"]}
            self.assertIn(".claude-plugin/plugin.json", paths)
            self.assertIn(".claude-plugin/marketplace.json", paths)
