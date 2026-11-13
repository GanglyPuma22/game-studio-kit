"""studio-video-gen runner: offline checks only, the network is replaced."""

import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("video_job", ROOT / "skills/studio-video-gen/scripts/video_job.py")
vj = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vj)

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
SECRET = "sk-test-not-a-real-key-123"


class FakeRunway:
    """Accepts every POST, finishes every task at once, serves a tiny mp4."""

    def __init__(self, balance=10000, fail_post=False):
        self.balance, self.fail_post, self.posts = balance, fail_post, []

    def __call__(self, method, url, key=None, provider="runway", body=None, raw=False):
        if url.endswith("/organization"):
            return 200, {"creditBalance": self.balance}
        if method == "POST":
            if self.fail_post:
                return None, {"error": "TimeoutError: timed out"}
            self.posts.append(body)
            return 200, {"id": "task-%d" % len(self.posts)}
        if "/tasks/" in url:
            return 200, {"status": "SUCCEEDED", "output": ["https://example.invalid/out.mp4"]}
        return 200, MP4


class VideoJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="video job ")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        (self.dir / "clip.mp4").write_bytes(MP4)
        self.real_http = vj.http
        self.addCleanup(setattr, vj, "http", self.real_http)
        os.environ[vj.PROVIDERS["runway"]["env"]] = SECRET
        self.addCleanup(os.environ.pop, vj.PROVIDERS["runway"]["env"], None)

    def jobs(self, cap=3.0, n=1, seconds=6):
        spec = {"provider": "runway", "cap_usd": cap, "jobs": [
            {"name": "j%d" % i, "endpoint": "video_to_video", "ref_seconds": seconds, "out_seconds": seconds,
             "body": {"model": "seedance2_5", "promptVideo": "@file:clip.mp4", "duration": seconds,
                      "promptText": "test"}} for i in range(n)]}
        path = self.dir / "jobs.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return str(path)

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            vj.main(list(argv))
        return out.getvalue()

    def test_seedance_estimate_matches_published_rate_and_minimum(self):
        self.assertEqual(vj.runway_credits({"body": {"model": "seedance2_5"}, "out_seconds": 6, "ref_seconds": 6}), 270)
        self.assertEqual(vj.runway_credits({"body": {"model": "seedance2_5"}, "out_seconds": 1, "ref_seconds": 1}), 80)

    def test_unknown_model_needs_an_explicit_estimate(self):
        with self.assertRaises(SystemExit):
            vj.runway_credits({"body": {"model": "new_model"}, "out_seconds": 5})
        self.assertEqual(vj.runway_credits({"body": {"model": "new_model"}, "est_credits": 42}), 42)

    def test_file_placeholders_become_data_uris(self):
        body = vj.resolve({"a": ["@file:clip.mp4"]}, str(self.dir))
        self.assertTrue(body["a"][0].startswith("data:video/mp4;base64,"))

    def test_submit_refuses_without_approval(self):
        with self.assertRaises(SystemExit):
            self.run_cli("submit", self.jobs(), "--out", str(self.dir / "out"), "--approval", "  ")

    def test_cap_stops_jobs_past_it_and_key_never_printed(self):
        fake = FakeRunway()
        vj.http = fake
        out_dir = self.dir / "out"
        printed = self.run_cli("submit", self.jobs(cap=5.0, n=3), "--out", str(out_dir), "--approval", "go test, cap $5")
        record = json.loads((out_dir / "record.json").read_text())
        states = [record["jobs"]["j%d" % i]["state"] for i in range(3)]
        self.assertEqual(states, ["DONE", "SKIPPED_OVER_CAP", "SKIPPED_OVER_CAP"])
        self.assertEqual(len(fake.posts), 1)
        self.assertEqual(record["approval"], "go test, cap $5")
        self.assertTrue((out_dir / "j0.mp4").is_file())
        self.assertNotIn(SECRET, printed)
        self.assertNotIn(SECRET, (out_dir / "record.json").read_text())

    def test_low_balance_skips_before_posting(self):
        fake = FakeRunway(balance=100)
        vj.http = fake
        self.run_cli("submit", self.jobs(), "--out", str(self.dir / "out"), "--approval", "go")
        self.assertEqual(fake.posts, [])

    def test_unknown_outcome_is_recorded_and_resume_does_not_resubmit(self):
        vj.http = FakeRunway(fail_post=True)
        out_dir = self.dir / "out"
        self.run_cli("submit", self.jobs(), "--out", str(out_dir), "--approval", "go")
        record = json.loads((out_dir / "record.json").read_text())
        self.assertEqual(record["jobs"]["j0"]["state"], "SUBMISSION_UNKNOWN")
        fake = FakeRunway()
        vj.http = fake
        self.run_cli("resume", str(out_dir))
        self.assertEqual(fake.posts, [])

    def test_existing_record_is_never_overwritten(self):
        vj.http = FakeRunway()
        out_dir = self.dir / "out"
        self.run_cli("submit", self.jobs(), "--out", str(out_dir), "--approval", "go")
        with self.assertRaises(SystemExit):
            self.run_cli("submit", self.jobs(), "--out", str(out_dir), "--approval", "go")

    def test_aleph_prompt_limit_is_checked_offline(self):
        job = {"name": "a", "body": {"model": "aleph2", "promptText": "x" * 1001}}
        self.assertTrue(vj.check_job(job, str(self.dir)))


if __name__ == "__main__":
    unittest.main()
