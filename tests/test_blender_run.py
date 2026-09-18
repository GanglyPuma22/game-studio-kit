"""`studio blender run`: a project-owned script Blender executes headlessly (offline).

A small Python shim stands in for blender.exe the way `test_launch_evidence.py`
stands in for the engine: the argument line this adapter builds is handed to it
unchanged, so the flags, the separator and the passthrough are exercised rather
than asserted against a mock that never ran.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import re

from studio_tools import cli, processes
from studio_tools.adapters import blender
from studio_tools.cli import parser
from studio_tools.common import StudioError, read_json, sha256, write_json
from studio_tools.config import load

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/studio-blender/SKILL.md"
DIRECTOR = ROOT / "skills/studio-director/SKILL.md"

SHIM = '''"""Stand-in for blender.exe: check the launch line, then run the script."""
import runpy
import sys

argv = sys.argv[1:]
if argv[:2] != ["--background", "--factory-startup"]:
    print("fake blender: unexpected launch flags")
    raise SystemExit(2)
if argv[3:5] != ["--python-exit-code", "1"] or argv[5] != "--python" or argv[7:8] != ["--"]:
    print("fake blender: unexpected script flags")
    raise SystemExit(2)
print("Read blend file:", argv[2])
try:
    runpy.run_path(argv[6], run_name="__main__")
except SystemExit:
    raise
except BaseException as exc:
    print("Error: script raised", type(exc).__name__)
    raise SystemExit(1)
'''

BAKE = '''import os
import sys
from pathlib import Path

extra = sys.argv[sys.argv.index("--") + 1:]
print("passthrough:", " ".join(extra))
print("fixture env:", os.environ.get("STUDIO_JOB_FIXTURE", ""), file=sys.stderr)
Path("artifacts/bakes").mkdir(parents=True, exist_ok=True)
Path("artifacts/bakes/normal.png").write_text("baked " + " ".join(extra), encoding="utf-8")
'''


class BlenderRunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio blender space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        (self.root / "source").mkdir(parents=True)
        (self.root / "tools").mkdir()
        (self.root / "source/asset.blend").write_text("not a real blend", encoding="utf-8")
        self.script("tools/rebake.py", BAKE)
        self.shim = Path(self.tmp.name) / "fake_blender.py"
        self.shim.write_text(SHIM, encoding="utf-8")
        self.config = load(overrides={"executables": {"blender": sys.executable}})
        self.host_config = Path(self.tmp.name) / "host.json"
        write_json(self.host_config, {"executables": {"blender": sys.executable}})
        self.last_args = None
        self.last_kwargs = None

    def script(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def fake_blender(self, args, **kwargs):
        """Run the real argument line through the shim instead of Blender."""
        self.last_args = list(args)
        self.last_kwargs = kwargs
        return processes.run([sys.executable, str(self.shim), *list(args)[1:]], **kwargs)

    def cli_run(self, *argv):
        with patch("studio_tools.adapters.blender.run", side_effect=self.fake_blender):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = cli.main([
                        "blender", "run", "--project", str(self.root),
                        "--config", str(self.host_config), *argv,
                    ])
        return code, out.getvalue(), err.getvalue()

    def run_dir(self, label):
        return self.root / "artifacts/blender/runs" / label


class BlenderRunTests(BlenderRunCase):
    def test_cli_run_writes_receipts_without_argv_or_environment_values(self):
        with patch.dict(os.environ, {"STUDIO_JOB_FIXTURE": "private-env"}):
            code, out, err = self.cli_run(
                "--source", "source/asset.blend", "--script", "tools/rebake.py",
                "--label", "bake-1", "--result", "artifacts/bakes/normal.png",
                "--", "--marker", "private-arg",
            )
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        verdict = json.loads(out)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["kind"], "blender-run")
        self.assertEqual(verdict["status"], "completed")
        self.assertEqual(verdict["returncode"], 0)
        self.assertFalse(verdict["timed_out"])
        run_dir = self.run_dir("bake-1")
        receipt = read_json(run_dir / "run.json")
        self.assertEqual(receipt["label"], "bake-1")
        self.assertEqual(receipt["blender"],
                         {"path": str(Path(sys.executable).resolve()), "sha256": sha256(sys.executable)})
        self.assertEqual(receipt["source"],
                         {"path": "source/asset.blend", "sha256": sha256(self.root / "source/asset.blend")})
        self.assertEqual(receipt["script"],
                         {"path": "tools/rebake.py", "sha256": sha256(self.root / "tools/rebake.py")})
        self.assertEqual(receipt["passthrough_count"], 2)
        self.assertEqual(receipt["result_files"], [{
            "path": "artifacts/bakes/normal.png", "present": True,
            "sha256": sha256(self.root / "artifacts/bakes/normal.png"),
        }])
        self.assertIn("not visual acceptance", receipt["limits"])
        self.assertIsNone(receipt["failure"])
        self.assertGreater(read_json(run_dir / "process/process.json")["pid"], 0)
        log = (run_dir / "process/stdout.log").read_text(encoding="utf-8")
        self.assertIn("private-arg", log)
        self.assertIn("private-env", log)
        for name in ("run.json", "process/process.json"):
            self.assertNotIn("private-", (run_dir / name).read_text(encoding="utf-8"))
        self.assertNotIn("private-", out)

    def test_headless_argument_line_carries_the_source_script_and_separator(self):
        self.cli_run("--source", "source/asset.blend", "--script", "tools/rebake.py",
                     "--label", "line", "--", "--samples", "8")
        self.assertEqual(self.last_args, [
            str(Path(sys.executable).resolve()), "--background", "--factory-startup",
            str((self.root / "source/asset.blend").resolve()),
            "--python-exit-code", "1",
            "--python", str((self.root / "tools/rebake.py").resolve()),
            "--", "--samples", "8",
        ])
        self.assertEqual(self.last_kwargs["cwd"], str(self.root))
        self.assertTrue(self.last_kwargs["hide_window"])
        self.assertEqual(self.last_kwargs["timeout"], 600.0)
        self.assertEqual(self.last_kwargs["job_dir"], self.run_dir("line") / "process")

    def test_run_without_passthrough_still_ends_at_blenders_own_separator(self):
        code, out, _ = self.cli_run("--source", "source/asset.blend",
                                    "--script", "tools/rebake.py", "--label", "bare")
        self.assertEqual(code, 0)
        self.assertEqual(self.last_args[-1], "--")
        self.assertEqual(json.loads(out)["passthrough_count"], 0)

    def test_missing_declared_result_is_not_ok(self):
        self.script("tools/quiet.py", "print('nothing produced')\n")
        code, out, _ = self.cli_run(
            "--source", "source/asset.blend", "--script", "tools/quiet.py",
            "--label", "quiet", "--result", "artifacts/bakes/normal.png",
        )
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["status"], "completed")
        self.assertEqual(verdict["returncode"], 0)
        self.assertEqual(verdict["result_files"],
                         [{"path": "artifacts/bakes/normal.png", "present": False, "sha256": None}])

    def test_failing_script_is_a_verdict_and_never_echoes_the_passthrough(self):
        self.script("tools/broken.py",
                    "import sys\n"
                    "print('passthrough:', ' '.join(sys.argv[sys.argv.index('--') + 1:]))\n"
                    "raise RuntimeError('bake failed')\n")
        code, out, err = self.cli_run(
            "--source", "source/asset.blend", "--script", "tools/broken.py",
            "--label", "broken", "--", "private-arg",
        )
        self.assertEqual(err, "")
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["status"], "failed")
        self.assertEqual(verdict["returncode"], 1)
        self.assertNotIn("private-arg", out)
        self.assertIn("exited with code 1", verdict["failure"])
        self.assertIn("private-arg", (self.run_dir("broken") / "process/stdout.log").read_text())
        self.assertNotIn("private-arg", (self.run_dir("broken") / "run.json").read_text())

    def test_timeout_is_a_verdict_with_owned_cleanup(self):
        self.script("tools/slow.py", "import time,sys;print('partial',flush=True);time.sleep(30)\n")
        code, out, _ = self.cli_run(
            "--source", "source/asset.blend", "--script", "tools/slow.py",
            "--label", "slow", "--timeout", "1",
        )
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertTrue(verdict["timed_out"])
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["status"], "timed_out")
        self.assertEqual(verdict["cleanup"], "owned_tree_stopped")
        self.assertIn("partial", Path(verdict["log"]).read_text(encoding="utf-8"))
        self.assertTrue((self.run_dir("slow") / "run.json").is_file())

    def test_label_collision_is_refused_with_the_run_intact(self):
        self.cli_run("--source", "source/asset.blend", "--script", "tools/rebake.py",
                     "--label", "same")
        first = (self.run_dir("same") / "run.json").read_text(encoding="utf-8")
        code, out, err = self.cli_run("--source", "source/asset.blend",
                                      "--script", "tools/rebake.py", "--label", "same")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("choose a new label", json.loads(err)["error"])
        self.assertEqual((self.run_dir("same") / "run.json").read_text(encoding="utf-8"), first)

    def test_declared_result_inside_the_run_directory_is_refused_before_launch(self):
        with patch("studio_tools.adapters.blender.run") as runner:
            code, _, err = self.cli_run(
                "--source", "source/asset.blend", "--script", "tools/rebake.py",
                "--label", "owned", "--result", "artifacts/blender/runs/owned/run.json",
            )
            runner.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("must not be files this runner writes", json.loads(err)["error"])
        self.assertFalse(self.run_dir("owned").exists())

    def test_inputs_are_checked_before_anything_is_launched(self):
        with patch("studio_tools.adapters.blender.run") as runner:
            for arguments, message in (
                (["--source", "source/missing.blend", "--script", "tools/rebake.py"], ".blend --source"),
                (["--source", "tools/rebake.py", "--script", "tools/rebake.py"], ".blend --source"),
                (["--source", "source/asset.blend", "--script", "tools/missing.py"], ".py --script"),
                (["--source", "source/asset.blend", "--script", "source/asset.blend"], ".py --script"),
                (["--source", "../escape.blend", "--script", "tools/rebake.py"], "escapes the declared project root"),
                (["--source", "source/asset.blend", "--script", "tools/rebake.py",
                  "--timeout", "0"], "1–3600"),
                (["--source", "source/asset.blend", "--script", "tools/rebake.py",
                  "--timeout", "4000"], "1–3600"),
                (["--source", "source/asset.blend", "--script", "tools/rebake.py",
                  "--label", "not a label"], "letters, digits"),
                (["--source", "source/asset.blend", "--script", "tools/rebake.py",
                  "--result", "../outside.png"], "escapes the declared project root"),
            ):
                with self.subTest(arguments=arguments):
                    code, _, err = self.cli_run(*arguments)
                    self.assertEqual(code, 1)
                    self.assertIn(message, json.loads(err)["error"])
            runner.assert_not_called()
        self.assertFalse((self.root / "artifacts/blender/runs").exists())

    def test_the_adapter_refuses_a_project_that_does_not_exist(self):
        with self.assertRaisesRegex(StudioError, "existing game project"):
            blender.script_run(self.config, self.root / "absent",
                               source="source/asset.blend", script="tools/rebake.py")

    def test_the_four_packaged_operations_keep_their_argument_surface(self):
        for argv in (
            ["blender", "fixture", "--project", "game", "--output", "source/bell"],
            ["blender", "inspect", "--project", "game", "--source", "assets/a.glb",
             "--output", "artifacts/a.json"],
            ["blender", "export", "--project", "game", "--source", "source/a.blend",
             "--collection", "RuntimeAsset", "--output", "assets/a.glb"],
            ["blender", "render", "--project", "game", "--source", "source/a.blend",
             "--camera", "ReviewCamera", "--frames", "1,13", "--angles", "0,90",
             "--target", "0,0,0.75", "--output", "artifacts/turntable"],
        ):
            with self.subTest(operation=argv[1]):
                parsed = parser().parse_args(argv)
                self.assertEqual(parsed.command, "blender")
                self.assertEqual(parsed.operation, argv[1])
                self.assertEqual(parsed.project, "game")
        for argv in (["blender", "run", "--project", "game", "--script", "tools/x.py"],
                     ["blender", "run", "--project", "game", "--source", "source/a.blend"],
                     ["blender", "bake", "--project", "game"]):
            with self.subTest(refused=argv):
                with self.assertRaises(SystemExit):
                    with contextlib.redirect_stderr(io.StringIO()):
                        parser().parse_args(argv)


class BlenderRunDiscoverabilityTests(unittest.TestCase):
    """The throwaway wrapper existed because no description named this command."""

    def test_the_blender_skill_description_names_the_command(self):
        text = SKILL.read_text(encoding="utf-8")
        description = re.search(r"^description: (.+)$", text, re.M)
        self.assertIsNotNone(description)
        self.assertIn("`studio blender run`", description.group(1))

    def test_the_skill_says_when_to_use_run_instead_of_the_interactive_mcp(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("## `run` or the interactive MCP", text)
        self.assertIn("blender run --project <GAME> --source", text)
        # The two limits an agent most needs before it trusts a green run.
        self.assertIn("it is not visual acceptance", text)
        self.assertIn("never their values", text)
        # The run's working directory is what makes a relative --result land
        # where the script writes it; the test above proves the behaviour.
        self.assertIn("working directory", text)

    def test_the_director_routing_table_routes_a_headless_script_to_run(self):
        text = DIRECTOR.read_text(encoding="utf-8")
        row = [line for line in text.splitlines() if "`studio blender run`" in line]
        self.assertEqual(len(row), 1, "the routing table needs exactly one blender run row")
        self.assertIn("bake, export, mesh repair", row[0])

    def test_blender_stays_one_declared_command_with_its_adapter_packaged(self):
        manifest = read_json(ROOT / "studio-kit.json")
        self.assertIn("blender", manifest["commands"])
        self.assertIn("studio_tools/adapters/blender.py", manifest["resources"])


if __name__ == "__main__":
    unittest.main()
