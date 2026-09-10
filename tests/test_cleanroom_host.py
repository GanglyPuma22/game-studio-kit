"""Cleanroom benchmark windows and host readiness (offline; no desktop, no registry writes)."""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cleanroom, cli, host, processes
from studio_tools.common import StudioError, read_json
from studio_tools.config import load

ROOT = Path(__file__).resolve().parents[1]
MB = 1024 * 1024


def snap(processes_, at="2026-09-10T10:00:00+00:00", gpu=None, power=None, battery=None, recorder=(),
         process_status="ok", helper_pids=()):
    return {
        "at_utc": at, "monotonic": 0.0, "processes": processes_, "process_count": len(processes_),
        "process_status": process_status, "process_reason": None, "helper_pids": list(helper_pids),
        "gpu": gpu or {"status": "unavailable"}, "power_scheme": power or {"status": "unavailable"},
        "battery": battery or {"status": "unavailable"}, "recorder": list(recorder),
    }


def proc(pid, name, cpu=0.0, ws=10 * MB, ppid=None):
    return {"pid": pid, "ppid": ppid, "name": name, "cpu_seconds": cpu, "working_set_bytes": ws}


WINDOW = {"started_utc": "2026-09-10T10:00:01+00:00", "finished_utc": "2026-09-10T10:05:01+00:00", "elapsed_seconds": 300.0}


class StubSampler:
    """A sampler that observes nothing, so execute tests never depend on what
    else the machine running them happens to start inside the window."""

    recorders = ()
    newcomers = ()
    samples = 2
    instances = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = self.stopped = False
        if self.instances is not None:
            self.instances.append(self)

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True
        return self.observation()

    def observation(self):
        return {
            "sampler": {"mode": "stub", "pid": os.getpid(), "command": "stub",
                        "interval_seconds": self.kwargs.get("interval"), "helper_pids": [], "owned_pids": []},
            "samples": self.samples, "failed_samples": 0,
            "first_sample_utc": "2026-09-10T10:00:02+00:00", "last_sample_utc": "2026-09-10T10:05:00+00:00",
            "recorders": [dict(entry) for entry in self.recorders],
            "newcomers": [dict(entry) for entry in self.newcomers],
        }


def stub_sampler(**attrs):
    """A fresh StubSampler subclass usable as a sampler_factory or as Sampler."""
    return type("ConfiguredStubSampler", (StubSampler,), {"instances": [], **attrs})


def observed(pid, name, first, last, samples=2, cpu=0.0, ws=10 * MB):
    return {"pid": pid, "name": name, "first_seen_utc": first, "last_seen_utc": last,
            "samples": samples, "cpu_seconds": cpu, "working_set_bytes": ws}


class CompareTests(unittest.TestCase):
    def test_flags_new_exited_and_busy_processes_and_ignores_self(self):
        before = snap([proc(1, "idle"), proc(2, "browser", cpu=10.0), proc(3, "big", ws=500 * MB), proc(99, "self", cpu=0.0)])
        after = snap([proc(1, "idle"), proc(2, "browser", cpu=14.0), proc(4, "newcomer", ws=300 * MB), proc(5, "tiny"), proc(99, "self", cpu=50.0)])
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB, self_pid=99)
        self.assertFalse(result["attributable"])
        self.assertEqual([p["name"] for p in result["contamination"]["new_heavy"]], ["newcomer"])
        self.assertEqual([p["name"] for p in result["contamination"]["exited_heavy"]], ["big"])
        self.assertEqual(result["contamination"]["busy"], [{"pid": 2, "name": "browser", "cpu_delta_seconds": 4.0}])
        self.assertEqual(len(result["reasons"]), 3)
        self.assertNotIn("self", json.dumps(result["contamination"]))

    def test_clean_window_is_attributable_and_gpu_unavailable_is_a_limit(self):
        before = snap([proc(1, "idle", cpu=1.0), proc(2, "steady", cpu=5.0)])
        after = snap([proc(1, "idle", cpu=1.2), proc(2, "steady", cpu=5.5)], at="2026-09-10T10:05:02+00:00")
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertTrue(result["attributable"])
        self.assertEqual(result["reasons"], [])
        self.assertIn("GPU counters unavailable for this window", result["limits"])
        self.assertIsNone(result["contamination"]["agent_log"])

    def test_agent_log_timestamps_inside_window_break_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "agent.log"
            # A naive stamp is interpreted as host-local time; derive one from a
            # known UTC instant so the test is correct regardless of host tz.
            naive_local = (
                datetime.fromisoformat("2026-09-10T10:04:00+00:00").astimezone().replace(tzinfo=None).isoformat()
            )
            log.write_text(
                "2026-09-10T09:59:00Z before window secret-before\n"
                "2026-09-10T10:02:30+00:00 tool call secret-inside\n"
                "2026-09-10 10:03:00.250Z another secret-inside\n"
                f"{naive_local} naive stamp secret-naive\n"
                "2026-09-10T10:06:00Z after window\n"
            )
            before = snap([proc(1, "idle")])
            after = snap([proc(1, "idle")])
            result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB, agent_log=log)
        self.assertFalse(result["attributable"])
        self.assertIn("agent activity logged inside the window", result["reasons"])
        self.assertIn("agent log has timestamps without a UTC offset", result["reasons"])
        # The naive stamp maps into the window once read as host-local time.
        self.assertEqual(result["contamination"]["agent_log"]["timestamps_in_window"], 3)
        self.assertEqual(result["contamination"]["agent_log"]["naive_timestamps"], 1)
        self.assertNotIn("secret", json.dumps(result))

    def test_gpu_power_battery_and_recorder_reasons(self):
        gpu_before = {"status": "ok", "devices": [], "compute_apps": [{"pid": 7, "name": "godot", "used_memory_mib": "1"}]}
        gpu_after = {"status": "ok", "devices": [], "compute_apps": [{"pid": 7, "name": "godot", "used_memory_mib": "1"}, {"pid": 8, "name": "blender", "used_memory_mib": "9"}]}
        before = snap([proc(1, "idle")], gpu=gpu_before, power={"status": "ok", "guid": "a", "name": "High performance"})
        after = snap([proc(1, "idle")], gpu=gpu_after, power={"status": "ok", "guid": "b", "name": "Balanced"},
                     battery={"status": "ok", "on_ac": False, "percent": 40}, recorder=[{"pid": 9, "name": "obs64"}])
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        for reason in ("GPU compute processes appeared inside the window", "power scheme changed inside the window",
                       "host is on battery power", "recorder process present"):
            self.assertIn(reason, result["reasons"])
        self.assertNotIn("GPU counters unavailable for this window", result["limits"])

    def test_gpu_compute_apps_exiting_is_also_contamination(self):
        gpu_before = {"status": "ok", "devices": [], "compute_apps": [{"pid": 7, "name": "godot", "used_memory_mib": "1"}]}
        gpu_after = {"status": "ok", "devices": [], "compute_apps": []}
        before = snap([proc(1, "idle")], gpu=gpu_before)
        after = snap([proc(1, "idle")], gpu=gpu_after)
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertIn("GPU compute processes exited inside the window", result["reasons"])
        self.assertFalse(result["attributable"])

    def test_partial_gpu_status_is_treated_as_unavailable_in_compare(self):
        before = snap([proc(1, "idle")], gpu={"status": "partial", "reason": "x", "devices": [], "compute_apps": []})
        after = snap([proc(1, "idle")], gpu={"status": "ok", "devices": [], "compute_apps": []})
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertIn("GPU counters unavailable for this window", result["limits"])
        self.assertEqual(result["reasons"], [])

    def test_battery_reason_fires_from_either_snapshot(self):
        before = snap([proc(1, "idle")], battery={"status": "ok", "on_ac": False, "percent": 80})
        after = snap([proc(1, "idle")], battery={"status": "ok", "on_ac": True, "percent": 79})
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertIn("host is on battery power", result["reasons"])

    def test_pid_reused_by_different_program_or_reset_counter_is_exit_plus_appearance(self):
        # pid 10: OS reused the same pid for a different program.
        # pid 20: same name but its CPU counter went backwards (a restart).
        before = snap([proc(10, "godot", cpu=0.4, ws=50 * MB), proc(20, "helper", cpu=2.0, ws=300 * MB)])
        after = snap([proc(10, "chrome", cpu=0.1, ws=250 * MB), proc(20, "helper", cpu=0.5, ws=10 * MB)],
                     at="2026-09-10T10:05:02+00:00")
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertEqual([p["name"] for p in result["contamination"]["new_heavy"]], ["chrome"])
        self.assertEqual([p["name"] for p in result["contamination"]["exited_heavy"]], ["helper"])
        self.assertEqual(result["contamination"]["busy"], [])

    def test_a_cpu_heavy_process_that_exits_is_contamination_even_when_it_is_small(self):
        # A shader compiler or asset importer can burn a core inside the window
        # and quit before the after snapshot while never holding much memory.
        before = snap([proc(1, "idle"), proc(7, "shader-compiler", cpu=45.0, ws=12 * MB)])
        after = snap([proc(1, "idle")], at="2026-09-10T10:05:02+00:00")
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertEqual([p["name"] for p in result["contamination"]["exited_heavy"]], ["shader-compiler"])
        self.assertEqual(result["contamination"]["exited_heavy"][0]["cpu_seconds"], 45.0)
        self.assertIn("heavy processes exited inside the window", result["reasons"])
        self.assertFalse(result["attributable"])

    def test_compare_refuses_attribution_when_either_snapshot_lacks_process_data(self):
        good = snap([proc(1, "idle"), proc(2, "big", ws=900 * MB)])
        blind = snap([], process_status="unavailable")
        for before, after in ((blind, good), (good, blind), (blind, blind)):
            result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
            self.assertFalse(result["attributable"])
            self.assertIn("host process enumeration failed; the window cannot be attributed", result["reasons"])
            # Half a process table is not evidence of anything appearing or exiting.
            self.assertEqual(result["contamination"]["new_heavy"], [])
            self.assertEqual(result["contamination"]["exited_heavy"], [])
            self.assertEqual(result["contamination"]["busy"], [])
        self.assertEqual(
            cleanroom.compare(good, good, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)["process_enumeration"],
            {"before": "ok", "after": "ok"},
        )

    def test_snapshot_enumeration_helpers_are_not_processes_that_appeared(self):
        # PowerShell lists itself, so the helper each snapshot spawned would
        # otherwise look like a heavy program that appeared inside the window.
        before = snap([proc(1, "idle"), proc(500, "powershell", ws=900 * MB)], helper_pids=[500])
        after = snap([proc(1, "idle"), proc(600, "powershell", ws=900 * MB)], helper_pids=[600])
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertTrue(result["attributable"], result["reasons"])
        self.assertNotIn("powershell", json.dumps(result["contamination"]))


class SamplerTests(unittest.TestCase):
    def sampler(self, tables, **kwargs):
        readings = iter(tables)
        stamps = iter([f"2026-09-10T10:00:{2 + 10 * n:02d}+00:00" for n in range(len(tables))])
        return cleanroom.Sampler(interval=1, reader=lambda on_pid=None: next(readings),
                                 clock=lambda: next(stamps), **kwargs)

    def test_a_recorder_alive_only_between_the_snapshots_is_still_observed(self):
        tables = [
            [proc(1, "idle"), proc(50, "studio")],
            [proc(1, "idle"), proc(50, "studio"), proc(77, "obs64", ws=400 * MB), proc(88, "blender", ws=900 * MB)],
            [proc(1, "idle"), proc(50, "studio"), proc(77, "obs64", ws=420 * MB), proc(88, "blender", ws=900 * MB)],
            [proc(1, "idle"), proc(50, "studio")],
        ]
        sampler = self.sampler(tables, ignore_pids={50})
        for _ in tables:
            sampler.sample()
        during = sampler.observation()
        self.assertEqual(during["samples"], 4)
        self.assertEqual([r["name"] for r in during["recorders"]], ["obs64"])
        self.assertEqual(during["recorders"][0]["first_seen_utc"], "2026-09-10T10:00:12+00:00")
        self.assertEqual(during["recorders"][0]["last_seen_utc"], "2026-09-10T10:00:22+00:00")
        self.assertEqual(during["recorders"][0]["samples"], 2)
        self.assertEqual(sorted(n["name"] for n in during["newcomers"]), ["blender", "obs64"])
        self.assertEqual(during["sampler"]["pid"], os.getpid())
        # Neither snapshot ever saw them; only the mid-window record does.
        before, after = snap([proc(1, "idle")]), snap([proc(1, "idle")])
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0,
                                   heavy_working_set_bytes=200 * MB, during=during)
        self.assertFalse(result["attributable"])
        self.assertIn("a recorder process ran inside the window", result["reasons"])
        self.assertIn("heavy processes ran and exited inside the window", result["reasons"])
        self.assertEqual([n["name"] for n in result["during"]["heavy_newcomers"]], ["blender", "obs64"])
        self.assertFalse(any(n["present_after"] for n in result["during"]["heavy_newcomers"]))

    def test_the_sampler_excludes_its_own_helper_and_the_owned_capture_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "process.json"
            record.write_text(json.dumps({"status": "running", "pid": 4242}), encoding="utf-8")
            tables = [
                [proc(1, "idle")],
                [proc(1, "idle"), proc(4242, "studio", ws=900 * MB),
                 proc(4243, "godot", ws=900 * MB, ppid=4242), proc(999, "powershell", ws=900 * MB)],
            ]
            readings = iter(tables)
            stamps = iter(["2026-09-10T10:00:02+00:00", "2026-09-10T10:00:12+00:00"])

            def reader(on_pid=None):
                if on_pid is not None:
                    on_pid(999)
                return next(readings)

            sampler = cleanroom.Sampler(interval=1, reader=reader, clock=lambda: next(stamps),
                                        owned_record=record)
            sampler.sample()
            sampler.sample()
            during = sampler.observation()
        self.assertEqual(during["newcomers"], [])
        self.assertEqual(during["recorders"], [])
        self.assertEqual(during["sampler"]["helper_pids"], [999])
        self.assertEqual(during["sampler"]["owned_pids"], [4242])

    def test_a_failed_reading_counts_as_a_failed_sample_and_not_as_a_quiet_host(self):
        tables = [[proc(1, "idle")], {"status": "unavailable", "reason": "x", "processes": []}]
        sampler = self.sampler(tables)
        sampler.sample()
        sampler.sample()
        during = sampler.observation()
        self.assertEqual((during["samples"], during["failed_samples"]), (1, 1))
        result = cleanroom.compare(snap([proc(1, "idle")]), snap([proc(1, "idle")]), WINDOW,
                                   busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB, during=during)
        self.assertIn("the window was not sampled between the two snapshots", result["limits"])
        self.assertTrue(result["attributable"], result["reasons"])

    def test_the_threaded_sampler_starts_stops_and_stops_nothing_else(self):
        bystander = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        self.addCleanup(bystander.kill)
        sampler = cleanroom.Sampler(interval=1)
        sampler.start()
        during = sampler.stop()
        self.assertGreaterEqual(during["samples"], 2)
        self.assertEqual(during["sampler"]["mode"], "in-process-thread")
        self.assertIsNone(bystander.poll())
        with self.assertRaisesRegex(StudioError, "already running"):
            sampler.start()


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio bench space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        self.config = load(overrides={"timeout": 5})

    def test_capture_runs_once_between_snapshots_and_leaves_other_processes_alone(self):
        bystander = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        self.addCleanup(bystander.kill)
        snapshots = [snap([proc(1, "idle")]), snap([proc(1, "idle")], at="2026-09-10T10:05:02+00:00")]
        calls = []

        def reader():
            calls.append(len(calls))
            return snapshots[len(calls) - 1]

        capture = [sys.executable, "-c", "import json;print(json.dumps({'ok': True, 'verdict': 'completed'}))"]
        factory = stub_sampler()
        result = cleanroom.execute(self.config, self.root, capture, label="clean", snapshot_reader=reader,
                                   sampler_factory=factory, self_pid=os.getpid())
        self.assertEqual(calls, [0, 1])
        self.assertEqual([(s.started, s.stopped) for s in factory.instances], [(True, True)])
        self.assertEqual(factory.instances[0].kwargs["interval"], 10.0)
        self.assertEqual(Path(factory.instances[0].kwargs["owned_record"]).name, "process.json")
        self.assertIn(os.getpid(), factory.instances[0].kwargs["ignore_pids"])
        self.assertTrue(result["attributable"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["capture"]["status"], "completed")
        self.assertEqual(result["capture"]["verdict"]["verdict"], "completed")
        self.assertIsNone(bystander.poll())
        bench = self.root / "artifacts/bench/clean"
        for name in ("before.json", "after.json", "during.json", "cleanroom.json", "capture/process.json", "capture/stdout.log"):
            self.assertTrue((bench / name).is_file(), name)
        self.assertEqual(read_json(bench / "cleanroom.json")["window"]["elapsed_seconds"], result["window"]["elapsed_seconds"])
        self.assertGreater(result["thresholds"]["busy_cpu_seconds"], 0)

    def test_capture_timeout_is_owned_and_marks_ok_false(self):
        reader = lambda: snap([proc(1, "idle")])
        result = cleanroom.execute(self.config, self.root, [sys.executable, "-c", "import time;time.sleep(30)"],
                                   label="slow", timeout=1, snapshot_reader=reader,
                                   sampler_factory=stub_sampler(), self_pid=os.getpid())
        self.assertFalse(result["ok"])
        self.assertTrue(result["attributable"])
        self.assertEqual(result["capture"]["status"], "timed_out")
        self.assertEqual(result["capture"]["cleanup"], "owned_tree_stopped")
        self.assertIsNone(result["capture"]["verdict"])

    def test_bad_inputs_refused_before_snapshot(self):
        with patch("studio_tools.cleanroom.run") as run:
            for kwargs in ({"capture": []}, {"capture": ["x"], "timeout": 0}, {"capture": ["x"], "settle": -1},
                           {"capture": ["x"], "sample_interval": 0.5}, {"capture": ["x"], "sample_interval": 61},
                           {"capture": ["x"], "agent_log": str(self.root / "missing.log")}):
                with self.assertRaises(StudioError):
                    cleanroom.execute(self.config, self.root, kwargs.pop("capture"), snapshot_reader=lambda: snap([]), **kwargs)
            run.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["bench", "cleanroom", "--project", str(self.root)]), 1)
        self.assertIn("capture command", err.getvalue())

    def test_cli_route_strips_separator(self):
        with patch("studio_tools.cleanroom.Sampler", stub_sampler()), \
                patch("studio_tools.cleanroom.snapshot", side_effect=[snap([proc(1, "idle")]), snap([proc(1, "idle")])]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = cli.main(["bench", "cleanroom", "--project", str(self.root), "--label", "cli", "--",
                                 sys.executable, "-c", "print('{\"ok\": true}')"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["capture"]["verdict"], {"ok": True})

    def test_real_snapshot_readers_run_on_this_host(self):
        result = cleanroom.snapshot()
        self.assertEqual(result["process_status"], "ok")
        self.assertIn(os.getpid(), {p["pid"] for p in result["processes"]})
        self.assertIn(result["gpu"]["status"], {"ok", "partial", "unavailable"})
        self.assertIn(result["power_scheme"]["status"], {"ok", "unavailable"})
        self.assertIn(result["battery"]["status"], {"ok", "unavailable"})
        json.dumps(result, allow_nan=False)

    def test_read_gpu_reports_partial_when_compute_apps_query_fails_but_devices_succeed(self):
        device_csv = "NVIDIA GeForce RTX 4090, 12, 1024, 24576, 2100, 55, 120.5"

        def fake_query(args, timeout=15):
            if any(str(a).startswith("--query-gpu=") for a in args):
                return device_csv
            return None  # The compute-apps query fails while the device query succeeds.

        with patch("studio_tools.cleanroom.shutil.which", return_value="/usr/bin/nvidia-smi"), \
                patch("studio_tools.cleanroom._query", side_effect=fake_query):
            result = cleanroom.read_gpu()
        self.assertEqual(result["status"], "partial")
        self.assertIn("reason", result)
        self.assertEqual(result["compute_apps"], [])
        self.assertEqual(len(result["devices"]), 1)

    def test_scope_is_persisted_and_mismatch_with_capture_scope_is_flagged(self):
        reader = lambda: snap([proc(1, "idle")])
        scoped_capture = [sys.executable, "-c", "import json;print(json.dumps({'ok': True, 'verdict': 'completed', 'scope': 'rung-1'}))"]
        matched = cleanroom.execute(self.config, self.root, scoped_capture, label="match", scope="rung-1",
                                     snapshot_reader=reader, sampler_factory=stub_sampler(), self_pid=os.getpid())
        self.assertEqual(matched["scope"], "rung-1")
        self.assertEqual(matched["scope_check"], "match")
        self.assertTrue(matched["attributable"])
        self.assertNotIn("capture scope does not match bench scope", matched["reasons"])
        mismatched = cleanroom.execute(self.config, self.root, scoped_capture, label="mismatch", scope="rung-2",
                                        snapshot_reader=reader, sampler_factory=stub_sampler(), self_pid=os.getpid())
        self.assertFalse(mismatched["attributable"])
        self.assertEqual(mismatched["scope_check"], "mismatch")
        self.assertIn("capture scope does not match bench scope", mismatched["reasons"])
        with self.assertRaisesRegex(StudioError, "letters, digits"):
            cleanroom.execute(self.config, self.root, scoped_capture, scope="bad scope!", snapshot_reader=reader)

    def test_a_scoped_bench_needs_a_capture_receipt_that_names_the_same_rung(self):
        # Asking for a rung is asking for proof of it: a receipt without a scope,
        # or one that cannot be parsed at all, must not be citable for that rung.
        reader = lambda: snap([proc(1, "idle")])
        for label, capture, expected, reason in (
            ("no-scope-field", "import json;print(json.dumps({'ok': True}))", "missing",
             "capture receipt does not name a scope rung"),
            ("null-scope", "import json;print(json.dumps({'ok': True, 'scope': None}))", "missing",
             "capture receipt does not name a scope rung"),
            ("unparsed", "print('not json at all')", "unparsed",
             "capture receipt could not be parsed, so its scope is unknown"),
        ):
            result = cleanroom.execute(self.config, self.root, [sys.executable, "-c", capture], label=label,
                                       scope="rung-1", snapshot_reader=reader,
                                       sampler_factory=stub_sampler(), self_pid=os.getpid())
            self.assertEqual(result["scope_check"], expected, label)
            self.assertIn(reason, result["reasons"])
            self.assertFalse(result["attributable"], label)
            self.assertFalse(result["ok"], label)
        # Without --scope an unscoped capture receipt is still perfectly fine.
        unscoped = cleanroom.execute(self.config, self.root, [sys.executable, "-c", "print('{\"ok\": true}')"],
                                     label="no-scope-asked", snapshot_reader=reader,
                                     sampler_factory=stub_sampler(), self_pid=os.getpid())
        self.assertIsNone(unscoped["scope_check"])
        self.assertTrue(unscoped["attributable"], unscoped["reasons"])

    def test_execute_records_mid_window_observations_in_the_receipt(self):
        reader = lambda: snap([proc(1, "idle")])
        factory = stub_sampler(recorders=[observed(77, "obs64", "2026-09-10T10:00:12+00:00",
                                                   "2026-09-10T10:00:22+00:00", cpu=9.0, ws=400 * MB)])
        result = cleanroom.execute(self.config, self.root, [sys.executable, "-c", "print('{}')"], label="mid",
                                   snapshot_reader=reader, sampler_factory=factory, self_pid=os.getpid())
        self.assertFalse(result["attributable"])
        self.assertFalse(result["ok"])
        self.assertIn("a recorder process ran inside the window", result["reasons"])
        self.assertEqual(result["during"]["recorders"][0]["name"], "obs64")
        self.assertEqual(result["during"]["recorders"][0]["first_seen_utc"], "2026-09-10T10:00:12+00:00")
        during = read_json(self.root / "artifacts/bench/mid/during.json")
        self.assertEqual(during["recorders"][0]["pid"], 77)
        self.assertEqual(read_json(self.root / "artifacts/bench/mid/cleanroom.json")["during"]["record"],
                         str(self.root / "artifacts/bench/mid/during.json"))

    def test_cli_route_passes_scope_and_sample_interval(self):
        with patch("studio_tools.cleanroom.Sampler", stub_sampler()), \
                patch("studio_tools.cleanroom.snapshot", side_effect=[snap([proc(1, "idle")]), snap([proc(1, "idle")])]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = cli.main(["bench", "cleanroom", "--project", str(self.root), "--label", "cli-scope",
                                 "--scope", "rung-3", "--sample-interval", "5", "--",
                                 sys.executable, "-c", "import json;print(json.dumps({'ok': True, 'scope': 'rung-3'}))"])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["scope"], "rung-3")
        self.assertEqual(result["scope_check"], "match")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["bench", "cleanroom", "--project", str(self.root), "--sample-interval", "99", "--",
                                       sys.executable, "-c", "pass"]), 1)
        self.assertIn("Sample interval", err.getvalue())

    def test_failed_process_enumeration_reports_a_status_instead_of_an_empty_host(self):
        with patch("studio_tools.cleanroom._powershell", return_value=None):
            self.assertEqual(cleanroom.read_processes_windows()["status"], "unavailable")
        with patch("studio_tools.cleanroom._powershell", return_value="pwsh"), \
                patch("studio_tools.cleanroom._query", return_value=None):
            self.assertEqual(cleanroom.read_processes_windows()["processes"], [])
        with patch("studio_tools.cleanroom._powershell", return_value="pwsh"), \
                patch("studio_tools.cleanroom._query", return_value="[]"):
            self.assertEqual(cleanroom.read_processes_windows()["status"], "unavailable")
        with patch("studio_tools.cleanroom.os.sysconf", side_effect=OSError):
            self.assertEqual(cleanroom.read_processes_posix()["status"], "unavailable")
        blind = cleanroom.snapshot(process_reader=lambda on_pid=None: {"status": "unavailable", "reason": "no ps", "processes": []},
                                   gpu_reader=lambda: {"status": "unavailable"},
                                   power_reader=lambda: {"status": "unavailable"},
                                   battery_reader=lambda: {"status": "unavailable"})
        self.assertEqual((blind["process_status"], blind["process_count"]), ("unavailable", 0))
        empty = cleanroom.snapshot(process_reader=lambda on_pid=None: [], gpu_reader=lambda: {"status": "unavailable"},
                                   power_reader=lambda: {"status": "unavailable"}, battery_reader=lambda: {"status": "unavailable"})
        self.assertEqual(empty["process_status"], "unavailable")

    def test_gpu_query_asks_for_used_gpu_memory_and_reports_compute_apps(self):
        calls = []

        def fake_query(args, timeout=15):
            calls.append(" ".join(str(a) for a in args))
            if any(str(a).startswith("--query-gpu=") for a in args):
                return "NVIDIA GeForce RTX 4090, 12, 1024, 24576, 2100, 55, 120.5"
            return "4321, /opt/godot/godot, 512"

        with patch("studio_tools.cleanroom.shutil.which", return_value="/usr/bin/nvidia-smi"), \
                patch("studio_tools.cleanroom._query", side_effect=fake_query):
            result = cleanroom.read_gpu()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["compute_apps"], [{"pid": 4321, "name": "godot", "used_memory_mib": "512"}])
        self.assertTrue(any("--query-compute-apps=pid,process_name,used_gpu_memory" in call for call in calls), calls)


class HostPreflightTests(unittest.TestCase):
    def state(self, **overrides):
        base = {
            "host_kind": "windows",
            "windows_update": {"pause_start": "2026-09-10T00:00:00Z", "pause_expiry": "2026-09-20T00:00:00Z", "feature_end": None, "quality_end": None},
            "active_hours": {"start": 18, "end": 12},
            "pending_reboot": {"cbs": False, "wu": False, "pending_file_rename": False},
            "power_scheme": {"status": "ok", "guid": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "name": "High performance"},
            "battery": {"status": "ok", "on_ac": True, "percent": 100},
        }
        for key, value in overrides.items():
            if isinstance(value, dict):
                base[key].update(value)
            else:
                base[key] = value
        return base

    def evaluate(self, state, start="2026-09-15T02:00:00+00:00", end="2026-09-15T06:00:00+00:00"):
        window = (datetime.fromisoformat(start), datetime.fromisoformat(end))
        return host.evaluate(state, window, now=datetime(2026, 9, 10, tzinfo=timezone.utc), tz=timezone.utc)

    def test_ready_host_has_no_reasons(self):
        result = self.evaluate(self.state())
        self.assertTrue(result["ready"], result["reasons"])
        self.assertEqual(result["checks"]["active_hours"]["window_hours_local"], [2, 3, 4, 5])

    def test_september_nine_active_hours_do_not_cover_the_overnight_window(self):
        result = self.evaluate(self.state(active_hours={"start": 9, "end": 3}), "2026-09-15T03:00:00+00:00", "2026-09-15T09:00:00+00:00")
        self.assertFalse(result["ready"])
        self.assertIn("active hours do not cover the whole window", result["reasons"])
        covered = self.evaluate(self.state(active_hours={"start": 18, "end": 12}), "2026-09-15T03:00:00+00:00", "2026-09-15T09:00:00+00:00")
        self.assertTrue(covered["ready"], covered["reasons"])

    def test_pause_expiry_pending_reboot_power_and_battery_reasons(self):
        expiring = self.evaluate(self.state(windows_update={"pause_expiry": "2026-09-15T04:00:00Z"}))
        self.assertIn("Windows Update pause expires before the window ends", expiring["reasons"])
        unpaused = self.evaluate(self.state(windows_update={"pause_expiry": None}))
        self.assertIn("Windows Update is not paused", unpaused["reasons"])
        pending = self.evaluate(self.state(pending_reboot={"cbs": True}))
        self.assertIn("a reboot is pending; restart before the window", pending["reasons"])
        balanced = self.evaluate(self.state(power_scheme={"guid": "381b4222-f694-41f0-9685-ff5bb260df2e", "name": "Balanced"}))
        self.assertIn("power scheme is not High performance", balanced["reasons"])
        battery = self.evaluate(self.state(battery={"on_ac": False}))
        self.assertIn("host is on battery power", battery["reasons"])
        too_long = self.evaluate(self.state(), "2026-09-15T00:00:00+00:00", "2026-09-15T20:00:00+00:00")
        self.assertIn("window must be between 1 minute and 18 hours long", too_long["reasons"])

    def test_power_scheme_unreadable_is_not_ready(self):
        result = self.evaluate(self.state(power_scheme={"status": "unavailable"}))
        self.assertFalse(result["ready"])
        self.assertIn("power scheme could not be read", result["reasons"])
        self.assertNotIn("power scheme is not High performance", result["reasons"])

    def test_a_window_ending_inside_an_hour_still_needs_that_hour_covered(self):
        # Sampling at hourly offsets from the start would step from 10:59 to
        # 11:59, past the window end, and never notice local hour 11 at all.
        result = self.evaluate(self.state(active_hours={"start": 22, "end": 11}),
                               "2026-09-15T10:59:00+00:00", "2026-09-15T11:01:00+00:00")
        self.assertEqual(result["checks"]["active_hours"]["window_hours_local"], [10, 11])
        self.assertFalse(result["checks"]["active_hours"]["covers_window"])
        self.assertIn("active hours do not cover the whole window", result["reasons"])
        covered = self.evaluate(self.state(active_hours={"start": 22, "end": 12}),
                                "2026-09-15T10:59:00+00:00", "2026-09-15T11:01:00+00:00")
        self.assertTrue(covered["ready"], covered["reasons"])
        # The end instant is exclusive: a window ending exactly on the hour must
        # not demand the hour it stops at.
        exact = self.evaluate(self.state(active_hours={"start": 22, "end": 11}),
                              "2026-09-15T10:00:00+00:00", "2026-09-15T11:00:00+00:00")
        self.assertEqual(exact["checks"]["active_hours"]["window_hours_local"], [10])
        self.assertTrue(exact["ready"], exact["reasons"])

    def test_active_hours_window_walks_the_utc_timeline_across_a_dst_transition(self):
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/New_York")
        # 2026-03-08 is the US spring-forward date; local clocks jump from
        # 02:00 to 03:00, so local hour 2 never exists that day.
        window = (datetime(2026, 3, 8, 6, 0, tzinfo=timezone.utc), datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc))
        state = {"host_kind": "windows", "active_hours": {"start": 0, "end": 6}}
        result = host.evaluate(state, window, now=datetime(2026, 3, 1, tzinfo=timezone.utc), tz=tz)
        self.assertEqual(result["checks"]["active_hours"]["window_hours_local"], [1, 3])

    def test_preflight_with_fake_reader_writes_receipt_and_refuses_half_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "preflight.json"
            result = host.preflight(load(), window_start="2026-09-15T02:00:00Z", window_end="2026-09-15T06:00:00Z", output=output, reader=self.state)
            self.assertEqual(result["kind"], "host-preflight")
            self.assertEqual(read_json(output)["window"]["start_utc"], "2026-09-15T02:00:00+00:00")
            with self.assertRaisesRegex(StudioError, "exists"):
                host.preflight(load(), output=output, reader=self.state)
        with self.assertRaisesRegex(StudioError, "both"):
            host.preflight(load(), window_start="2026-09-15T02:00:00Z", reader=self.state)
        with self.assertRaisesRegex(StudioError, "after"):
            host.preflight(load(), window_start="2026-09-15T06:00:00Z", window_end="2026-09-15T02:00:00Z", reader=self.state)

    def test_receipt_paths_inside_the_installed_toolkit_are_refused(self):
        # The installed package is read-only during production; evidence belongs
        # in a game/output root, like every other mutating command's output.
        with self.assertRaisesRegex(StudioError, "outside the toolkit"):
            host.preflight(load(), output=str(ROOT / "artifacts" / "preflight.json"), reader=self.state)
        with self.assertRaisesRegex(StudioError, "outside the toolkit"):
            host.preflight(load(), output=str(ROOT / "studio_tools" / "preflight.json"), reader=self.state)
        with patch("studio_tools.host.IS_WINDOWS", True), patch("studio_tools.host._powershell", return_value="C:/pwsh.exe"), \
                patch("studio_tools.host.subprocess.run") as runner:
            with self.assertRaisesRegex(StudioError, "outside the toolkit"):
                host.apply(load(), receipt=str(ROOT / "artifacts" / "apply.json"), what_if=True)
            runner.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Windows reads the registry")
    def test_linux_preflight_reports_unsupported_without_exception(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["host", "preflight"]), 1)
        self.assertEqual(err.getvalue(), "")
        result = json.loads(out.getvalue())
        self.assertEqual(result["host_kind"], "unsupported")
        self.assertFalse(result["ready"])
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["host", "apply", "--receipt", str(ROOT / "never.json"), "--what-if"]), 1)
        self.assertIn("native Windows", err.getvalue())

    def test_apply_invokes_script_with_whatif_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "apply.json"
            receipt_body = {"kind": "overnight-host-preparation", "what_if": True}

            def fake_run(command, **kwargs):
                # -WhatIf prints ShouldProcess diagnostics on stdout before the
                # script writes its receipt file; the receipt is the trustworthy result.
                receipt.write_text(json.dumps(receipt_body))
                stdout = (
                    'What if: Performing the operation "set High performance" on target "Power scheme".\n'
                    + json.dumps(receipt_body)
                )
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            with patch("studio_tools.host.IS_WINDOWS", True), patch("studio_tools.host._powershell", return_value="C:/pwsh.exe"), \
                    patch("studio_tools.host.subprocess.run", side_effect=fake_run) as runner:
                result = host.apply(load(), receipt=receipt, pause_days=2, active_start=20, active_end=10, what_if=True)
                command = runner.call_args.args[0]
            self.assertEqual(command[:4], ["C:/pwsh.exe", "-NoProfile", "-NonInteractive", "-File"])
            self.assertTrue(command[4].endswith("Prepare-OvernightHost.ps1"))
            self.assertIn("-WhatIf", command)
            self.assertIn("-ReceiptPath", command)
            self.assertEqual(command[command.index("-PauseDays") + 1], "2")
            self.assertTrue(result["ok"])
            self.assertTrue(result["what_if"])
            self.assertEqual(result["kind"], "overnight-host-preparation")
            with patch("studio_tools.host.IS_WINDOWS", True), patch("studio_tools.host._powershell", return_value="C:/pwsh.exe"), \
                    patch("studio_tools.host.subprocess.run") as runner:
                for kwargs in ({"pause_days": 0}, {"active_start": 5, "active_end": 5}, {"receipt": None}):
                    with self.assertRaises(StudioError):
                        host.apply(load(), **{"receipt": receipt, **kwargs})
                runner.assert_not_called()

    def test_apply_reads_a_receipt_that_carries_a_utf8_byte_order_mark(self):
        # Windows PowerShell 5.1 writes UTF-8 with a BOM through several output
        # paths, and by the time the receipt is read the host is already changed.
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "apply.json"
            body = {"kind": "overnight-host-preparation", "what_if": False, "refused": None}

            def fake_run(command, **kwargs):
                receipt.write_bytes(b"\xef\xbb\xbf" + json.dumps(body).encode("utf-8"))
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("studio_tools.host.IS_WINDOWS", True), patch("studio_tools.host._powershell", return_value="C:/pwsh.exe"), \
                    patch("studio_tools.host.subprocess.run", side_effect=fake_run):
                result = host.apply(load(), receipt=receipt)
            self.assertEqual(result["kind"], "overnight-host-preparation")
            self.assertTrue(result["ok"])
            self.assertTrue(result["receipt_written"])
            # The shared strict reader is what the BOM would have defeated.
            with self.assertRaises(StudioError):
                read_json(receipt)

    def test_apply_falls_back_to_stdout_json_only_when_receipt_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "apply.json"
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"kind": "overnight-host-preparation"}), stderr="")
            with patch("studio_tools.host.IS_WINDOWS", True), patch("studio_tools.host._powershell", return_value="C:/pwsh.exe"), \
                    patch("studio_tools.host.subprocess.run", return_value=completed):
                result = host.apply(load(), receipt=receipt, what_if=True)
            self.assertEqual(result["kind"], "overnight-host-preparation")
            # No receipt on disk: the reported path must not claim otherwise.
            self.assertFalse(result["receipt_written"])
            completed_bad = subprocess.CompletedProcess([], 0, stdout="not json at all", stderr="")
            with patch("studio_tools.host.IS_WINDOWS", True), patch("studio_tools.host._powershell", return_value="C:/pwsh.exe"), \
                    patch("studio_tools.host.subprocess.run", return_value=completed_bad):
                with self.assertRaisesRegex(StudioError, "invalid JSON"):
                    host.apply(load(), receipt=Path(tmp) / "apply2.json", what_if=True)


class PrepareScriptContractTests(unittest.TestCase):
    SCRIPT = ROOT / "skills/studio-review/scripts/host/Prepare-OvernightHost.ps1"

    def test_static_contracts(self):
        source = self.SCRIPT.read_text(encoding="utf-8")
        for needle in ("SupportsShouldProcess = $true", "ShouldProcess(", "function Test-Admin", "function Get-PendingReboot",
                       "PauseUpdatesStartTime", "PauseUpdatesExpiryTime", "PauseFeatureUpdatesStartTime", "PauseFeatureUpdatesEndTime",
                       "PauseQualityUpdatesStartTime", "PauseQualityUpdatesEndTime", "ActiveHoursStart", "-Type DWord",
                       "RebootPending", "RebootRequired", "PendingFileRenameOperations",
                       "[Parameter(Mandatory=$true)][string]$ReceiptPath", "$WhatIfPreference", "ConvertTo-Json",
                       "[System.IO.Directory]::CreateDirectory(",
                       "[System.IO.File]::WriteAllText($ReceiptPath, $json, [System.Text.UTF8Encoding]::new($false))"):
            self.assertIn(needle, source, needle)
        for forbidden in ("Stop-Process", "taskkill", "Remove-Item -Recurse", "Restart-Computer", "shutdown"):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertLess(source.index("Get-PendingReboot\n  if ($pending.cbs"), source.index("Set-ItemProperty"))
        self.assertEqual(host.HOST_ROOT / host.SCRIPT, self.SCRIPT)
        # The apply refusal must also cover a pending file-rename operation.
        self.assertIn("if ($pending.cbs -or $pending.wu -or $pending.pending_file_rename)", source)
        # Every powercfg /setactive call (apply and -Restore) must check $LASTEXITCODE
        # and refuse to continue silently if Windows rejected the scheme change.
        contract = re.findall(
            r"powercfg /setactive \$\w+ \| Out-Null\s*\n\s*if \(\$LASTEXITCODE -ne 0\) \{ throw 'powercfg rejected the scheme change' \}",
            source,
        )
        self.assertEqual(len(contract), source.count("powercfg /setactive"))
        self.assertGreaterEqual(len(contract), 2)
        # The receipt is the evidence that the run happened, -WhatIf included.
        # ShouldProcess suppresses the file-writing cmdlets, and Windows
        # PowerShell 5.1 gives `Set-Content -Encoding UTF8` a byte-order mark
        # the caller's strict UTF-8 reader would reject after the host was
        # already changed, so the write goes through .NET instead.
        self.assertNotIn("Set-Content", source)
        self.assertNotIn("-Encoding UTF8", source)
        self.assertNotIn("New-Item -ItemType Directory", source)
        self.assertGreater(source.index("[System.IO.File]::WriteAllText"), source.rindex("ShouldProcess("))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell parser not installed")
    def test_script_parses(self):
        check = ("$e=$null;[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e)|Out-Null;"
                 "if($e.Count){exit 1}" % self.SCRIPT.as_posix())
        self.assertEqual(subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", check], check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
