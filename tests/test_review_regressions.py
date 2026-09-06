"""Parent-review regressions: explicit capabilities and non-destructive adapters."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio_tools.adapters import godot, gaea, meshy
from studio_tools.common import StudioError, write_json, read_json, sha256
from studio_tools.config import load


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = load(overrides={"executables": {"godot": sys.executable}})

    def test_smoke_requires_declared_protocol_before_launch(self):
        (self.root / "project.godot").touch()
        for declaration in (
            None,
            {},
            {"godot_smoke": None},
            {"godot_smoke": "future-v2"},
        ):
            if declaration is not None:
                write_json(self.root / "project.json", {"capabilities": declaration})
            with patch("studio_tools.adapters.godot.run") as run:
                with self.assertRaisesRegex(StudioError, "project-specific tests"):
                    godot.execute(self.config, self.root, "smoke")
                run.assert_not_called()

    def test_fixture_declares_smoke_but_generic_template_does_not(self):
        kit = Path(__file__).resolve().parents[1]
        self.assertEqual(
            read_json(kit / "examples/harbor-pocket/project.json")["capabilities"][
                "godot_smoke"
            ],
            "studio-smoke-v1",
        )
        self.assertIsNone(
            read_json(kit / "templates/project.json")["capabilities"]["godot_smoke"]
        )
        bindings = read_json(kit / "docs/evidence/current-inputs.json")["files"]
        for name, expected in bindings.items():
            self.assertEqual(sha256(kit / "examples/harbor-pocket" / name), expected)

    def test_export_requires_templates_before_launch(self):
        (self.root / "project.godot").touch()
        (self.root / "export_presets.cfg").touch()
        with patch("studio_tools.adapters.godot.run") as run:
            with self.assertRaisesRegex(StudioError, "godot_export_templates"):
                godot.execute(
                    self.config, self.root, "export", self.root / "game.exe", "Windows"
                )
            run.assert_not_called()

    def test_export_stages_templates_and_cleans_profile_success_and_failure(self):
        (self.root / "project.godot").touch()
        (self.root / "export_presets.cfg").touch()
        source = self.root / "installed" / "4.5.1.stable" / "windows_release_x86_64.exe"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"original")
        self.config["godot_export_templates"] = str(source.parent.parent)
        output = self.root / "game.exe"
        profiles = []
        before = dict(os.environ)
        for fail in (False, True):

            def fake_run(args, **kwargs):
                profile = Path(kwargs["env"]["APPDATA"])
                profiles.append(profile)
                folder = "Godot" if os.name == "nt" else "godot"
                copy = (
                    profile / folder / "export_templates" / "4.5.1.stable" / source.name
                )
                self.assertEqual(copy.read_bytes(), b"original")
                copy.write_bytes(b"changed by export")
                if fail:
                    raise StudioError("simulated failure")
                output.write_bytes(b"build")
                return {"stdout": "mock export completed", "elapsed_seconds": 1}

            with patch("studio_tools.adapters.godot.run", side_effect=fake_run):
                if fail:
                    with self.assertRaisesRegex(StudioError, "simulated"):
                        godot.execute(
                            self.config, self.root, "export", output, "Windows"
                        )
                else:
                    self.assertEqual(
                        godot.execute(
                            self.config, self.root, "export", output, "Windows"
                        )["status"],
                        "export_completed",
                    )
            self.assertFalse(profiles[-1].exists())
            self.assertEqual(source.read_bytes(), b"original")
        self.assertNotEqual(profiles[0], profiles[1])
        self.assertEqual(dict(os.environ), before)

    def test_windows_export_template_layout_and_self_contained_refusal(self):
        (self.root / "project.godot").touch()
        (self.root / "export_presets.cfg").touch()
        executable = self.root / "godot.exe"
        executable.touch()
        executable.chmod(0o755)
        self.config["executables"]["godot"] = str(executable)
        templates = self.root / "installed" / "4.5.1.stable"
        templates.mkdir(parents=True)
        (templates / "windows_release_x86_64.exe").write_bytes(b"template")
        self.config["godot_export_templates"] = str(templates.parent)
        output = self.root / "game.exe"

        def fake_run(args, **kwargs):
            staged = (
                Path(kwargs["env"]["APPDATA"])
                / "Godot"
                / "export_templates"
                / templates.name
            )
            self.assertEqual(
                (staged / "windows_release_x86_64.exe").read_bytes(), b"template"
            )
            output.write_bytes(b"export")
            return {"stdout": "mock export completed", "elapsed_seconds": 1}

        with patch("studio_tools.adapters.godot.run", side_effect=fake_run):
            godot.execute(self.config, self.root, "export", output, "Windows")
        (self.root / "_sc_").touch()
        with patch("studio_tools.adapters.godot.run") as runner:
            with self.assertRaisesRegex(StudioError, "self-contained"):
                godot.execute(self.config, self.root, "export", output, "Windows")
            runner.assert_not_called()

    def test_gaea_reserved_variables_do_not_write_or_launch(self):
        for key in ("graph", "output"):
            destination = self.root / key
            recipe = dict(
                version="test",
                entitlement_confirmed=True,
                ui_build_verified=True,
                graph="unused",
                graph_sha256="unused",
                arguments=[],
                outputs=["height.raw"],
                variables={key: "elsewhere"},
            )
            with patch("studio_tools.adapters.gaea.run") as run:
                with self.assertRaisesRegex(StudioError, "reserved"):
                    gaea.build(self.config, recipe, destination)
                run.assert_not_called()
            self.assertFalse(destination.exists())

    def test_meshy_tasks_share_root_without_overwriting_and_refuse_changed_files(self):
        class Download:
            def __init__(self):
                self.calls = 0

            def download(self, url, path):
                self.calls += 1
                path.write_bytes(url.encode())

        transport = Download()
        archive = self.root / "archive"
        results = []
        for task in ("first", "second"):
            record = self.root / (task + ".json")
            write_json(
                record,
                {
                    "status": "SUCCEEDED",
                    "task_id": task,
                    "response": {
                        "model_urls": {"glb": "https://example.org/" + task + ".glb"}
                    },
                },
            )
            result = meshy.archive(record, archive, transport)
            path = archive / result["outputs"][0]["name"]
            results.append(path)
            self.assertEqual(path.parent.name, task)
        self.assertNotEqual(results[0].read_bytes(), results[1].read_bytes())
        results[0].write_bytes(b"user modified")
        with self.assertRaisesRegex(StudioError, "ownership/hash"):
            meshy.archive(self.root / "first.json", archive, transport)
        self.assertEqual(results[0].read_bytes(), b"user modified")
        self.assertFalse(read_json(self.root / "first.json")["archive_complete"])
        self.assertEqual(transport.calls, 2)
        # A same-task filename without an owning output record also remains untouched.
        data = read_json(self.root / "second.json")
        data["outputs"] = []
        write_json(self.root / "second.json", data)
        before = results[1].read_bytes()
        with self.assertRaisesRegex(StudioError, "ownership/hash"):
            meshy.archive(self.root / "second.json", archive, transport)
        self.assertEqual(results[1].read_bytes(), before)
        self.assertEqual(transport.calls, 2)
