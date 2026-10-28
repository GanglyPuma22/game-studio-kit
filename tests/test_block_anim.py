"""Boxes-first runtime rig helpers: package wiring and the Godot golden self-test.

The self-test needs a Godot 4 binary. Set STUDIO_GODOT to its path, or put
`godot` on PATH; without one the Godot test is skipped.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANIM = ROOT / "skills" / "studio-animation"
MODULES = ["block_chain", "two_bone", "gait", "plant", "motion_check", "skin_blocks", "selftest"]


class BlockAnimPackageTests(unittest.TestCase):
    def test_modules_and_references_are_declared_resources(self):
        resources = set(json.loads((ROOT / "studio-kit.json").read_text(encoding="utf-8"))["resources"])
        for name in MODULES:
            path = f"skills/studio-animation/scripts/block_anim/{name}.gd"
            self.assertIn(path, resources)
            self.assertTrue((ROOT / path).is_file(), path)
        for ref in ("block-motion-rules.md", "runtime-block-rigs.md", "primitive-planning.md"):
            self.assertIn(f"skills/studio-animation/references/{ref}", resources)
        self.assertIn("templates/block-rig.json", resources)

    def test_skill_routes_to_the_block_references(self):
        skill = (ANIM / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/runtime-block-rigs.md", skill)
        self.assertIn("references/block-motion-rules.md", skill)

    def test_rig_template_is_consistent(self):
        rig = json.loads((ROOT / "templates" / "block-rig.json").read_text(encoding="utf-8"))
        names = {b["name"] for b in rig["blocks"]}
        for b in rig["blocks"]:
            self.assertTrue(b["parent"] is None or b["parent"] in names, b)
        referenced = list(rig["limits"]) + list(rig["hinges"]) + rig["contacts"] + rig["soft"]
        referenced += [n for pair in rig["no_overlap"] for n in pair]
        referenced += [n for pair in rig["stance"]["pairs"] for n in pair]
        for move in rig["moves"].values():
            referenced += move.get("planted", [])
        self.assertEqual(sorted(set(referenced) - names), [])

    def test_modules_name_no_particular_game(self):
        for name in MODULES:
            text = (ANIM / "scripts" / "block_anim" / f"{name}.gd").read_text(encoding="utf-8").lower()
            for word in ("creeper", "snapjaw", "skybreak", "res://scripts"):
                self.assertNotIn(word, text, f"{name}.gd mentions {word}")


def _godot():
    path = os.environ.get("STUDIO_GODOT") or shutil.which("godot")
    return path if path and Path(path).is_file() else None


@unittest.skipUnless(_godot(), "no Godot binary (set STUDIO_GODOT)")
class BlockAnimSelfTest(unittest.TestCase):
    def test_golden_poses(self):
        script = ANIM / "scripts" / "block_anim" / "selftest.gd"
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run(
                [_godot(), "--headless", "--script", str(script)],
                cwd=tmp, capture_output=True, text=True, timeout=180,
            )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("block_anim selftest: all passed", run.stdout)
        self.assertNotIn("SCRIPT ERROR", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
