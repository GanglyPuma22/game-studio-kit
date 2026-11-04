"""Live status and run guards for Colab runs, with a fake colab CLI and ssh.

The fakes run the "runtime" in a temporary folder on this machine, so the real
colab_job.sh, runtime_job.sh and runtime_probe.sh run end to end: no Colab,
no network, no units.
"""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/studio-cloudrun/scripts"

spec = importlib.util.spec_from_file_location("live_status", SCRIPTS / "live_status.py")
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)

FAKE_COLAB = r"""#!/bin/bash
args=(); while [ $# -gt 0 ]; do case "$1" in --auth=*) shift ;; --config) shift 2 ;; *) args+=("$1"); shift ;; esac; done
set -- "${args[@]}"
case "$1" in
	--version) echo "colab 0.0-fake" ;;
	usage) if [ -f "$FAKE/session" ]; then echo "Rate: 1.94 compute units per hour"; else echo "Rate: 0 compute units per hour"; fi ;;
	sessions) [ -f "$FAKE/session" ] && echo "$(cat "$FAKE/session") L4 running"; [ -f "$FAKE/other" ] && cat "$FAKE/other"; true ;;
	new) shift; s=""; while [ $# -gt 0 ]; do [ "$1" = -s ] && s=$2; shift; done
		echo "$s" > "$FAKE/session"; echo "new $s" >> "$FAKE/calls"; mkdir -p "$FAKE/content" ;;
	stop) rm -f "$FAKE/session"; echo stop >> "$FAKE/calls" ;;
esac
"""

# ssh to the fake runtime: /content is a folder under $FAKE; no session, no answer.
FAKE_SSH = r"""#!/bin/bash
while [ $# -gt 0 ]; do case "$1" in -F) shift 2 ;; runtime) shift; break ;; *) shift ;; esac; done
[ -f "$FAKE/session" ] || exit 255
cmd="$*"; cmd=${cmd//\/content/$FAKE/content}
export JOB_ROOT=$FAKE/content/job
exec bash -c "$cmd"
"""

FAKE_NVIDIA = r"""#!/bin/bash
case "$*" in *utilization*) echo "${FAKE_GPU_UTIL:-0}, 0" ;; *--query-gpu*) echo "Fake L4, 0, 23034 MiB" ;; esac
exit 0
"""


def write_exe(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class LiveStatusLogicTests(unittest.TestCase):
    def test_step_lines_give_an_eta(self):
        s = {"id": "a", "gpu": "L4", "state": "running"}
        probe = {"job": "1", "pid_alive": "1", "finished": "0", "stage": "run", "gpu_util_max": "40"}
        self.assertEqual(ls.tick(s, {**probe, "step": "render 100/1000"}, 1000.0), "ok")
        self.assertNotIn("eta_min", s)
        self.assertEqual(ls.tick(s, {**probe, "step": "render 200/1000"}, 1060.0), "ok")
        self.assertEqual(s["eta_min"], 8.0)  # 100 poses a minute, 800 left
        self.assertEqual((s["step_n"], s["step_total"]), (200, 1000))
        ls.tick(s, {**probe, "step": "train step 3 of 10"}, 1120.0)
        self.assertNotIn("eta_min", s)  # a new counter starts over

    def test_units_spent_come_from_the_own_rate(self):
        s = ls.set_fields({}, ["runtime_started_s=0", "rate=2", "max_units=1.5"], 1800.0)
        self.assertEqual(s["units_spent"], 1.0)
        self.assertIn("1 units of 1.5", ls.line(s, 1800.0))

    def test_gpu_idle_stops_only_gpu_jobs_in_their_run_stage(self):
        probe = {"job": "1", "pid_alive": "1", "finished": "0", "stage": "run", "gpu_util_max": "0"}
        s = {"gpu": "L4"}
        self.assertEqual(ls.tick(s, probe, 0.0, gpu_idle_min=5), "ok")
        self.assertEqual(ls.tick(s, probe, 240.0, gpu_idle_min=5), "ok")
        self.assertTrue(ls.tick(s, probe, 300.0, gpu_idle_min=5).startswith("idle "))
        busy = {"gpu": "L4"}
        ls.tick(busy, probe, 0.0)
        ls.tick(busy, {**probe, "gpu_util_max": "3"}, 200.0)
        self.assertEqual(ls.tick(busy, probe, 400.0), "ok")  # the clock restarted at 400
        for status, p in (({"gpu": "CPU"}, probe), ({"gpu": "L4"}, {**probe, "stage": "setup"}),
                          ({"gpu": "L4"}, {k: v for k, v in probe.items() if k != "gpu_util_max"})):
            ls.tick(status, p, 0.0)
            self.assertEqual(ls.tick(status, p, 3600.0), "ok", (status, p))
        off = {"gpu": "L4"}
        ls.tick(off, probe, 0.0, gpu_idle_min=0)
        self.assertEqual(ls.tick(off, probe, 3600.0, gpu_idle_min=0), "ok")

    def test_a_runtime_with_no_job_or_no_answer_is_lost(self):
        self.assertTrue(ls.tick({}, {"job": "0"}, 0.0).startswith("lost "))
        self.assertTrue(ls.tick({}, {"ssh": "fail", "session": "gone"}, 0.0).startswith("lost "))
        s = {}
        self.assertEqual(ls.tick(s, {"ssh": "fail"}, 0.0, ssh_lost_min=5), "ok")
        self.assertEqual(ls.tick(s, {"ssh": "fail"}, 240.0, ssh_lost_min=5), "ok")
        self.assertTrue(ls.tick(s, {"ssh": "fail"}, 300.0, ssh_lost_min=5).startswith("lost "))
        gone = {}
        dead = {"job": "1", "pid_alive": "0", "finished": "0", "stage": "run"}
        self.assertEqual(ls.tick(gone, dead, 0.0), "ok")
        self.assertTrue(ls.tick(gone, dead, 60.0).startswith("lost "))
        self.assertEqual(ls.tick({}, {**dead, "finished": "1"}, 0.0), "finished")

    def test_a_status_nobody_updates_is_flagged_stale(self):
        s = {"id": "a", "state": "running", "updated_s": 0}
        self.assertIn("STALE", ls.line(s, 600.0))
        self.assertNotIn("STALE", ls.line({**s, "state": "done"}, 600.0))


class IdleLimitJobFieldTests(unittest.TestCase):
    def test_the_idle_limit_is_checked_and_shown_in_the_plan(self):
        from studio_tools import cloudrun
        job = {"schema": 1, "id": "game-clips-1", "type": "godot-capture", "repo": "Owner/game", "ref": "main",
               "command": "x", "max_minutes": 60}
        self.assertEqual(cloudrun.validate({**job, "gpu_idle_minutes": 0}), [])
        self.assertTrue(any("gpu_idle_minutes" in e for e in cloudrun.validate({**job, "gpu_idle_minutes": -1})))
        self.assertTrue(any("STUDIO_PROGRESS" in e for e in cloudrun.validate({**job, "env": {"STUDIO_PROGRESS": "x"}})))
        self.assertEqual(cloudrun.idle_minutes(job), 5)
        self.assertEqual(cloudrun.idle_minutes({**job, "gpu": "CPU", "gpu_idle_minutes": 9}), 0)
        self.assertEqual(cloudrun.idle_minutes({"type": "model-run", "recipe": "ace-step-music"}), 10)
        steps = " ".join(cloudrun.plan(job)["steps"])
        self.assertIn("0 % for 5 min", steps)
        self.assertIn("no GPU idle stop", " ".join(cloudrun.plan({**job, "gpu": "CPU"})["steps"]))


@unittest.skipUnless(shutil.which("flock") and shutil.which("git"), "needs flock and git")
class ColabJobEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        write_exe(bin_dir / "colab", FAKE_COLAB)
        write_exe(bin_dir / "ssh", FAKE_SSH)
        self.bin = bin_dir
        self.work = self.tmp / "work"
        # The game repository, served from a local path.
        origin = self.tmp / "git" / "Owner" / "game.git"
        origin.parent.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        src = self.tmp / "src"
        g = ["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
        (src / "README").write_text("game\n")
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", "one"], check=True)
        subprocess.run(g + ["push", "-q", str(origin), "main"], check=True)
        self.src, self.g, self.origin = src, g, origin

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **extra):
        e = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", FAKE=str(self.fake), CLOUDRUN_WORK=str(self.work),
                 GH=f"file://{self.tmp}/git/", POLL_S="1", STUDIO_GPU_SAMPLE_S="1", STATUS_PUSH_MIN="0")
        e.pop("RESULTS_REPO", None)
        e.update(extra)
        return e

    def run_job(self, command, timeout=120, env=None, **over):
        job = {"schema": 1, "id": "live-test", "type": "godot-capture", "repo": "Owner/game", "ref": "main",
               "command": command, "where": "colab", "gpu": "CPU", "max_minutes": 5}
        job.update(over)
        path = self.tmp / "job.json"
        path.write_text(json.dumps(job))
        return subprocess.run(["bash", str(SCRIPTS / "colab_job.sh"), str(path)], capture_output=True, text=True,
                              timeout=timeout, env=env or self.env())

    def status(self):
        return json.loads((self.work / "status" / "live-test.json").read_text())

    def calls(self):
        p = self.fake / "calls"
        return p.read_text().split("\n") if p.exists() else []

    def test_a_job_reports_steps_and_ends_done(self):
        # A worktree in the mirror holds a branch checked out; a new branch still arrives.
        mirror = self.work / "repos" / "Owner__game.git"
        mirror.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(self.origin), str(mirror)], check=True)
        subprocess.run(["git", "-C", str(mirror), "worktree", "add", "-q", str(self.tmp / "wt"), "main"], check=True)
        subprocess.run(self.g + ["checkout", "-qb", "claude/new"], check=True)
        (self.src / "NEW").write_text("x\n")
        subprocess.run(self.g + ["add", "-A"], check=True)
        subprocess.run(self.g + ["commit", "-qm", "two"], check=True)
        subprocess.run(self.g + ["push", "-q", str(self.origin), "claude/new"], check=True)
        cmd = ('test -f NEW && for i in 1 2 3 4; do echo "render $i/4" >> "$STUDIO_PROGRESS"; sleep 1.5; done; '
               'echo ok > "$OUT_DIR/a.txt"')
        r = self.run_job(cmd, ref="claude/new")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.status()
        self.assertEqual((s["state"], s["stage"], s["exit"]), ("done", "done", 0))
        self.assertEqual(s["rate"], 1.94)
        self.assertIn("units_spent", s)
        res = Path(s["res"])
        self.assertEqual((res / "a.txt").read_text(), "ok\n")
        self.assertIn("render 4/4", (res / "job-progress.txt").read_text())
        self.assertIn("render", (res / "driver.log").read_text())
        self.assertEqual(self.calls().count("stop"), 1)
        show = subprocess.run(["python3", str(SCRIPTS / "live_status.py"), "show", "--work", str(self.work)],
                              capture_output=True, text=True)
        self.assertIn("live-test | done", show.stdout)

    def test_a_second_copy_of_a_running_job_is_refused_before_any_runtime(self):
        (self.work / "locks").mkdir(parents=True)
        with open(self.work / "locks" / "job-live-test.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.run_job("true")
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertIn("already running", r.stderr)
        self.assertEqual([c for c in self.calls() if c], [])

    def test_the_default_session_name_is_locked_too(self):
        (self.work / "locks").mkdir(parents=True)
        with open(self.work / "locks" / "session-studio-live-test.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.run_job("true")
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertEqual([c for c in self.calls() if c], [])

    def test_the_results_branch_never_carries_a_stale_status(self):
        results = self.tmp / "git" / "Owner" / "results.git"
        subprocess.run(["git", "init", "-q", "--bare", str(results)], check=True)
        r = self.run_job('echo ok > "$OUT_DIR/a.txt"', env=self.env(RESULTS_REPO="Owner/results", STATUS_PUSH_MIN="5"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        files = subprocess.run(["git", "-C", str(results), "ls-tree", "-r", "--name-only", "studio-results/live-test"],
                               capture_output=True, text=True, check=True).stdout
        self.assertNotIn("status.json", files)
        live = subprocess.run(["git", "-C", str(results), "show", "studio-status/live-test:STATUS.json"],
                              capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(live)["state"], "done")

    def test_failed_gpu_queries_never_count_as_idle(self):
        write_exe(self.bin / "nvidia-smi", FAKE_NVIDIA)
        r = self.run_job("sleep 8", gpu="L4", screen=False, gpu_idle_minutes=0.05,
                         env=self.env(FAKE_GPU_UTIL="[N/A]"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.status()["gpu_util"])

    def test_an_existing_session_name_is_refused(self):
        (self.fake / "other").write_text("studio-live-test L4 running\n")
        r = self.run_job("true")
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertFalse(any(c.startswith("new") or c == "stop" for c in self.calls()))
        self.assertEqual(self.status()["state"], "failed")

    def test_a_runtime_that_lost_its_job_fails_loudly(self):
        r = self.run_job("rm -f ../job.json; sleep 60")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("RUNTIME LOST", r.stdout)
        s = self.status()
        self.assertEqual((s["state"], s["stage"]), ("failed", "lost"))
        self.assertIn("stop", self.calls())

    def test_a_gpu_job_at_zero_gpu_is_stopped_early(self):
        write_exe(self.bin / "nvidia-smi", FAKE_NVIDIA)
        r = self.run_job("sleep 60", gpu="L4", screen=False, gpu_idle_minutes=0.05)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("GPU IDLE", r.stdout)
        s = self.status()
        self.assertEqual(s["state"], "failed")
        self.assertEqual(s["gpu_util"], 0)
        self.assertIn("stop", self.calls())


if __name__ == "__main__":
    unittest.main()
