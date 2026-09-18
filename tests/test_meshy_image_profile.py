"""The image-to-3d profile can ask for a game-ready mesh (offline).

Its only real call returned a 4.8M-triangle sculpt because the profile could
not carry a polycount, which left a paid remesh or a decimation pass as the
only ways forward. No network call is made here.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cli
from studio_tools.adapters import meshy
from studio_tools.common import StudioError, read_json, write_json
from studio_tools.config import load

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/studio-meshy/SKILL.md"
API = ROOT / "skills/studio-meshy/references/api.md"
BUDGET = {
    "authorized": True,
    "work_card": "fixture",
    "rate_checked_at": "2026-09-05",
    "units": "test units",
    "estimated": 1,
    "maximum": 1,
}
GAME_READY = {
    "image_url": "https://example.org/reference.png",
    "should_remesh": True,
    "target_polycount": 20000,
    "topology": "quad",
    "symmetry_mode": "off",
}


class FakeTransport:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append(args)
        return self.response


class ImageProfileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio image space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        (self.root / "requests").mkdir(parents=True)
        self.environment = patch.dict(os.environ, {"MESHY_API_KEY": "test-meshy-secret"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        write_json(self.root / "requests/image.json", GAME_READY)
        write_json(self.root / "requests/budget.json", BUDGET)
        self.host = Path(self.tmp.name) / "host.json"
        write_json(self.host, {})


class ImageProfileTests(ImageProfileCase):
    def test_a_game_ready_image_request_is_accepted_and_submitted_unchanged(self):
        transport = FakeTransport({"result": "image-task"})
        record = meshy.submit(
            load(), "image", dict(GAME_READY), self.root / "task.json", BUDGET,
            transport=transport,
        )
        submitted = transport.calls[0][3]
        for field, value in GAME_READY.items():
            self.assertEqual(submitted[field], value, field)
        # The profile still fixes the model and the runtime format it supports.
        self.assertEqual(submitted["ai_model"], "meshy-6")
        self.assertEqual(submitted["target_formats"], ["glb"])
        self.assertEqual(record["request"], submitted)

    def test_the_new_fields_reuse_the_bounds_the_other_profiles_already_had(self):
        for field, value, message in (
            ("target_polycount", 4853274, "100–300000"),
            ("target_polycount", 99, "100–300000"),
            ("target_polycount", 20000.5, "100–300000"),
            ("topology", "ngon", "Invalid topology"),
            ("symmetry_mode", "mirror", "off, auto or on"),
            ("should_remesh", "true", "must be a boolean"),
        ):
            with self.subTest(field=field, value=value):
                body = {**GAME_READY, field: value}
                with self.assertRaisesRegex(StudioError, message):
                    meshy.profile("image", body)

    def test_an_unsupported_field_is_still_refused(self):
        with self.assertRaisesRegex(StudioError, "Unsupported Meshy fields: texture_richness"):
            meshy.profile("image", {**GAME_READY, "texture_richness": "high"})

    def test_the_helper_sets_no_polycount_of_its_own(self):
        plain = meshy.profile("image", {"image_url": "https://example.org/reference.png"})
        self.assertNotIn("target_polycount", plain)
        self.assertNotIn("should_remesh", plain)
        self.assertNotIn("symmetry_mode", plain)

    def test_cli_submit_carries_the_request_fields_to_the_provider(self):
        transport = FakeTransport({"result": "image-task"})
        with patch("studio_tools.adapters.meshy.Transport", return_value=transport):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = cli.main([
                        "meshy", "submit", "--project", str(self.root), "--config", str(self.host),
                        "--profile", "image", "--request", "requests/image.json",
                        "--budget", "requests/budget.json", "--record", "artifacts/tasks/image-001.json",
                    ])
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(code, 0)
        submitted = transport.calls[0][3]
        self.assertEqual(submitted["target_polycount"], 20000)
        self.assertTrue(submitted["should_remesh"])
        self.assertEqual(submitted["topology"], "quad")
        self.assertEqual(submitted["symmetry_mode"], "off")
        record = read_json(self.root / "artifacts/tasks/image-001.json")
        self.assertEqual(record["task_id"], "image-task")
        self.assertEqual(record["request"], submitted)
        self.assertEqual(json.loads(out.getvalue())["request"]["target_polycount"], 20000)
        self.assertNotIn("test-meshy-secret", out.getvalue())

    def test_cli_submit_refuses_an_out_of_range_request_without_a_call(self):
        write_json(self.root / "requests/image.json", {**GAME_READY, "target_polycount": 4853274})
        with patch("studio_tools.adapters.meshy.Transport") as made:
            with contextlib.redirect_stdout(io.StringIO()):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = cli.main([
                        "meshy", "submit", "--project", str(self.root), "--config", str(self.host),
                        "--profile", "image", "--request", "requests/image.json",
                        "--budget", "requests/budget.json", "--record", "artifacts/tasks/image-002.json",
                    ])
            made.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("100–300000", json.loads(err.getvalue())["error"])
        self.assertFalse((self.root / "artifacts/tasks/image-002.json").exists())


class ImageProfileDocumentationTests(unittest.TestCase):
    def test_the_skill_tells_an_agent_to_size_the_mesh_and_what_omitting_it_costs(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("`should_remesh: true` with an explicit `target_polycount`", text)
        self.assertIn("paid remesh", text)
        for role in ("Hero landmark", "rigged", "Prop"):
            self.assertIn(role, text)
        self.assertIn('`topology: "triangle"`', text)
        self.assertIn("not provider recommendations", text)

    def test_the_api_reference_lists_the_new_optional_fields_and_their_bounds(self):
        text = API.read_text(encoding="utf-8")
        for field in ("should_remesh", "target_polycount", "topology", "symmetry_mode"):
            self.assertIn(field, text)
        self.assertIn("100–300000", text)
        self.assertIn("sets no polycount default", text)


if __name__ == "__main__":
    unittest.main()
