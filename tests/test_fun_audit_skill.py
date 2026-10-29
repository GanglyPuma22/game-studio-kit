"""The fun audit skill, its references and its record template are shipped files; check what they promise."""

from pathlib import Path
import re
import unittest

from studio_tools.common import read_json

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/studio-fun-audit/SKILL.md"
REFERENCES = ROOT / "skills/studio-fun-audit/references"
TEMPLATE = ROOT / "templates/fun-audit.json"

KINDS = ("sensation", "fantasy", "narrative", "challenge", "fellowship", "discovery", "expression", "submission")
KEYS = ("hard", "easy", "people", "serious")
LEGS = ("cap", "job", "readability", "stakes")


class FunAuditSkillTests(unittest.TestCase):
    def test_skill_is_declared_with_its_references_and_template(self):
        manifest = read_json(ROOT / "studio-kit.json")
        self.assertIn({"name": "studio-fun-audit", "path": "skills/studio-fun-audit/SKILL.md"}, manifest["skills"])
        references = sorted(REFERENCES.glob("*.md"))
        self.assertGreaterEqual(len(references), 4)
        for path in references:
            self.assertIn(path.relative_to(ROOT).as_posix(), manifest["resources"])
        self.assertIn("templates/fun-audit.json", manifest["resources"])

    def test_skill_names_the_vocabulary_and_the_six_steps(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertTrue(re.search(r"^name: studio-fun-audit$", skill, re.M))
        description = re.search(r"^description: (.+)$", skill, re.M).group(1)
        # The method's premise: the word fun describes nothing in a design document.
        self.assertIn("not the word fun", description)
        for kind in KINDS:
            self.assertIn(f"`{kind}`", skill, kind)
        for key in KEYS:
            self.assertIn(f"`{key}`", skill, key)
        for heading in ("## Step 1: name the fun targets",
                        "## Step 2: score each candidate, per role",
                        "## Step 3: score every dead state on the four legs",
                        "## Step 4: set and measure the death-readability window",
                        "## Step 5: spec the death-screen progress pattern",
                        "## Step 6: write the experiment, not the opinion",
                        "## Checklist before handing back"):
            self.assertIn(heading, skill, heading)
        # Every score is one of two things, and the record says which.
        self.assertIn("`evidence`", skill)
        self.assertIn("`hypothesis`", skill)
        # Asymmetric play is scored from both sides.
        self.assertIn("fun to use and fun to face", skill)
        # The audit never grants acceptance; that stays with review.
        self.assertIn("issues no acceptance verdict", skill)

    def test_skill_links_every_reference_and_the_sibling_skills(self):
        skill = SKILL.read_text(encoding="utf-8")
        for path in sorted(REFERENCES.glob("*.md")):
            self.assertIn(f"references/{path.name}", skill, path.name)
        for sibling in ("studio-game-design", "studio-playtest", "studio-gym", "studio-review"):
            self.assertIn(f"../{sibling}/SKILL.md", skill, sibling)
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", skill):
            if target.startswith("http"):
                continue
            self.assertTrue((SKILL.parent / target).resolve().exists(), target)

    def test_references_carry_the_four_legs_and_the_one_word_method(self):
        legs = (REFERENCES / "respawn-and-dead-time.md").read_text(encoding="utf-8")
        for heading in ("## Leg 1: cap the dead time", "## Leg 2: give the dead a job",
                        "## Leg 3: make deaths readable", "## Leg 4: let stakes convert spectating into drama",
                        "## Diagnosis template"):
            self.assertIn(heading, legs, heading)
        kinds = (REFERENCES / "kinds-of-fun.md").read_text(encoding="utf-8")
        self.assertIn("## The eight kinds (MDA aesthetics)", kinds)
        self.assertIn("## The four keys (Lazzaro)", kinds)
        self.assertIn("## The one-word method", kinds)
        for kind in KINDS:
            self.assertIn(f"`{kind}`", kinds, kind)
        examples = (REFERENCES / "worked-examples.md").read_text(encoding="utf-8")
        self.assertIn("## Example 1", examples)
        self.assertIn("## Example 2", examples)
        self.assertIn("Weakest leg", examples)
        sources = (REFERENCES / "sources.md").read_text(encoding="utf-8")
        self.assertIn("MDA.pdf", sources)
        self.assertIn("urf-academy", sources)

    def test_template_record_carries_the_vocabulary_and_every_section(self):
        record = read_json(TEMPLATE)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["kind"], "fun-audit")
        vocabulary = record["vocabulary"]
        for kind in KINDS:
            self.assertIn(kind, vocabulary["kinds"])
        self.assertEqual(tuple(vocabulary["keys"]), KEYS)
        self.assertEqual(tuple(vocabulary["legs"]), LEGS)
        self.assertEqual(vocabulary["status_values"], ["evidence", "hypothesis", "not_run"])
        for section in ("targets", "candidates", "death_readability", "death_screen_progress",
                        "experiments", "recommendation"):
            self.assertIn(section, record, section)
        target = record["targets"][0]
        for field in ("role", "primary", "secondary", "mechanic", "keys", "status", "basis"):
            self.assertIn(field, target, field)
        # A fresh record claims nothing: every example row starts as a hypothesis or not run.
        self.assertEqual(target["status"], "hypothesis")
        candidate = record["candidates"][0]
        role = candidate["roles"][0]
        for field in ("delivery", "use", "face", "required_fellowship", "visible_contribution",
                      "efficiency_fantasy", "keys"):
            self.assertIn(field, role, field)
        dead = candidate["dead_states"][0]
        self.assertEqual(tuple(dead["legs"]), LEGS)
        self.assertIn("weakest_leg", dead)
        self.assertEqual(record["death_readability"]["status"], "not_run")
        self.assertEqual(record["death_screen_progress"]["status"], "not_run")
        experiment = record["experiments"][0]
        for field in ("hypothesis", "prototype", "measures", "changes_recommendation_if"):
            self.assertIn(field, experiment, field)
        self.assertIn("runner_up_wins_if", record["recommendation"])

    def test_shipped_files_stay_game_neutral_and_host_neutral(self):
        # The skill audits any game; a project's own names belong in its record, not here.
        host_specific = re.compile(r"[A-Za-z]:\\\\?Users|/home/[a-z]|/Users/[A-Za-z]|/mnt/[a-z]/")
        for path in (SKILL, TEMPLATE, *sorted(REFERENCES.glob("*.md"))):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(host_specific.search(text), path.name)
            self.assertNotIn("Skybreak", text, path.name)


if __name__ == "__main__":
    unittest.main()
