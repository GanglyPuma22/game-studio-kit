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
CONTRACTS = ROOT / "references/production-contracts.md"
MANIFEST = ROOT / "templates/feature-manifest.json"
RETURN = ROOT / "templates/return.md"
STATE = ROOT / "templates/state.md"
CHANGED_MARKDOWN = (PROCEDURE, BLOCK, PLAYTEST, REVIEW, GAME_DESIGN, CONTRACTS, RETURN, STATE)


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
            self.assertNotIn("effective outer yield is capped", body, path.name)
        # An early return has three possible causes and none of them is a hang.
        self.assertIn("never evidence that the run hung", text(PROCEDURE))
        for path in (BLOCK, EXECUTION):
            self.assertIn("undersized", text(path), path.name)

    def test_sizing_is_stated_per_command_because_only_launch_has_a_timeout(self):
        # `batch` and `playtest` have no `--timeout`, so one formula could not
        # be followed; the procedure carries the table and the block summarises it.
        procedure = text(PROCEDURE)
        self.assertIn("only `launch` has a\n`--timeout`", procedure)
        for row in (
            "| `launch` | (`--timeout` in seconds plus 30) times 1000 |",
            "(`--max-minutes` times 60, plus 30) times 1000",
            "`playtest --session handoff --max-minutes 0` | the harness's maximum",
            "| `playtest --session attended` | none.",
        ):
            self.assertIn(row, procedure)
        self.assertIn("An omitted `--max-minutes` is 60 minutes", procedure)
        block = text(BLOCK)
        self.assertIn("only `launch` has a `--timeout`", block)
        self.assertIn("(`--max-minutes` times 60, plus 30) times 1000", block)
        self.assertIn("`playtest --session attended` is never waited for", block)
        execution = text(EXECUTION)
        self.assertIn("That formula is `launch`'s own", execution)
        self.assertIn("sized from `--max-minutes` instead", execution)

    def test_an_early_return_takes_exactly_one_sized_wait(self):
        procedure = text(PROCEDURE)
        self.assertIn(
            "When the call returns early despite the directive, the expected path is exactly\n"
            "one `wait` sized to the time the command still has, and that `wait` is not\n"
            "polling",
            procedure,
        )
        self.assertIn("the same single sized `wait` is expected after an uncapped `handoff`", procedure)
        self.assertIn("a single sized `wait` after an early return is expected", text(BLOCK))

    def test_no_claim_is_made_about_a_harness_cap(self):
        # The measurement (360 s directive, 263 s held) contradicts a claimed
        # 30,000 ms ceiling, so the text states what was measured and leaves the
        # harness's behaviour open rather than asserting either.
        procedure = text(PROCEDURE)
        self.assertIn("the\ndirective is what has been measured to hold a call open", procedure)
        self.assertIn("Harness versions may cap\nit, and this procedure claims neither that they do nor that they do not", procedure)
        self.assertNotIn("30,000", procedure)
        self.assertIn("capped by a harness version", text(BLOCK))
        self.assertIn("capped by a harness version", text(EXECUTION))

    def test_a_capped_harness_is_recorded_against_the_cleanroom_captures(self):
        procedure = text(PROCEDURE)
        section = procedure[procedure.index("## 4. Benchmarks"):procedure.index("## 5. Return")]
        self.assertIn("depends on what the agent's\n`--agent-log` records", section)
        self.assertIn("captures were completed under a capped\nharness", section)
        self.assertIn("captures completed under a capped harness", text(STATE))

    def test_the_only_continuation_is_one_sized_wait(self):
        for path in (PROCEDURE, BLOCK, EXECUTION):
            body = text(path)
            self.assertIn("`wait`", body, path.name)
            self.assertIn("`write_stdin`", body, path.name)
            self.assertIn("short waits", body, path.name)

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
        self.assertEqual(record["route_source"], "contract")

    def test_template_is_a_listed_resource(self):
        resources = set(read_json(ROOT / "studio-kit.json")["resources"])
        self.assertIn("templates/feature-manifest.json", resources)

    def test_procedure_names_the_manifest_path_and_the_return_obligation(self):
        procedure = text(PROCEDURE)
        self.assertIn("<run>/artifacts/run/feature-manifest.json", procedure)
        self.assertIn("feature-manifest.json", text(RETURN) + text(STATE))
        ret = procedure[procedure.index("## 5. Return"):procedure.index("## 6. Stop rules")]
        self.assertIn("**Accepted features.**", ret)
        self.assertIn("`pending`", ret)
        self.assertIn("`accepted`", ret)
        self.assertIn("`rejected` row with the\nreason it was rejected, a `pending` row as unreviewed", ret)
        self.assertIn("Not demonstrated", ret)
        self.assertIn("Accepted features", text(RETURN))
        self.assertIn("`rejected` with the reason, `pending` as unreviewed", text(RETURN))

    def test_an_accepted_row_carries_its_own_identity_receipt(self):
        for path in (PROCEDURE, REVIEW, PLAYTEST):
            body = text(path)
            self.assertIn("candidate new", body, path.name)
            self.assertIn("artifacts/run/identity/<feature>.json", body, path.name)
            self.assertIn("content_digest", body, path.name)
        procedure = text(PROCEDURE)
        self.assertIn("immediately after that session and\nbefore any edit", procedure)
        self.assertIn("`studio_tools/evidence.py`'s `new_candidate`", procedure)
        self.assertIn("never type one", procedure)
        self.assertIn("is historical", procedure)
        self.assertIn("a playtest receipt that records the digest itself would be a\nlater kit change", procedure)
        review = text(REVIEW)
        self.assertIn("copied, never typed", review)
        self.assertIn("cannot be accepted for that candidate", review)

    def test_pending_is_not_acceptance(self):
        review = text(REVIEW)
        self.assertIn("`human_verdict: accepted`", review)
        self.assertIn("nothing but `accepted` satisfies this", review)
        self.assertIn("treated as `pending`", review)
        playtest = text(PLAYTEST)
        self.assertIn("`human_verdict: accepted`", playtest)
        self.assertIn("then `accepted` or `rejected`", playtest)

    def test_the_canonical_route_has_a_declared_source(self):
        contracts = text(CONTRACTS)
        self.assertIn("`canonical_route`", contracts)
        self.assertIn('{"id": "<route-step-id>", "description": "<what the player does>"}', contracts)
        self.assertIn('"route_source": "contract"', contracts)
        self.assertIn('"route_source": "derived"', contracts)
        self.assertIn("`input_route`", contracts)
        procedure = text(PROCEDURE)
        self.assertIn('recording `"route_source": "contract"`', procedure)
        self.assertIn('record `"route_source": "derived"`', procedure)
        self.assertIn("route_source", text(RETURN) + text(STATE))

    def test_playtest_owns_the_canonical_route_and_review_owns_the_wiring_gap(self):
        playtest = text(PLAYTEST)
        self.assertIn("## The canonical route", playtest)
        self.assertIn("canonical_route", playtest)
        self.assertIn("installed_by", playtest)
        self.assertIn("Observed in the scene where it was built is not that", playtest)
        review = text(REVIEW)
        self.assertIn("wiring gap", review)
        self.assertIn("human_verdict", review)
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
        self.assertIn("run <run-id>: snapshot at Return", ret)
        self.assertIn("A run commits nothing by default", ret)
        self.assertIn("No push, no merge, no rebase", ret)
        self.assertIn("uncommitted overlay: <staged> staged, <modified> modified or\ndeleted unstaged, <untracked> untracked", ret)
        self.assertIn("git status --porcelain", ret)
        self.assertIn("git add -- <eligible paths>", ret)
        self.assertIn('git commit --only -- <eligible paths> -m "run <run-id>: snapshot at Return"', ret)
        self.assertIn("stays out of the snapshot; count it among the excluded", ret)

    def test_an_authorized_run_with_nothing_eligible_commits_nothing(self):
        procedure = text(PROCEDURE)
        ret = procedure[procedure.index("## 5. Return"):procedure.index("## 6. Stop rules")]
        self.assertIn("snapshot: no eligible changes, ref <current commit>", ret)
        self.assertIn("create no branch and commit nothing", ret)
        self.assertIn("an empty commit records a baseline that does not exist", ret)
        for path in (RETURN, STATE):
            self.assertIn("snapshot: no eligible changes, ref <current commit>", text(path), path.name)

    def test_both_records_carry_the_snapshot_line(self):
        for path in (RETURN, STATE):
            body = text(path)
            self.assertIn("run/<run-id>", body, path.name)
            self.assertIn(
                "uncommitted overlay: <staged> staged, <modified> modified or deleted unstaged, <untracked> untracked",
                body, path.name,
            )


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
