"""Explicit overall cutoffs, using clocks and Python mocks only."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import batch, cleanroom, cli
from studio_tools.common import StudioError, read_json, sha256, write_json
from studio_tools.config import load
from test_batch import FakeClock
from test_cleanroom_host import snap, stub_sampler


NOW = datetime(2026, 10, 3, 10, tzinfo=timezone.utc)


def completed_launch():
    return {
        "status": "completed", "verdict": "completed", "ok": True,
        "elapsed_seconds": 1, "timed_out": False, "failure": None,
        **{key: None for key in ("run_dir", "launch_record", "exit_record",
                                "diagnostics_record", "process_record", "log")},
    }


class CutoffCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio cutoff ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "project.godot").touch()
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 20})
        self.plan = self.root / "plan.json"

    def batch(self, runs=None, **kwargs):
        write_json(self.plan, {"schema_version": 1, "kind": "launch-batch-plan",
                               "runs": runs or [{"label": "first"}, {"label": "second"}]})
        return batch.execute(self.config, self.root, plan=self.plan,
                             sha256_expected=sha256(sys.executable), label="batch", **kwargs)

    def bench(self, **kwargs):
        self.sampler = stub_sampler()
        return cleanroom.execute(self.config, self.root, ["capture", "--opaque=value"],
                                 label="bench", snapshot_reader=lambda: snap([]),
                                 sampler_factory=self.sampler, **kwargs)


class BatchCutoffTests(CutoffCase):
    def test_expired_overall_cutoff_starts_no_launch(self):
        cutoff = NOW - timedelta(seconds=1)
        with patch("studio_tools.batch.datetime", FakeClock(NOW)), \
                patch("studio_tools.batch.launch.execute") as launcher:
            result = self.batch(cutoff_utc=cutoff.isoformat())
        launcher.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["stopped_early"], "cutoff_passed")
        self.assertEqual(result["totals"]["not_run"], 2)
        self.assertEqual(result["max_minutes_effective"], 0)
        self.assertEqual(read_json(Path(result["batch_record"]))["cutoff_utc"], cutoff.isoformat())

    def test_cutoff_during_sequence_prevents_later_launch(self):
        cutoff = NOW + timedelta(seconds=10)
        with patch("studio_tools.batch.datetime", FakeClock(NOW, NOW, cutoff)), \
                patch("studio_tools.batch.launch.execute", return_value=completed_launch()) as launcher:
            result = self.batch(cutoff_utc=cutoff.isoformat())
        self.assertEqual(launcher.call_count, 1)
        self.assertEqual(launcher.call_args.kwargs["cutoff_utc"], cutoff.isoformat())
        self.assertEqual(result["stopped_early"], "cutoff_passed")
        self.assertEqual(result["runs"][1]["status"], "not_run")

    def test_each_launch_keeps_the_earliest_run_batch_or_overall_cutoff(self):
        earlier = NOW + timedelta(seconds=5)
        overall = NOW + timedelta(seconds=10)
        runs = [{"label": "first", "cutoff_utc": earlier.isoformat()},
                {"label": "second", "cutoff_utc": (NOW + timedelta(hours=1)).isoformat()}]
        with patch("studio_tools.batch.datetime", FakeClock(NOW)), \
                patch("studio_tools.batch.launch.execute", return_value=completed_launch()) as launcher:
            result = self.batch(runs, cutoff_utc=overall.isoformat())
        self.assertTrue(result["ok"])
        self.assertEqual([call.kwargs["cutoff_utc"] for call in launcher.call_args_list],
                         [earlier.isoformat(), overall.isoformat()])

    def test_max_minutes_remains_binding_when_overall_cutoff_is_later(self):
        with patch("studio_tools.batch.datetime", FakeClock(NOW)), \
                patch("studio_tools.batch.launch.execute", return_value=completed_launch()) as launcher:
            result = self.batch(max_minutes=1, cutoff_utc=(NOW + timedelta(hours=1)).isoformat())
        self.assertEqual(result["deadline_utc"], (NOW + timedelta(minutes=1)).isoformat())
        self.assertEqual(launcher.call_args.kwargs["cutoff_utc"], result["deadline_utc"])

    def test_absent_cutoff_preserves_timeout_deadline_and_receipt_shape(self):
        with patch("studio_tools.batch.datetime", FakeClock(NOW)), \
                patch("studio_tools.batch.launch.execute", return_value=completed_launch()) as launcher:
            result = self.batch([{"label": "first", "timeout": 12}])
        self.assertEqual(result["deadline_utc"], (NOW + timedelta(minutes=60)).isoformat())
        self.assertNotIn("cutoff_utc", result)
        self.assertEqual(launcher.call_args.kwargs["timeout"], 12)

    def test_launch_timeout_is_bounded_again_after_preparation(self):
        cutoff = NOW + timedelta(seconds=10)
        with patch("studio_tools.batch.datetime", FakeClock(NOW)), \
                patch("studio_tools.launch.datetime", FakeClock(NOW, NOW + timedelta(seconds=4))), \
                patch("studio_tools.launch.prelaunch_baseline", return_value={}), \
                patch("studio_tools.launch.self_contained", return_value=False), \
                patch("studio_tools.launch.run", side_effect=StudioError("mock capture")) as runner:
            self.batch([{"label": "first", "timeout": 20}], cutoff_utc=cutoff.isoformat())
        self.assertEqual(runner.call_args.kwargs["timeout"], 6)
        owned = read_json(self.root / "artifacts/launches/first/owned-launch.json")
        self.assertEqual(owned["timeout_seconds_effective"], 6)

    def test_cutoff_during_launch_preparation_starts_no_engine(self):
        cutoff = NOW + timedelta(seconds=10)
        with patch("studio_tools.batch.datetime", FakeClock(NOW)), \
                patch("studio_tools.launch.datetime", FakeClock(NOW, cutoff)), \
                patch("studio_tools.launch.prelaunch_baseline", return_value={}), \
                patch("studio_tools.launch.self_contained", return_value=False), \
                patch("studio_tools.launch.run") as runner:
            result = self.batch([{"label": "first"}], cutoff_utc=cutoff.isoformat())
        runner.assert_not_called()
        self.assertEqual(result["runs"][0]["verdict"], "cutoff_passed")

    def test_malformed_explicit_cutoff_is_refused_before_receipts(self):
        with self.assertRaises(StudioError):
            self.batch(cutoff_utc="")
        self.assertFalse((self.root / "artifacts").exists())


class CleanroomCutoffTests(CutoffCase):
    def test_expired_cutoff_refuses_capture_before_bench_creation(self):
        with patch("studio_tools.cleanroom.datetime", FakeClock(NOW)), \
                patch("studio_tools.cleanroom.run") as runner:
            with self.assertRaisesRegex(StudioError, "cutoff already passed"):
                self.bench(cutoff_utc=NOW.isoformat())
        runner.assert_not_called()
        self.assertFalse((self.root / "artifacts").exists())

    def test_cutoff_during_preparation_refuses_capture_and_stops_sampler(self):
        cutoff = NOW + timedelta(seconds=10)
        with patch("studio_tools.cleanroom.datetime", FakeClock(NOW, NOW, cutoff)), \
                patch("studio_tools.cleanroom.run") as runner:
            result = self.bench(cutoff_utc=cutoff.isoformat())
        runner.assert_not_called()
        self.assertTrue(self.sampler.instances[0].stopped)
        self.assertEqual(result["capture"]["status"], "refused")
        self.assertIsNone(result["timeout_seconds_effective"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["performance_class"], "diagnostic")

    def test_capture_timeout_is_capped_and_arbitrary_argv_is_intact(self):
        cutoff = NOW + timedelta(seconds=10)
        with patch("studio_tools.cleanroom.datetime", FakeClock(NOW, NOW, NOW + timedelta(seconds=4))), \
                patch("studio_tools.cleanroom.run") as runner:
            result = self.bench(timeout=20, cutoff_utc=cutoff.isoformat())
        self.assertEqual(runner.call_args.args[0], ["capture", "--opaque=value"])
        self.assertEqual(runner.call_args.kwargs["timeout"], 6)
        self.assertEqual(result["timeout_seconds_effective"], 6)
        self.assertEqual(result["timeout_seconds_requested"], 20)
        self.assertEqual(result["cutoff_utc"], cutoff.isoformat())

    def test_requested_timeout_remains_binding(self):
        with patch("studio_tools.cleanroom.datetime", FakeClock(NOW)), \
                patch("studio_tools.cleanroom.run") as runner:
            self.bench(timeout=2, cutoff_utc=(NOW + timedelta(minutes=10)).isoformat())
        self.assertEqual(runner.call_args.kwargs["timeout"], 2)

    def test_settle_wait_is_bounded_by_cutoff(self):
        cutoff = NOW + timedelta(seconds=3)
        with patch("studio_tools.cleanroom.datetime", FakeClock(NOW, NOW, NOW, cutoff)), \
                patch("studio_tools.cleanroom.time.sleep") as sleeper, \
                patch("studio_tools.cleanroom.run") as runner:
            self.bench(settle=30, cutoff_utc=cutoff.isoformat())
        sleeper.assert_called_once_with(3)
        runner.assert_not_called()

    def test_absent_cutoff_preserves_capture_and_receipt_shape(self):
        with patch("studio_tools.cleanroom.run") as runner:
            result = self.bench(timeout=12)
        self.assertEqual(runner.call_args.kwargs["timeout"], 12)
        self.assertNotIn("cutoff_utc", result)
        self.assertNotIn("timeout_seconds_effective", result)

    def test_timeout_cleanup_receipt_and_evidence_guard_are_preserved(self):
        def timed_out(args, **kwargs):
            folder = kwargs["job_dir"]
            folder.mkdir()
            write_json(folder / "process.json", {"status": "timed_out", "cleanup": "owned_tree_stopped"})
            raise StudioError("mock timeout")

        with patch("studio_tools.cleanroom.datetime", FakeClock(NOW)), \
                patch("studio_tools.cleanroom.run", side_effect=timed_out):
            result = self.bench(cutoff_utc=(NOW + timedelta(seconds=10)).isoformat())
        self.assertTrue(self.sampler.instances[0].stopped)
        self.assertEqual(result["capture"]["cleanup"], "owned_tree_stopped")
        self.assertEqual(result["capture"]["status"], "timed_out")
        self.assertFalse(result["ok"])
        self.assertEqual(result["performance_class"], "diagnostic")

    def test_interrupt_still_stops_sampler(self):
        with patch("studio_tools.cleanroom.datetime", FakeClock(NOW)), \
                patch("studio_tools.cleanroom.run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.bench(cutoff_utc=(NOW + timedelta(seconds=10)).isoformat())
        self.assertTrue(self.sampler.instances[0].stopped)

    def test_malformed_explicit_cutoff_is_refused(self):
        with self.assertRaises(StudioError):
            self.bench(cutoff_utc=False)
        self.assertFalse((self.root / "artifacts").exists())


class CutoffCliTests(CutoffCase):
    def test_batch_cli_forwards_cutoff(self):
        cutoff = NOW.isoformat()
        args = cli.parser().parse_args(["batch", "--project", str(self.root), "--plan", "plan.json",
                                        "--sha256", "0" * 64, "--cutoff-utc", cutoff])
        with patch("studio_tools.batch.execute", return_value={}) as execute:
            cli.dispatch(args)
        self.assertEqual(execute.call_args.kwargs["cutoff_utc"], cutoff)

    def test_cleanroom_cli_forwards_cutoff_without_modifying_nested_command(self):
        cutoff = NOW.isoformat()
        nested = ["python", "studio.py", "batch", "--cutoff-utc", cutoff]
        args = cli.parser().parse_args(["bench", "cleanroom", "--project", str(self.root),
                                        "--cutoff-utc", cutoff, "--", *nested])
        with patch("studio_tools.cleanroom.execute", return_value={}) as execute:
            cli.dispatch(args)
        self.assertEqual(execute.call_args.kwargs["cutoff_utc"], cutoff)
        self.assertEqual(execute.call_args.args[2], nested)


if __name__ == "__main__":
    unittest.main()
