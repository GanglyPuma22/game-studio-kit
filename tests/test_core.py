import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools.common import StudioError, file_record, relative, write_json
from studio_tools.config import load, app_path, executable
from studio_tools.doctor import inspect, setup
from studio_tools.evidence import new_candidate
from studio_tools.records import validate
from studio_tools.package import check
from studio_tools.processes import run

ROOT = Path(__file__).resolve().parents[1]


class TempCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio test space ")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()


class PackageTests(TempCase):
    def copy_package(self):
        root = self.root / "relocated kit"
        shutil.copytree(
            ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv")
        )
        return root

    def test_complete_package(self):
        self.assertEqual(check(ROOT), {"ok": True, "errors": []})

    def test_missing_reference_fails_with_location(self):
        root = self.copy_package()
        (root / "references/acceptance.md").unlink()
        result = check(root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("acceptance.md" in s for s in result["errors"]))

    def test_duplicate_skill_fails(self):
        root = self.copy_package()
        data = json.loads((root / "studio-kit.json").read_text())
        data["skills"][1] = data["skills"][0]
        write_json(root / "studio-kit.json", data)
        self.assertFalse(check(root)["ok"])

    def test_relocated_absolute_entrypoint_empty_profile_different_cwd(self):
        kit = self.copy_package()
        game = self.root / "unrelated game"
        game.mkdir()
        profile = self.root / "empty agent profile"
        profile.mkdir()
        env = {
            **os.environ,
            "CODEX_HOME": str(profile),
            "PYTHONPATH": "",
            "STUDIO_CONFIG": "",
        }
        result = subprocess.run(
            [
                sys.executable,
                str(kit / "scripts/studio.py"),
                "check-package",
                "--root",
                str(kit),
            ],
            cwd=game,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        # Execute a real helper mutation from the relocated tree, outside its cache.
        result = subprocess.run(
            [
                sys.executable,
                str(kit / "scripts/studio.py"),
                "audio",
                "local",
                "--project",
                str(game),
                "--output",
                "assets/test.wav",
            ],
            cwd=game,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((game / "assets/test.wav").is_file())
        self.assertFalse((kit / "assets/test.wav").exists())

    def test_cache_mutation_rejected(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/studio.py"),
                "terrain",
                "--project",
                str(ROOT / "forbidden-output"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((ROOT / "forbidden-output").exists())

    def test_tampered_adaptation_fails(self):
        root = self.copy_package()
        p = root / "skills/studio-audio/references/elevenlabs-effects.md"
        p.write_text(p.read_text() + "changed")
        self.assertFalse(check(root)["ok"])


class ConfigDoctorTests(TempCase):
    def test_missing_offline_actionable_and_no_secret_leak(self):
        config = load(
            overrides={
                "executables": {
                    k: str(self.root / "missing")
                    for k in ["blender", "godot", "gaea", "ffmpeg", "ffprobe"]
                }
            }
        )
        with patch.dict(os.environ, {"MESHY_API_KEY": "secret-for-test"}, clear=True):
            report = inspect(config)
        self.assertEqual(report["capabilities"]["blender"]["status"], "needs_setup")
        self.assertEqual(report["capabilities"]["meshy"]["status"], "unverified")
        self.assertEqual(report["capabilities"]["computer_use"]["status"], "unverified")
        self.assertNotIn("secret-for-test", json.dumps(report))
        self.assertEqual(setup(report)["applied"], [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_explicit_missing_override_never_falls_back(self):
        with patch(
            "studio_tools.config.shutil.which",
            side_effect=lambda v: None if v == "missing-tool" else "/found/blender",
        ):
            self.assertIsNone(
                executable(
                    load(overrides={"executables": {"blender": "missing-tool"}}),
                    "blender",
                )
            )

    def test_version_probe(self):
        with (
            patch(
                "studio_tools.doctor.executable",
                return_value="/configured/tool with spaces",
            ),
            patch(
                "studio_tools.doctor.run", return_value={"stdout": "Blender 5.0.1\n"}
            ),
        ):
            report = inspect(load())
        self.assertEqual(report["capabilities"]["blender"]["version"], "5.0.1")
        self.assertEqual(report["capabilities"]["blender"]["operations"], "unverified")

    def test_old_version_unsupported(self):
        with (
            patch("studio_tools.doctor.executable", return_value="/tool"),
            patch("studio_tools.doctor.run", return_value={"stdout": "Blender 3.6.0"}),
        ):
            report = inspect(load())
        self.assertEqual(report["capabilities"]["blender"]["status"], "unsupported")

    def test_overrides_and_mapping_do_not_affect_native_linux_tool(self):
        file = self.root / "host.json"
        write_json(
            file,
            {
                "timeout": 12,
                "executables": {"blender": "old"},
                "path_mappings": [{"from": str(self.root), "to": "C:\\Work"}],
            },
        )
        cfg = load(file, {"executables": {"blender": "new"}})
        self.assertEqual(cfg["executables"]["blender"], "new")
        self.assertEqual(cfg["timeout"], 12)
        with patch("studio_tools.config.executable", return_value="/apps/blender.exe"):
            self.assertEqual(
                app_path(cfg, self.root / "asset name.blend", "blender"),
                "C:\\Work\\asset name.blend",
            )
        with patch("studio_tools.config.executable", return_value="/apps/godot"):
            self.assertEqual(
                app_path(cfg, self.root / "asset name.glb", "godot"),
                str(self.root / "asset name.glb"),
            )


class ProcessTests(TempCase):
    def test_argument_array_preserves_spaces(self):
        script = self.root / "path with spaces.py"
        script.write_text("import sys;print(sys.argv[1])")
        self.assertIn(
            "argument with spaces",
            run([sys.executable, script, "argument with spaces"])["stdout"],
        )

    def test_timeout_stops_only_owned_process(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(30)"]
        )
        try:
            with self.assertRaisesRegex(StudioError, "timed out"):
                run([sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.05)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait()

    def test_failure_does_not_echo_secret_stdout(self):
        with self.assertRaises(StudioError) as cm:
            run([sys.executable, "-c", 'print("secret-value");raise SystemExit(2)'])
        self.assertNotIn("secret-value", str(cm.exception))


class RecordTests(TempCase):
    def candidate(self):
        (self.root / "project.godot").write_text("content")
        return new_candidate(self.root, "test", "4.5.1", "0.1.0")

    def test_pending_candidate_valid_but_cannot_accept(self):
        c = self.candidate()
        self.assertTrue(validate(c, self.root)["ok"])
        c["settings"] = {"renderer": "test", "viewport": [1280, 720]}
        c["input_route"] = "test ordinary input route"
        c["acceptance"] = {
            "decision": "accepted",
            "reviewer": "test",
            "rationale": "test",
        }
        with self.assertRaisesRegex(StudioError, "Acceptance blocked"):
            validate(c, self.root)

    def test_missing_capture_and_mismatched_candidate_fail(self):
        c = self.candidate()
        c["verdicts"]["visual"] = {"status": "pass", "evidence": []}
        with self.assertRaisesRegex(StudioError, "needs evidence"):
            validate(c, self.root)
        p = self.root / "artifacts/review.txt"
        p.parent.mkdir()
        p.write_text("review")
        entry = {
            **file_record(self.root, p),
            "content_digest": "other",
            "method": "native_visual",
            "observer": "tester",
        }
        c["verdicts"]["visual"]["evidence"] = [entry]
        with self.assertRaisesRegex(StudioError, "different candidate"):
            validate(c, self.root)

    def test_content_modified_or_added_invalidates_candidate(self):
        c = self.candidate()
        (self.root / "new-runtime-file").write_text("changed")
        with self.assertRaisesRegex(StudioError, "content changed"):
            validate(c, self.root)
        (self.root / "new-runtime-file").unlink()
        (self.root / "project.godot").write_text("changed")
        with self.assertRaisesRegex(StudioError, "Hash mismatch"):
            validate(c, self.root)

    def test_technical_audio_not_listening(self):
        c = self.candidate()
        p = self.root / "artifacts/smoke.json"
        p.parent.mkdir()
        p.write_text("{}")
        c["verdicts"]["audio"] = {
            "status": "pass",
            "evidence": [
                {
                    **file_record(self.root, p),
                    "content_digest": c["content_digest"],
                    "method": "technical_runtime_smoke",
                    "observer": "test",
                }
            ],
        }
        with self.assertRaisesRegex(StudioError, "Perceptual pass"):
            validate(c, self.root)

    def test_screenshot_method_cannot_pass_audio(self):
        c = self.candidate()
        p = self.root / "artifacts/screenshot.txt"
        p.parent.mkdir()
        p.write_text("A screenshot is not listening")
        c["verdicts"]["audio"] = {
            "status": "pass",
            "evidence": [
                {
                    **file_record(self.root, p),
                    "content_digest": c["content_digest"],
                    "method": "native_visual",
                    "observer": "test",
                }
            ],
        }
        with self.assertRaisesRegex(StudioError, "appropriate review method"):
            validate(c, self.root)

    def test_workflow_identity_cannot_be_changed_without_inventory(self):
        c = self.candidate()
        c["workflow_digest"] = "wrong"
        with self.assertRaisesRegex(StudioError, "Workflow inventory"):
            validate(c, self.root)

    def test_valid_evidence_and_explicit_acceptance(self):
        c = self.candidate()
        p = self.root / "artifacts/review.txt"
        p.parent.mkdir()
        p.write_text("Reviewer inspected actual captures")
        for key in c["verdicts"]:
            c["verdicts"][key] = {
                "status": "pass",
                "evidence": [
                    {
                        **file_record(self.root, p),
                        "content_digest": c["content_digest"],
                        "method": {
                            "audio": "listening",
                            "interaction": "ordinary_input",
                            "performance": "profiler_measurement",
                        }.get(key, "native_visual"),
                        "observer": "tester",
                    }
                ],
            }
        c["verdicts"]["audio"]["evidence"][0]["listening"] = {
            "performed": True, "playback_route": "fixture playback", "interval_seconds": [0, 4]}
        c["settings"] = {"renderer": "test", "viewport": [1280, 720]}
        c["input_route"] = "test ordinary input route"
        c["acceptance"] = {
            "decision": "accepted",
            "reviewer": "tester",
            "rationale": "Scoped fixture review",
        }
        self.assertTrue(validate(c, self.root)["ok"])
        c["defects"] = [{"status": "open", "description": "bad seam"}]
        with self.assertRaisesRegex(StudioError, "unresolved defects"):
            validate(c, self.root)

    def test_export_and_animation_metadata_required(self):
        source = self.root / "source.blend"
        source.write_bytes(b"fake source")
        a = {
            "schema_version": 1,
            "kind": "asset",
            "asset_id": "a",
            "stage": "exported",
            "source": [file_record(self.root, source)],
            "runtime": [],
            "units": "metres",
            "dimensions_m": [1, 1, 1],
            "pivot": "ground",
            "materials": [],
            "provenance": {"rights": "original"},
            "animated": False,
        }
        with self.assertRaisesRegex(StudioError, "runtime export"):
            validate(a, self.root)
        runtime = self.root / "asset.glb"
        runtime.write_bytes(b"fake runtime")
        a["runtime"] = [file_record(self.root, runtime)]
        a["animated"] = True
        a["rig"] = {"name": "rig"}
        a["clips"] = []
        with self.assertRaisesRegex(StudioError, "clip metadata"):
            validate(a, self.root)

    def test_portable_paths_and_symlink_escape(self):
        for name in ["../outside", "C:/secret", "/tmp/secret", "a\\b", "a:file"]:
            with self.assertRaises(StudioError):
                relative(self.root, name)
        if hasattr(os, "symlink"):
            (self.root / "escape").symlink_to(
                self.root.parent, target_is_directory=True
            )
            with self.assertRaises(StudioError):
                relative(self.root, "escape/file")

    def test_example_records_actual_artifacts(self):
        example = ROOT / "examples/harbor-pocket"
        for name in ["project.json", "asset.json", "audio-cues.json"]:
            self.assertTrue(
                validate(json.loads((example / name).read_text()), example)["ok"]
            )
