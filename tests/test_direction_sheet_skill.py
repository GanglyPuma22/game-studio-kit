"""The direction sheet skill, its template and the avoid ledger script are shipped files; check what they promise."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from studio_tools.common import read_json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills/studio-direction-sheet"
SKILL = BASE / "SKILL.md"
REFERENCES = BASE / "references"
SCRIPT = BASE / "scripts/avoid_ledger.py"
TEMPLATE = ROOT / "templates/direction-sheet.md"
SPEC = importlib.util.spec_from_file_location("avoid_ledger", SCRIPT)
ledger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ledger)

DECISIONS = ("D1", "D2", "D3", "D4", "D5", "D6", "D7")


def entry(**overrides):
    base = {"id": "a-walk-gap", "date": "2026-11-05", "tags": ["large", "walk", "rig"],
            "tried": "walk on rigid pieces", "failed": "gaps at every bend",
            "impact": "two days of retakes", "lesson": "skin one mesh first", "decision": "D3"}
    base.update(overrides)
    return base


class DirectionSheetSkillTests(unittest.TestCase):
    def test_skill_is_declared_with_its_references_script_and_template(self):
        manifest = read_json(ROOT / "studio-kit.json")
        self.assertIn({"name": "studio-direction-sheet", "path": "skills/studio-direction-sheet/SKILL.md"},
                      manifest["skills"])
        for path in sorted(REFERENCES.glob("*.md")):
            self.assertIn(path.relative_to(ROOT).as_posix(), manifest["resources"])
        self.assertIn("skills/studio-direction-sheet/scripts/avoid_ledger.py", manifest["resources"])
        self.assertIn("templates/direction-sheet.md", manifest["resources"])

    def test_skill_and_template_carry_all_seven_decisions(self):
        skill = SKILL.read_text(encoding="utf-8")
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertTrue(re.search(r"^name: studio-direction-sheet$", skill, re.M))
        for decision in DECISIONS:
            self.assertIn(f"| {decision} |", skill)
            self.assertIn(f"## {decision}.", template)

    def test_the_real_time_limits_are_stated(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("No stepped cadence on locomotion, blend spaces, camera", skill)
        self.assertIn("Loops are for idles and ambient material only", skill)
        self.assertIn("Anticipation length is a balance value", skill)
        self.assertIn("documents, it does not forbid", (REFERENCES / "avoid-ledger.md").read_text(encoding="utf-8"))

    def test_both_keep_kill_lanes_exist(self):
        text = (REFERENCES / "keep-kill.md").read_text(encoding="utf-8")
        self.assertIn("## In-engine", text)
        self.assertIn("## Video", text)

    def test_references_are_reachable_from_the_skill(self):
        skill = SKILL.read_text(encoding="utf-8")
        for name in ("decisions.md", "keep-kill.md", "avoid-ledger.md"):
            self.assertIn(f"(references/{name}", skill)
        self.assertIn("(../../templates/direction-sheet.md)", skill)

    def test_shipped_files_name_no_game(self):
        # The ledger's entries belong to a game's own repository, never to the kit.
        for path in [SKILL, TEMPLATE, SCRIPT, *REFERENCES.glob("*.md")]:
            text = path.read_text(encoding="utf-8").lower()
            for name in ("skybreak", "tetherquake", "vaulter", "warden", "salvage"):
                self.assertNotIn(name, text, path)


class AvoidLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "design" / "avoid-ledger.jsonl"

    def test_add_then_query_by_tags_and_text(self):
        ledger.add(self.path, entry())
        ledger.add(self.path, entry(id="a-burst-orb", tags=["large", "particles"], tried="round burst",
                                    failed="read as an orb", decision="D7", date="2026-11-20"))
        self.assertEqual([e["id"] for e in ledger.query(self.path, ["large"])], ["a-burst-orb", "a-walk-gap"])
        self.assertEqual([e["id"] for e in ledger.query(self.path, ["large", "walk"])], ["a-walk-gap"])
        self.assertEqual(len(ledger.query(self.path, ["walk", "particles"], any_tag=True)), 2)
        self.assertEqual([e["id"] for e in ledger.query(self.path, words=["orb"])], ["a-burst-orb"])
        self.assertEqual([e["id"] for e in ledger.query(self.path, decision="D3")], ["a-walk-gap"])

    def test_superseded_entries_stay_but_leave_default_queries(self):
        ledger.add(self.path, entry())
        ledger.set_status(self.path, "a-walk-gap", "superseded", superseded_by="one-skin rig")
        self.assertEqual(ledger.query(self.path, ["walk"]), [])
        kept = ledger.query(self.path, ["walk"], all_status=True)
        self.assertEqual(kept[0]["superseded_by"], "one-skin rig")
        self.assertIn("[superseded]", ledger.brief(kept[0]))

    def test_add_refuses_bad_or_duplicate_entries(self):
        ledger.add(self.path, entry())
        with self.assertRaises(ledger.LedgerError):
            ledger.add(self.path, entry())
        for bad in ({"tags": ["Upper Case"]}, {"impact": ""}, {"decision": "D9"}, {"date": "27/11/2026"},
                    {"colour": "red"}, {"status": "banned"}):
            with self.assertRaises(ledger.LedgerError):
                ledger.add(self.path, entry(id="other", **bad))

    def test_check_names_the_bad_line(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(entry()) + "\nnot json\n", encoding="utf-8")
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.load(self.path)
        self.assertIn("line 2", str(caught.exception))

    def test_a_markdown_ledger_keeps_its_prose_and_fence(self):
        path = Path(self.tmp.name) / "avoid-ledger.md"
        path.write_text("# Avoid ledger\n\nNotes about the file.\n\n```jsonl\n```\n", encoding="utf-8")
        ledger.add(path, entry())
        ledger.add(path, entry(id="second", tags=["walk"]))
        ledger.set_status(path, "second", "retired", note="system replaced")
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Avoid ledger\n\nNotes about the file."))
        self.assertTrue(text.rstrip().endswith("```"))
        self.assertEqual([e["id"] for e in ledger.query(path, ["walk"])], ["a-walk-gap"])
        self.assertEqual(ledger.query(path, all_status=True, words=["replaced"])[0]["status"], "retired")

    def test_cli_prints_one_line_per_entry(self):
        ledger.add(self.path, entry())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ledger.main(["query", str(self.path), "--tag", "walk"]), 0)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("a-walk-gap D3 [large,walk,rig] tried walk on rigid pieces", lines[0])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ledger.main(["check", str(self.path)]), 0)
            self.assertEqual(ledger.main(["add", str(self.path), "--json", json.dumps(entry())]), 2)


if __name__ == "__main__":
    unittest.main()
