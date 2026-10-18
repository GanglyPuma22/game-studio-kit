"""The gameplay gym skill and its plan template are shipped files; check what they promise."""

from pathlib import Path
import re
import unittest

from studio_tools.common import read_json

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/studio-gym/SKILL.md"
REFERENCES = ROOT / "skills/studio-gym/references"
PLAN = ROOT / "templates/gym-plan.json"


class GymSkillTests(unittest.TestCase):
    def test_skill_is_declared_with_its_references_and_template(self):
        manifest = read_json(ROOT / "studio-kit.json")
        self.assertIn({"name": "studio-gym", "path": "skills/studio-gym/SKILL.md"}, manifest["skills"])
        for path in sorted(REFERENCES.glob("*.md")):
            self.assertIn(path.relative_to(ROOT).as_posix(), manifest["resources"])
        self.assertIn("templates/gym-plan.json", manifest["resources"])

    def test_skill_walks_the_four_steps_and_names_its_commands(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertTrue(re.search(r"^name: studio-gym$", skill, re.M))
        description = re.search(r"^description: (.+)$", skill, re.M).group(1)
        for command in ("`studio playtest start`", "`studio launch`"):
            self.assertIn(command, description)
        for step in ("## Step 1: inventory", "## Step 2: map", "## Step 3: choose layout",
                     "## Step 4: wire in automated checks"):
            self.assertIn(step, skill)
        # A gym never stands in for the canonical route or a person's verdict.
        self.assertIn("never sets a feature row to `human_verdict: accepted`", skill)
        self.assertIn("not_established", skill)
        self.assertIn("Run the real code.", skill)

    def test_the_harness_route_matches_what_the_kit_supplies(self):
        # Only a driven playtest passes the template its report path, and the
        # kit refuses declared results inside the run directory it owns.
        checks = (REFERENCES / "checks-and-capture.md").read_text(encoding="utf-8")
        godot = (REFERENCES / "godot-gym.md").read_text(encoding="utf-8")
        self.assertIn("rather than batching room harnesses", checks)
        for text in (checks, godot):
            self.assertIn("artifacts/gym-results/<label>.json", text)
            self.assertNotIn("next to the harness report", text)
        # The gym entry must not compile gym code into normal launches.
        self.assertIn("load(GYM_SCRIPT)", godot)
        self.assertNotIn('const GYM := preload', godot)
        self.assertIn("RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME", godot)

    def test_traversal_and_godot_tailoring_are_reachable(self):
        skill = SKILL.read_text(encoding="utf-8")
        for name in ("room-catalog.md", "godot-gym.md", "checks-and-capture.md",
                     "swing-traversal.md", "sources.md"):
            self.assertIn(f"(references/{name})", skill)

    def test_plan_template_carries_the_fields_the_skill_names(self):
        plan = read_json(PLAN)
        self.assertEqual(plan["kind"], "gym-plan")
        for key in ("inventory", "rooms", "gaps", "key_registry", "entry", "engine"):
            self.assertIn(key, plan)
        row = plan["inventory"][0]
        for key in ("verb", "input", "owner", "numbers", "isolated_today", "not_in_gym"):
            self.assertIn(key, row)
        room = plan["rooms"][0]
        self.assertEqual(set(room["status"]), {"built", "checked", "observed"})
        # A status is bound to the build it was established on.
        for status in room["status"].values():
            self.assertEqual(set(status), {"ok", "content_digest", "content_identity_method", "evidence"})
        self.assertEqual(plan["schema_version"], 2)
        self.assertIn("byte-hashed", plan["$comment"])
        self.assertIn("content_digest_after_exit", plan["$comment"])
        self.assertIn("engine_running_at_collect is false", plan["$comment"])
        self.assertIn("adds content_identity_method", plan["$comment"])
        for key in ("metric", "expected", "tolerance", "source"):
            self.assertIn(key, room["questions"][0])

    def test_shipped_gym_files_carry_no_host_specific_path(self):
        host_specific = re.compile(r"[A-Za-z]:\\\\?Users|/home/[a-z]|/Users/[A-Za-z]|/mnt/[a-z]/")
        for path in [SKILL, PLAN, *REFERENCES.glob("*.md")]:
            found = host_specific.search(path.read_text(encoding="utf-8"))
            self.assertIsNone(found, f"{path.name} names a host-specific path: {found}")


if __name__ == "__main__":
    unittest.main()
