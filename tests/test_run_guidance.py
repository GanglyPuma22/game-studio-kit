"""The run guidance a Codex agent executes: waiting, feature rows, tiers, snapshots."""

from pathlib import Path
import unittest

from studio_tools.cli import parser
from studio_tools.common import read_json

ROOT = Path(__file__).resolve().parents[1]
PROCEDURE = ROOT / "skills/studio-director/references/overnight-run.md"
BLOCK = ROOT / "references/codex/AGENTS-overnight.md"
EXECUTION = ROOT / "skills/studio-godot/references/execution.md"
PLAYTEST = ROOT / "skills/studio-playtest/SKILL.md"
REVIEW = ROOT / "skills/studio-review/SKILL.md"
GAME_DESIGN = ROOT / "skills/studio-game-design/SKILL.md"
MANIFEST = ROOT / "templates/feature-manifest.json"
RETURN = ROOT / "templates/return.md"
STATE = ROOT / "templates/state.md"
CHANGED_MARKDOWN = (PROCEDURE, BLOCK, PLAYTEST, REVIEW, GAME_DESIGN, RETURN, STATE)


def text(path):
    return path.read_text(encoding="utf-8")


class WaitingGuidanceTests(unittest.TestCase):
    def test_every_blocking_place_names_the_outer_yield_directive(self):
        # The agent that polled a launch had no way to know the 30 s return was
        # its own harness default, so each place a launch is described names the
        # directive that holds the call open.
        for path in (PROCEDURE, BLOCK, EXECUTION):
            body = text(path)
            self.assertIn('yield_time_ms', body, path.name)
            self.assertIn('// @exec:', body, path.name)
            self.assertIn("plus 30) times", body, path.name)
            self.assertIn("30 seconds", body, path.name)
            self.assertIn("verdict JSON", body, path.name)

    def test_the_only_continuation_is_one_sized_wait(self):
        for path in (PROCEDURE, BLOCK, EXECUTION):
            body = text(path)
            self.assertIn("`wait`", body, path.name)
            self.assertIn("`write_stdin`", body, path.name)
            self.assertIn("repeated short waits", body, path.name)

    def test_an_early_return_is_not_a_reason_to_start_a_second_engine(self):
        self.assertIn("not a host cap", text(PROCEDURE))
        self.assertIn("not a host cap", text(BLOCK))
        for path in (PROCEDURE, BLOCK, EXECUTION):
            self.assertIn("second", text(path), path.name)
        self.assertIn("263", text(PROCEDURE))

    def test_cleanroom_section_points_at_the_directive_and_its_own_timeout(self):
        procedure = text(PROCEDURE)
        section = procedure[procedure.index("## 4. Benchmarks"):procedure.index("## 5. Return")]
        self.assertIn("outer yield directive", section)
        self.assertIn("not from\nthe nested launch's", section)
        self.assertIn("agent activity log", section)

    def test_blocking_commands_tell_the_caller_to_wait(self):
        choices = parser()._subparsers._group_actions[0].choices
        for name in ("launch", "batch", "playtest"):
            description = choices[name].description or ""
            self.assertIn("blocks", description, name)
            self.assertIn("wait at least that long", description, name)
            self.assertIn("wait", choices[name].format_help(), name)


class FeatureManifestTests(unittest.TestCase):
    def test_template_parses_and_carries_the_row_fields(self):
        record = read_json(MANIFEST)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["kind"], "feature-manifest")
        self.assertEqual(record["canonical_route"], [])
        self.assertEqual(len(record["features"]), 1)
        row = record["features"][0]
        for field in (
            "feature",
            "route_step",
            "entry",
            "launch_flags",
            "source_revision",
            "installed_by",
            "human_verdict",
            "evidence",
            "content_digest",
        ):
            self.assertIn(field, row)
        self.assertEqual(row["human_verdict"], "pending")
        self.assertIsInstance(row["evidence"], list)

    def test_template_is_a_listed_resource(self):
        resources = set(read_json(ROOT / "studio-kit.json")["resources"])
        self.assertIn("templates/feature-manifest.json", resources)

    def test_procedure_names_the_manifest_path_and_the_return_obligation(self):
        procedure = text(PROCEDURE)
        self.assertIn("<run>/artifacts/run/feature-manifest.json", procedure)
        self.assertIn("feature-manifest.json", text(RETURN) + text(STATE))
        ret = procedure[procedure.index("## 5. Return"):procedure.index("## 6. Stop rules")]
        self.assertIn("**Accepted features.**", ret)
        self.assertIn("`human_verdict`", ret)
        self.assertIn("Not demonstrated", ret)
        self.assertIn("Accepted features", text(RETURN))

    def test_playtest_owns_the_canonical_route_and_review_owns_the_wiring_gap(self):
        playtest = text(PLAYTEST)
        self.assertIn("## The canonical route", playtest)
        self.assertIn("canonical_route", playtest)
        self.assertIn("installed_by", playtest)
        self.assertIn("Observed in the scene where it was built is not that", playtest)
        review = text(REVIEW)
        self.assertIn("wiring gap", review)
        self.assertIn("`human_verdict`", review)
        self.assertIn("`content_digest`", review)


class CreatureTierTests(unittest.TestCase):
    def test_game_design_defines_the_three_tiers_with_their_tests(self):
        design = text(GAME_DESIGN)
        for tier in ("Animated asset", "Resident", "Gameplay-ready encounter"):
            self.assertIn(f"**{tier}.**", design)
        self.assertEqual(design.count("Test:"), 3)
        self.assertIn("only the gameplay-ready encounter may be called gameplay-ready", design)

    def test_review_refuses_an_untiered_creature_claim(self):
        self.assertIn("is not a claim", text(REVIEW))


class SnapshotCommitTests(unittest.TestCase):
    def test_authorization_line_and_branch_are_named_in_both_rule_sets(self):
        for path in (PROCEDURE, BLOCK):
            body = text(path)
            self.assertIn("`snapshot_commit: authorized`", body, path.name)
            self.assertIn("`run/<run-id>`", body, path.name)
            self.assertIn("never evidence of acceptance", body, path.name)

    def test_the_commit_is_one_commit_at_return_with_a_fixed_message(self):
        procedure = text(PROCEDURE)
        ret = procedure[procedure.index("## 5. Return"):procedure.index("## 6. Stop rules")]
        self.assertIn("`run <run-id>: snapshot at Return`", ret)
        self.assertIn("A run commits nothing by default", ret)
        self.assertIn("No push, no merge, no rebase", ret)
        self.assertIn("uncommitted overlay: <staged> staged, <untracked>", ret)

    def test_both_records_carry_the_snapshot_line(self):
        for path in (RETURN, STATE):
            body = text(path)
            self.assertIn("run/<run-id>", body, path.name)
            self.assertIn("uncommitted overlay: <staged> staged, <untracked> untracked", body, path.name)


class PortabilityTests(unittest.TestCase):
    def test_changed_markdown_carries_no_absolute_host_path(self):
        for path in CHANGED_MARKDOWN:
            body = text(path)
            for forbidden in ("C:\\", "/home/", "/mnt/"):
                self.assertNotIn(forbidden, body, f"{path.name} contains {forbidden}")

    def test_the_launch_section_of_execution_md_stays_portable(self):
        # The rest of the file documents export-template roots, whose example
        # paths are placeholders the reader replaces.
        body = text(EXECUTION)
        section = body[body.index("## Owned blocking launch"):]
        for forbidden in ("C:\\", "/home/", "/mnt/"):
            self.assertNotIn(forbidden, section, f"execution.md launch section contains {forbidden}")


if __name__ == "__main__":
    unittest.main()
