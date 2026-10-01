"""Small RNA contract regression; native bake evidence is separate."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest


class ActionBindingTests(unittest.TestCase):
    def test_modern_blender_clears_action_without_setting_unassigned_slot(self):
        # Blender5.1 raises if action_slot is assigned while Action is None.
        # Extract the dependency-free helper so core tests need no Blender.
        path = Path(__file__).resolve().parents[1]/"studio_tools/blender_scripts/unimate_bake.py"
        tree = ast.parse(path.read_text())
        helper = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="bind_action")
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[helper],type_ignores=[])),str(path),"exec"),namespace)
        class Data:
            action = None
            _slot = None
            @property
            def action_slot(self):
                return self._slot
            @action_slot.setter
            def action_slot(self,value):
                if self.action is None:
                    raise RuntimeError("Cannot set slot without an assigned Action")
                self._slot=value
        data = Data()
        arm = SimpleNamespace(animation_data=data,animation_data_create=lambda:None)
        slot = object()
        action = SimpleNamespace(slots=[slot])
        namespace["bind_action"](arm,action)
        self.assertIs(data.action,action)
        self.assertIs(data.action_slot,slot)
        namespace["bind_action"](arm,None)
        self.assertIsNone(data.action)


class ClipDurationTests(unittest.TestCase):
    def helper(self):
        path = Path(__file__).resolve().parents[1]/"studio_tools/blender_scripts/unimate_verify.py"
        tree = ast.parse(path.read_text())
        helper = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="verify_clip_durations")
        namespace = {"math":math}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[helper],type_ignores=[])),str(path),"exec"),namespace)
        return namespace["verify_clip_durations"]

    def fixture(self):
        expected = {"bank_left":2.,"bank_right":2.,"glide":4.,"generated":59/30}
        return expected,[{"name":name,"duration_seconds":duration} for name,duration in expected.items()]

    def test_float32_export_time_accepts_original_seconds_but_changed_duration_refuses(self):
        expected,clips = self.fixture()
        clips[-1]["duration_seconds"] = 1.9666666984558105
        self.helper()(clips,expected)
        for index in range(len(clips)):
            changed = [dict(clip) for clip in clips]
            changed[index]["duration_seconds"] += .01
            with self.subTest(clip=clips[index]["name"]),self.assertRaises(RuntimeError):
                self.helper()(changed,expected)

    def test_duplicate_missing_and_nonfinite_clip_evidence_refuses(self):
        expected,clips = self.fixture()
        for changed in (clips+[clips[0]],clips[:-1],clips[:-1]+[clips[0]],
                        [dict(clip,duration_seconds=float("nan")) for clip in clips]):
            with self.subTest(clips=changed),self.assertRaises(RuntimeError):
                self.helper()(changed,expected)


if __name__=="__main__":
    unittest.main()
