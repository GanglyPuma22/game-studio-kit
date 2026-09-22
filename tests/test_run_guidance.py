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
BLENDER = ROOT / "skills/studio-blender/SKILL.md"
DIRECTOR = ROOT / "skills/studio-director/SKILL.md"
WORK_CARD = ROOT / "templates/work-card.md"
JOURNAL = ROOT / "templates/edit-journal.json"
CHANGED_MARKDOWN = (
    PROCEDURE, BLOCK, PLAYTEST, REVIEW, GAME_DESIGN, CONTRACTS, RETURN, STATE,
    BLENDER, DIRECTOR, WORK_CARD,
)
MATURITY = ("source-ready", "root-reviewed", "integrated", "native-reviewed", "user-accepted")


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
        self.assertIn('git commit -m "run <run-id>: snapshot at Return" --only -- <eligible paths>', ret)
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


class DecisionTypeTests(unittest.TestCase):
    def test_the_work_card_asks_for_the_decision_type_and_the_chosen_route(self):
        # The route was chosen inside the Blender skill, after a generator had
        # already answered a look question, so the card asks for it up front.
        card = text(WORK_CARD)
        self.assertIn(
            "- Decision type (perceptual-exploratory | deterministic-repeatable)"
            " and chosen route (live scene | owned background job):",
            card,
        )
        self.assertIn("Decision type picks the route before the first command", card)
        self.assertIn("time-boxed blockout that enters a visual loop immediately", card)
        for word in ("silhouette", "camera readability", "qualification", "replay of a settled edit"):
            self.assertIn(word, card)

    def test_the_director_row_carries_the_deciding_question_and_both_routes(self):
        row = next(
            line for line in text(DIRECTOR).splitlines()
            if line.startswith("| Is this Blender question perceptual")
        )
        self.assertIn("camera readability", row)
        self.assertIn("deterministic", row)
        self.assertIn("persistent [live scene]", row)
        self.assertIn("../studio-blender/SKILL.md#live-sessions-journal-then-save-announce-stop", row)
        self.assertIn("`blender run`", row)

    def test_the_blender_skill_leads_its_route_section_with_the_rule(self):
        blender = text(BLENDER)
        heading = "## `run` or the interactive MCP"
        section = blender[blender.index(heading):]
        first = section.split("\n\n")[1]
        self.assertTrue(first.startswith("The kind of question decides the route before any command runs."), first[:80])
        self.assertLess(section.index("persistent live scene"), section.index("Use `run` when the work is a script"))
        self.assertIn("time-boxed blockout", section)

    def test_a_settled_live_edit_is_extracted_before_it_is_replayed(self):
        blender = text(BLENDER)
        self.assertIn("**The hybrid.**", blender)
        self.assertIn("save the live source", blender)
        self.assertIn("extract the transformation into a guarded project script", blender)
        self.assertIn("export and qualification in the background", blender)


class LaneMaturityTests(unittest.TestCase):
    def test_the_manifest_row_carries_a_maturity_and_the_template_names_every_step(self):
        record = read_json(MANIFEST)
        self.assertEqual(record["maturity_values"], list(MATURITY))
        self.assertEqual(record["features"][0]["maturity"], "source-ready")
        self.assertEqual(record["route_source"], "contract")

    def test_each_step_names_the_evidence_that_reaches_it(self):
        # 76 assertions, a green launch and a clean export are all produced by
        # the lane that built the thing; none of them reaches the route.
        review = text(REVIEW)
        procedure = text(PROCEDURE)
        for step in MATURITY:
            self.assertIn(f"`{step}`", review, step)
            self.assertIn(f"`{step}`", procedure, step)
        self.assertIn("set at most `source-ready`", review)
        self.assertIn("`installed_by` names a scene the route enters", review)
        self.assertIn("`human_verdict: accepted` with its identity receipt", review)
        self.assertIn("**Lanes by maturity.**", procedure)
        self.assertIn("A worker report is not integration.", procedure)
        self.assertIn("counting every row at each step, wired or not", procedure)
        self.assertIn("`native-reviewed` needs a native launch receipt", procedure)
        self.assertIn("Lanes by maturity", text(RETURN))

    def test_a_finished_worker_does_not_remove_its_unintegrated_lane(self):
        for path in (REVIEW, PROCEDURE):
            body = text(path)
            self.assertIn("leaves the active-worker list", body, path.name)
        self.assertIn("never drop a row because its\nworker finished", text(PROCEDURE))

    def test_a_row_exists_before_the_lane_is_wired(self):
        # A manifest of wired features only cannot show the finished lane
        # nobody integrated, which is the failure it exists to make visible.
        procedure = text(PROCEDURE)
        self.assertIn("A row is created by the work existing, not by the work being wired", procedure)
        for field in ("route_step", "entry", "installed_by", "launch_flags"):
            self.assertIn(f"`{field}`", procedure, field)
        self.assertIn('`"maturity": "source-ready"`', procedure)
        self.assertIn('`"human_verdict": "pending"`', procedure)
        self.assertIn("`null` until integration fills them", text(REVIEW))


class EditJournalTests(unittest.TestCase):
    def test_template_parses_and_carries_the_checkpoint_fields(self):
        record = read_json(JOURNAL)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["kind"], "edit-journal")
        self.assertEqual(sorted(record["source"]), ["path", "sha256_before"])
        self.assertEqual(len(record["checkpoints"]), 1)
        checkpoint = record["checkpoints"][0]
        for field in ("id", "working_receipt", "applied", "saved_scene", "evidence", "authority", "limitation"):
            self.assertIn(field, checkpoint)
        self.assertEqual(checkpoint["applied"]["kind"], "script | live-code")
        self.assertFalse(checkpoint["applied"]["reproducible"])
        self.assertIn("sha256", checkpoint["applied"])
        self.assertIn("sha256_after", checkpoint["saved_scene"])
        self.assertEqual(checkpoint["authority"], "agent | human")
        self.assertIn("transcript-only edits; not reproducible from a project script", checkpoint["limitation"])

    def test_template_is_a_listed_resource(self):
        resources = set(read_json(ROOT / "studio-kit.json")["resources"])
        self.assertIn("templates/edit-journal.json", resources)

    def test_the_journal_has_one_place_in_the_project_and_is_handed_back(self):
        # A journal nobody can find is the transcript again.
        self.assertIn("artifacts/blender/journal/<source-stem>.json", text(PROCEDURE))
        self.assertIn("artifacts/blender/journal/<source-stem>.json", text(RETURN))

    def test_the_skill_binds_a_checkpoint_to_a_saved_scene_and_a_hash(self):
        blender = text(BLENDER)
        self.assertIn("../../templates/edit-journal.json", blender)
        self.assertIn("saves a versioned scene", blender)
        self.assertIn("<GAME>/artifacts/blender/journal/<source-stem>.json", blender)
        self.assertIn("reproducible only when it names a project script with that script's hash", blender)
        self.assertIn("transcript-only limitation", blender)
        self.assertIn("no report may call it reproducible", blender)
        self.assertIn("refuses a source whose hash differs from that checkpoint's `sha256_after`", blender)
        self.assertIn("Keep secrets and user prompts out of the journal", blender)


class LiveSessionStopTests(unittest.TestCase):
    def test_save_announce_stop_is_stated_in_the_skill_and_the_global_block(self):
        # A listener restart read as a crash because nothing announced that the
        # visible window would close.
        for path in (BLENDER, BLOCK):
            body = text(path)
            self.assertIn("save a checkpoint", body, path.name)
            self.assertIn("tell the human the visible window will close", body, path.name)
            self.assertIn("report `CLOSED` before starting or reusing a session", body, path.name)
            self.assertIn("receipt-bound", body, path.name)
            # The bare verb was not runnable: this command requires --project,
            # --config and the receipt `ensure` returned (studio_tools/cli.py).
            self.assertIn("scripts/studio.py blender-mcp stop --project ", body, path.name)
            self.assertIn("--config ", body, path.name)
            self.assertIn("--receipt ", body, path.name)
        self.assertIn("never reported as a crash without the receipt", text(BLENDER))
        self.assertIn("unconfirmed stop named with its receipt, never a crash", text(BLOCK))

    def test_both_connection_layers_are_named_with_the_reconnect(self):
        for path in (BLENDER, BLOCK):
            body = text(path)
            self.assertIn("add-on", body, path.name)
            self.assertIn("listener", body, path.name)
            self.assertIn("Codex connector", body, path.name)
            self.assertIn("reconnect", body, path.name)


class DiagnosticBatchTests(unittest.TestCase):
    def test_a_batch_that_varied_nothing_is_not_evidence(self):
        procedure = text(PROCEDURE)
        self.assertIn("`must_vary` is a list of JSON pointers", procedure)
        self.assertIn("`invariants` is a list of `{field, equals}` entries", procedure)
        self.assertIn("first declared result file", procedure)
        self.assertIn("checked after all the runs have\nfinished", procedure)
        self.assertIn("is `invalid_experiment`, not evidence", procedure)
        self.assertIn("`experiment` block names the pointer that failed", procedure)
        self.assertIn("leaves the check\n`unverified`, which is not a pass", procedure)
        self.assertIn("twilight", procedure)
        self.assertIn("before paying", procedure)

if __name__ == "__main__":
    unittest.main()
