"""Cloud run jobs and queues: validation and plans, with no runtime or network."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from studio_tools import cloudrun
from studio_tools.common import StudioError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/studio-cloudrun/scripts"


def job(**over):
    j = {
        "schema": 1, "id": "game-clips-1", "type": "godot-capture",
        "repo": "Owner/game", "ref": "claude/clips", "setup": "tools/setup.sh",
        "command": "tools/clips.sh recipe.json \"$OUT_DIR\"", "where": "colab", "gpu": "L4",
        "max_minutes": 60,
    }
    j.update(over)
    return j


class CloudrunJobTests(unittest.TestCase):
    def test_a_complete_job_is_runnable(self):
        self.assertEqual(cloudrun.validate(job()), [])

    def test_bad_fields_are_each_named(self):
        cases = {
            "id": ("Bad_ID", "id must be"),
            "type": ("model-run", "reserved"),
            "repo": ("not a repo", "repo must be"),
            "ref": ("../main", "ref must be"),
            "command": ("a\nb", "command must be one line"),
            "where": ("laptop", "where must be"),
            "gpu": ("H100", "gpu must be"),
            "max_minutes": (0, "max_minutes"),
            "results_max_mb": (10_000, "results_max_mb"),
        }
        for key, (value, message) in cases.items():
            with self.subTest(key=key):
                errors = cloudrun.validate(job(**{key: value}))
                self.assertTrue(any(message in e for e in errors), errors)

    def test_the_status_branch_id_is_reserved(self):
        self.assertTrue(any("queue-status" in e for e in cloudrun.validate(job(id="queue-status"))))

    def test_unknown_type_is_refused(self):
        self.assertTrue(any("type must be" in e for e in cloudrun.validate(job(type="anything"))))

    def test_env_cannot_carry_secrets_or_runner_names(self):
        self.assertTrue(cloudrun.validate(job(env={"API_TOKEN": "x"})))
        self.assertTrue(cloudrun.validate(job(env={"OUT_DIR": "/tmp"})))
        self.assertTrue(cloudrun.validate(job(env={"lower": "x"})))
        self.assertEqual(cloudrun.validate(job(env={"CLIP_SET": "review"})), [])

    def test_pinned_engine_needs_https_and_sha256(self):
        self.assertTrue(cloudrun.validate(job(godot={"url": "http://x/godot.zip", "sha256": "0" * 64})))
        self.assertTrue(cloudrun.validate(job(godot={"url": "https://x/godot.zip", "sha256": "abc"})))
        self.assertEqual(cloudrun.validate(job(godot={"url": "https://x/godot.zip", "sha256": "a" * 64})), [])

    def test_service_allow_lists(self):
        self.assertEqual(cloudrun.validate(job(), ["Owner/*"], ["claude/*", "main"]), [])
        self.assertTrue(any("allowed list" in e for e in cloudrun.validate(job(), ["Other/*"])))
        self.assertTrue(any("allowed list" in e for e in cloudrun.validate(job(ref="feature/x"), None, ["claude/*"])))

    def test_plan_names_every_host_and_runtime_step(self):
        steps = cloudrun.plan(job())["steps"]
        self.assertIn("git archive", steps[0])
        self.assertTrue(any("colab new --gpu L4" in s for s in steps))
        self.assertTrue(any(s.startswith("runtime: run:") for s in steps))
        self.assertTrue(any("stop the runtime" in s for s in steps))
        here = cloudrun.plan(job(), "here")["steps"]
        self.assertFalse(any("colab" in s for s in here))

    def test_plan_refuses_an_invalid_job(self):
        with self.assertRaises(StudioError):
            cloudrun.plan(job(id="x"))


class CloudrunQueueTests(unittest.TestCase):
    def test_lines_comments_and_stop(self):
        jobs, stop = cloudrun.parse_queue("# clips\nskybreak-clips-1.json\n\nsalvage-x.json  note\nSTOP\nlater.json\n")
        self.assertEqual(jobs, ["skybreak-clips-1.json", "salvage-x.json"])
        self.assertTrue(stop)

    def test_a_path_or_odd_name_is_refused(self):
        for line in ("../x.json", "jobs/x.json", "X.json", "x.txt"):
            with self.subTest(line=line), self.assertRaises(StudioError):
                cloudrun.parse_queue(line)


class CloudrunCliAndScriptsTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/studio.py"), "cloudrun", *args],
                              capture_output=True, text=True)

    def test_cli_validate_plan_and_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "job.json"
            good.write_text(json.dumps(job()), encoding="utf-8")
            r = self.run_cli("validate", "--job", str(good))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["ok"])
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(job(max_minutes=9999)), encoding="utf-8")
            r = self.run_cli("validate", "--job", str(bad))
            self.assertEqual(r.returncode, 1)
            r = self.run_cli("plan", "--job", str(good), "--where", "here")
            self.assertEqual(json.loads(r.stdout)["where"], "here")
        r = self.run_cli("types")
        self.assertIn("godot-capture", json.loads(r.stdout)["types"])

    def test_shell_runners_parse(self):
        for script in sorted(SCRIPTS.glob("*.sh")):
            with self.subTest(script=script.name):
                r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_service_host_never_runs_job_commands(self):
        # The host packs, copies and polls; setup and command run only on the runtime.
        text = (SCRIPTS / "colab_job.sh").read_text(encoding="utf-8")
        self.assertNotIn('bash -c "$CMD"', text)
        self.assertNotIn('d["command"]', text)
        self.assertIn("git -C \"$MIRROR\" archive", text)
        self.assertIn('"${COLAB[@]}" stop -s "$SESSION"', text)
        self.assertIn("trap", text)


if __name__ == "__main__":
    unittest.main()
