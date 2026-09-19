"""Windows descendant identity: who a PID belongs to before anything is killed.

There is no Windows host here, so the CIM rows and the handle times are fakes,
as in `test_cleanroom_host.py`. No test signals a real process on Windows: the
point of these is that `taskkill` is reached for a proven descendant and for
nothing else.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from studio_tools import launch, processes
from studio_tools.common import read_json, sha256
from studio_tools.config import load

# The job's root: started at 100, exited at 200, in FILETIME ticks.
ROOT = {"pid": 10, "name": "godot.exe", "created_filetime": "100", "exited_filetime": "200"}


def row(pid, ppid, created, name="worker.exe"):
    return {"pid": pid, "ppid": ppid, "name": name, "created_filetime": created}


def snapshot(*rows):
    return {"status": "ok", "processes": list(rows), "note": None}


def ownership(*prelaunch, status="ok", identity=ROOT):
    """The evidence `run` records on Windows, as it reaches cleanup."""
    return {
        "status": status,
        "identity": identity,
        "prelaunch": [{"pid": entry["pid"], "created_filetime": entry["created_filetime"]}
                      for entry in prelaunch],
        "note": None,
    }


class WindowsIdentityCase(unittest.TestCase):
    def windows(self):
        return patch("studio_tools.processes.os.name", "nt")

    def options(self):
        # This host has no Windows creation flags to pass to subprocess.
        return patch("studio_tools.processes._creation_options", return_value={})

    def identities(self, *rows):
        """`_windows_identity` answering from a table, as the live host would."""
        table = {entry["pid"]: entry for entry in rows}
        return patch("studio_tools.processes._windows_identity",
                     side_effect=lambda pid, hide_window: table.get(pid))


class WindowsDescendantClassificationTests(WindowsIdentityCase):
    def test_a_reused_root_pid_is_not_walked_into_a_strangers_tree(self):
        # Something else holds PID 10 now, and it has a child of its own.
        stranger = row(20, 10, "500", name="unrelated.exe")
        below = row(30, 20, "600", name="unrelated-child.exe")
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      return_value=snapshot(stranger, below)), \
                patch("studio_tools.processes._windows_identity") as identity, \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["status"], "unavailable")
        # The stranger is reported, its child never even reached: an unproven
        # row does not lend its children this job's name.
        self.assertEqual(result["pids"], [20])
        self.assertEqual(result["verified_pids"], [])
        self.assertEqual(result["unverified"],
                         [{"pid": 20, "reason": "created_outside_root_lifetime"}])
        self.assertFalse(result["stopped"])
        identity.assert_not_called()
        terminate.assert_not_called()

    def test_a_child_born_in_the_root_lifetime_is_stopped_and_reported(self):
        child = row(20, 10, "110")
        grandchild = row(30, 20, "120")
        unrelated = snapshot(row(99, 1, "50", name="explorer.exe"))
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(child, grandchild), unrelated]), \
                self.identities(child, grandchild), \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, hide_window=True, ownership=ownership())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pids"], [20, 30])
        self.assertEqual(result["verified_pids"], [20, 30])
        self.assertEqual(result["unverified"], [])
        self.assertTrue(result["stopped"])
        self.assertEqual(
            [tuple(entry.args[0]) for entry in terminate.call_args_list],
            [("taskkill", "/PID", "20", "/T", "/F"), ("taskkill", "/PID", "30", "/T", "/F")],
        )

    def test_a_candidate_without_a_creation_time_is_reported_not_terminated(self):
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      return_value=snapshot(row(20, 10, None))), \
                patch("studio_tools.processes._windows_identity") as identity, \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["pids"], [20])
        self.assertEqual(result["verified_pids"], [])
        self.assertEqual(result["unverified"],
                         [{"pid": 20, "reason": "current_identity_incomplete"}])
        # A run that left something it cannot name has not cleaned up.
        self.assertFalse(result["stopped"])
        identity.assert_not_called()
        terminate.assert_not_called()

    def test_a_process_already_running_before_the_launch_is_not_a_descendant(self):
        older = row(20, 10, "50", name="agent.exe")
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(older), snapshot(older)]), \
                patch("studio_tools.processes._windows_identity") as identity, \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=ownership(older))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pids"], [])
        self.assertEqual(result["ignored"], [20])
        self.assertTrue(result["stopped"])
        identity.assert_not_called()
        terminate.assert_not_called()

    def test_a_prelaunch_pid_reused_during_the_run_is_still_classified(self):
        # Same number, different process: the creation time says so.
        current = row(20, 10, "150")
        before = row(20, 10, "50", name="agent.exe")
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(current), snapshot()]), \
                self.identities(current), \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=ownership(before))
        self.assertEqual(result["verified_pids"], [20])
        self.assertEqual(result["ignored"], [])
        terminate.assert_called_once()

    def test_a_prelaunch_row_without_a_creation_time_blocks_termination(self):
        blind = {"pid": 20, "created_filetime": None}
        evidence = ownership()
        evidence["prelaunch"] = [blind]
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      return_value=snapshot(row(20, 10, "110"))), \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=evidence)
        self.assertEqual(result["unverified"],
                         [{"pid": 20, "reason": "prelaunch_identity_incomplete"}])
        self.assertFalse(result["stopped"])
        terminate.assert_not_called()


class WindowsTerminationBoundaryTests(WindowsIdentityCase):
    def test_a_pid_that_changed_hands_before_the_kill_is_skipped(self):
        child = row(20, 10, "110")
        recycled = row(20, 10, "300", name="unrelated.exe")
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(child), snapshot(recycled)]), \
                self.identities(recycled), \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["status"], "unavailable")
        self.assertIn({"pid": 20, "reason": "identity_changed_before_stop"}, result["unverified"])
        self.assertFalse(result["stopped"])
        terminate.assert_not_called()

    def test_without_launch_evidence_nothing_under_the_pid_is_signalled(self):
        child = row(20, 10, "110")
        for evidence in (None, ownership(status="unavailable"),
                         ownership(identity={**ROOT, "exited_filetime": None}),
                         ownership(identity={**ROOT, "pid": 11})):
            with self.subTest(evidence=evidence):
                with self.windows(), self.options(), \
                        patch("studio_tools.processes._windows_snapshot",
                              return_value=snapshot(child)), \
                        patch("studio_tools.processes.subprocess.run") as terminate:
                    result = processes.stop_survivors(10, ownership=evidence)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["unverified"],
                                 [{"pid": 20, "reason": "ownership_evidence_unavailable"}])
                self.assertFalse(result["stopped"])
                terminate.assert_not_called()

    def test_a_host_that_cannot_enumerate_reports_instead_of_guessing(self):
        blind = {"status": "unavailable", "processes": [], "note": "process enumeration failed"}
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot", return_value=blind), \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["pids"], [])
        self.assertFalse(result["stopped"])
        terminate.assert_not_called()


class WindowsRootIdentityTests(unittest.TestCase):
    """The handle `Popen` owns is read while the PID still means this process."""

    def kernel(self, created=110, exited=200, image="C:\\Godot\\godot.exe", times=1, name=1):
        kernel = MagicMock()

        def fill_times(handle, creation, exit_time, in_kernel, in_user):
            if not times:
                return 0
            creation._obj.low, creation._obj.high = created, 0
            exit_time._obj.low, exit_time._obj.high = exited, 0
            return 1

        def fill_name(handle, flags, buffer, size):
            if not name:
                return 0
            buffer.value = image
            return 1

        kernel.GetProcessTimes.side_effect = fill_times
        kernel.QueryFullProcessImageNameW.side_effect = fill_name
        return kernel

    def test_identity_comes_from_the_handle_not_from_the_pid(self):
        process = MagicMock(pid=4242, _handle=7)
        with patch("ctypes.WinDLL", return_value=self.kernel(), create=True):
            with patch("studio_tools.processes._windows_identity") as lookup:
                identity = processes._windows_root_identity(process, False)
            self.assertEqual(processes._windows_handle_times(process), ("110", "200"))
        self.assertEqual(identity, {"pid": 4242, "name": "godot.exe",
                                    "created_filetime": "110", "exited_filetime": None})
        lookup.assert_not_called()

    def test_a_running_process_has_no_exit_time_yet(self):
        process = MagicMock(pid=4242, _handle=7)
        with patch("ctypes.WinDLL", return_value=self.kernel(exited=0), create=True):
            self.assertEqual(processes._windows_handle_times(process), ("110", None))

    def test_a_handle_that_cannot_be_read_falls_back_to_the_live_row(self):
        process = MagicMock(pid=4242, _handle=7)
        live = row(4242, 10, "110", name="godot.exe")
        with patch("ctypes.WinDLL", side_effect=OSError("no Windows APIs"), create=True):
            with patch("studio_tools.processes._windows_identity", return_value=live):
                identity = processes._windows_root_identity(process, False)
            self.assertEqual(identity["name"], "godot.exe")
            self.assertEqual(identity["created_filetime"], "110")
            # A host that cannot answer at all gets no invented identity.
            with patch("studio_tools.processes._windows_identity", return_value=None):
                self.assertIsNone(processes._windows_root_identity(process, False))

    def test_the_recorded_evidence_carries_identity_and_no_host_inventory(self):
        baseline = snapshot(row(99, 1, "50", name="private-tool.exe"))
        evidence = processes._windows_ownership(baseline, dict(ROOT))
        self.assertEqual(evidence["status"], "ok")
        self.assertEqual(evidence["identity"], ROOT)
        # Only what the "was already running" test reads is kept; a receipt is
        # not a list of every program on the operator's machine.
        self.assertEqual(evidence["prelaunch"], [{"pid": 99, "created_filetime": "50"}])
        self.assertNotIn("private-tool", str(evidence))
        blind = processes._windows_ownership(
            {"status": "unavailable", "processes": [], "note": "no"}, dict(ROOT))
        self.assertEqual(blind["status"], "unavailable")
        self.assertEqual(processes._windows_ownership(baseline, None)["status"], "unavailable")


class PosixSurvivorTests(unittest.TestCase):
    @unittest.skipUnless(os.name != "nt" and Path("/proc").is_dir(),
                         "descendant enumeration needs POSIX /proc")
    def test_the_process_group_is_still_stopped_whatever_windows_evidence_says(self):
        tmp = tempfile.TemporaryDirectory(prefix="studio process identity ")
        self.addCleanup(tmp.cleanup)
        code = ("import subprocess,sys;"
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
                "print(child.pid)")
        result = processes.run([sys.executable, "-c", code], job_dir=Path(tmp.name) / "job")
        record = read_json(Path(tmp.name) / "job/process.json")
        grandchild = int(result["stdout"].split()[0])
        self.addCleanup(self._reap, grandchild)
        # Windows evidence is meaningless here and must not change the outcome.
        left = processes.stop_survivors(record["pid"], ownership=ownership())
        self.assertEqual(left["status"], "ok")
        self.assertEqual(left["pids"], [grandchild])
        self.assertTrue(left["stopped"])
        self.assertEqual(left["unverified"], [])
        self.assertNotIn("windows_ownership", record)
        self.assertFalse(self._alive(grandchild))

    def _alive(self, pid):
        state = processes._proc_state(pid)
        return state is not None and state[0] != "Z"

    def _reap(self, pid):
        try:
            os.kill(pid, 9)
        except OSError:
            pass


class UnverifiedDescendantReceiptTests(unittest.TestCase):
    """What a launch receipt says when a process could not be attributed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio unverified space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)

    def test_a_launch_with_unverified_descendants_does_not_claim_it_stopped_them(self):
        left = {
            "status": "unavailable", "pids": [4242, 4243], "stopped": False,
            "verified_pids": [4242],
            "unverified": [{"pid": 4243, "reason": "current_identity_incomplete"}],
            "ignored": [], "note": "left running",
        }
        code = ("import os,sys;print('private-arg');"
                "print(os.environ['STUDIO_JOB_FIXTURE'],file=sys.stderr)")

        def fake_run(args, **kwargs):
            return processes.run([sys.executable, "-c", code], **kwargs)

        with patch.dict(os.environ, {"STUDIO_JOB_FIXTURE": "private-env"}):
            with patch("studio_tools.launch.run", side_effect=fake_run):
                with patch("studio_tools.launch.stop_survivors", return_value=left):
                    result = launch.execute(self.config, self.root,
                                            sha256_expected=self.sha, label="unattributed")
        self.assertEqual(result["verdict"], "descendants_unverified")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["survivors"]["stopped"])
        self.assertEqual(result["survivors"]["unverified"],
                         [{"pid": 4243, "reason": "current_identity_incomplete"}])
        self.assertIn("4243", result["failure"])
        run_dir = self.root / "artifacts/launches/unattributed"
        for name in ("owned-launch.json", "exit.json"):
            receipt = read_json(run_dir / name)
            self.assertEqual(receipt["survivors"]["unverified"], left["unverified"])
            self.assertFalse(receipt["survivors"]["stopped"])
            self.assertNotIn("private-", (run_dir / name).read_text())


if __name__ == "__main__":
    unittest.main()
