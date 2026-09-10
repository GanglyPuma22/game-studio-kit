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


def snap(processes_, at="2026-09-10T10:00:00+00:00", gpu=None, power=None, battery=None, recorder=()):
    return {
        "at_utc": at, "monotonic": 0.0, "processes": processes_, "process_count": len(processes_),
        "gpu": gpu or {"status": "unavailable"}, "power_scheme": power or {"status": "unavailable"},
        "battery": battery or {"status": "unavailable"}, "recorder": list(recorder),
    }


def proc(pid, name, cpu=0.0, ws=10 * MB):
    return {"pid": pid, "name": name, "cpu_seconds": cpu, "working_set_bytes": ws}


WINDOW = {"started_utc": "2026-09-10T10:00:01+00:00", "finished_utc": "2026-09-10T10:05:01+00:00", "elapsed_seconds": 300.0}


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
        before = snap([proc(10, "godot", cpu=5.0, ws=50 * MB), proc(20, "helper", cpu=2.0, ws=300 * MB)])
        after = snap([proc(10, "chrome", cpu=0.1, ws=250 * MB), proc(20, "helper", cpu=0.5, ws=10 * MB)],
                     at="2026-09-10T10:05:02+00:00")
        result = cleanroom.compare(before, after, WINDOW, busy_cpu_seconds=1.0, heavy_working_set_bytes=200 * MB)
        self.assertEqual([p["name"] for p in result["contamination"]["new_heavy"]], ["chrome"])
        self.assertEqual([p["name"] for p in result["contamination"]["exited_heavy"]], ["helper"])
        self.assertEqual(result["contamination"]["busy"], [])


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
        result = cleanroom.execute(self.config, self.root, capture, label="clean", snapshot_reader=reader, self_pid=os.getpid())
        self.assertEqual(calls, [0, 1])
        self.assertTrue(result["attributable"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["capture"]["status"], "completed")
        self.assertEqual(result["capture"]["verdict"]["verdict"], "completed")
        self.assertIsNone(bystander.poll())
        bench = self.root / "artifacts/bench/clean"
        for name in ("before.json", "after.json", "cleanroom.json", "capture/process.json", "capture/stdout.log"):
            self.assertTrue((bench / name).is_file(), name)
        self.assertEqual(read_json(bench / "cleanroom.json")["window"]["elapsed_seconds"], result["window"]["elapsed_seconds"])
        self.assertGreater(result["thresholds"]["busy_cpu_seconds"], 0)

    def test_capture_timeout_is_owned_and_marks_ok_false(self):
        reader = lambda: snap([proc(1, "idle")])
        result = cleanroom.execute(self.config, self.root, [sys.executable, "-c", "import time;time.sleep(30)"],
                                   label="slow", timeout=1, snapshot_reader=reader, self_pid=os.getpid())
        self.assertFalse(result["ok"])
        self.assertTrue(result["attributable"])
        self.assertEqual(result["capture"]["status"], "timed_out")
        self.assertEqual(result["capture"]["cleanup"], "owned_tree_stopped")
        self.assertIsNone(result["capture"]["verdict"])

    def test_bad_inputs_refused_before_snapshot(self):
        with patch("studio_tools.cleanroom.run") as run:
            for kwargs in ({"capture": []}, {"capture": ["x"], "timeout": 0}, {"capture": ["x"], "settle": -1},
                           {"capture": ["x"], "agent_log": str(self.root / "missing.log")}):
                with self.assertRaises(StudioError):
                    cleanroom.execute(self.config, self.root, kwargs.pop("capture"), snapshot_reader=lambda: snap([]), **kwargs)
            run.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["bench", "cleanroom", "--project", str(self.root)]), 1)
        self.assertIn("capture command", err.getvalue())

    def test_cli_route_strips_separator(self):
        with patch("studio_tools.cleanroom.snapshot", side_effect=[snap([proc(1, "idle")]), snap([proc(1, "idle")])]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = cli.main(["bench", "cleanroom", "--project", str(self.root), "--label", "cli", "--",
                                 sys.executable, "-c", "print('{\"ok\": true}')"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["capture"]["verdict"], {"ok": True})

    def test_real_snapshot_readers_run_on_this_host(self):
        result = cleanroom.snapshot()
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
                                     snapshot_reader=reader, self_pid=os.getpid())
        self.assertEqual(matched["scope"], "rung-1")
        self.assertTrue(matched["attributable"])
        self.assertNotIn("capture scope does not match bench scope", matched["reasons"])
        mismatched = cleanroom.execute(self.config, self.root, scoped_capture, label="mismatch", scope="rung-2",
                                        snapshot_reader=reader, self_pid=os.getpid())
        self.assertFalse(mismatched["attributable"])
        self.assertIn("capture scope does not match bench scope", mismatched["reasons"])
        no_scope_field = [sys.executable, "-c", "import json;print(json.dumps({'ok': True}))"]
        unscoped_result = cleanroom.execute(self.config, self.root, no_scope_field, label="no-scope-field", scope="rung-1",
                                             snapshot_reader=reader, self_pid=os.getpid())
        self.assertNotIn("capture scope does not match bench scope", unscoped_result["reasons"])
        with self.assertRaisesRegex(StudioError, "letters, digits"):
            cleanroom.execute(self.config, self.root, scoped_capture, scope="bad scope!", snapshot_reader=reader)

    def test_cli_route_passes_scope(self):
        with patch("studio_tools.cleanroom.snapshot", side_effect=[snap([proc(1, "idle")]), snap([proc(1, "idle")])]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = cli.main(["bench", "cleanroom", "--project", str(self.root), "--label", "cli-scope", "--scope", "rung-3", "--",
                                 sys.executable, "-c", "print('{\"ok\": true}')"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["scope"], "rung-3")


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

    def test_apply_falls_back_to_stdout_json_only_when_receipt_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "apply.json"
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"kind": "overnight-host-preparation"}), stderr="")
            with patch("studio_tools.host.IS_WINDOWS", True), patch("studio_tools.host._powershell", return_value="C:/pwsh.exe"), \
                    patch("studio_tools.host.subprocess.run", return_value=completed):
                result = host.apply(load(), receipt=receipt, what_if=True)
            self.assertEqual(result["kind"], "overnight-host-preparation")
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
                       "[Parameter(Mandatory=$true)][string]$ReceiptPath", "$WhatIfPreference", "ConvertTo-Json"):
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

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell parser not installed")
    def test_script_parses(self):
        check = ("$e=$null;[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e)|Out-Null;"
                 "if($e.Count){exit 1}" % self.SCRIPT.as_posix())
        self.assertEqual(subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", check], check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
