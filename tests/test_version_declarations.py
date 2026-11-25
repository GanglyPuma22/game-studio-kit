"""Every version declaration of a release agrees, and check-package says so."""
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

import studio_tools
from studio_tools import package

ROOT = Path(__file__).resolve().parents[1]


class VersionDeclarationTests(unittest.TestCase):
    def copied_kit(self):
        temporary = tempfile.TemporaryDirectory(prefix="kit versions ")
        self.addCleanup(temporary.cleanup)
        kit = Path(temporary.name) / "kit"
        shutil.copytree(ROOT, kit, ignore=shutil.ignore_patterns(".git", "__pycache__", "artifacts"))
        return kit

    def rewrite(self, path, old, new):
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_source_tree_declares_one_version(self):
        manifest = package.read_json(ROOT / "studio-kit.json")["version"]
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["version"], manifest)
        self.assertEqual(studio_tools.__version__, manifest)
        self.assertEqual(package.read_json(ROOT / ".codex-plugin/plugin.json")["version"], manifest)
        self.assertEqual(package.read_json(ROOT / ".claude-plugin/plugin.json")["version"], manifest)

    def test_stale_pyproject_version_is_rejected(self):
        kit = self.copied_kit()
        version = studio_tools.__version__
        self.rewrite(kit / "pyproject.toml", f'version = "{version}"', 'version = "0.0.1"')
        result = package.check(kit)
        self.assertFalse(result["ok"])
        self.assertIn("pyproject.toml version disagrees with package", result["errors"])
        self.assertIn("pyproject.toml and studio_tools.__version__ disagree", result["errors"])

    def test_stale_module_version_is_rejected(self):
        kit = self.copied_kit()
        version = studio_tools.__version__
        self.rewrite(kit / "studio_tools/__init__.py", f'__version__ = "{version}"', '__version__ = "0.0.1"')
        result = package.check(kit)
        self.assertFalse(result["ok"])
        self.assertIn("studio_tools.__version__ version disagrees with package", result["errors"])

    def test_staged_manifest_suffix_keeps_the_python_version(self):
        kit = self.copied_kit()
        version = studio_tools.__version__
        for name in ("studio-kit.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
            self.rewrite(kit / name, f'"version": "{version}"', '"version": "0.1.1+staging.test"')
        self.assertEqual(package.check(kit), {"ok": True, "errors": []})


if __name__ == "__main__":
    unittest.main()
