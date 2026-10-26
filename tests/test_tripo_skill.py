"""Optional Tripo resource graph validation, with tiny engine-free fixtures."""

from pathlib import Path
import tempfile
import unittest

from studio_tools.common import read_json, write_json
from studio_tools.package import check


ROOT = Path(__file__).resolve().parents[1]
TRIPO_PATH = "skills/studio-tripo/SKILL.md"
TRIPO_REFERENCE = "skills/studio-tripo/references/provider-workflow.md"


class TripoPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio tripo graph ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {
            "name": "game-studio-kit", "version": "0.1.9",
            "skills": [skill for skill in read_json(ROOT / "studio-kit.json")["skills"]
                       if skill["name"] != "studio-tripo"],
            "resources": [],
        }
        for skill in self.manifest["skills"]:
            self.skill_file(skill["name"], skill["path"])
        write_json(self.root / ".codex-plugin/plugin.json", {
            "name": "game-studio-kit", "version": "0.1.9", "skills": "./skills/",
        })
        write_json(self.root / "upstream-lock.json", {"sources": []})
        (self.root / "templates").mkdir()

    def skill_file(self, name, path):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"---\nname: {name}\ndescription: Test graph fixture.\n---\n",
                          encoding="utf-8")

    def add_tripo(self):
        self.manifest["skills"].append({"name": "studio-tripo", "path": TRIPO_PATH})
        self.manifest["resources"].append(TRIPO_REFERENCE)
        self.skill_file("studio-tripo", TRIPO_PATH)
        target = self.root / TRIPO_REFERENCE
        target.parent.mkdir(parents=True)
        target.write_text("# Provider workflow\n", encoding="utf-8")

    def result(self):
        write_json(self.root / "studio-kit.json", self.manifest)
        return check(self.root)

    def assert_failure(self, message):
        result = self.result()
        self.assertFalse(result["ok"])
        self.assertTrue(any(message in error for error in result["errors"]), result)

    def test_base_fifteen_without_tripo_still_passes(self):
        self.assertEqual(self.result(), {"ok": True, "errors": []})

    def test_sixteen_with_declared_skill_and_workflow_passes(self):
        self.add_tripo()
        self.assertEqual(self.result(), {"ok": True, "errors": []})

    def test_arbitrary_extra_skill_does_not_enable_optional_count(self):
        self.manifest["skills"].append({"name": "studio-other", "path": "skills/studio-other/SKILL.md"})
        self.skill_file("studio-other", "skills/studio-other/SKILL.md")
        self.assert_failure("expected 15 distinct")

    def test_a_base_skill_replaced_by_another_name_fails(self):
        self.manifest["skills"] = [s for s in self.manifest["skills"] if s["name"] != "studio-gym"]
        self.manifest["skills"].append({"name": "studio-other", "path": "skills/studio-other/SKILL.md"})
        self.skill_file("studio-other", "skills/studio-other/SKILL.md")
        self.assert_failure("missing required skill declaration: studio-gym")

    def test_description_must_be_a_yaml_plain_scalar(self):
        path = "skills/studio-gym/SKILL.md"
        (self.root / path).write_text(
            "---\nname: studio-gym\ndescription: Build a gym for a game: rooms.\n---\n", encoding="utf-8")
        self.assert_failure("description is not a valid one-line YAML scalar: " + path)

    def test_quoted_descriptions_are_validated_not_exempted(self):
        path = "skills/studio-gym/SKILL.md"
        for bad in ('"Build a game: safely', "'Build a game's gym'", '"Build\\q"', '"Build\\u12xy"', '"Build\\uD800"', '"Build\\U00110000"'):
            (self.root / path).write_text(
                f"---\nname: studio-gym\ndescription: {bad}\n---\n", encoding="utf-8")
            self.assert_failure("description is not a valid one-line YAML scalar: " + path)
        for good in ('"Build a game: safely"', "'Build a game''s gym: rooms'", '"Tab\\t and \\u00e9"', '"Slash \\\\uD800"', '"Emoji \\U0001F600"', '"Accent \\u00e9abcd"'):
            (self.root / path).write_text(
                f"---\nname: studio-gym\ndescription: {good}\n---\n", encoding="utf-8")
            self.assertEqual(self.result(), {"ok": True, "errors": []})

    def test_plain_descriptions_follow_the_indicator_lookahead(self):
        path = "skills/studio-gym/SKILL.md"
        for bad in ("   ", "- list item", "? key", ": value", "-"):
            (self.root / path).write_text(
                f"---\nname: studio-gym\ndescription: {bad}\n---\n", encoding="utf-8")
            self.assert_failure("description is not a valid one-line YAML scalar: " + path)
        for good in ("-based workflows", "?help", ":colon start"):
            (self.root / path).write_text(
                f"---\nname: studio-gym\ndescription: {good}\n---\n", encoding="utf-8")
            self.assertEqual(self.result(), {"ok": True, "errors": []})

    def test_tripo_replacing_a_base_skill_does_not_pass_with_fifteen(self):
        self.add_tripo()
        self.manifest["skills"].pop(0)
        self.assert_failure("expected 16 distinct")

    def test_missing_tripo_skill_fails(self):
        self.add_tripo()
        (self.root / TRIPO_PATH).unlink()
        self.assert_failure("missing skill: " + TRIPO_PATH)

    def test_wrong_tripo_metadata_fails(self):
        self.add_tripo()
        self.skill_file("studio-other", TRIPO_PATH)
        self.assert_failure("invalid skill metadata: " + TRIPO_PATH)

    def test_misdeclared_tripo_path_fails(self):
        self.add_tripo()
        self.manifest["skills"][-1]["path"] = "skills/studio-other/SKILL.md"
        self.skill_file("studio-tripo", "skills/studio-other/SKILL.md")
        self.assert_failure("canonical skill path")

    def test_undeclared_tripo_directory_fails(self):
        self.skill_file("studio-tripo", TRIPO_PATH)
        self.assert_failure("require its skill declaration")

    def test_dangling_tripo_resource_fails(self):
        self.manifest["resources"].append(TRIPO_REFERENCE)
        self.assert_failure("require its skill declaration")

    def test_workflow_must_be_declared(self):
        self.add_tripo()
        self.manifest["resources"].clear()
        self.assert_failure("workflow must be declared")

    def test_workflow_must_exist(self):
        self.add_tripo()
        (self.root / TRIPO_REFERENCE).unlink()
        self.assert_failure("missing resource: " + TRIPO_REFERENCE)


if __name__ == "__main__":
    unittest.main()
