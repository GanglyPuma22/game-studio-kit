"""Shared package guard; actual Claude discovery is a separate host check."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import evidence, package
from studio_tools.evidence import new_candidate

ROOT = Path(__file__).resolve().parents[1]


class ClaudePackageTests(unittest.TestCase):
    def copied_kit(self):
        temporary = tempfile.TemporaryDirectory(prefix="claude package ")
        self.addCleanup(temporary.cleanup)
        kit = Path(temporary.name) / "kit with spaces"
        shutil.copytree(ROOT, kit, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return kit

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
        kit = self.copied_kit()
        (kit / ".claude-plugin/plugin.json").unlink()
        (kit / ".claude-plugin/marketplace.json").unlink()
        readme = kit / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8").replace(
            "[.claude-plugin/plugin.json](.claude-plugin/plugin.json)", "the optional Claude manifest"
        ), encoding="utf-8")
        manifest_path = kit / "studio-kit.json"
        manifest = package.read_json(manifest_path)
        manifest["resources"] = [name for name in manifest["resources"] if not name.startswith(".claude-plugin/")]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(package.check(kit), {"ok": True, "errors": []})
        code = re.search(r"```python\n(.*?)\n```", (kit / "docs/plugin-staging.md").read_text(), re.S).group(1)
        receipt = kit.parent / "legacy-staging.json"
        subprocess.run([sys.executable, "-c", code, str(kit), "0.1.9+staging.legacy", str(receipt), "a" * 40],
                       cwd=kit.parent, capture_output=True, text=True, check=True)
        self.assertEqual(set(package.read_json(receipt)["files"]), {".codex-plugin/plugin.json", "studio-kit.json"})
        self.assertEqual(package.check(kit), {"ok": True, "errors": []})

    def test_malformed_claude_manifest_returns_structured_errors(self):
        kit = self.copied_kit()
        target = kit / ".claude-plugin/plugin.json"
        for payload in ("{", "[]", "null", '"manifest"', "42"):
            with self.subTest(payload=payload):
                target.write_text(payload, encoding="utf-8")
                result = package.check(kit)
                self.assertFalse(result["ok"])
                self.assertTrue(result["errors"])
                self.assertTrue(all(isinstance(error, str) for error in result["errors"]))

    def test_invalid_marketplace_is_rejected(self):
        kit = self.copied_kit()
        target = kit / ".claude-plugin/marketplace.json"
        original = target.read_text(encoding="utf-8")
        mutations = {
            "wrong-name": lambda value: value.update(name="other-marketplace"),
            "missing-name": lambda value: value.pop("name"),
            "malformed-owner": lambda value: value.update(owner=[]),
            "missing-owner-name": lambda value: value.update(owner={}),
            "blank-owner-name": lambda value: value.update(owner={"name": " "}),
            "malformed-plugins": lambda value: value.update(plugins={}),
            "malformed-plugin-entry": lambda value: value.update(plugins=[None]),
            "missing-plugin-name": lambda value: value["plugins"][0].pop("name"),
            "wrong-plugin-name": lambda value: value["plugins"][0].update(name="other-kit"),
            "duplicate-plugin": lambda value: value["plugins"].append(dict(value["plugins"][0])),
            "missing-source": lambda value: value["plugins"][0].pop("source"),
            "absent-directory": lambda value: value["plugins"][0].update(source="./absent/"),
            "other-existing-directory": lambda value: value["plugins"][0].update(source="./skills/"),
            "escaping-source": lambda value: value["plugins"][0].update(source="../"),
            "malformed-source": lambda value: value["plugins"][0].update(source={"source": "github"}),
            "null-byte-source": lambda value: value["plugins"][0].update(source="\u0000"),
            "stale-entry-version": lambda value: value["plugins"][0].update(version="0.0.0"),
        }
        for label, mutation in mutations.items():
            with self.subTest(mutation=label):
                value = json.loads(original)
                mutation(value)
                target.write_text(json.dumps(value), encoding="utf-8")
                result = package.check(kit)
                self.assertFalse(result["ok"], result)
                self.assertTrue(result["errors"])
        for payload in ("{", "[]", "null"):
            with self.subTest(payload=payload):
                target.write_text(payload, encoding="utf-8")
                self.assertFalse(package.check(kit)["ok"])

    def test_shared_root_marketplace_source_and_matching_version_validate(self):
        kit = self.copied_kit()
        target = kit / ".claude-plugin/marketplace.json"
        marketplace = package.read_json(target)
        entry = marketplace["plugins"][0]
        entry["version"] = package.read_json(kit / "studio-kit.json")["version"]
        for source in (".", "./"):
            with self.subTest(source=source):
                entry["source"] = source
                target.write_text(json.dumps(marketplace), encoding="utf-8")
                self.assertEqual(package.check(kit), {"ok": True, "errors": []})

    def test_claude_manifest_is_bound_into_workflow_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "scene.gd").write_text("pass\n")
            candidate = new_candidate(project, "claude-workflow-test", "not-run", "test")
            paths = {item["path"] for item in candidate["workflow_files"]}
            self.assertIn(".claude-plugin/plugin.json", paths)
            self.assertIn(".claude-plugin/marketplace.json", paths)
            self.assertIn("docs/claude-code.md", paths)

    def test_runtime_document_bytes_change_workflow_digest(self):
        kit = self.copied_kit()
        project = kit.parent / "game"
        project.mkdir()
        (project / "scene.gd").write_text("pass\n", encoding="utf-8")
        with patch.object(evidence, "__file__", str(kit / "studio_tools/evidence.py")):
            before = new_candidate(project, "policy-before", "not-run", "test")
            document = kit / "docs/claude-code.md"
            document.write_bytes(document.read_bytes() + b"\nChanged runtime policy.\n")
            after = new_candidate(project, "policy-after", "not-run", "test")
            self.assertNotEqual(before["workflow_digest"], after["workflow_digest"])
            paths = [item["path"] for item in after["workflow_files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertEqual([name for name in paths if name.startswith("docs/")], ["docs/claude-code.md"])
            historical = kit / "docs/plugin-staging.md"
            historical.write_bytes(historical.read_bytes() + b"\nHistorical docs update.\n")
            unrelated = new_candidate(project, "policy-unrelated", "not-run", "test")
            self.assertEqual(after["workflow_digest"], unrelated["workflow_digest"])
            document.unlink()
            absent = new_candidate(project, "policy-absent", "not-run", "test")
            self.assertNotIn("docs/claude-code.md", {item["path"] for item in absent["workflow_files"]})
