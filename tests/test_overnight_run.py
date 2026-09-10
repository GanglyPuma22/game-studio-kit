"""The packaged overnight-run procedure, global block and templates stay consistent."""

from pathlib import Path
import re
import unittest

from studio_tools.common import read_json

ROOT = Path(__file__).resolve().parents[1]
PROCEDURE = ROOT / "skills/studio-director/references/overnight-run.md"
BLOCK = ROOT / "references/codex/AGENTS-overnight.md"
TEMPLATES = [ROOT / "templates" / name for name in ("return.md", "worker-brief.md", "state.md")]


class OvernightRunTests(unittest.TestCase):
    def test_every_named_command_exists(self):
        commands = set(read_json(ROOT / "studio-kit.json")["commands"])
        for path in (PROCEDURE, BLOCK):
            text = path.read_text(encoding="utf-8")
            named = set(re.findall(r"studio(?:\.py)? ([a-z-]+)", text))
            self.assertTrue(named, path.name)
            self.assertFalse(named - commands, f"{path.name} names unknown commands: {named - commands}")
        procedure = PROCEDURE.read_text(encoding="utf-8")
        for needle in ("host preflight", "candidate verify", "bench cleanroom", "evidence launches", "launch --mode native"):
            self.assertIn(needle, procedure)

    def test_rules_carry_no_host_specific_paths_or_names(self):
        for path in (PROCEDURE, BLOCK, *TEMPLATES):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("C:\\Users\\", "/home/", "/mnt/c/", "Maxim", "Salvage"):
                self.assertNotIn(forbidden, text, f"{path.name} contains {forbidden}")

    def test_block_and_procedure_state_the_budgets_and_ladder(self):
        block = BLOCK.read_text(encoding="utf-8")
        procedure = PROCEDURE.read_text(encoding="utf-8")
        for text in (block, procedure):
            self.assertIn("90 minutes, 8M tokens, two compactions", text)
            self.assertIn("third", text)
            self.assertIn("never cited for a higher one", text)
            self.assertIn("Never claim acceptance from exit codes", text)
        self.assertIn("| 4 Performance cleanroom |", procedure)
        self.assertIn("attributable", procedure)

    def test_templates_are_listed_and_referenced(self):
        resources = set(read_json(ROOT / "studio-kit.json")["resources"])
        for path in (PROCEDURE, BLOCK, *TEMPLATES):
            self.assertIn(path.relative_to(ROOT).as_posix(), resources)
        procedure = PROCEDURE.read_text(encoding="utf-8")
        for template in TEMPLATES:
            self.assertIn(template.name, procedure)
        director = (ROOT / "skills/studio-director/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/overnight-run.md", director)
        setup = (ROOT / "docs/setup-windows.md").read_text(encoding="utf-8")
        self.assertIn("AGENTS-overnight.md", setup)

    def test_return_template_leads_with_player_facing_metrics(self):
        text = (ROOT / "templates/return.md").read_text(encoding="utf-8")
        self.assertLess(text.index("Player-facing outcome"), text.index("Scorecard"))
        self.assertLess(text.index("Not demonstrated"), text.index("Evidence index"))

    def test_benchmark_example_scopes_both_commands_and_caps_the_capture_timeout(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        example = procedure[procedure.index("## 4. Benchmarks"):procedure.index("## 5. Root refresh")]
        self.assertEqual(example.count("--scope <rung>"), 2)
        self.assertIn("bench cleanroom --project <GAME>", example)
        self.assertIn("--timeout 2700", example)
        self.assertIn("persist it in\ntheir receipts", procedure)

    def test_stage_four_and_five_state_their_launch_totals(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("one capture per rung plus one repeat (five for the four-rung example)", procedure)
        self.assertIn("3 per hypothesis, 6 in total", procedure)
        self.assertIn("stop at 6 total launches", procedure)

    def test_run_id_convention_and_evidence_root_are_defined(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("`<run>` is `<GAME>/artifacts/runs/<run-id>/`", procedure)
        self.assertIn("must start with `<run-id>-`", procedure)
        self.assertIn("evidence launches <GAME>/artifacts/launches", procedure)
        for template in (ROOT / "templates/return.md", ROOT / "templates/state.md"):
            self.assertIn("<run-id>-<stage>-<n>", template.read_text(encoding="utf-8"))

    def test_worker_brief_schema_uses_status_and_incomplete_fields(self):
        brief = (ROOT / "templates/worker-brief.md").read_text(encoding="utf-8")
        self.assertIn('"status": "complete" | "incomplete"', brief)
        self.assertIn('"incomplete_fields": []', brief)
        self.assertNotIn("not_run", brief)

    def test_setup_windows_creates_codex_dir_before_first_add_content(self):
        setup = (ROOT / "docs/setup-windows.md").read_text(encoding="utf-8")
        self.assertLess(
            setup.index('New-Item -ItemType Directory -Force -Path $Codex'),
            setup.index("Add-Content"),
        )


if __name__ == "__main__":
    unittest.main()
