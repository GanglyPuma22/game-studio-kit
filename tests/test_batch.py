"""Batched owned launches: one blocking call, one rollup, no polling (offline)."""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import batch, cli, launch, processes
from studio_tools.common import StudioError, read_json, sha256, write_json
from studio_tools.config import load

ROOT = Path(__file__).resolve().parents[1]
DIRECTOR = ROOT / "skills/studio-director/SKILL.md"
PROCEDURE = ROOT / "skills/studio-director/references/overnight-run.md"
BLOCK = ROOT / "references/codex/AGENTS-overnight.md"
OK = "print('run ok')"
# Exit zero with an engine error: the case a batch of return codes would miss.
FAILS = "print('SCRIPT ERROR: broken')"


class FakeClock:
    """Stand-in for the batch module's datetime with scripted now() values.

    The last value repeats, so only the instants a test cares about are scripted.
    """

    fromisoformat = staticmethod(datetime.fromisoformat)

    def __init__(self, *values):
        self.values = list(values)

    def now(self, tz=None):
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class BatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio batch space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)
        self.host_config = Path(self.tmp.name) / "host.json"
        write_json(self.host_config, {"executables": {"godot": sys.executable}, "timeout": 5})
        self.plans = 0

    def plan(self, *runs, document=None):
        """Write a plan file and return its path."""
        self.plans += 1
        path = Path(self.tmp.name) / f"plan-{self.plans}.json"
        write_json(path, {"schema_version": 1, "kind": "launch-batch-plan", "runs": list(runs)}
                   if document is None else document)
        return path

    def fake_child(self, *codes):
        """Stand in for the engine, one scripted child per run; the last repeats."""
        queue = list(codes) or [OK]

        def fake_run(args, **kwargs):
            self.last_args = args
            code = queue.pop(0) if len(queue) > 1 else queue[0]
            return processes.run([sys.executable, "-c", code], **kwargs)
        return fake_run

    def cli_batch(self, plan, *extra, codes=(OK,)):
        """Drive the real command line, the way a caller does."""
        argv = ["batch", "--project", str(self.root), "--config", str(self.host_config),
                "--sha256", self.sha, "--plan", str(plan), *extra]
        with patch("studio_tools.launch.run", side_effect=self.fake_child(*codes)):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def rollup(self, plan, *extra, codes=(OK,)):
        code, out, err = self.cli_batch(plan, *extra, codes=codes)
        self.assertEqual(err, "")
        return code, json.loads(out)


class BatchRollupTests(BatchCase):
    def test_two_run_plan_blocks_and_rolls_up_both_runs(self):
        plan = self.plan({"label": "first", "scope": "macro-terrain"}, {"label": "second"})
        code, rollup = self.rollup(plan, "--label", "nightly")
        self.assertEqual(code, 0)
        self.assertTrue(rollup["ok"])
        self.assertEqual(rollup["execution"], "sequential")
        self.assertIsNone(rollup["stopped_early"])
        self.assertEqual(rollup["totals"], {"planned": 2, "ran": 2, "not_started": 0, "ok": 2, "not_ok": 0, "not_run": 0})
        # Every run is finished when the single call returns; nothing is pending.
        self.assertEqual([run["verdict"] for run in rollup["runs"]], ["completed", "completed"])
        self.assertEqual([run["label"] for run in rollup["runs"]], ["first", "second"])
        self.assertEqual(rollup["runs"][0]["scope"], "macro-terrain")
        self.assertIsNotNone(rollup["finished_utc"])
        record = self.root / "artifacts/batches/nightly/batch.json"
        self.assertTrue(record.is_file())
        self.assertEqual(rollup["batch_record"], str(record))
        self.assertEqual(read_json(record)["totals"], rollup["totals"])

    def test_rollup_indexes_each_run_receipt_by_relative_path(self):
        plan = self.plan({"label": "first"}, {"label": "second"})
        _, rollup = self.rollup(plan, "--label", "indexed")
        for run in rollup["runs"]:
            for field in ("run_dir", "launch_record", "exit_record", "diagnostics_record",
                          "process_record", "log"):
                value = run[field]
                self.assertFalse(Path(value).is_absolute(), f"{field} is absolute")
                self.assertTrue((self.root / value).exists(), f"{field} does not exist")
            self.assertEqual(run["exit_record"], f"artifacts/launches/{run['label']}/exit.json")
            self.assertEqual(read_json(self.root / run["exit_record"])["label"], run["label"])

    def test_a_failing_run_fails_the_batch_while_the_other_still_runs(self):
        plan = self.plan({"label": "broken"}, {"label": "healthy"})
        code, rollup = self.rollup(plan, "--label", "mixed", codes=(FAILS, OK))
        self.assertEqual(code, 1)
        self.assertFalse(rollup["ok"])
        self.assertIsNone(rollup["stopped_early"])
        self.assertEqual(rollup["totals"], {"planned": 2, "ran": 2, "not_started": 0, "ok": 1, "not_ok": 1, "not_run": 0})
        self.assertFalse(rollup["runs"][0]["ok"])
        self.assertEqual(rollup["runs"][0]["verdict"], "engine_errors")
        # The second run was still attempted and still owns a full set of receipts.
        self.assertTrue(rollup["runs"][1]["ok"])
        self.assertTrue((self.root / "artifacts/launches/healthy/exit.json").is_file())

    def test_stop_on_first_failure_leaves_the_later_run_unrun(self):
        plan = self.plan({"label": "broken"}, {"label": "never"})
        code, rollup = self.rollup(plan, "--label", "halted", "--stop-on-first-failure", codes=(FAILS, OK))
        self.assertEqual(code, 1)
        self.assertFalse(rollup["ok"])
        self.assertTrue(rollup["stop_on_first_failure"])
        self.assertEqual(rollup["stopped_early"], "first_failure")
        self.assertEqual(rollup["totals"], {"planned": 2, "ran": 1, "not_started": 0, "ok": 0, "not_ok": 1, "not_run": 1})
        self.assertEqual(rollup["runs"][1]["status"], "not_run")
        self.assertIn("stopped earlier: first_failure", rollup["runs"][1]["failure"])
        self.assertIsNone(rollup["runs"][1]["exit_record"])
        # A run that never started leaves no receipts to be mistaken for evidence.
        self.assertFalse((self.root / "artifacts/launches/never").exists())

    def test_a_failing_last_run_does_not_claim_the_batch_stopped_early(self):
        # Nothing was skipped, so a stop reason here would contradict not_run: 0.
        plan = self.plan({"label": "green"}, {"label": "broken"})
        _, rollup = self.rollup(plan, "--label", "lastfails", "--stop-on-first-failure",
                                codes=(OK, FAILS))
        self.assertFalse(rollup["ok"])
        self.assertEqual(rollup["totals"]["not_run"], 0)
        self.assertIsNone(rollup["stopped_early"])

    def test_a_verdict_with_no_engine_behind_it_is_not_counted_as_a_launch(self):
        # A cutoff that had already passed returns an ordinary verdict with a
        # null PID; counting it as a run would inflate the batch's own tally.
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        plan = self.plan({"label": "late", "cutoff_utc": past}, {"label": "ontime"})
        code, rollup = self.rollup(plan, "--label", "cutoffs")
        self.assertEqual(code, 1)
        self.assertFalse(rollup["ok"])
        self.assertEqual(rollup["runs"][0]["verdict"], "cutoff_passed")
        self.assertEqual(rollup["runs"][0]["status"], "not_started")
        # The second run was unaffected: only the first had no engine behind it.
        self.assertEqual(rollup["totals"], {"planned": 2, "ran": 1, "not_started": 1,
                                            "ok": 1, "not_ok": 1, "not_run": 0})
        # The launcher still wrote its own receipts for the run it refused.
        self.assertTrue((self.root / rollup["runs"][0]["exit_record"]).is_file())

    def test_an_interrupted_run_keeps_the_receipts_the_launcher_already_wrote(self):
        # The launcher finishes its receipts before it re-raises, and this
        # record is the recovery record, so it must not disown them.
        plan = self.plan({"label": "cut"}, {"label": "after"})
        with patch("studio_tools.launch.run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                batch.execute(self.config, self.root, plan=plan,
                              sha256_expected=self.sha, label="stopped")
        record = read_json(self.root / "artifacts/batches/stopped/batch.json")
        row = record["runs"][0]
        # No engine ever started here, so the row does not claim one did.
        self.assertEqual(row["status"], "not_started")
        self.assertEqual(row["verdict"], "interrupted")
        self.assertEqual(row["run_dir"], "artifacts/launches/cut")
        self.assertEqual(row["launch_record"], "artifacts/launches/cut/owned-launch.json")
        self.assertEqual(row["exit_record"], "artifacts/launches/cut/exit.json")
        self.assertTrue((self.root / row["exit_record"]).is_file())
        self.assertEqual(record["stopped_early"], "interrupted")
        self.assertEqual(record["runs"][1]["status"], "not_run")

    def test_an_interrupted_engine_that_started_is_still_counted_as_a_launch(self):
        # The process receipt carries the PID, and it is the only account of
        # whether anything ran once the launcher re-raises instead of returning.
        def interrupt_after_start(args, **kwargs):
            processes.run([sys.executable, "-c", "print('started')"], **kwargs)
            raise KeyboardInterrupt

        plan = self.plan({"label": "cut"})
        with patch("studio_tools.launch.run", side_effect=interrupt_after_start):
            with self.assertRaises(KeyboardInterrupt):
                batch.execute(self.config, self.root, plan=plan,
                              sha256_expected=self.sha, label="midflight")
        record = read_json(self.root / "artifacts/batches/midflight/batch.json")
        self.assertGreater(read_json(self.root / "artifacts/launches/cut/process/process.json")["pid"], 0)
        self.assertEqual(record["runs"][0]["status"], "ran")
        self.assertEqual(record["runs"][0]["verdict"], "interrupted")
        self.assertEqual(record["totals"]["ran"], 1)
        self.assertFalse(record["ok"])

    def test_the_rollup_marks_a_run_in_flight_before_the_launcher_is_called(self):
        # The file is a crash record: a host that dies inside a launch must not
        # leave a row claiming the batch never reached a run whose receipts are
        # already on disk beside it. Read from inside the call, which is where
        # a post-crash reader would find it.
        seen = []
        real = launch.execute

        def observing(*args, **kwargs):
            record = read_json(self.root / "artifacts/batches/crashy/batch.json")
            seen.append([(run["status"], run["failure"]) for run in record["runs"]])
            return real(*args, **kwargs)

        plan = self.plan({"label": "one"}, {"label": "two"})
        with patch("studio_tools.batch.launch.execute", side_effect=observing):
            _, rollup = self.rollup(plan, "--label", "crashy")
        self.assertEqual(seen[0][0][0], "in_flight")
        self.assertIn("inside this launch", seen[0][0][1])
        self.assertEqual(seen[0][1][0], "not_run")
        # The finished row of the earlier run survives into the next snapshot.
        self.assertEqual([status for status, _ in seen[1]], ["ran", "in_flight"])
        self.assertTrue(rollup["ok"])

    def test_acceptance_stays_not_established_when_every_run_is_green(self):
        plan = self.plan({"label": "green-one"}, {"label": "green-two"})
        _, rollup = self.rollup(plan, "--label", "allgreen")
        self.assertTrue(rollup["ok"])
        self.assertEqual(rollup["acceptance"], "not_established")
        self.assertEqual(read_json(self.root / "artifacts/batches/allgreen/batch.json")["acceptance"],
                         "not_established")
        self.assertIn("exit zero is not acceptance; a green batch is a batch of runs that ran",
                      rollup["limits"])

    def test_receipts_hold_no_argv_or_environment_while_the_log_does(self):
        code = (
            "import os,sys;print('private-arg');"
            "print(os.environ['STUDIO_BATCH_FIXTURE'],file=sys.stderr)"
        )
        plan = self.plan({"label": "quiet", "passthrough": ["--", "private-arg"]})
        with patch.dict(os.environ, {"STUDIO_BATCH_FIXTURE": "private-env"}):
            _, rollup = self.rollup(plan, "--label", "receipts", codes=(code,))
        self.assertEqual(rollup["runs"][0]["passthrough_count"], 1)
        for name in ("artifacts/batches/receipts/batch.json",
                     "artifacts/launches/quiet/owned-launch.json",
                     "artifacts/launches/quiet/exit.json",
                     "artifacts/launches/quiet/process/process.json"):
            self.assertNotIn("private-", (self.root / name).read_text(encoding="utf-8"), name)
        self.assertNotIn("private-", json.dumps(rollup))
        self.assertIn("private-arg", (self.root / "artifacts/launches/quiet/process/stdout.log").read_text())


class BatchRefusalTests(BatchCase):
    def refusal(self, plan, *extra):
        code, out, err = self.cli_batch(plan, *extra)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        return json.loads(err)["error"]

    def test_a_run_missing_its_label_is_refused_by_position(self):
        plan = self.plan({"label": "first"}, {"mode": "import"})
        error = self.refusal(plan, "--label", "bad")
        self.assertEqual(error, "Batch plan run 2 is missing a required field: label")
        # Nothing ran, and the batch left no directory behind either.
        self.assertFalse((self.root / "artifacts").exists())

    def test_an_unknown_field_is_refused_and_names_the_entry(self):
        plan = self.plan({"label": "typo", "result": ["artifacts/out.json"]})
        self.assertEqual(self.refusal(plan),
                         'Batch plan run 1 (label "typo") has an unknown field: result')

    def test_a_mode_that_needs_a_script_is_refused_before_any_run(self):
        plan = self.plan({"label": "first"}, {"label": "checked", "mode": "check"})
        self.assertEqual(
            self.refusal(plan),
            'Batch plan run 2 (label "checked") is missing a required field: script, which mode check needs',
        )
        self.assertFalse((self.root / "artifacts").exists())

    def test_every_field_refusal_names_the_entry_it_came_from(self):
        cases = [
            ("label", "not a label", "has a label that is not an ID"),
            ("scope", "not a rung", "has a scope that is not a rung ID"),
            ("cutoff_utc", "tonight", "has a cutoff_utc that is not an ISO 8601"),
            ("timeout", 99999, "has a timeout outside 1-3600 seconds"),
            ("mode", "sideways", "has an unknown mode"),
            ("results", ["", "artifacts/out.json"], "has a results that is not a list of nonempty strings"),
        ]
        for field, value, expected in cases:
            plan = self.plan({"label": "fine"}, {"label": "second", field: value})
            error = self.refusal(plan)
            self.assertTrue(error.startswith("Batch plan run 2"), error)
            self.assertIn(expected, error)

    def test_a_duplicate_label_inside_the_plan_is_refused(self):
        plan = self.plan({"label": "same"}, {"label": "same"})
        self.assertEqual(self.refusal(plan), 'Batch plan run 2 (label "same") reuses the label of run 1')

    def test_a_run_label_that_already_has_a_launch_directory_is_refused(self):
        (self.root / "artifacts/launches/taken").mkdir(parents=True)
        plan = self.plan({"label": "fresh"}, {"label": "taken"})
        self.assertEqual(
            self.refusal(plan),
            'Batch plan run 2 (label "taken") names a launch directory that exists; choose a new label',
        )
        self.assertFalse((self.root / "artifacts/launches/fresh").exists())

    def test_a_reused_batch_label_is_refused(self):
        plan = self.plan({"label": "once"})
        code, rollup = self.rollup(plan, "--label", "same-batch")
        self.assertEqual(code, 0)
        again = self.plan({"label": "twice"})
        self.assertEqual(self.refusal(again, "--label", "same-batch"),
                         "Batch directory exists; choose a new label")
        self.assertFalse((self.root / "artifacts/launches/twice").exists())

    def test_an_empty_or_shapeless_plan_is_refused(self):
        self.assertEqual(self.refusal(self.plan()),
                         "Batch plan lists no runs; a batch of nothing has nothing to report")
        shapeless = self.plan(document={"schema_version": 1, "runs": {"label": "first"}})
        self.assertEqual(self.refusal(shapeless), 'Batch plan must be a JSON object with a "runs" list')

    def test_a_plan_that_does_not_declare_this_format_is_refused(self):
        # A mistyped kind or a version this code does not know must be refused,
        # never reinterpreted with the semantics it happens to be read by.
        run = {"label": "first"}
        wrong_kind = self.plan(document={"schema_version": 1, "kind": "launch-plan", "runs": [run]})
        self.assertEqual(self.refusal(wrong_kind), 'Batch plan must declare kind "launch-batch-plan"')
        future = self.plan(document={"schema_version": 2, "kind": "launch-batch-plan", "runs": [run]})
        self.assertEqual(self.refusal(future), "Batch plan schema_version must be 1")
        self.assertFalse((self.root / "artifacts").exists())

    def test_a_result_the_launcher_writes_or_one_outside_the_project_is_refused(self):
        # The launcher applies both rules, but only once that run starts. Found
        # here, they cost nothing; found there, they cost every earlier window.
        owned = self.plan({"label": "first"},
                          {"label": "second", "results": ["artifacts/launches/second/exit.json"]})
        self.assertEqual(self.refusal(owned), 'Batch plan run 2 (label "second") declares a result under artifacts/launches or artifacts/batches, where the kit writes receipts; name a file the run produces')
        # A result under a *later* run's directory would create that directory
        # and get the later launch refused by its own mkdir, after this run had
        # already spent its window.
        neighbour = self.plan({"label": "first", "results": ["artifacts/launches/second/out.json"]},
                              {"label": "second"})
        self.assertEqual(self.refusal(neighbour), 'Batch plan run 1 (label "first") declares a result under artifacts/launches or artifacts/batches, where the kit writes receipts; name a file the run produces')
        escaping = self.plan({"label": "first"}, {"label": "second", "results": ["../elsewhere.json"]})
        self.assertEqual(
            self.refusal(escaping),
            'Batch plan run 2 (label "second") declares a result outside the project; '
            "use a portable project-relative path",
        )
        self.assertFalse((self.root / "artifacts/launches/first").exists())

    def test_a_result_inside_the_batch_record_directory_is_refused(self):
        # The rollup is rewritten between runs, so a run declaring a file in
        # there would have its output overwritten by the receipt that then
        # reports it completed, carrying a hash for bytes that are gone.
        plan = self.plan({"label": "first"},
                         {"label": "second", "results": ["artifacts/batches/nightly/batch.json"]})
        self.assertEqual(self.refusal(plan, "--label", "nightly"),
                         'Batch plan run 2 (label "second") declares a result under artifacts/launches or artifacts/batches, where the kit writes receipts; name a file the run produces')
        self.assertFalse((self.root / "artifacts/batches/nightly").exists())

    def test_labels_that_differ_only_in_case_collide(self):
        # One directory on Windows, so the second run would be refused only
        # after the first had already spent its window.
        self.assertEqual(self.refusal(self.plan({"label": "Run"}, {"label": "run"})),
                         'Batch plan run 2 (label "run") reuses the label of run 1')

    def test_a_present_but_empty_cutoff_is_refused_rather_than_dropped(self):
        # Dropping it would silently hand the run the far later batch deadline.
        for value in ("", False, 0):
            plan = self.plan({"label": "first"}, {"label": "second", "cutoff_utc": value})
            self.assertIn("has a cutoff_utc that is not an ISO 8601", self.refusal(plan))

    def test_an_unbounded_or_oversized_total_cap_is_refused(self):
        plan = self.plan({"label": "first"})
        for value in ("0", "1441", "-5"):
            self.assertEqual(
                self.refusal(plan, "--max-minutes", value),
                "Batch --max-minutes must be 1-1440; an unattended batch stays bounded",
            )
        self.assertFalse((self.root / "artifacts").exists())

    def test_a_missing_or_unparsable_plan_file_is_refused(self):
        missing = Path(self.tmp.name) / "absent.json"
        self.assertEqual(self.refusal(missing),
                         "Batch needs an existing, readable --plan file listing the runs")
        broken = Path(self.tmp.name) / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.refusal(broken), "Cannot read JSON record: broken.json")


class BatchBudgetTests(BatchCase):
    def test_the_total_cap_is_recorded_with_the_deadline_it_produced(self):
        plan = self.plan({"label": "capped"})
        _, rollup = self.rollup(plan, "--label", "budgeted", "--max-minutes", "30")
        self.assertEqual(rollup["max_minutes"], 30.0)
        self.assertEqual(rollup["max_minutes_effective"], 30.0)
        started = datetime.fromisoformat(rollup["started_utc"])
        self.assertEqual(datetime.fromisoformat(rollup["deadline_utc"]), started + timedelta(minutes=30))
        # The cap is the batch's, not the run's: the run keeps its own timeout
        # and only inherits the deadline as a cutoff it may not outlive.
        owned = read_json(self.root / "artifacts/launches/capped/owned-launch.json")
        self.assertEqual(datetime.fromisoformat(owned["cutoff_utc"]),
                         datetime.fromisoformat(rollup["deadline_utc"]))

    def test_a_spent_budget_stops_the_batch_without_starting_the_next_run(self):
        now = datetime.now(timezone.utc)
        plan = self.plan({"label": "inside"}, {"label": "outside"})
        # Scripted instants: the batch starts, the first run is inside the
        # window, and by the second the whole window has been spent.
        with patch("studio_tools.batch.datetime", FakeClock(now, now, now + timedelta(hours=3))):
            code, rollup = self.rollup(plan, "--label", "spent", "--max-minutes", "60")
        self.assertEqual(code, 1)
        self.assertFalse(rollup["ok"])
        self.assertEqual(rollup["stopped_early"], "budget_exhausted")
        self.assertEqual(rollup["totals"], {"planned": 2, "ran": 1, "not_started": 0, "ok": 1, "not_ok": 0, "not_run": 1})
        self.assertEqual(rollup["runs"][1]["status"], "not_run")
        self.assertIn("budget was spent", rollup["runs"][1]["failure"])
        self.assertFalse((self.root / "artifacts/launches/outside").exists())


class BatchNeverPollsTests(BatchCase):
    """The defect this command exists to remove.

    A hand-rolled batch starts each run and then asks, in a loop, whether it has
    finished: `wait` calls, sleeps, empty stdin writes. A batch that blocks calls
    the launcher exactly once per run and never asks anything about a pid.
    """

    def test_batch_calls_the_blocking_launcher_once_per_run_and_never_polls(self):
        plan = self.plan({"label": "one"}, {"label": "two"}, {"label": "three"})
        real = launch.execute
        calls = []

        def counted(*args, **kwargs):
            calls.append(kwargs["label"])
            return real(*args, **kwargs)

        with patch("studio_tools.batch.launch.execute", side_effect=counted):
            with patch("studio_tools.processes.alive") as alive:
                with patch("studio_tools.processes.start") as start:
                    code, rollup = self.rollup(plan, "--label", "noloop")
        self.assertEqual(code, 0)
        # One blocking call per run. A polling wrapper would show many more.
        self.assertEqual(calls, ["one", "two", "three"])
        # Neither of the kit's non-blocking primitives was touched: `start`
        # returns before the child is done and `alive` is the "is it done yet"
        # question, so a batch built on them would have to poll to finish.
        alive.assert_not_called()
        start.assert_not_called()
        # And the single verdict is complete: no run is still pending when the
        # command returns, so there is nothing left for a caller to wait on.
        self.assertEqual(rollup["totals"]["ran"], 3)
        for run in rollup["runs"]:
            self.assertEqual(run["status"], "ran")
            self.assertIn(run["verdict"], ("completed", "engine_errors", "timed_out"))
            self.assertIsNotNone(run["elapsed_seconds"])

    def test_the_module_owns_no_waiting_of_its_own(self):
        # `batch` reuses `launch.execute`, which owns the one bounded wait. If
        # this module ever grew a wait of its own, that would be the polling
        # loop coming back inside the kit instead of outside it.
        source = Path(batch.__file__).read_text(encoding="utf-8")
        body = re.sub(r'""".*?"""', "", source, flags=re.S)
        for forbidden in ("sleep", "poll(", "time.monotonic", "communicate", "wait("):
            self.assertNotIn(forbidden, body, f"batch.py uses {forbidden}")


class BatchDiscoverabilityTests(BatchCase):
    """No skill description named a single command, which is why agents improvised."""

    def test_the_director_routing_table_says_when_to_batch(self):
        director = DIRECTOR.read_text(encoding="utf-8")
        self.assertIn("`studio batch --plan <file>`", director)
        self.assertIn("instead of repeated `launch` calls", director)

    def test_the_owning_skills_name_their_commands_in_the_description(self):
        expected = {
            "studio-godot": ("`studio launch`", "`studio batch`"),
            "studio-review": ("`studio evidence launches`",),
            "studio-playtest": ("`studio playtest start`", "`studio playtest collect`"),
        }
        for name, commands in expected.items():
            text = (ROOT / f"skills/{name}/SKILL.md").read_text(encoding="utf-8")
            description = re.search(r"^description: (.+)$", text, re.M)
            self.assertIsNotNone(description, name)
            for command in commands:
                self.assertIn(command, description.group(1), f"{name} description omits {command}")

    def test_the_overnight_rules_name_batch_as_the_replacement_for_a_wait_loop(self):
        for path in (PROCEDURE, BLOCK):
            text = path.read_text(encoding="utf-8")
            self.assertIn("hand-rolled wait loop", text)
            # Both keep the one case a fixed plan cannot express.
            self.assertIn("depend on an earlier run's verdict", text)
        # The procedure resolves the helper the way every other stage does;
        # the installed global block is prose about the command's name.
        procedure = PROCEDURE.read_text(encoding="utf-8")
        # Executable as written: the resolved helper, the project, the host
        # config and the engine digest argparse requires.
        self.assertIn("python <KIT>/scripts/studio.py batch --project <run> --config <host config>",
                      procedure)
        self.assertIn("--sha256 <engine> --plan <plan>", procedure)
        block = BLOCK.read_text(encoding="utf-8")
        # The rule most often read on its own spells its own invocation, and the
        # preamble says once how every other command in the block is invoked.
        self.assertIn("python <KIT>/scripts/studio.py batch --project <run> --plan <file>", block)
        self.assertIn("There is no `studio` on PATH", block)
        self.assertNotIn("with an explicit `--project`, as that procedure", block)

    def test_the_rules_keep_the_stage_that_cannot_be_batched(self):
        # Stage 4 wants one cleanroom capture per rung; one batch inside one
        # wrapper is one attribution window, not five.
        for path in (PROCEDURE, BLOCK):
            self.assertIn("`bench cleanroom` window", path.read_text(encoding="utf-8"))

    def test_batch_is_a_declared_command_with_its_plan_template(self):
        manifest = read_json(ROOT / "studio-kit.json")
        self.assertIn("batch", manifest["commands"])
        self.assertIn("studio_tools/batch.py", manifest["resources"])
        self.assertIn("templates/batch-plan.json", manifest["resources"])
        template = read_json(ROOT / "templates/batch-plan.json")
        self.assertEqual(template["kind"], "launch-batch-plan")
        # The shipped example has to be a plan this command actually accepts, so
        # it is run rather than inspected: every entry reaches the launcher.
        copied = self.plan(document=template)
        _, rollup = self.rollup(copied, "--label", "shipped")
        self.assertEqual([run["label"] for run in rollup["runs"]],
                         [run["label"] for run in template["runs"]])
        self.assertTrue(all(run["status"] == "ran" for run in rollup["runs"]))
        self.assertEqual(rollup["plan"], {"path": str(copied.resolve()), "sha256": sha256(copied)})


class BatchDirectTests(BatchCase):
    def test_execute_refuses_a_project_that_is_not_a_directory(self):
        plan = self.plan({"label": "first"})
        with self.assertRaisesRegex(StudioError, "existing game project directory"):
            batch.execute(self.config, self.root / "absent", plan=plan, sha256_expected=self.sha)

    def test_an_engine_mismatch_refuses_the_first_run_and_fails_the_batch(self):
        # The launcher's own refusal is this run's verdict, not an exception
        # that throws away the rollup the remaining runs are recorded in.
        plan = self.plan({"label": "first"}, {"label": "second"})
        result = batch.execute(self.config, self.root, plan=plan, sha256_expected="0" * 64,
                               label="mismatched")
        self.assertFalse(result["ok"])
        self.assertEqual([run["status"] for run in result["runs"]], ["not_started", "not_started"])
        self.assertEqual([run["verdict"] for run in result["runs"]], ["refused", "refused"])
        self.assertIn("identity mismatch", result["runs"][0]["failure"])
        # No engine started, so nothing may be counted as having run.
        self.assertEqual(result["totals"], {"planned": 2, "ran": 0, "not_started": 2,
                                            "ok": 0, "not_ok": 2, "not_run": 0})


if __name__ == "__main__":
    unittest.main()
