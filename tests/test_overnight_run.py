"""The packaged overnight-run procedure, global block and templates stay consistent."""

from pathlib import Path
import re
import unittest

from studio_tools.common import read_json, safe_id

ROOT = Path(__file__).resolve().parents[1]
PROCEDURE = ROOT / "skills/studio-director/references/overnight-run.md"
BLOCK = ROOT / "references/codex/AGENTS-overnight.md"
TEMPLATES = [ROOT / "templates" / name for name in ("return.md", "worker-brief.md", "state.md")]
SCOPE_LADDER_IDS = ("macro-terrain", "three-sites", "hero-obstructions", "habitat-chunk")


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
        self.assertIn("bench cleanroom --project <run>", example)
        self.assertIn("--timeout 2700", example)
        self.assertIn("persist it in\ntheir receipts", procedure)

    def test_stage_four_and_five_state_their_launch_totals(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("one capture per rung plus one repeat (five for the four-rung example)", procedure)
        self.assertIn("3 per hypothesis, 6 in total", procedure)
        self.assertIn("stop at 6 total launches", procedure)

    def test_run_id_convention_and_evidence_root_are_defined(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("`<GAME>` and `<run>` are the same path", procedure)
        self.assertIn("must start with `<run-id>-`", procedure)
        self.assertIn("evidence launches <run>/artifacts/launches", procedure)
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

    def test_setup_windows_pointer_install_carries_a_recognizable_marker(self):
        setup = (ROOT / "docs/setup-windows.md").read_text(encoding="utf-8")
        self.assertIn("game-studio-kit overnight-run pointer", setup)
        marker_index = setup.index("game-studio-kit overnight-run pointer")
        # The marker is checked with Test-Path/Select-String before the pointer
        # file is (re)written with Set-Content.
        self.assertLess(setup.index("Test-Path $PointerPath"), setup.index("Set-Content -Path $PointerPath"))
        self.assertLess(marker_index, setup.index("Set-Content -Path $PointerPath"))

    def test_scope_ladder_rung_ids_are_safe_id_valid(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        for rung_id in SCOPE_LADDER_IDS:
            self.assertIn(f"`{rung_id}`", procedure)
            self.assertEqual(safe_id(rung_id), rung_id)

    def test_nested_launch_in_benchmark_example_carries_its_own_config(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        section = procedure[procedure.index("## 4. Benchmarks"):procedure.index("## 5. Root refresh")]
        code_start = section.index("```text")
        code = section[code_start:section.index("```", code_start + len("```text"))]
        self.assertEqual(code.count("--config <host config>"), 2)
        self.assertIn("launch --project <run> --config <host config>", code)
        self.assertIn("does not propagate", section)

    def test_stop_rules_mark_which_stages_are_retryable(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertEqual(procedure.count("(retryable)"), 3)
        for stage in ("Native admission", "Performance cleanroom", "Traversal"):
            self.assertIn(stage, procedure)

    def test_setup_windows_checks_pointer_conflict_before_appending_global_rules(self):
        setup = (ROOT / "docs/setup-windows.md").read_text(encoding="utf-8")
        conflict_index = setup.index("Refusing to overwrite $PointerPath")
        for needle in ("Add-Content -Path $AgentsPath", "Set-Content -Path $AgentsPath"):
            self.assertLess(conflict_index, setup.index(needle))
        self.assertIn("game-studio-kit overnight-rules begin", setup)
        self.assertIn("game-studio-kit overnight-rules end", setup)
        self.assertIn("Singleline", setup)
        self.assertIn("only one game-studio-kit overnight-rules marker", setup)

    def test_agents_overnight_block_is_wrapped_in_markers(self):
        text = BLOCK.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!-- game-studio-kit overnight-rules begin -->"))
        self.assertTrue(text.rstrip("\n").endswith("<!-- game-studio-kit overnight-rules end -->"))

    def test_worktree_precedes_verification_in_preflight(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        preflight = procedure[procedure.index("## 1. Preflight"):procedure.index("## 2. Stage gates")]
        self.assertLess(preflight.index("git worktree add"), preflight.index("candidate verify"))
        self.assertIn("records identities at the moment it runs", preflight)

    def test_run_directory_is_the_worktree(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("`<GAME>` and `<run>` are the same path", procedure)
        for path in (
            "<run>/artifacts/run/STATE.md",
            "<run>/artifacts/run/host/",
            "<run>/artifacts/run/identity-manifest.json",
        ):
            self.assertIn(path, procedure)
        self.assertNotIn("<GAME>/artifacts/runs", procedure)

    def test_stage2_compile_verdict_gates_candidate_creation(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("compile_verdict: pass", procedure)
        self.assertIn("compile_verdict: fail", procedure)
        self.assertIn("candidate new --project <run>", procedure)
        self.assertIn("validate-record --project <run> --record artifacts/candidate.json", procedure)
        brief = (ROOT / "templates/worker-brief.md").read_text(encoding="utf-8")
        self.assertIn('"compile_verdict": "pass" | "fail"', brief)

    def test_stage5_launch_uses_explicit_native_mode(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("| 5 Traversal | root | `launch --mode native", procedure)
        self.assertIn("with the game's route probe and synthetic input", procedure)
        self.assertIn("default mode is `import`", procedure)

    def test_preflight_stop_rule_is_scoped_to_windows(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        block = BLOCK.read_text(encoding="utf-8")
        for text in (procedure, block):
            self.assertIn("host_kind: unsupported", text)
            self.assertIn("Windows", text)

    def test_launch_inventory_root_is_the_run_worktree(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("never reuses a worktree", procedure)
        self.assertIn("There is no\nflag to filter by run", procedure)

    def test_worker_brief_omits_incomplete_fields_instead_of_using_null(self):
        brief = (ROOT / "templates/worker-brief.md").read_text(encoding="utf-8")
        self.assertNotIn("use `null`", brief)
        self.assertIn("omit any field not produced", brief)
        self.assertIn("incomplete_fields", brief)

    def test_state_md_checkpoints_are_enumerated(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("is write-once", procedure)
        self.assertIn("rewritten atomically", procedure)
        for checkpoint in ("after each preflight attempt", "at each stage transition", "after the third compaction", "at handback"):
            self.assertIn(checkpoint, procedure)

    def test_corrections_invalidate_all_stage_evidence(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("every stage 3-7 receipt recorded under the previous digest is invalid", procedure)
        self.assertIn("no exception for a correction that only touched a renderer, LOD or scope setting", procedure)
        self.assertIn("stages 3 through 7 are repeated in order under the new digest", procedure)
        self.assertEqual(procedure.count("may cite only receipts produced under the final"), 2)
        self.assertNotIn("Stage 4 runs immediately after any renderer, LOD or scope change and blocks", procedure)
        state = (ROOT / "templates/state.md").read_text(encoding="utf-8")
        self.assertIn("Candidate digest", state)

    def test_worker_paths_live_under_artifacts_run(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        brief = (ROOT / "templates/worker-brief.md").read_text(encoding="utf-8")
        for text in (procedure, brief):
            self.assertIn("<run>/artifacts/run/workers/", text)
            self.assertNotIn("<run>/workers/", text)

    def test_launch_rows_bound_by_stage_deadline(self):
        procedure = PROCEDURE.read_text(encoding="utf-8")
        # 4 stage-table rows (3, 5, 6, 7) plus the cleanroom-wrapped launch in Section 4.
        self.assertEqual(
            procedure.count("--timeout <remaining, max 3600> --cutoff-utc <stage deadline>"), 5
        )
        section = procedure[procedure.index("## 4. Benchmarks"):procedure.index("## 5. Root refresh")]
        self.assertIn("--timeout <remaining, max 3600> --cutoff-utc <stage deadline>", section)
        self.assertIn("host config's default timeout is not a stage bound", procedure)

    def test_scorecard_has_five_separate_review_dimensions(self):
        text = (ROOT / "templates/return.md").read_text(encoding="utf-8")
        for dimension in ("Visual", "Interaction", "Motion", "Audio", "Performance"):
            self.assertIn(f"6/7 {dimension} | pass / fail / not_run", text)
        self.assertNotIn("| 6 Visual review |", text)
        self.assertNotIn("| 7 Audiovisual and human acceptance |", text)

    def test_setup_linux_has_global_rules_install_with_markers(self):
        setup = (ROOT / "docs/setup-linux.md").read_text(encoding="utf-8")
        self.assertIn("game-studio-kit overnight-rules begin", setup)
        self.assertIn("game-studio-kit overnight-rules end", setup)
        self.assertIn("game-studio-kit overnight-run pointer", setup)
        self.assertLess(setup.index("Refusing to overwrite"), setup.index("python3 -"))
        procedure = PROCEDURE.read_text(encoding="utf-8")
        self.assertIn("setup-linux.md#install-global-codex-rules-for-unattended-runs", procedure)


if __name__ == "__main__":
    unittest.main()
