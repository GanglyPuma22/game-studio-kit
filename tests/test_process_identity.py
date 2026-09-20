"""Windows descendant identity: who a PID belongs to before anything is killed.

There is no Windows host here, so the CIM rows and the handle times are fakes,
as in `test_cleanroom_host.py`. No test signals a real process on Windows: the
point of these is that `taskkill` is reached for a proven descendant and for
nothing else.
"""

from datetime import datetime, timedelta, timezone
import itertools
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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


class Host:
    """A fake Windows process table that a signalled PID actually leaves.

    One object answers both the per-PID lookup and `taskkill`, so a kill this
    test lets through takes the row out while one named in `survive` stays: the
    difference the cleanup loop now has to notice on its own, because a walk
    from the root cannot see past a parent that is already gone.
    """

    def __init__(self, *rows, survive=()):
        self.table = {entry["pid"]: entry for entry in rows}
        self.survive = set(survive)
        self.commands = []

    def lookup(self):
        return patch("studio_tools.processes._windows_identity_state", self.state)

    def taskkill(self):
        return patch("studio_tools.processes.subprocess.run", self.terminate)

    def state(self, pid, hide_window):
        entry = self.table.get(pid)
        return ("present", entry) if entry is not None else ("absent", None)

    def terminate(self, args, **kwargs):
        self.commands.append(tuple(args))
        member = int(args[2])
        if member not in self.survive:
            self.table.pop(member, None)
        return SimpleNamespace(returncode=0)

    @property
    def kills(self):
        return [int(command[2]) for command in self.commands]


class WindowsIdentityCase(unittest.TestCase):
    def windows(self):
        return patch("studio_tools.processes.os.name", "nt")

    def options(self):
        # This host has no Windows creation flags to pass to subprocess.
        return patch("studio_tools.processes._creation_options", return_value={})

    def deadline(self, step=2):
        """A clock that reaches the five-second cleanup deadline in a few polls.

        Only `_windows_stop` reads the module's clock, and a test that waits
        out a real deadline proves nothing the step size does not.
        """
        ticks = itertools.count(0, step)
        return patch("studio_tools.processes.time",
                     SimpleNamespace(monotonic=lambda: next(ticks),
                                     sleep=lambda seconds: None))

    def identities(self, *rows):
        """`_windows_identity_state` answering from a table, as the live host would.

        A PID the table does not hold is absent, which is what the live query
        reports for a process that exited between the snapshot and the kill.
        """
        table = {entry["pid"]: entry for entry in rows}
        return patch(
            "studio_tools.processes._windows_identity_state",
            side_effect=lambda pid, hide_window: (
                ("present", table[pid]) if pid in table else ("absent", None)
            ),
        )


class WindowsDescendantClassificationTests(WindowsIdentityCase):
    def test_a_reused_root_pid_is_not_walked_into_a_strangers_tree(self):
        # Something else holds PID 10 now, and it has a child of its own.
        stranger = row(20, 10, "500", name="unrelated.exe")
        below = row(30, 20, "600", name="unrelated-child.exe")
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      return_value=snapshot(stranger, below)), \
                patch("studio_tools.processes._windows_identity_state") as identity, \
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
        host = Host(child, grandchild)
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(child, grandchild), unrelated]), \
                host.lookup(), host.taskkill():
            result = processes.stop_survivors(10, hide_window=True, ownership=ownership())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pids"], [20, 30])
        self.assertEqual(result["verified_pids"], [20, 30])
        self.assertEqual(result["unverified"], [])
        self.assertTrue(result["stopped"])
        # Each proven PID on its own and deepest first, so the parent's row is
        # still there to be walked while its child is being confirmed gone.
        self.assertEqual(
            host.commands,
            [("taskkill", "/PID", "30", "/F"), ("taskkill", "/PID", "20", "/F")],
        )
        self.assertEqual(result["exited_pids"], [])
        self.assertEqual(result["unstopped_pids"], [])

    def test_a_candidate_without_a_creation_time_is_reported_not_terminated(self):
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      return_value=snapshot(row(20, 10, None))), \
                patch("studio_tools.processes._windows_identity_state") as identity, \
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
                patch("studio_tools.processes._windows_identity_state") as identity, \
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
        host = Host(current)
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(current), snapshot()]), \
                host.lookup(), host.taskkill():
            result = processes.stop_survivors(10, ownership=ownership(before))
        self.assertEqual(result["verified_pids"], [20])
        self.assertEqual(result["ignored"], [])
        self.assertEqual(host.kills, [20])

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

    def test_only_the_proven_pid_is_signalled_not_the_tree_under_it(self):
        # A child the same walk refused hangs under a verified one: /T would
        # have taken it along, which is exactly what it is not this job's to do.
        child = row(20, 10, "110")
        stranger = row(30, 20, "900", name="unrelated.exe")
        host = Host(child, stranger)
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(child, stranger), snapshot(stranger)]), \
                host.lookup(), host.taskkill():
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["verified_pids"], [20])
        self.assertEqual(host.commands, [("taskkill", "/PID", "20", "/F")])
        self.assertEqual(result["unverified"],
                         [{"pid": 30, "reason": "created_outside_root_lifetime"}])
        self.assertFalse(result["stopped"])

    def test_a_pid_that_exited_before_the_kill_counts_as_stopped(self):
        # The child ended on its own between the snapshot and the lookup: there
        # is nothing to signal, and nothing left running to report either.
        child = row(20, 10, "110")
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(child), snapshot()]), \
                self.identities(), \
                patch("studio_tools.processes.subprocess.run") as terminate:
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["exited_pids"], [20])
        self.assertEqual(result["unverified"], [])
        self.assertTrue(result["stopped"])
        terminate.assert_not_called()

    def test_a_lookup_that_failed_before_the_kill_is_refused_not_signalled(self):
        child = row(20, 10, "110")
        recycled = row(20, 10, "300", name="unrelated.exe")
        cases = [
            (("present", recycled), "identity_changed_before_stop"),
            (("unknown", None), "identity_unavailable_before_stop"),
        ]
        for answer, reason in cases:
            with self.subTest(reason=reason):
                with self.windows(), self.options(), \
                        patch("studio_tools.processes._windows_snapshot",
                              side_effect=[snapshot(child), snapshot(recycled)]), \
                        patch("studio_tools.processes._windows_identity_state",
                              return_value=answer), \
                        patch("studio_tools.processes.subprocess.run") as terminate:
                    result = processes.stop_survivors(10, ownership=ownership())
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["exited_pids"], [])
                self.assertIn({"pid": 20, "reason": reason}, result["unverified"])
                self.assertFalse(result["stopped"])
                terminate.assert_not_called()

    def test_an_unverified_process_seen_only_while_stopping_is_still_reported(self):
        # It appears under the child while the child is being stopped, and is
        # gone from the last snapshot: without accumulation the run would end
        # clean while a process nobody can name was still running.
        child = row(20, 10, "110")
        latecomer = row(30, 20, "900", name="unrelated.exe")
        host = Host(child)
        with self.windows(), self.options(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=[snapshot(child), snapshot(child, latecomer), snapshot()]), \
                host.lookup(), host.taskkill():
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["unverified"],
                         [{"pid": 30, "reason": "created_outside_root_lifetime"}])
        self.assertFalse(result["stopped"])

    def test_a_kill_that_failed_deep_in_the_tree_is_not_reported_as_stopped(self):
        # The parent went, so a walk from the root cannot reach the grandchild
        # at all: an empty enumeration would pass for a tree that stopped, and
        # only the grandchild's own lookup can say it is still running.
        child = row(20, 10, "110")
        grandchild = row(30, 20, "120")
        host = Host(child, grandchild, survive=[30])
        walks = [snapshot(child, grandchild)]
        with self.windows(), self.options(), self.deadline(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=lambda hide_window: walks.pop(0) if walks else snapshot()), \
                host.lookup(), host.taskkill():
            result = processes.stop_survivors(10, ownership=ownership())
        # Deepest first: the grandchild is signalled while its parent's row is
        # still in the table, so the walk can still account for it.
        self.assertEqual(host.kills, [30, 20])
        self.assertEqual(result["unstopped_pids"], [30])
        self.assertFalse(result["stopped"])
        self.assertIn("still running", result["note"])

    def test_a_signalled_pid_that_cannot_be_read_again_is_unconfirmed(self):
        child = row(20, 10, "110")
        # Present at the kill, then the host stops answering about it: nothing
        # says it stopped and nothing says it is running.
        answers = [("present", child)]
        walks = [snapshot(child)]
        with self.windows(), self.options(), self.deadline(), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=lambda hide_window: walks.pop(0) if walks else snapshot()), \
                patch("studio_tools.processes._windows_identity_state",
                      side_effect=lambda pid, hide_window: (
                          answers.pop(0) if answers else ("unknown", None))), \
                patch("studio_tools.processes.subprocess.run"):
            result = processes.stop_survivors(10, ownership=ownership())
        self.assertEqual(result["unverified"], [{"pid": 20, "reason": "stop_unconfirmed"}])
        self.assertEqual(result["unstopped_pids"], [])
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["stopped"])

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


class Clock:
    """`datetime.now` as the launch module reads it, advanced by the work between.

    Only `now` is scripted; everything else the module asks `datetime` for is
    the real thing.
    """

    fromisoformat = staticmethod(datetime.fromisoformat)

    def __init__(self, value):
        self.value = value

    def now(self, tz=None):
        return self.value


class PrelaunchSnapshotTests(unittest.TestCase):
    """The enumeration is slow, so who pays for it and when decides a launch."""

    def windows(self):
        """A Windows `os.name` for this module alone.

        Patching the real `os.name` would also make `pathlib` parse every path
        as a Windows path, which this host cannot even instantiate.
        """
        return patch("studio_tools.processes.os", SimpleNamespace(name="nt"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio prelaunch space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        self.config = load(overrides={"executables": {"godot": sys.executable}, "timeout": 5})
        self.sha = sha256(sys.executable)

    def test_the_cutoff_is_rechecked_after_the_prelaunch_snapshot(self):
        opened = datetime.now(timezone.utc)
        clock = Clock(opened)
        taken = []

        def slow_snapshot(hide_window=False):
            # Half a minute of PowerShell: the window closes while it runs, and
            # a check made before it would already have authorized the launch.
            taken.append(hide_window)
            clock.value = opened + timedelta(seconds=31)
            return snapshot()

        with patch("studio_tools.launch.datetime", clock), \
                patch("studio_tools.launch.prelaunch_baseline", slow_snapshot), \
                patch("studio_tools.launch.run") as started:
            result = launch.execute(
                self.config, self.root, sha256_expected=self.sha, label="slow-snapshot",
                cutoff_utc=(opened + timedelta(seconds=30)).isoformat(),
            )
            started.assert_not_called()
        self.assertEqual(result["verdict"], "cutoff_passed")
        self.assertFalse(result["ok"])
        self.assertEqual(taken, [True])
        run_dir = self.root / "artifacts/launches/slow-snapshot"
        owned = read_json(run_dir / "owned-launch.json")
        self.assertEqual(owned["status"], "refused")
        self.assertIsNone(owned["timeout_seconds_effective"])
        self.assertFalse((run_dir / "process").exists())

    def test_the_engine_is_rehashed_after_the_prelaunch_snapshot(self):
        engine = Path(self.tmp.name) / "swappable engine"
        engine.write_bytes(b"verified engine bytes")
        engine.chmod(0o755)
        config = load(overrides={"executables": {"godot": str(engine)}, "timeout": 5})
        expected = sha256(engine)

        def slow_snapshot(hide_window=False):
            # Half a minute of PowerShell, and the bytes are swapped during it:
            # a digest checked before this would describe an engine that is no
            # longer the one about to start.
            engine.write_bytes(b"replaced engine bytes")
            return snapshot()

        with patch("studio_tools.launch.prelaunch_baseline", slow_snapshot), \
                patch("studio_tools.launch.run") as started:
            result = launch.execute(config, self.root, sha256_expected=expected,
                                    label="swapped-in-snapshot")
            started.assert_not_called()
        self.assertEqual(result["verdict"], "engine_replaced")
        self.assertFalse(result["ok"])
        run_dir = self.root / "artifacts/launches/swapped-in-snapshot"
        owned = read_json(run_dir / "owned-launch.json")
        self.assertEqual(owned["status"], "refused")
        self.assertIsNone(owned["process_record"])
        self.assertFalse((run_dir / "process").exists())

    def test_run_uses_a_supplied_baseline_instead_of_taking_its_own(self):
        given = snapshot(row(99, 1, "50", name="explorer.exe"))
        with self.windows(), \
                patch("studio_tools.processes._creation_options", return_value={}), \
                patch("studio_tools.processes._windows_snapshot",
                      return_value=snapshot()) as own:
            processes.run([sys.executable, "-c", "pass"],
                          job_dir=Path(self.tmp.name) / "given", baseline=given)
            own.assert_not_called()
            record = read_json(Path(self.tmp.name) / "given/process.json")
            self.assertEqual(record["windows_ownership"]["prelaunch"],
                             [{"pid": 99, "created_filetime": "50"}])
            # A caller that supplies none still gets one taken here, which is
            # what the Blender adapter relies on.
            processes.run([sys.executable, "-c", "pass"],
                          job_dir=Path(self.tmp.name) / "own")
            own.assert_called_once()

    def test_an_interrupt_during_the_snapshot_still_leaves_a_process_record(self):
        job = Path(self.tmp.name) / "interrupted"
        with self.windows(), patch("studio_tools.processes._creation_options", return_value={}), \
                patch("studio_tools.processes._windows_snapshot",
                      side_effect=KeyboardInterrupt), \
                patch("studio_tools.processes.subprocess.Popen") as popen:
            with self.assertRaises(KeyboardInterrupt):
                processes.run([sys.executable, "-c", "pass"], job_dir=job)
            popen.assert_not_called()
        # The directory was reserved by this run, so it must not be left with
        # nothing in it saying what reserved it.
        record = read_json(job / "process.json")
        self.assertIn(record["status"], ("starting", "interrupted"))
        self.assertIsNone(record["pid"])


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
