import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio_tools.common import StudioError, read_json, write_json, sha256
from studio_tools.config import load
from studio_tools.adapters import (
    audio,
    blender,
    meshy,
    gaea,
    godot,
    terrain,
    elevenlabs,
)
from studio_tools.adapters.http import ProviderError, Transport

ROOT = Path(__file__).resolve().parents[1]
BUDGET = {
    "authorized": True,
    "work_card": "fixture",
    "rate_checked_at": "2026-09-05",
    "units": "test units",
    "estimated": 1,
    "maximum": 1,
}
ELIGIBLE = {
    "body_type": "humanoid_biped",
    "textured": True,
    "checked": True,
    "limbs_clear": True,
    "face_count": 1000,
}
GLB = (ROOT / "examples/harbor-pocket/assets/harbor-bell.glb").read_bytes()


class TempCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio adapter space ")
        self.root = Path(self.temp.name)
        self.config = load()
        self.env = patch.dict(
            os.environ,
            {
                "MESHY_API_KEY": "test-meshy-secret",
                "ELEVENLABS_API_KEY": "test-eleven-secret",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()


class FakeTransport:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []
        self.downloads = []
        self.fail_download = False

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def download(self, url, destination):
        self.downloads.append(url)
        if self.fail_download:
            raise ProviderError("partial download")
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(GLB)


class MeshyTests(TempCase):
    def submit(self, t=None):
        return meshy.submit(
            self.config,
            "image",
            {"image_url": "https://example.org/reference.png"},
            self.root / "task.json",
            BUDGET,
            transport=t or FakeTransport([{"result": "same-task"}]),
        )

    def test_profiles_wire_endpoints_and_fields(self):
        cases = {
            "image": {"image_url": "https://example.org/image.png"},
            "preview": {"prompt": "Original ceramic bell"},
            "refine": {"preview_task_id": "preview-id"},
            "remesh": {"input_task_id": "input-id", "target_polycount": 1000},
            "retexture": {
                "input_task_id": "input-id",
                "text_style_prompt": "matte ochre",
            },
            "rig": {"input_task_id": "input-id", "height_meters": 1.8},
            "animate": {"rig_task_id": "rig-id", "action_id": 92},
        }
        for op, body in cases.items():
            with self.subTest(operation=op):
                t = FakeTransport([{"result": "task-" + op}])
                record = meshy.submit(
                    self.config,
                    op,
                    body,
                    self.root / (op + ".json"),
                    BUDGET,
                    ELIGIBLE,
                    t,
                )
                args, _ = t.calls[0]
                self.assertEqual(args[0], "POST")
                self.assertTrue(args[1].endswith(meshy.ENDPOINTS[op]))
                self.assertEqual(record["request"], args[3])

    def test_resume_gets_existing_id_and_archives_without_repost(self):
        t = FakeTransport(
            [
                {"result": "same-task"},
                {"id": "same-task", "status": "IN_PROGRESS"},
                {
                    "id": "same-task",
                    "status": "SUCCEEDED",
                    "consumed_credits": 12,
                    "expires_at": 123,
                    "model_urls": {"glb": "https://assets.example.org/model.glb"},
                },
            ]
        )
        self.submit(t)
        meshy.observe(self.config, self.root / "task.json", t)
        meshy.observe(self.config, self.root / "task.json", t)
        result = meshy.archive(self.root / "task.json", self.root / "archive", t)
        self.assertEqual([c[0][0] for c in t.calls], ["POST", "GET", "GET"])
        self.assertTrue(result["archive_complete"])
        self.assertEqual(result["response"]["consumed_credits"], 12)
        meshy.archive(self.root / "task.json", self.root / "archive", t)
        self.assertEqual(len(t.downloads), 1)

    def test_ambiguous_submission_never_resubmits(self):
        t = FakeTransport([ProviderError("echo test-meshy-secret")])
        with self.assertRaises(StudioError) as cm:
            self.submit(t)
        self.assertNotIn("test-meshy-secret", str(cm.exception))
        self.assertEqual(
            read_json(self.root / "task.json")["status"], "SUBMISSION_UNKNOWN"
        )
        with self.assertRaisesRegex(StudioError, "already exists"):
            self.submit(t)
        self.assertEqual(len(t.calls), 1)
        meshy.attach_task(self.root / "task.json", "reconciled-task")
        t.responses = [{"id": "reconciled-task", "status": "PENDING"}]
        self.assertEqual(
            meshy.observe(self.config, self.root / "task.json", t)["task_id"],
            "reconciled-task",
        )

    def test_crash_after_claim_preserves_unknown_intent(self):
        write_json(self.root / "task.json", {"status": "SUBMITTING", "task_id": None})
        t = FakeTransport([])
        with self.assertRaises(StudioError):
            self.submit(t)
        self.assertEqual(t.calls, [])

    def test_nonhumanoid_oversize_or_untextured_rejected_before_paid_call(self):
        for eligibility in [
            {**ELIGIBLE, "body_type": "quadruped"},
            {**ELIGIBLE, "face_count": 300001},
            {**ELIGIBLE, "textured": False},
            {},
        ]:
            t = FakeTransport([])
            with self.assertRaisesRegex(StudioError, "studio-animation"):
                meshy.submit(
                    self.config,
                    "rig",
                    {"input_task_id": "input", "height_meters": 1.7},
                    self.root / "rig.json",
                    BUDGET,
                    eligibility,
                    t,
                )
            self.assertEqual(t.calls, [])
            self.assertFalse((self.root / "rig.json").exists())

    def test_failed_expired_pending_and_unavailable_preserved(self):
        self.submit()
        for status in ["PENDING", "FAILED", "EXPIRED", "CANCELED"]:
            t = FakeTransport([{"id": "same-task", "status": status}])
            self.assertEqual(
                meshy.observe(self.config, self.root / "task.json", t)["status"], status
            )
            with self.assertRaises(StudioError):
                meshy.archive(self.root / "task.json", self.root / "archive", t)
        with self.assertRaises(ProviderError):
            meshy.observe(
                self.config,
                self.root / "task.json",
                FakeTransport([ProviderError("not found", 404)]),
            )
        self.assertEqual(read_json(self.root / "task.json")["status"], "UNAVAILABLE")

    def test_partial_archive_does_not_pass_then_can_resume(self):
        self.submit()
        r = read_json(self.root / "task.json")
        r.update(
            status="SUCCEEDED",
            response={"model_urls": {"glb": "https://assets.example.org/model.glb"}},
        )
        write_json(self.root / "task.json", r)
        t = FakeTransport()
        t.fail_download = True
        with self.assertRaises(ProviderError):
            meshy.archive(self.root / "task.json", self.root / "archive", t)
        self.assertFalse(
            read_json(self.root / "task.json").get("archive_complete", False)
        )
        t.fail_download = False
        self.assertTrue(
            meshy.archive(self.root / "task.json", self.root / "archive", t)[
                "archive_complete"
            ]
        )

    def test_nested_rig_outputs_archived(self):
        write_json(
            self.root / "task.json",
            {
                "status": "SUCCEEDED",
                "outputs": [],
                "response": {
                    "result": {
                        "rigged_character_glb_url": "https://a.example/character.glb",
                        "basic_animations": {
                            "walking_glb_url": "https://a.example/walk.glb"
                        },
                    }
                },
            },
        )
        self.assertEqual(
            len(
                meshy.archive(
                    self.root / "task.json", self.root / "archive", FakeTransport()
                )["outputs"]
            ),
            2,
        )

    def test_invalid_inputs_budget_missing_key_never_claim(self):
        t = FakeTransport()
        for body in [
            {"image_url": "https://x/a.png", "unknown": True},
            {"image_url": "file:///private"},
            {"image_url": "https://x/a.png", "ai_model": "latest"},
        ]:
            with self.assertRaises(StudioError):
                meshy.submit(
                    self.config,
                    "image",
                    body,
                    self.root / "task.json",
                    BUDGET,
                    transport=t,
                )
        with self.assertRaises(StudioError):
            meshy.submit(
                self.config,
                "image",
                {"image_url": "https://x/a.png"},
                self.root / "task.json",
                {**BUDGET, "estimated": 2},
                transport=t,
            )
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(StudioError):
            self.submit(t)
        self.assertFalse((self.root / "task.json").exists())
        self.assertEqual(t.calls, [])

    def test_provider_diagnostic_secret_redacted(self):
        self.submit()
        t = FakeTransport(
            [
                {
                    "id": "same-task",
                    "status": "FAILED",
                    "task_error": {"message": "test-meshy-secret"},
                }
            ]
        )
        result = meshy.observe(self.config, self.root / "task.json", t)
        self.assertNotIn("test-meshy-secret", json.dumps(result))
        self.assertNotIn("test-meshy-secret", (self.root / "task.json").read_text())


class HttpTests(TempCase):
    def test_truncated_glb_atomic_failure(self):
        t = Transport()
        dest = self.root / "model.glb"
        with (
            patch.object(t, "request", return_value=(GLB[:-20], {})),
            self.assertRaises(ProviderError),
        ):
            t.download("https://example.org/model.glb", dest)
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".glb.part").exists())

    def test_content_length_mismatch(self):
        class Response(io.BytesIO):
            headers = {"Content-Length": "1000"}

        with (
            patch("urllib.request.urlopen", return_value=Response(b"{}")),
            self.assertRaisesRegex(ProviderError, "Incomplete"),
        ):
            Transport().request("GET", "https://example.org/task")

    def test_size_bounded_and_https_required(self):
        class Response(io.BytesIO):
            headers = {}

        with (
            patch("urllib.request.urlopen", return_value=Response(b"123456")),
            self.assertRaisesRegex(ProviderError, "byte limit"),
        ):
            Transport(max_bytes=5).request("GET", "https://example.org/task")
        with self.assertRaises(ProviderError):
            Transport().request("GET", "http://example.org/task")


class AudioTests(TempCase):
    def test_deterministic_pcm_and_trim_loop_metadata(self):
        a = self.root / "original.wav"
        b = self.root / "again.wav"
        out = self.root / "runtime.wav"
        info = audio.synthesize(a, 2, kind="ambience")
        audio.synthesize(b, 2, kind="ambience")
        self.assertEqual(sha256(a), sha256(b))
        self.assertEqual(info["sample_rate"], 48000)
        self.assertEqual(info["channels"], 1)
        self.assertEqual(info["duration_seconds"], 2)
        before = sha256(a)
        prepared = audio.prepare(a, out, start=0.25, end=1.75, loop=True)
        self.assertEqual(prepared["duration_seconds"], 1.5)
        self.assertEqual(prepared["loop_end_seconds"], 1.5)
        self.assertEqual(before, sha256(a))
        self.assertLess(prepared["peak_dbfs"], 0)

    def test_missing_invalid_trim_preserve_original(self):
        with self.assertRaises(StudioError):
            audio.measure(self.root / "missing.wav")
        p = self.root / "cue.wav"
        audio.synthesize(p)
        with self.assertRaises(StudioError):
            audio.prepare(p, p)
        with self.assertRaises(StudioError):
            audio.prepare(p, self.root / "new.wav", end=10)
        self.assertFalse((self.root / "new.wav").exists())

    def test_hosted_profiles_archive_and_provenance(self):
        for op, body in [
            ("effects", {"text": "Hollow tap", "duration_seconds": 1}),
            (
                "speech",
                {
                    "text": "Welcome",
                    "voice_id": "licensed-voice",
                    "model_id": "eleven_multilingual_v2",
                },
            ),
            (
                "music",
                {"prompt": "Original quiet instrumental", "music_length_ms": 3000},
            ),
        ]:
            t = FakeTransport(
                [(b"ID3" + b"\0" * 50, {"request-id": "provider-request"})]
            )
            result = elevenlabs.generate(
                self.config,
                op,
                body,
                self.root / (op + ".json"),
                self.root / (op + ".mp3"),
                BUDGET,
                {"rights": "Test fixture"},
                t,
            )
            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(
                result["response_metadata"]["request-id"], "provider-request"
            )
            self.assertNotIn("test-eleven-secret", json.dumps(result))
            self.assertEqual(t.calls[0][0][0], "POST")

    def test_hosted_error_no_retry_no_partial(self):
        t = FakeTransport([ProviderError("test-eleven-secret")])
        args = (
            self.config,
            "effects",
            {"text": "tap", "duration_seconds": 1},
            self.root / "job.json",
            self.root / "cue.mp3",
            BUDGET,
            {"rights": "original"},
            t,
        )
        with self.assertRaises(StudioError) as cm:
            elevenlabs.generate(*args)
        self.assertNotIn("test-eleven-secret", str(cm.exception))
        self.assertFalse((self.root / "cue.mp3").exists())
        with self.assertRaisesRegex(StudioError, "already exists"):
            elevenlabs.generate(*args)
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(
            read_json(self.root / "job.json")["status"], "SUBMISSION_UNKNOWN"
        )


class TerrainGaeaTests(TempCase):
    def test_heightfield_dimensions_range_and_seams(self):
        r = terrain.create(self.root, resolution=17, width=8, depth=12, elevation=2)
        self.assertTrue(terrain.validate(r, self.root)["ok"])
        v = [
            list(map(float, line.split()[1:]))
            for line in (self.root / "terrain.obj").read_text().splitlines()
            if line.startswith("v ")
        ]
        self.assertEqual(max(x[0] for x in v) - min(x[0] for x in v), 8)
        self.assertEqual(max(x[2] for x in v) - min(x[2] for x in v), 12)
        self.assertEqual(max(x[1] for x in v), 2)

    def test_corrupt_heightfield_rejected(self):
        r = terrain.create(self.root)
        (self.root / "height.pgm").write_bytes(b"bad")
        with self.assertRaisesRegex(StudioError, "Hash mismatch"):
            terrain.validate(r, self.root)

    def test_gaea_missing_capability_no_execution(self):
        with (
            patch("studio_tools.adapters.gaea.run") as runner,
            self.assertRaisesRegex(StudioError, "entitled"),
        ):
            gaea.build(self.config, {}, self.root / "build")
        runner.assert_not_called()

    def test_verified_gaea_recipe_checks_graph_outputs(self):
        graph = self.root / "graph.terrain"
        graph.write_text("test graph")
        out = self.root / "build"
        cfg = load(overrides={"executables": {"gaea": sys.executable}})
        recipe = {
            "version": "test",
            "entitlement_confirmed": True,
            "ui_build_verified": True,
            "graph": str(graph),
            "graph_sha256": sha256(graph),
            "variables": {"seed": 7},
            "arguments": ["{graph}", "--output", "{output}", "--seed", "{seed}"],
            "outputs": ["height.raw"],
        }

        def fake_run(args, **kw):
            self.assertEqual(args[1], str(graph))
            self.assertEqual(args[-1], "7")
            (out / "height.raw").write_bytes(b"terrain")
            return {"elapsed_seconds": 1}

        with patch("studio_tools.adapters.gaea.run", side_effect=fake_run):
            result = gaea.build(cfg, recipe, out)
        self.assertEqual(result["status"], "built")
        graph.write_text("changed")
        with self.assertRaisesRegex(StudioError, "changed"):
            gaea.build(cfg, recipe, self.root / "other")


class BlenderGodotTests(TempCase):
    def test_real_export_geometry_skin_materials_clips(self):
        info = blender.glb_info(ROOT / "examples/harbor-pocket/assets/harbor-bell.glb")
        self.assertEqual(info["mesh_count"], 4)
        self.assertEqual(info["skin_count"], 1)
        self.assertEqual(info["material_count"], 3)
        self.assertEqual({c["name"] for c in info["clips"]}, {"idle", "response"})
        self.assertAlmostEqual(
            next(c["duration_seconds"] for c in info["clips"] if c["name"] == "idle"), 2
        )

    def test_background_commands_preserve_arguments(self):
        cfg = load(overrides={"executables": {"blender": sys.executable}})
        args = blender.command(
            cfg,
            "export.py",
            ["RuntimeAsset", "output name.glb"],
            self.root / "source file.blend",
        )
        self.assertIn("--background", args)
        self.assertIn("--factory-startup", args)
        self.assertIn("--python-exit-code", args)
        self.assertEqual(args[-2:], ["RuntimeAsset", "output name.glb"])
        self.assertIn(str(self.root / "source file.blend"), args)

    def test_missing_blender_project_fail_actionably(self):
        cfg = load(overrides={"executables": {"blender": "missing-blender-xyz"}})
        with self.assertRaisesRegex(StudioError, "needs setup"):
            blender.command(cfg, "fixture.py")
        with self.assertRaisesRegex(StudioError, "project.godot"):
            godot.command(load(), self.root)

    def test_godot_commands_export_prerequisites(self):
        (self.root / "project.godot").write_text("test")
        cfg = load(overrides={"executables": {"godot": sys.executable}})
        args = godot.command(
            cfg, self.root, "smoke", self.root / "artifact with spaces.json"
        )
        self.assertIn("--headless", args)
        self.assertEqual(
            args[-1], "--studio-smoke=" + str(self.root / "artifact with spaces.json")
        )
        with self.assertRaises(StudioError):
            godot.command(cfg, self.root, "export", self.root / "build.exe", "Windows")

    def test_godot_zero_exit_script_error_is_failure_and_profile_is_isolated(self):
        (self.root / "project.godot").write_text("test")
        cfg = load(overrides={"executables": {"godot": sys.executable}})
        with (
            patch(
                "studio_tools.adapters.godot.run",
                return_value={"stdout": "SCRIPT ERROR: invalid", "elapsed_seconds": 1},
            ) as runner,
            self.assertRaisesRegex(StudioError, "reported an error"),
        ):
            godot.execute(cfg, self.root)
        self.assertTrue(
            runner.call_args.kwargs["env"]["XDG_DATA_HOME"].startswith(str(self.root))
        )


class AdditionalBoundaryTests(TempCase):
    def test_invalid_render_samples_never_launch(self):
        source = self.root / "source.blend"
        source.write_bytes(b"test")
        with (
            patch("studio_tools.adapters.blender.run") as runner,
            self.assertRaises(StudioError),
        ):
            blender.render(
                self.config,
                source,
                self.root / "renders",
                "ReviewCamera",
                frames="1,2",
                angles="nan",
            )
        runner.assert_not_called()

    def test_typed_provider_options_rejected_before_submission(self):
        for body in (
            {"prompt": []},
            {"prompt": "x" * 801},
            {"prompt": "bell", "should_remesh": "yes"},
        ):
            with self.assertRaises(StudioError):
                meshy.profile("preview", body)
        with self.assertRaises(StudioError):
            elevenlabs.profile("effects", {"text": "tap", "duration_seconds": "1"})
        with self.assertRaises(StudioError):
            elevenlabs.profile(
                "speech",
                {
                    "text": "Hello",
                    "voice_id": "voice",
                    "model_id": "model",
                    "voice_settings": {"arbitrary": True},
                },
            )
