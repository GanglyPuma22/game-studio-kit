"""CPU-only argument and pose-mode contracts for structural inspection."""
import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from studio_tools.adapters import blender
from studio_tools.common import StudioError, write_json
from studio_tools.config import load


class BlenderInspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "mock.glb"
        self.source.write_bytes(b"not native model data")
        self.config = load(overrides={"executables": {"blender": sys.executable}})

    def fake_run(self, command, **kwargs):
        args = command[command.index("--") + 1:]
        write_json(args[1], {"dimensions_m": [1, 2, 3],
                            "bounds_pose": "armature_rest" if "--rest-pose" in args else "imported"})

    def test_default_inspection_keeps_original_arguments_and_imported_pose(self):
        output = self.root / "default.json"
        with patch.object(blender, "run", side_effect=self.fake_run) as run:
            report = blender.inspect(self.config, self.source, output)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--") + 1:], [str(self.source), str(output)])
        self.assertEqual(report["bounds_pose"], "imported")

    def test_rest_inspection_passes_explicit_flag_and_retains_marker(self):
        output = self.root / "rest.json"
        with patch.object(blender, "run", side_effect=self.fake_run) as run:
            report = blender.inspect(self.config, self.source, output, rest_pose=True)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--") + 1:], [str(self.source), str(output), "--rest-pose"])
        self.assertEqual(report["bounds_pose"], "armature_rest")

    def test_pose_option_requires_boolean(self):
        with patch.object(blender, "run") as run:
            with self.assertRaisesRegex(StudioError, "boolean"):
                blender.inspect(self.config, self.source, self.root / "bad.json", rest_pose="false")
            run.assert_not_called()

    def pose_function(self, update):
        # Execute only the pure pose-selection helper against a fake view layer;
        # never import bpy, launch Blender or execute the inspector's native body.
        script = Path(blender.SCRIPTS) / "inspect.py"
        tree = ast.parse(script.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "set_bounds_pose")
        namespace = {"bpy": SimpleNamespace(context=SimpleNamespace(view_layer=SimpleNamespace(update=update)))}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(script), "exec"), namespace)
        return namespace["set_bounds_pose"]

    def test_rest_mode_updates_every_armature_before_view_layer(self):
        rigs = [SimpleNamespace(data=SimpleNamespace(pose_position="POSE")) for _ in range(2)]
        observed = []
        update = Mock(side_effect=lambda: observed.append([rig.data.pose_position for rig in rigs]))
        select = self.pose_function(update)
        self.assertEqual(select(rigs, True), "armature_rest")
        self.assertEqual(observed, [["REST", "REST"]])
        update.assert_called_once_with()

    def test_default_pose_mode_does_not_change_armatures_or_update(self):
        rig = SimpleNamespace(data=SimpleNamespace(pose_position="POSE"))
        update = Mock()
        self.assertEqual(self.pose_function(update)([rig], False), "imported")
        self.assertEqual(rig.data.pose_position, "POSE")
        update.assert_not_called()

    def test_static_rest_request_still_returns_explicit_pose_marker(self):
        update = Mock()
        self.assertEqual(self.pose_function(update)([], True), "armature_rest")
        update.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
