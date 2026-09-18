"""Topology audit arithmetic and `studio blender reduce` (offline).

The arithmetic is tested directly on hand-built triangle lists, because that is
the part a wrong answer would silently ruin: a mesh reported clean that is not
goes on to fail during rigging, collision generation or baking, far away from
here. The command is tested with a small Python shim standing in for
`blender.exe` exactly as `test_blender_run.py` does, so the real launch line and
the real packaged script path are exercised rather than asserted.
"""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cli, processes
from studio_tools.adapters import blender
from studio_tools.blender_scripts import topology
from studio_tools.cli import parser
from studio_tools.common import read_json, sha256, write_json

ROOT = Path(__file__).resolve().parents[1]
BLENDER_SKILL = ROOT / "skills/studio-blender/SKILL.md"
MESHY_SKILL = ROOT / "skills/studio-meshy/SKILL.md"
DIRECTOR = ROOT / "skills/studio-director/SKILL.md"

# A closed, consistently wound tetrahedron: every edge shared by exactly two
# faces that traverse it in opposite directions.
TETRAHEDRON = ([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
               [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)])

SHIM = '''"""Stand-in for blender.exe: check the launch line, write the canned reduction."""
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
if argv[:2] != ["--background", "--factory-startup"]:
    print("fake blender: unexpected launch flags")
    raise SystemExit(2)
if argv[2:4] != ["--python-exit-code", "1"] or argv[4] != "--python" or argv[6] != "--":
    print("fake blender: unexpected script flags")
    raise SystemExit(2)
if Path(argv[5]).name != "reduce.py" or not Path(argv[5]).is_file():
    print("fake blender: unexpected packaged script")
    raise SystemExit(2)
source, target, output, audit, selected = argv[7:12]
print("reduce:", source, target, output, selected)
plan = json.loads(Path(os.environ["STUDIO_FAKE_REDUCE"]).read_text(encoding="utf-8"))
report = plan["audit"]
report["target_triangles"] = int(target)
Path(audit).parent.mkdir(parents=True, exist_ok=True)
Path(audit).write_text(json.dumps(report), encoding="utf-8")
if plan.get("save", True):
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("reduced blend", encoding="utf-8")
if plan.get("source") == "change":
    Path(source).write_text("edited while the reduction was running", encoding="utf-8")
elif plan.get("source") == "delete":
    Path(source).unlink()
raise SystemExit(plan.get("returncode", 0))
'''


def counts(vertices, triangles, uv_layers=0, numpy=False):
    record = topology.audit_triangles(vertices, triangles, uv_layers, numpy=numpy)
    return (record["boundary_edges"], record["nonmanifold_edges"],
            record["inconsistent_winding_edges"])


class TopologyArithmeticTests(unittest.TestCase):
    """The audit counts defects; it never repairs and never modifies input."""

    def test_a_closed_consistently_wound_solid_reports_no_defects(self):
        vertices, triangles = TETRAHEDRON
        self.assertEqual(counts(vertices, triangles), (0, 0, 0))
        record = topology.audit_triangles(vertices, triangles, 2, numpy=False)
        self.assertEqual(record["triangles"], 4)
        self.assertEqual(record["uv_layers"], 2)
        self.assertTrue(topology.clean(record))

    def test_one_open_triangle_is_three_boundary_edges(self):
        record = topology.audit_triangles(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], numpy=False
        )
        self.assertEqual(record["boundary_edges"], 3)
        self.assertEqual(record["nonmanifold_edges"], 0)
        self.assertEqual(record["inconsistent_winding_edges"], 0)
        self.assertFalse(topology.clean(record))

    def test_an_edge_shared_by_three_faces_is_one_nonmanifold_edge(self):
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, -1, 0)]
        fan = [(0, 1, 2), (0, 1, 3), (0, 1, 4)]
        self.assertEqual(counts(vertices, fan), (6, 1, 0))

    def test_two_faces_that_traverse_a_shared_edge_the_same_way_are_inconsistent(self):
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        self.assertEqual(counts(vertices, [(0, 1, 2), (0, 1, 3)]), (4, 0, 1))
        # The same pair wound in opposite directions is a clean shared edge.
        self.assertEqual(counts(vertices, [(0, 1, 2), (1, 0, 3)]), (4, 0, 0))

    def test_a_duplicated_seam_vertex_is_welded_by_position_not_counted_as_a_hole(self):
        vertices, triangles = TETRAHEDRON
        seam = list(vertices) + [vertices[3]]
        split = list(triangles[:3]) + [(1, 2, 4)]
        self.assertEqual(counts(seam, split), (0, 0, 0))
        # Vertex 4 only exists as a duplicate position, so the count welds it away.
        self.assertEqual(topology.audit_triangles(seam, split, numpy=False)["triangles"], 4)

    def test_two_shells_touching_at_one_vertex_are_caught_by_nothing_but_the_vertex_test(self):
        # Every edge is shared by exactly two faces wound in opposite
        # directions, so all three edge counts are zero and the surface is
        # still unusable at the point where the shells meet.
        vertices = TETRAHEDRON[0] + [(0, 0, 0), (-1, 0, 0), (0, -1, 0), (0, 0, -1)]
        faces = list(TETRAHEDRON[1]) + [(4 + a, 4 + b, 4 + c) for a, b, c in TETRAHEDRON[1]]
        record = topology.audit_triangles(vertices, faces, numpy=False)
        self.assertEqual(record["boundary_edges"], 0)
        self.assertEqual(record["nonmanifold_edges"], 0)
        self.assertEqual(record["inconsistent_winding_edges"], 0)
        self.assertEqual(record["nonmanifold_vertices"], 1)
        self.assertFalse(topology.clean(record))
        # The two shells welded into one vertex, so eight triangles remain.
        self.assertEqual(record["triangles"], 8)

    def test_a_closed_fan_around_every_vertex_reports_no_nonmanifold_vertex(self):
        self.assertEqual(
            topology.audit_triangles(*TETRAHEDRON, numpy=False)["nonmanifold_vertices"], 0
        )
        # An open fan is one group too: a hole is boundary, not a bowtie.
        self.assertEqual(
            topology.audit_triangles([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)],
                                     numpy=False)["nonmanifold_vertices"], 0)

    def test_the_vertex_defect_is_part_of_the_clean_verdict(self):
        self.assertIn("nonmanifold_vertices", topology.DEFECTS)
        self.assertFalse(topology.clean(dict.fromkeys(topology.DEFECTS, 0)
                                        | {"nonmanifold_vertices": 1}))

    def test_totals_add_the_meshes_up_and_stay_clean_only_when_every_mesh_is(self):
        good = topology.audit_triangles(*TETRAHEDRON, numpy=False)
        bad = topology.audit_triangles(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], numpy=False
        )
        self.assertTrue(topology.totals([good, good])["clean"])
        total = topology.totals([good, bad])
        self.assertFalse(total["clean"])
        self.assertEqual(total["meshes_measured"], 2)
        self.assertEqual(total["triangles"], 5)
        self.assertEqual(total["boundary_edges"], 3)

    def test_the_absence_of_numpy_is_reported_rather_than_guessed(self):
        self.assertEqual(topology.UNAVAILABLE["status"], "unavailable")
        self.assertIn("numpy", topology.UNAVAILABLE["reason"])
        self.assertFalse(topology.clean(topology.UNAVAILABLE))

    @unittest.skipIf(topology.numpy_module() is None, "numpy is not installed here")
    def test_the_numpy_path_agrees_with_the_plain_python_path(self):
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, -1, 0)]
        for triangles in (TETRAHEDRON[1], [(0, 1, 2)], [(0, 1, 2), (0, 1, 3), (0, 1, 4)],
                          [(0, 1, 2), (0, 1, 3)]):
            with self.subTest(triangles=triangles):
                source = TETRAHEDRON[0] if triangles is TETRAHEDRON[1] else vertices
                self.assertEqual(
                    topology.audit_triangles(source, triangles, 1, numpy=False),
                    topology.audit_triangles(source, triangles, 1),
                )


CLEAN = (0, 0, 0, 0)


def report(before=CLEAN, after=CLEAN, status="measured", saved=True,
           before_triangles=4853274, after_triangles=300000, applied=()):
    """The audit JSON the packaged script writes, as the fake Blender writes it."""
    def totals(defects, triangles):
        record = {"status": "measured", "meshes_measured": 1, "triangles": triangles}
        record.update(zip(topology.DEFECTS, defects))
        record["clean"] = defects == CLEAN
        return record

    first, second = totals(before, before_triangles), totals(after, after_triangles)
    ratio = after_triangles / before_triangles if before_triangles else None
    return {
        "schema_version": 1, "blender_version": "4.5.1", "status": status,
        "target_triangles": 300000, "weld_distance": 1e-07,
        "objects": [{
            "index": 0,
            "name_sha256": hashlib.sha256(b"Tree").hexdigest(),
            "applied_modifiers": list(applied),
            "before": dict(first, uv_layers=1),
            "welded_triangles": before_triangles,
            "collapse_ratio": ratio, "decimated": True,
            "after": dict(second, uv_layers=1),
        }],
        "before": first, "after": second,
        "ratio": ratio, "saved": saved,
    }


class ReduceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio blender space ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        (self.root / "source").mkdir(parents=True)
        self.source = self.root / "source/original.blend"
        self.source.write_text("not a real blend", encoding="utf-8")
        self.shim = Path(self.tmp.name) / "fake_blender.py"
        self.shim.write_text(SHIM, encoding="utf-8")
        self.plan = Path(self.tmp.name) / "plan.json"
        self.canned(report())
        self.host_config = Path(self.tmp.name) / "host.json"
        write_json(self.host_config, {"executables": {"blender": sys.executable}})
        self.last_args = None
        self.last_kwargs = None

    def canned(self, audit, save=True, returncode=0, source=None):
        write_json(self.plan, {"audit": audit, "save": save,
                               "returncode": returncode, "source": source})

    def fake_blender(self, args, **kwargs):
        self.last_args = list(args)
        self.last_kwargs = kwargs
        return processes.run([sys.executable, str(self.shim), *list(args)[1:]], **kwargs)

    def raw_cli(self, *argv):
        with patch.dict(os.environ, {"STUDIO_FAKE_REDUCE": str(self.plan)}):
            with patch("studio_tools.adapters.blender.run", side_effect=self.fake_blender):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    with contextlib.redirect_stderr(io.StringIO()) as err:
                        code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def cli_reduce(self, *argv):
        return self.raw_cli("blender", "reduce", "--project", str(self.root),
                            "--config", str(self.host_config), *argv)

    def reduce_dir(self, label):
        return self.root / "artifacts/blender/reduce" / label

    def default(self, *argv):
        return self.cli_reduce(
            "--source", "source/original.blend", "--target-triangles", "300000",
            "--output", "source/original-300k.blend", *argv,
        )


class ReduceTests(ReduceCase):
    def test_a_clean_reduction_writes_a_receipt_holding_both_audits(self):
        code, out, err = self.default("--label", "tree-300k")
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        verdict = json.loads(out)
        self.assertTrue(verdict["ok"])
        self.assertIsNone(verdict["reason"])
        receipt = read_json(self.reduce_dir("tree-300k") / "reduce.json")
        self.assertEqual(receipt["kind"], "blender-reduce")
        self.assertEqual(receipt["label"], "tree-300k")
        self.assertEqual(receipt["target_triangles"], 300000)
        self.assertEqual(receipt["source"],
                         {"path": "source/original.blend", "sha256": sha256(self.source)})
        self.assertEqual(receipt["output"]["path"], "source/original-300k.blend")
        self.assertTrue(receipt["output"]["present"])
        self.assertEqual(receipt["output"]["sha256"],
                         sha256(self.root / "source/original-300k.blend"))
        self.assertEqual(receipt["before"]["triangles"], 4853274)
        self.assertEqual(receipt["after"]["triangles"], 300000)
        for name in ("boundary_edges", "nonmanifold_edges", "inconsistent_winding_edges"):
            self.assertEqual(receipt["after"][name], 0)
        self.assertEqual(receipt["weld_distance"], 1e-07)
        self.assertAlmostEqual(receipt["ratio"], 300000 / 4853274)
        # The object is identified by index and name digest, never by name.
        self.assertEqual(receipt["objects"][0]["index"], 0)
        self.assertEqual(receipt["objects"][0]["name_sha256"],
                         hashlib.sha256(b"Tree").hexdigest())
        self.assertNotIn("name", receipt["objects"][0])
        self.assertEqual(receipt["source_after"],
                         {"present": True, "sha256": sha256(self.source)})
        self.assertFalse(receipt["object_selected"])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["returncode"], 0)
        self.assertIsNone(receipt["failure"])
        self.assertIn("not visual acceptance", receipt["limits"])
        self.assertIn("intentional walk-through gap stays open", receipt["limits"])
        self.assertTrue((self.reduce_dir("tree-300k") / "audit.json").is_file())
        self.assertGreater(read_json(self.reduce_dir("tree-300k") / "process/process.json")["pid"], 0)

    def test_the_launch_line_runs_the_packaged_reduce_script_after_blenders_separator(self):
        self.default("--label", "line", "--object", "Tree")
        self.assertEqual(self.last_args[:3],
                         [str(Path(sys.executable).resolve()), "--background", "--factory-startup"])
        self.assertEqual(self.last_args[3:6], ["--python-exit-code", "1", "--python"])
        self.assertEqual(Path(self.last_args[6]),
                         ROOT / "studio_tools/blender_scripts/reduce.py")
        self.assertEqual(self.last_args[7], "--")
        self.assertEqual(self.last_args[8], str(self.source.resolve()))
        self.assertEqual(self.last_args[9], "300000")
        self.assertEqual(self.last_args[12], "Tree")
        self.assertEqual(self.last_kwargs["cwd"], str(self.root))
        self.assertTrue(self.last_kwargs["hide_window"])
        self.assertEqual(self.last_kwargs["job_dir"], self.reduce_dir("line") / "process")

    def test_a_defective_source_cannot_be_qualified_by_reducing_it(self):
        # The measured provider remesh: 125k triangles, 91 boundary, 87 nonmanifold.
        self.canned(report(before=(91, 87, 0, 0), before_triangles=125485))
        code, out, _ = self.default("--label", "provider")
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"],
                         "source topology not clean; reduction cannot qualify it")
        self.assertEqual(verdict["before"]["boundary_edges"], 91)
        self.assertFalse(verdict["before"]["clean"])
        self.assertFalse(read_json(self.reduce_dir("provider") / "reduce.json")["ok"])

    def test_a_reduction_that_introduces_a_defect_is_not_ok(self):
        self.canned(report(after=(0, 12, 0, 0)))
        code, out, _ = self.default("--label", "torn")
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertIn("introduced boundary, nonmanifold", verdict["reason"])

    def test_a_result_still_over_the_requested_budget_is_not_ok(self):
        self.canned(report(after_triangles=412000))
        code, out, _ = self.default("--label", "over")
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertIn("over target", verdict["reason"])
        self.assertIn("object 0 holds 412000 triangles", verdict["reason"])
        self.assertIn("target of 300000", verdict["reason"])

    def test_a_nonmanifold_vertex_in_the_result_is_not_ok(self):
        # Zero boundary, zero nonmanifold and zero inconsistent edges: only the
        # vertex test sees this one.
        self.canned(report(after=(0, 0, 0, 3)))
        code, out, _ = self.default("--label", "bowtie")
        self.assertEqual(code, 1)
        self.assertIn("nonmanifold vertex", json.loads(out)["reason"])

    def test_a_selection_with_no_triangles_is_refused_rather_than_called_clean(self):
        for label, audit in (
            ("empty-after", report(after_triangles=0)),
            ("empty-before", report(before_triangles=0, after_triangles=0)),
        ):
            with self.subTest(label=label):
                self.canned(audit)
                code, out, _ = self.default("--label", label,
                                            "--output", "source/%s.blend" % label)
                self.assertEqual(code, 1)
                verdict = json.loads(out)
                self.assertFalse(verdict["ok"])
                self.assertIn("hold no triangles", verdict["reason"])
                self.assertIn("objects 0", verdict["reason"])

    def test_a_reduction_that_selected_nothing_is_refused(self):
        audit = report()
        audit["objects"] = []
        self.canned(audit)
        code, out, _ = self.default("--label", "none")
        self.assertEqual(code, 1)
        self.assertIn("no mesh object was selected", json.loads(out)["reason"])

    def test_the_applied_modifier_stack_is_named_in_the_receipt(self):
        self.canned(report(applied=("Subdivision", "Mirror")))
        code, out, _ = self.default("--label", "applied")
        self.assertEqual(code, 0)
        receipt = read_json(self.reduce_dir("applied") / "reduce.json")
        self.assertEqual(receipt["objects"][0]["applied_modifiers"],
                         ["Subdivision", "Mirror"])

    def test_a_source_edited_during_the_reduction_is_not_ok_and_says_both_hashes(self):
        before = sha256(self.source)
        self.canned(report(), source="change")
        code, out, _ = self.default("--label", "edited")
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertIn(before, verdict["reason"])
        self.assertIn(sha256(self.source), verdict["reason"])
        self.assertEqual(verdict["source"]["sha256"], before)
        self.assertEqual(verdict["source_after"],
                         {"present": True, "sha256": sha256(self.source)})

    def test_a_source_deleted_during_the_reduction_still_writes_the_receipt(self):
        before = sha256(self.source)
        self.canned(report(), source="delete")
        code, out, err = self.default("--label", "gone")
        self.assertEqual(err, "")
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertIn("unreadable", verdict["reason"])
        receipt = read_json(self.reduce_dir("gone") / "reduce.json")
        self.assertEqual(receipt["source"]["sha256"], before)
        self.assertEqual(receipt["source_after"], {"present": False, "sha256": None})

    def test_a_blender_that_is_not_configured_leaves_no_reduce_directory(self):
        config = Path(self.tmp.name) / "no-blender.json"
        write_json(config, {"executables": {"blender": "missing-blender-xyz"}})
        with patch("studio_tools.adapters.blender.run") as runner:
            code, _, err = self.raw_cli(
                "blender", "reduce", "--project", str(self.root), "--config", str(config),
                "--source", "source/original.blend", "--target-triangles", "300000",
                "--output", "source/never.blend", "--label", "nohost",
            )
            runner.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("blender needs setup", json.loads(err)["error"])
        self.assertFalse((self.root / "artifacts").exists())

    def test_an_unsaved_reduction_is_not_ok_even_with_two_clean_audits(self):
        self.canned(report(saved=False), save=False)
        code, out, _ = self.default("--label", "unsaved")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["reason"], "no reduced .blend was saved")
        self.assertFalse((self.root / "source/original-300k.blend").exists())

    def test_a_build_without_numpy_reports_unmeasured_instead_of_a_clean_mesh(self):
        unavailable = report(status="unavailable")
        unavailable["reason"] = topology.UNAVAILABLE["reason"]
        self.canned(unavailable, save=False)
        code, out, _ = self.default("--label", "nonumpy")
        self.assertEqual(code, 1)
        self.assertIn("numpy", json.loads(out)["reason"])

    def test_a_failing_blender_is_a_verdict_with_the_receipt_still_written(self):
        self.canned(report(), save=False, returncode=1)
        code, out, err = self.default("--label", "failed")
        self.assertEqual(err, "")
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["status"], "failed")
        self.assertIn("Blender did not complete", verdict["reason"])
        self.assertTrue((self.reduce_dir("failed") / "reduce.json").is_file())

    def test_an_existing_output_is_refused_before_blender_is_launched(self):
        (self.root / "source/original-300k.blend").write_text("earlier", encoding="utf-8")
        with patch("studio_tools.adapters.blender.run") as runner:
            code, _, err = self.default("--label", "clash")
            runner.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("already exists", json.loads(err)["error"])
        self.assertEqual((self.root / "source/original-300k.blend").read_text(), "earlier")
        self.assertFalse(self.reduce_dir("clash").exists())

    def test_every_input_is_checked_before_anything_is_launched(self):
        with patch("studio_tools.adapters.blender.run") as runner:
            for arguments, message in (
                (["--target-triangles", "99"], "100–5000000"),
                (["--target-triangles", "5000001"], "100–5000000"),
                (["--source", "source/missing.blend"], ".blend or .glb --source"),
                (["--source", "../escape.blend"], "escapes the declared project root"),
                (["--output", "source/reduced.glb"], "--output must be a .blend"),
                (["--output", "../outside.blend"], "escapes the declared project root"),
                (["--label", "not a label"], "letters, digits"),
            ):
                with self.subTest(arguments=arguments):
                    overrides = dict(zip(arguments[::2], arguments[1::2]))
                    code, _, err = self.cli_reduce(
                        "--source", overrides.get("--source", "source/original.blend"),
                        "--target-triangles", overrides.get("--target-triangles", "300000"),
                        "--output", overrides.get("--output", "source/original-300k.blend"),
                        *(["--label", overrides["--label"]] if "--label" in overrides else []),
                    )
                    self.assertEqual(code, 1)
                    self.assertIn(message, json.loads(err)["error"])
            runner.assert_not_called()
        self.assertFalse((self.root / "artifacts/blender/reduce").exists())

    def test_a_repeated_label_is_refused_with_the_earlier_reduction_intact(self):
        self.default("--label", "same")
        first = (self.reduce_dir("same") / "reduce.json").read_text(encoding="utf-8")
        code, out, err = self.cli_reduce(
            "--source", "source/original.blend", "--target-triangles", "300000",
            "--output", "source/other-300k.blend", "--label", "same",
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("choose a new label", json.loads(err)["error"])
        self.assertEqual((self.reduce_dir("same") / "reduce.json").read_text(encoding="utf-8"),
                         first)

    def test_no_argv_value_lands_in_any_receipt(self):
        code, out, _ = self.default("--label", "quiet", "--object", "PrivateObjectName")
        self.assertEqual(code, 0)
        # The launch line carries the host's absolute paths and the selected
        # object; the receipts carry project-relative paths, hashes and counts.
        argv_values = [self.last_args[8], self.last_args[10], self.last_args[11],
                       "PrivateObjectName"]
        for name in ("reduce.json", "process/process.json"):
            text = (self.reduce_dir("quiet") / name).read_text(encoding="utf-8")
            for value in argv_values:
                self.assertNotIn(value, text)
            self.assertNotIn(str(self.root.resolve()), text)
        # The printed verdict adds only where its own receipts and log live,
        # so the source, the output and the selected object are still absent.
        for value in (self.last_args[8], self.last_args[10], "PrivateObjectName"):
            self.assertNotIn(value, out)
        # It did reach the process that needed it.
        self.assertIn("PrivateObjectName",
                      (self.reduce_dir("quiet") / "process/stdout.log").read_text(encoding="utf-8"))

    def test_a_shared_option_is_accepted_on_either_side_of_the_operation_name(self):
        for side, before, after in (
            ("after", [], ["--project", str(self.root), "--config", str(self.host_config),
                           "--source", "source/original.blend"]),
            ("before", ["--project", str(self.root), "--config", str(self.host_config),
                        "--source", "source/original.blend"], []),
        ):
            with self.subTest(side=side):
                code, out, err = self.raw_cli(
                    "blender", *before, "reduce", *after,
                    "--target-triangles", "300000",
                    "--output", "source/%s.blend" % side, "--label", side,
                )
                self.assertEqual(err, "")
                self.assertEqual(code, 0)
                self.assertTrue(json.loads(out)["ok"])
                self.assertEqual(json.loads(out)["source"]["path"], "source/original.blend")

    def test_the_operation_side_wins_when_a_shared_option_is_given_twice(self):
        code, out, err = self.raw_cli(
            "blender", "--project", str(self.root), "--config", str(self.host_config),
            "--source", "source/missing.blend", "reduce",
            "--source", "source/original.blend", "--target-triangles", "300000",
            "--output", "source/wins.blend", "--label", "wins",
        )
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["source"]["path"], "source/original.blend")

    def test_what_reduce_needs_is_named_where_it_runs_rather_than_by_argparse(self):
        # Nothing is `required` on the subparser, because that would refuse a
        # shared option spelled before the operation name.
        shared = ["--project", str(self.root), "--config", str(self.host_config)]
        with patch("studio_tools.adapters.blender.run") as runner:
            for arguments in (
                ["--target-triangles", "300000", "--output", "source/a.blend"],
                ["--source", "source/original.blend", "--output", "source/a.blend"],
                ["--source", "source/original.blend", "--target-triangles", "300000"],
            ):
                with self.subTest(arguments=arguments):
                    code, _, err = self.raw_cli("blender", "reduce", *shared, *arguments)
                    self.assertEqual(code, 1)
                    self.assertIn("needs --source, --target-triangles and --output",
                                  json.loads(err)["error"])
            code, _, err = self.raw_cli(
                "blender", "reduce", "--config", str(self.host_config),
                "--source", "source/original.blend", "--target-triangles", "300000",
                "--output", "source/a.blend",
            )
            self.assertEqual(code, 1)
            self.assertIn("needs --project", json.loads(err)["error"])
            runner.assert_not_called()

    def test_a_project_that_does_not_exist_is_refused_without_being_created(self):
        absent = Path(self.tmp.name) / "mistyped"
        with patch("studio_tools.adapters.blender.run") as runner:
            code, _, err = self.raw_cli(
                "blender", "reduce", "--project", str(absent), "--config", str(self.host_config),
                "--source", "source/original.blend", "--target-triangles", "300000",
                "--output", "source/a.blend",
            )
            runner.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("existing game project", json.loads(err)["error"])
        self.assertFalse(absent.exists())

    def test_the_reduce_argument_surface_parses_and_refuses_a_nonnumeric_budget(self):
        parsed = parser().parse_args([
            "blender", "reduce", "--project", "game", "--source", "source/a.glb",
            "--target-triangles", "300000", "--output", "source/a-300k.blend",
            "--object", "Tree", "--label", "tree",
        ])
        self.assertEqual((parsed.command, parsed.operation), ("blender", "reduce"))
        self.assertEqual(parsed.target_triangles, 300000)
        self.assertEqual(parsed.object, "Tree")
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                parser().parse_args([
                    "blender", "reduce", "--project", "game", "--source", "a.glb",
                    "--target-triangles", "many", "--output", "a.blend",
                ])


class ReduceGuidanceTests(unittest.TestCase):
    """The measurement is only worth having if the next agent reads it first."""

    def test_the_blender_skill_names_reduce_and_says_how_to_qualify_a_mesh(self):
        text = BLENDER_SKILL.read_text(encoding="utf-8")
        description = re.search(r"^description: (.+)$", text, re.M)
        self.assertIn("`studio blender reduce`", description.group(1))
        self.assertIn("## Qualify before collision or rig", text)
        self.assertIn("blender reduce --project <GAME> --source", text)
        self.assertIn("never the render mesh", text)
        self.assertIn("intentional", text)

    def test_the_meshy_skill_carries_what_was_measured_and_the_decision_rule(self):
        text = MESHY_SKILL.read_text(encoding="utf-8")
        description = re.search(r"^description: (.+)$", text, re.M)
        self.assertIn("topology", description.group(1))
        self.assertIn("## Polycount and topology: what was measured", text)
        for measurement in ("4,853,274", "125,485", "30,816", "300,000"):
            self.assertIn(measurement, text)
        self.assertIn("unqualified until", text)
        self.assertIn("archive", text)

    def test_the_director_routes_both_questions_this_night_produced(self):
        text = DIRECTOR.read_text(encoding="utf-8")
        inspect_row = [l for l in text.splitlines() if "`studio blender inspect`" in l]
        reduce_row = [l for l in text.splitlines() if "`studio blender reduce`" in l]
        self.assertEqual(len(inspect_row), 1)
        self.assertEqual(len(reduce_row), 1)
        self.assertIn("usable", inspect_row[0])
        self.assertIn("archived original", reduce_row[0])

    def test_the_packaged_reducer_never_writes_an_object_name_into_its_audit(self):
        # reduce.py imports bpy, so this is a source check rather than a run:
        # the behaviour it guards is that `--object` is a value the caller
        # passed in and a receipt is not the place to hand one back.
        source = (ROOT / "studio_tools/blender_scripts/reduce.py").read_text(encoding="utf-8")
        self.assertIn("name_sha256", source)
        self.assertIn("hashlib.sha256(obj.name.encode", source)
        self.assertNotIn('"name": obj.name', source)
        # The stack the source already carried is applied before anything is
        # measured, so what is measured is what gets saved.
        self.assertIn("applied = apply_existing_stack(obj)", source)
        self.assertLess(source.index("apply_existing_stack(obj)"),
                        source.index("before = measure(obj, numpy)"))

    def test_the_packaged_scripts_ship_with_the_kit(self):
        resources = read_json(ROOT / "studio-kit.json")["resources"]
        self.assertIn("studio_tools/blender_scripts/reduce.py", resources)
        self.assertIn("studio_tools/blender_scripts/topology.py", resources)


if __name__ == "__main__":
    unittest.main()
