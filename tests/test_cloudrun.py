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
            "type": ("salvage-batch", "reserved"),
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

    def test_model_run_examples_are_runnable(self):
        for recipe in ("stable-audio-open-sfx", "ace-step-music"):
            plan = json.loads((cloudrun.RECIPES_DIR / recipe / "plan.example.json").read_text())
            mj = {"schema": 1, "id": "audio-test", "type": "model-run", "recipe": recipe, "plan": plan,
                  "max_minutes": 20, "max_units": 1}
            self.assertEqual(cloudrun.validate(mj), [], recipe)
            steps = " ".join(cloudrun.plan(mj)["steps"])
            self.assertIn("1 units", steps)
            self.assertEqual("token never leaves the host" in steps, recipe == "stable-audio-open-sfx")

    def test_model_run_refuses_game_fields_missing_ceiling_and_bad_plans(self):
        plan = {"cues": [{"id": "swing", "prompt": "a swing", "seconds": 5, "seeds": [1, 2]}]}
        base = {"schema": 1, "id": "audio-test", "type": "model-run", "recipe": "stable-audio-open-sfx",
                "plan": plan, "max_minutes": 20, "max_units": 1}
        def errs(**over):
            return " ".join(cloudrun.validate({**base, **over}))
        self.assertIn("repo is not used", errs(repo="a/b"))
        self.assertIn("command is not used", errs(command="rm -rf /"))
        self.assertIn("max_units", errs(max_units=None))
        self.assertIn("recipe must be one of", errs(recipe="nope"))
        self.assertIn("runs on", errs(recipe="ace-step-music", gpu="L4",
                                      plan={"cues": [{"id": "mus", "caption": "x", "seconds": 60, "seeds": [1]}]}))
        self.assertIn("seconds", errs(plan={"cues": [{"id": "swing", "prompt": "x", "seconds": 90, "seeds": [1]}]}))
        self.assertIn("distinct", errs(plan={"cues": [{"id": "swing", "prompt": "x", "seconds": 5, "seeds": [1, 1]}]}))
        self.assertIn("prompt must be text", errs(plan={"cues": [{"id": "swing", "caption": "x", "seconds": 5, "seeds": [1]}]}))
        self.assertIn("limit", errs(plan={"cues": [{"id": "swing", "prompt": "x", "seconds": 5, "seeds": list(range(40))}]}))
        self.assertIn("colab only", errs(where="here"))
        music = {"recipe": "ace-step-music", "gpu": "A100"}
        self.assertIn("under half", errs(**music, plan={"loop_crossfade_seconds": 8, "cues": [{"id": "mus", "caption": "x", "seconds": 10, "seeds": [1]}]}))
        self.assertEqual(errs(**music, plan={"loop_crossfade_seconds": 4, "cues": [{"id": "mus", "caption": "x", "seconds": 10, "seeds": [1]}]}), "")

    def test_recipes_pin_their_models(self):
        for name, r in cloudrun.recipes().items():
            m = r["model"]
            pins = [m.get("revision"), m.get("commit")] + list(m.get("repos", {}).values())
            self.assertTrue(any(pins), name)
            for pin in filter(None, pins):
                self.assertRegex(pin, r"^[0-9a-f]{40}$", name)
            self.assertIn("license", m, name)
            for f in ("setup.sh", "run.sh", "worker.py", "plan.example.json"):
                self.assertTrue((cloudrun.RECIPES_DIR / name / f).is_file(), f"{name}/{f}")

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


class StageHfTokenFile(unittest.TestCase):
    def test_token_file_forms(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "skills/studio-cloudrun/scripts/stage_hf.py"
        spec = importlib.util.spec_from_file_location("stage_hf", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.token_from_file("hf_abc\n"), "hf_abc")
        self.assertEqual(m.token_from_file('export HF_TOKEN="hf_x"\n'), "hf_x")
        self.assertEqual(m.token_from_file("# note\nOTHER=1\nHF_TOKEN=hf_y\n"), "hf_y")
        self.assertEqual(m.token_from_file("OTHER=1\n"), "")


RECIPES = ROOT / "skills/studio-cloudrun/recipes"
SPEECH = ("speech-chatterbox-en", "speech-qwen3-base", "speech-cosyvoice3")
Z = "0" * 64


def speech_job(recipe="speech-chatterbox-en", **over):
    plan = json.loads((RECIPES / recipe / "plan.example.json").read_text())
    j = {"schema": 1, "id": "voice-test", "type": "model-run", "recipe": recipe, "plan": plan,
         "max_minutes": 30, "max_units": 0, "where": "attended"}
    if "reference" in plan:
        j["inputs"] = [{"path": "striker-reference.wav", "sha256": Z, "private": True}]
    j.update(over)
    return j


def plan_with(recipe="speech-chatterbox-en", **over):
    plan = json.loads((RECIPES / recipe / "plan.example.json").read_text())
    plan.update(over)
    return plan


class SpeechJobTests(unittest.TestCase):
    def errs(self, j):
        return " ".join(cloudrun.validate(j))

    def test_examples_are_runnable_attended_and_on_the_service(self):
        for recipe in SPEECH + ("casting-qwen3-voicedesign",):
            with self.subTest(recipe=recipe):
                self.assertEqual(cloudrun.validate(speech_job(recipe)), [])
                steps = " ".join(cloudrun.plan(speech_job(recipe))["steps"])
                self.assertIn("spend is 0", steps)
                paid = speech_job(recipe, where="colab", max_units=1, budget={"group": "striker-audition", "units": 3})
                self.assertEqual(cloudrun.validate(paid), [])
                steps = " ".join(cloudrun.plan(paid)["steps"])
                self.assertIn("budget group striker-audition", steps)
                self.assertEqual("never go to results" in steps, recipe in SPEECH)

    def test_attended_spends_nothing(self):
        self.assertIn("max_units must be 0", self.errs(speech_job(max_units=1)))
        self.assertIn("budget is not used", self.errs(speech_job(budget={"group": "abc", "units": 1})))
        self.assertIn("max_rate is not used", self.errs(speech_job(max_rate=2)))
        self.assertIn("max_units must be a number", self.errs(speech_job(where="colab")))  # 0 is not a paid ceiling

    def test_budget_rules(self):
        paid = dict(where="colab", max_units=2)
        self.assertIn("must not exceed budget.units", self.errs(speech_job(**paid, budget={"group": "abc", "units": 1})))
        self.assertIn("budget.group", self.errs(speech_job(**paid, budget={"group": "A", "units": 3})))
        self.assertIn("budget must be", self.errs(speech_job(**paid, budget={"group": "abc", "units": 3, "x": 1})))
        a = speech_job(**paid, budget={"group": "abc", "units": 3})
        b = speech_job(**paid, budget={"group": "abc", "units": 4})
        self.assertEqual(cloudrun.check_group([a, a]), [])
        self.assertTrue(cloudrun.check_group([a, b]))

    def test_inputs_and_reference(self):
        self.assertIn("only used by recipes that read files", self.errs(
            {"schema": 1, "id": "sfx-test", "type": "model-run", "recipe": "stable-audio-open-sfx", "max_minutes": 5, "max_units": 1,
             "plan": json.loads((RECIPES / "stable-audio-open-sfx/plan.example.json").read_text()),
             "inputs": [{"path": "a.wav", "sha256": Z}]}))
        self.assertIn("relative path", self.errs(speech_job(inputs=[{"path": "../a.wav", "sha256": Z}])))
        self.assertIn("relative path", self.errs(speech_job(inputs=[{"path": "/etc/passwd", "sha256": Z}])))
        self.assertIn("one of the job's inputs", self.errs(speech_job(inputs=[{"path": "other.wav", "sha256": Z}])))
        self.assertIn("must match that input", self.errs(speech_job(inputs=[{"path": "striker-reference.wav", "sha256": "1" * 64}])))
        self.assertIn("must be private", self.errs(speech_job(inputs=[{"path": "striker-reference.wav", "sha256": Z, "private": False}])))
        self.assertIn("plan.reference must name", self.errs(speech_job(plan=plan_with(reference=None))))
        ref = dict(plan_with()["reference"], transcript="")
        self.assertIn("transcript", self.errs(speech_job(plan=plan_with(reference=ref))))

    def test_plan_rules(self):
        self.assertIn("not supported by this recipe", self.errs(speech_job(plan=plan_with(controls={"instruct": "angry"}))))
        self.assertIn("from 0.25 to 2.0", self.errs(speech_job(plan=plan_with(controls={"exaggeration": 5}))))
        self.assertIn("plan.language", self.errs(speech_job(plan=plan_with(language="fr"))))
        self.assertIn("plan.character", self.errs(speech_job(plan=plan_with(character={"id": "striker"}))))
        self.assertIn("max_seconds", self.errs(speech_job(plan=plan_with(max_seconds=60))))
        self.assertIn("repeat a cue and one of its own seeds",
                      self.errs(speech_job(plan=plan_with(repeats=[{"cue": "striker-ult-ally", "seed": 999, "after_reload": True}]))))
        self.assertIn("after_reload", self.errs(speech_job(plan=plan_with(repeats=[{"cue": "striker-ult-ally", "seed": 101}]))))
        p = plan_with()
        p["cues"][0]["text"] = "two\nlines"
        self.assertIn("one line of spoken text", self.errs(speech_job(plan=p)))
        p = plan_with()
        p["cues"][0]["seeds"] = list(range(39))
        self.assertIn("recipe limit is 40", self.errs(speech_job(plan=p)))  # 39 + 3 + 1 repeat
        cast = plan_with("casting-qwen3-voicedesign", controls={})
        self.assertIn("instruct", self.errs(speech_job("casting-qwen3-voicedesign", plan=cast)))
        cast = plan_with("casting-qwen3-voicedesign", controls=None)
        cast["cues"][0]["controls"] = None
        self.assertIn("instruct", self.errs(speech_job("casting-qwen3-voicedesign", plan=cast)))
        twice = [{"cue": "striker-ult-ally", "seed": 101, "after_reload": True}] * 2
        self.assertIn("second time", self.errs(speech_job(plan=plan_with(repeats=twice))))
        sfx = {"schema": 1, "id": "sfx-test", "type": "model-run", "recipe": "stable-audio-open-sfx", "max_minutes": 5,
               "max_units": 0, "where": "attended", "plan": json.loads((RECIPES / "stable-audio-open-sfx/plan.example.json").read_text())}
        self.assertIn("gated weights", self.errs(sfx))
        cast = plan_with("casting-qwen3-voicedesign", reference={"input": "x", "sha256": Z, "transcript": "x"})
        self.assertIn("not used by casting", self.errs(speech_job("casting-qwen3-voicedesign", plan=cast)))

    def test_check_inputs(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "in"
            root.mkdir()
            (root / "ref.wav").write_bytes(b"voice")
            (Path(d) / "outside.wav").write_bytes(b"voice")
            sha = hashlib.sha256(b"voice").hexdigest()
            ok = {"inputs": [{"path": "ref.wav", "sha256": sha}]}
            self.assertEqual(cloudrun.check_inputs(ok, root), [])
            self.assertIn("does not match", " ".join(cloudrun.check_inputs({"inputs": [{"path": "ref.wav", "sha256": Z}]}, root)))
            self.assertIn("missing", " ".join(cloudrun.check_inputs({"inputs": [{"path": "nope.wav", "sha256": sha}]}, root)))
            try:
                (root / "link.wav").symlink_to(Path(d) / "outside.wav")
            except OSError:
                return
            self.assertIn("outside", " ".join(cloudrun.check_inputs({"inputs": [{"path": "link.wav", "sha256": sha}]}, root)))

    def test_cli_needs_the_inputs_folder(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            data = b"reference"
            sha = hashlib.sha256(data).hexdigest()
            plan = plan_with(reference={"input": "ref.wav", "sha256": sha, "transcript": "Ready."})
            j = speech_job(plan=plan, inputs=[{"path": "ref.wav", "sha256": sha, "private": True}])
            jf = Path(d) / "job.json"
            jf.write_text(json.dumps(j))
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts/studio.py"), "cloudrun", "validate", "--job", str(jf), *a],
                                            capture_output=True, text=True)
            self.assertIn("--inputs", run().stdout)
            (Path(d) / "in").mkdir()
            self.assertIn("missing", run("--inputs", str(Path(d) / "in")).stdout)
            (Path(d) / "in/ref.wav").write_bytes(data)
            self.assertTrue(json.loads(run("--inputs", str(Path(d) / "in")).stdout)["ok"])

    def test_speech_recipes_pin_every_file(self):
        for name, r in cloudrun.recipes().items():
            if r.get("kind") not in cloudrun.SPEECH_KINDS:
                continue
            with self.subTest(recipe=name):
                self.assertTrue(r.get("experimental"))
                self.assertTrue(r["tested"].startswith("not yet"))
                m = r["model"]
                self.assertRegex(m["commit"], r"^[0-9a-f]{40}$")
                self.assertTrue(m["files"])
                for path, pin in m["files"].items():
                    self.assertTrue(("sha256" in pin) != ("git_oid" in pin), path)
                    self.assertRegex(pin.get("sha256") or pin.get("git_oid"), r"^[0-9a-f]{40}([0-9a-f]{24})?$")
                    self.assertGreater(pin["size"], 0)
                self.assertNotIn("llm.rl.pt", m["files"])
                self.assertIn("speech_common", (RECIPES / name / "worker.py").read_text())
                self.assertEqual(r.get("inputs", False), r["kind"] == "speech")

    def test_runners_guard_private_inputs_and_budgets(self):
        text = (SCRIPTS / "colab_job.sh").read_text()
        for needle in ("budget.py\" open", "bill;", "recipe.name", "copies of a private input", '[ "$LEAK" = 0 ]', "speech_common.py"):
            self.assertIn(needle, text)
        self.assertIn("copies of a private input", (SCRIPTS / "attended.sh").read_text())
        with tempfile.TemporaryDirectory() as d:
            jf = Path(d) / "job.json"
            jf.write_text(json.dumps(speech_job("casting-qwen3-voicedesign", where="colab", max_units=1)))
            r = subprocess.run(["bash", str(SCRIPTS / "attended.sh"), str(jf), d, str(Path(d) / "out")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn("attended", r.stderr)
            out = Path(d) / "busy"
            out.mkdir()
            (out / "old.wav").write_bytes(b"x")
            jf.write_text(json.dumps(speech_job("casting-qwen3-voicedesign")))
            r = subprocess.run(["bash", str(SCRIPTS / "attended.sh"), str(jf), d, str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn("not empty", r.stderr)


class BudgetLedgerTests(unittest.TestCase):
    def test_open_spend_refuse(self):
        import importlib.util, os
        spec = importlib.util.spec_from_file_location("budget", SCRIPTS / "budget.py")
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("CLOUDRUN_WORK")
            os.environ["CLOUDRUN_WORK"] = d
            try:
                self.assertEqual(b.open_group("audition", 3.0, 2.0, "run-a"), (2.0, None))
                # A second run in parallel gets only what the first does not hold.
                self.assertEqual(b.open_group("audition", 3.0, 2.0, "run-b"), (1.0, None))
                self.assertIn("no units left", b.open_group("audition", 3.0, 1.0, "run-c")[1])
                b.spend("audition", 0.5, "run-a", "cast-1")  # releases run-a's 2.0, spends 0.5
                self.assertEqual(b.open_group("audition", 3.0, 5.0, "run-c"), (1.5, None))
                self.assertIn("opened with 3.0", b.open_group("audition", 5.0)[1])
                b.spend("audition", 0.0, "run-b", "speech-1")  # never got a GPU: costs nothing
                b.spend("audition", 1.5, "run-c", "speech-2")
                led = json.loads((Path(d) / "budgets/audition.json").read_text())
                self.assertEqual([r["job"] for r in led["runs"]], ["cast-1", "speech-1", "speech-2"])
                self.assertEqual(led["reserved"], {})
                self.assertEqual(led["spent"], 2.0)
                self.assertEqual(b.main(["open", "audition", "3", "2", "run-d"]), 0)
                self.assertEqual(b.main(["open", "audition", "3", "2", "run-e"]), 1)
            finally:
                if old is None:
                    os.environ.pop("CLOUDRUN_WORK")
                else:
                    os.environ["CLOUDRUN_WORK"] = old


def _speech_common():
    import importlib.util
    spec = importlib.util.spec_from_file_location("speech_common", RECIPES / "speech_common.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class SpeechCommonTests(unittest.TestCase):
    def test_fetch_checks_every_pin_then_goes_offline(self):
        import hashlib, os
        sc = _speech_common()
        with tempfile.TemporaryDirectory() as d:
            hub = Path(d) / "hub/org/model/resolve/" / ("a" * 40)
            (hub / "sub").mkdir(parents=True)
            big, small = b"weights" * 100, b'{"x": 1}'
            (hub / "model.bin").write_bytes(big)
            (hub / "sub/config.json").write_bytes(small)
            pins = {"model.bin": {"sha256": hashlib.sha256(big).hexdigest(), "size": len(big)},
                    "sub/config.json": {"git_oid": hashlib.sha1(b"blob %d\0" % len(small) + small).hexdigest(), "size": len(small)}}
            recipe = {"model": {"repo": "org/model", "revision": "a" * 40, "files": pins}}
            sc.HUB = (Path(d) / "hub").as_uri()
            saved = {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE")}
            try:
                sc.fetch(recipe, Path(d) / "model")
                self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
                self.assertEqual((Path(d) / "model/sub/config.json").read_bytes(), small)
                pins["model.bin"]["sha256"] = Z
                (Path(d) / "model/model.bin").unlink()
                with self.assertRaises(RuntimeError):
                    sc.fetch(recipe, Path(d) / "model2")
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_session_takes_repeats_overlength_and_private_guard(self):
        try:
            import numpy as np
            import soundfile as sf
        except ImportError:
            self.skipTest("numpy and soundfile not installed")
        import hashlib, os, shutil
        sc = _speech_common()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rdir = d / "speech-fake"
            rdir.mkdir()
            ref_audio = (np.sin(np.arange(24000) / 10) * 0.3).astype(np.float32)
            (d / "in").mkdir()
            sf.write(d / "in/ref.wav", ref_audio[:, None], 24000, subtype="FLOAT")
            ref_sha = hashlib.sha256((d / "in/ref.wav").read_bytes()).hexdigest()
            (rdir / "recipe.json").write_text(json.dumps({"kind": "speech", "model": {"repo": "org/m", "revision": "a" * 40, "files": {}}}))
            (rdir / "recipe.name").write_text("speech-chatterbox-en\n")
            plan = {"language": "en", "character": {"id": "striker", "profile_version": 1}, "max_seconds": 1,
                    "reference": {"input": "ref.wav", "sha256": ref_sha, "transcript": "Ready."},
                    "cues": [{"id": "short-line", "text": "Go!", "seeds": [1, 2]},
                             {"id": "long-line", "text": "A long one.", "max_seconds": 1, "seeds": [3]}],
                    "repeats": [{"cue": "short-line", "seed": 1, "after_reload": True}]}
            (d / "plan.json").write_text(json.dumps(plan))
            loads = []

            def load(path):
                loads.append(path)
                return "model"

            def take(model, cue, seed, controls, ref):
                self.assertEqual(ref["transcript"], "Ready.")
                n = 36000 if cue["id"] == "long-line" else 12000
                return np.random.default_rng(seed).normal(0, 0.1, n).astype(np.float32), 24000

            os.environ.pop("HF_HUB_OFFLINE", None)
            # A stand-in torch with a GPU, so the CUDA calls run as on a runtime.
            import types
            cuda = types.SimpleNamespace(is_available=lambda: True, get_device_name=lambda i: "Fake GPU",
                                         max_memory_allocated=lambda: 123, reset_peak_memory_stats=lambda: None,
                                         empty_cache=lambda: None, manual_seed_all=lambda s: None)
            fake = types.SimpleNamespace(cuda=cuda, __version__="0-test", manual_seed=lambda s: None)
            saved_torch = sys.modules.get("torch")
            sys.modules["torch"] = fake
            try:
                s = sc.Session(rdir, d / "plan.json", d / "model", d / "out", d / "in")
                s.run(load, take)
            finally:
                if saved_torch is None:
                    sys.modules.pop("torch", None)
                else:
                    sys.modules["torch"] = saved_torch
            for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
                os.environ.pop(k, None)
            r = json.loads((d / "out/receipt.json").read_text())
            self.assertEqual(r["status"], "generated_pending_listening")
            self.assertEqual(r["recipe"], "speech-chatterbox-en")
            self.assertEqual(r["hardware"]["gpu"], "Fake GPU")
            self.assertEqual(r["outputs"][0]["peak_vram_bytes"], 123)
            self.assertEqual(len(loads), 2)  # reloaded for the repeat
            self.assertEqual(len(r["outputs"]), 4)
            self.assertEqual(r["reference"]["sha256"], ref_sha)
            self.assertNotIn("reference", r["plan"])
            long = next(o for o in r["outputs"] if o["cue"] == "long-line")
            self.assertTrue(long["overlength"])
            self.assertEqual(long["original"]["frames"], 36000)  # kept whole, never cut
            rep = r["outputs"][-1]
            self.assertTrue(rep["after_reload"] and rep["same_bytes"])
            prev, _ = sf.read(d / "out" / r["outputs"][0]["preview"]["path"])
            self.assertAlmostEqual(20 * np.log10(np.sqrt(np.mean(prev ** 2))), -20.0, delta=0.5)
            self.assertFalse(any(p.read_bytes() == (d / "in/ref.wav").read_bytes() for p in (d / "out").rglob("*.wav")))

            # A take that is the reference itself is refused, and the run fails.
            shutil.rmtree(d / "out")
            plan["repeats"] = []
            (d / "plan.json").write_text(json.dumps(plan))
            s = sc.Session(rdir, d / "plan.json", d / "model", d / "out", d / "in")
            with self.assertRaises(SystemExit):
                s.run(load, lambda m, c, seed, ctl, ref: (sf.read(ref["path"], dtype="float32")[0], 24000))
            for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
                os.environ.pop(k, None)
            r = json.loads((d / "out/receipt.json").read_text())
            self.assertEqual(r["status"], "failed")
            self.assertIn("private input", r["traceback"])
            self.assertEqual(list((d / "out").rglob("*.wav")), [])


if __name__ == "__main__":
    unittest.main()
