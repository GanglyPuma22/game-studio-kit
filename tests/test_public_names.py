"""This repository is public: its text names no game, person or machine.

Lessons are written as "one game" with a date. The reserved job type
"salvage-batch" in studio_tools/cloudrun.py is an identifier other code
depends on, so the lower-case word alone is not on the list.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NAMES = re.compile(r"\b(Maxim|Salvage|Skybreak|skybreak|Tetherquake|tetherquake|Aptivio|aptivio)\b")
SCANNED = ("skills", "film-kit", "references", "docs", "templates", "examples", "scripts", "studio_tools")
SUFFIXES = {".md", ".json", ".py", ".sh", ".ps1", ".gd", ".toml", ".txt", ".yaml", ".yml", ".cfg"}


def scanned_files():
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix in SUFFIXES:
            yield path
    for name in SCANNED:
        for path in (ROOT / name).rglob("*"):
            if path.is_file() and path.suffix in SUFFIXES and "__pycache__" not in path.parts:
                yield path


class PublicNamesTests(unittest.TestCase):
    def test_no_game_person_or_machine_is_named(self):
        found = []
        for path in scanned_files():
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for match in NAMES.finditer(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {match.group(0)}")
        self.assertEqual(found, [])

    def test_the_scan_reaches_the_skills(self):
        self.assertIn(ROOT / "skills/studio-director/SKILL.md", set(scanned_files()))


if __name__ == "__main__":
    unittest.main()
