"""studio-motionbricks: package wiring, licence rule and helper syntax.

The helpers need numpy/scipy/warp to run, so only their syntax is checked here.
"""

import json
import py_compile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "studio-motionbricks"
SCRIPTS = ["mb_cpu.py", "soma_pose.py", "rig_map.py", "render.py", "retime.py", "dump_skeleton.gd"]
REFS = ["method.md", "lessons.md"]


class MotionBricksSkillTests(unittest.TestCase):
    def test_files_are_declared_resources(self):
        manifest = json.loads((ROOT / "studio-kit.json").read_text(encoding="utf-8"))
        self.assertIn({"name": "studio-motionbricks", "path": "skills/studio-motionbricks/SKILL.md"}, manifest["skills"])
        resources = set(manifest["resources"])
        for name in SCRIPTS:
            path = f"skills/studio-motionbricks/scripts/{name}"
            self.assertIn(path, resources)
            self.assertTrue((ROOT / path).is_file(), path)
        for name in REFS:
            self.assertIn(f"skills/studio-motionbricks/references/{name}", resources)

    def test_skill_routes_to_references_and_states_the_licence_rule(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for name in REFS:
            self.assertIn(f"references/{name}", text)
        self.assertIn("evaluation-only", text)
        self.assertIn("Smart Primitive", text)

    def test_python_helpers_compile(self):
        for name in SCRIPTS:
            if name.endswith(".py"):
                py_compile.compile(str(SKILL / "scripts" / name), doraise=True)


if __name__ == "__main__":
    unittest.main()
