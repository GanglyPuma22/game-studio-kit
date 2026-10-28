import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from studio_tools.model_qa.__main__ import discover, main
from studio_tools.model_qa.ecology import check as ecology

GEOMETRY = all(importlib.util.find_spec(name) for name in ("numpy", "trimesh", "scipy", "rtree", "pygltflib"))
# Attachment gaps use Blender's BVH (mathutils), so these run inside Blender's Python.
BLENDER_PY = GEOMETRY and importlib.util.find_spec("mathutils") is not None


class InputTests(unittest.TestCase):
    def test_ecology_needs_content_not_headings_or_comments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "entry.md"
            for text in ("# Habitat\n# Traits\n", "# Habitat\nTBD\n# Traits\n- flat\n",
                         "<!-- # Habitat\nwet ground\n# Traits\nlow because it helps -->"):
                path.write_text(text)
                self.assertEqual(ecology(path)["result"], "FAIL")
            path.write_text("# Habitat\nWindy ledges.\n# Traits\n- Low profile because it reduces wind damage.")
            self.assertEqual(ecology(path)["result"], "PASS")
            path.write_text("# Habitat\nWet ground.\n# Traits\n| Trait | Reason |\n|---|---|\n| Broad roots | Supports weight on soft soil |")
            self.assertEqual(ecology(path)["result"], "PASS")
            self.assertEqual(ecology(Path(folder) / "missing.md")["result"], "FAIL")

    def test_lods_sort_numerically_and_duplicates_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for name in ("model-lod10.glb", "model.glb", "model-lod2.glb"):
                (path / name).write_bytes(b"test")
            self.assertEqual([f["lod"] for f in discover([path])[0]["files"]], [0, 2, 10])
            (path / "model-lod0.glb").write_bytes(b"test")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                discover([path])

    def test_same_named_families_have_unambiguous_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for parent in ("a", "b", "c"):
                (path / parent).mkdir()
                (path / parent / "model.glb").write_bytes(b"test")
            self.assertEqual([f["name"] for f in discover([path])], ["a/model", "b/model", "c/model"])

    def test_missing_blender_writes_failures_and_refuses_stale_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            source = path / "model.glb"
            source.write_bytes(b"invalid")
            output = path / "out"
            args = [str(source), "--budget-tris", "100", "--ecology", str(path / "missing.md"),
                    "--out", str(output), "--blender", str(path / "missing-blender")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 1)
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(len(report["models"][0]["checks"]), 9)
            self.assertEqual({c['check']: c['result'] for c in report['models'][0]['checks']},
                             {'M12': 'UNMEASURED', 'M13': 'UNMEASURED', 'M14': 'UNMEASURED', 'M15': 'UNMEASURED',
                              'M5': 'UNMEASURED', 'M16': 'N/A', 'M17': 'N/A',
                              'triangles': 'UNMEASURED', 'ecology': 'FAIL'})
            self.assertTrue((output / "contact-sheet.png").read_bytes().startswith(b"\x89PNG"))
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                main(args)
            self.assertEqual(exc.exception.code, 2)


@unittest.skipUnless(BLENDER_PY, "Run inside Blender's Python (mathutils) with the model QA dependencies")
class AttachmentTests(unittest.TestCase):
    def test_self_intersection_limit_is_unmeasured_not_pass(self):
        import trimesh
        from studio_tools.model_qa.surface import self_intersections
        # Two crossing slabs welded into one part.
        a = trimesh.creation.box((1, 0.1, 1))
        b = trimesh.creation.box((0.1, 1, 1))
        part = trimesh.util.concatenate([a, b])
        self.assertEqual(self_intersections([part], ["slabs"])["result"], "FAIL")
        clean = trimesh.creation.icosphere(subdivisions=3)
        self.assertEqual(self_intersections([clean], ["ball"])["result"], "PASS")
        capped = self_intersections([clean], ["ball"], max_pairs=-1)
        self.assertEqual((capped["result"], capped["truncated"][0]["name"]), ("UNMEASURED", "ball"))

    def test_static_clean_floating_and_anchor_chain(self):
        from model_qa_fixtures import build, box
        from studio_tools.model_qa.geometry import load
        from studio_tools.model_qa.attachment import static
        with tempfile.TemporaryDirectory() as folder:
            build(folder)
            for name, expected in (("clean", "PASS"), ("floating", "FAIL")):
                _, parts, _, _ = load(Path(folder) / name / f"{name}-lod0.glb")
                self.assertEqual(static(parts)["result"], expected)
            parts = [box((1, 1, 1), (0, 0.5, 0)),
                     box((0.3, 0.3, 0.3), (0, 1.15, 0)),
                     box((0.2, 0.2, 0.2), (0, 1.4, 0))]
            self.assertEqual(static(parts)["result"], "PASS")
            for gap, expected in ((0.0029, "PASS"), (0.0031, "FAIL")):
                pieces = [box((1, 1, 1), (0, 0.5, 0)),
                          box((0.2, 0.2, 0.2), (0, 1.1 + gap, 0))]
                self.assertEqual(static(pieces)["result"], expected)

    def test_multiple_material_parts_retain_authored_names(self):
        import numpy as np
        import trimesh
        from model_qa_fixtures import box
        from studio_tools.model_qa.geometry import load
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "painted.glb"
            mesh = box((1, 1, 1), (0, 0, 0))
            from trimesh.visual.material import MultiMaterial, PBRMaterial
            mesh.visual = trimesh.visual.TextureVisuals(
                uv=np.zeros((len(mesh.vertices), 2)),
                material=MultiMaterial([PBRMaterial(name="a"), PBRMaterial(name="b")]),
                face_materials=np.arange(len(mesh.faces)) % 2)
            scene = trimesh.Scene()
            scene.add_geometry(mesh, node_name="painted-body", geom_name="painted-mesh")
            path.write_bytes(scene.export(file_type="glb"))
            first, second = load(path)[2], load(path)[2]
            self.assertEqual(first, second)
            self.assertTrue(all("painted-body / part-" in name for name in first))

    def test_skin_detaches_in_motion_and_unsupported_interpolation_refused(self):
        from model_qa_fixtures import skinned
        from studio_tools.model_qa.geometry import load
        from studio_tools.model_qa.attachment import skinned as check_skin
        from pygltflib import GLTF2
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "skin.glb"
            skinned(path)
            _, _, _, model = load(path)
            check = check_skin(model)
            self.assertEqual(check["result"], "FAIL")
            self.assertEqual(check["poses"], 7)
            self.assertTrue(any("detach" in r["worst_pose"] for r in check["parts"]))
            g = GLTF2().load(str(path))
            g.animations[0].samplers[0].interpolation = "CUSTOM"
            g.save(str(path))
            with self.assertRaisesRegex(ValueError, "LINEAR"):
                load(path)


@unittest.skipUnless(GEOMETRY and os.environ.get("MODEL_QA_BLENDER"), "Set MODEL_QA_BLENDER for owned headless integration tests")
class EndToEndTests(unittest.TestCase):
    def run_cli(self, source, ecology_path, output, *extra):
        command = [sys.executable, "-m", "studio_tools.model_qa", str(source), "--budget-tris", "100",
                   "--ecology", str(ecology_path), "--out", str(output), "--width", "640", "--height", "360",
                   "--timeout", "300", *extra]
        done = subprocess.run(command, capture_output=True, text=True, timeout=360)
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return done.returncode, json.loads((output / "report.json").read_text())

    def test_synthetic_glbs_and_negative_inputs(self):
        from model_qa_fixtures import build, skinned
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = build(root / "fixtures")
            for i in range(2):
                skinned(fixtures / "animated" / f"animated-lod{i}.glb")
            code, report = self.run_cli(fixtures, fixtures / "ecology.md", root / "combined", "--switch-distances", "2", "4")
            self.assertEqual(code, 1)
            self.assertEqual(report["errors"], [])
            checks = {(m["model"], m["lod"], c["check"]): c for m in report["models"] for c in m["checks"]}
            for lod in (0, 1):
                self.assertTrue(all(checks[("clean", lod, c)]["result"] == "PASS"
                                    for c in ("M12", "M13", "M5", "triangles", "ecology")))
                self.assertEqual(checks[("floating", lod, "M12")]["result"], "FAIL")
                self.assertEqual(checks[("clipping", lod, "M13")]["details"]["poses"][0]["major"], 1)
                self.assertEqual(checks[("animated", lod, "M12")]["result"], "FAIL")
            dropped = checks[("dropped", 1, "M5")]
            self.assertEqual(dropped["result"], "FAIL")
            self.assertIn("tip", dropped["details"]["disappeared_parts"][0]["name"])
            self.assertTrue((root / "combined/contact-sheet.png").is_file())
            code, clean = self.run_cli(fixtures / "clean", fixtures / "ecology.md", root / "clean", "--switch-distances", "2", "4")
            self.assertEqual((code, clean["result"]), (0, "PASS"))
            code, missing = self.run_cli(fixtures / "clean", root / "absent.md", root / "missing", "--budget-tris", "1")
            self.assertEqual(code, 1)
            for model in missing["models"]:
                results = {c["check"]: c["result"] for c in model["checks"]}
                self.assertEqual(results["M5"], "FAIL")
                self.assertEqual(results["ecology"], "FAIL")
                self.assertEqual(results["triangles"], "FAIL")

    def test_surface_checks_catch_inverted_folded_and_spiked(self):
        from model_qa_fixtures import build
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = build(root / "fixtures")
            source = root / "surface"
            source.mkdir()
            for name in ("clean", "inverted", "folded", "spiked"):
                (fixtures / name).rename(source / name)
            code, report = self.run_cli(source, fixtures / "ecology.md", root / "report", "--switch-distances", "2", "4")
            self.assertEqual((code, report["errors"]), (1, []))
            checks = {(m["model"], m["lod"], c["check"]): c for m in report["models"] for c in m["checks"]}
            for lod in (0, 1):
                self.assertEqual([checks[("clean", lod, c)]["result"] for c in ("M14", "M15")], ["PASS", "PASS"])
                # Inside-out: nothing else notices, the shell still touches itself and keeps its silhouette.
                self.assertEqual(checks[("inverted", lod, "M15")]["result"], "FAIL")
                self.assertEqual(checks[("inverted", lod, "M15")]["details"]["parts"][0]["kind"], "inside-out")
                self.assertEqual([checks[("inverted", lod, c)]["result"] for c in ("M12", "M13", "M14")], ["PASS"] * 3)
                self.assertEqual(checks[("folded", lod, "M14")]["result"], "FAIL")
            self.assertEqual(checks[("clean", 1, "M16")]["result"], "PASS")
            self.assertEqual(checks[("clean", 1, "M16")]["details"]["p99_px"], 0)
            spike = checks[("spiked", 1, "M16")]
            self.assertEqual(spike["result"], "FAIL")
            self.assertGreater(spike["details"]["added"]["max_px"], 2)

    def test_declared_clump_na_and_unset_budget_are_distinct(self):
        from model_qa_fixtures import build
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = build(root/'fixtures')/'clipping'
            (source/'model-qa.json').write_text(json.dumps(dict(schema_version=1, structure='clump',
                                                             ground_y_m=.2, living=False)))
            command = [sys.executable, '-m', 'studio_tools.model_qa', str(source), '--budget-tris', 'not-set',
                       '--out', str(root/'report'), '--switch-distances', '2', '4', '--timeout', '90']
            done = subprocess.run(command, capture_output=True, text=True, timeout=150)
            self.assertEqual(done.returncode, 1, done.stderr)
            data = json.loads((root/'report/report.json').read_text())
            self.assertEqual(data['errors'], [])
            self.assertEqual(data['result'], 'NOT SET')
            for model in data['models']:
                rows = {r['check']: r for r in model['checks']}
                self.assertEqual({c: r['result'] for c,r in rows.items()},
                                 dict(M12='PASS', M13='INFO', M14='INFO', M15='PASS', M5='PASS',
                                      M16='N/A' if model['lod'] == 0 else 'PASS', M17='N/A',
                                      triangles='NOT SET', ecology='N/A'))
                self.assertEqual(rows['M13']['details']['poses'][0]['major'], 1)


if __name__ == "__main__":
    unittest.main()
