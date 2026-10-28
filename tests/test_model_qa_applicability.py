"""0.1.16 regressions; synthetic geometry only, no project-specific inputs."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import numpy as np
    import yaml
    from pygltflib import GLTF2, Accessor, BufferView, Attributes
    from model_qa_fixtures import box, export, skinned
    from studio_tools.model_qa import geometry, attachment
    from studio_tools.model_qa.gltf_pose import acc
    GEOMETRY = True
except ImportError:
    GEOMETRY = False

from studio_tools.model_qa import ecology, report
from studio_tools.model_qa.__main__ import main, parser, discover


def accessor(g, array, kind, component=5126, normalized=False):
    data = bytearray(g.binary_blob())
    data.extend(b'\0' * (-len(data) % 4))
    offset = len(data)
    data.extend(array.tobytes())
    g.bufferViews.append(BufferView(buffer=0, byteOffset=offset, byteLength=array.nbytes))
    g.accessors.append(Accessor(bufferView=len(g.bufferViews)-1, componentType=component,
                               count=len(array), type=kind, normalized=normalized))
    g.buffers[0].byteLength = len(data)
    g.set_binary_blob(bytes(data))
    return len(g.accessors)-1


@unittest.skipUnless(GEOMETRY, 'Install model QA optional requirements')
class ApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_yaml_structure_does_not_approve_proposal(self):
        p = self.root/'ecology.md'
        p.write_text('---\nstatus: proposed\nreview_status: awaiting approval\n'
                     'habitat:\n  where: Exposed rocky ground\ntraits:\n'
                     '  - feature: Low spreading crown\n    because: Reduces wind damage\n---\n', encoding='utf-8')
        result = ecology.check(p)
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['status'], 'proposed')
        self.assertEqual(result['review_status'], 'awaiting approval')
        self.assertEqual(result['habitat'], 'Exposed rocky ground')
        p.write_text('---\nhabitat: {where: TBD}\ntraits: [{feature: flat, because: TODO}]\n---\n')
        self.assertEqual(ecology.check(p)['result'], 'FAIL')

    def test_nonliving_and_explicit_none_are_na(self):
        p = self.root/'stone.md'
        p.write_text('---\nliving: false\n---\n')
        self.assertEqual(ecology.check(p)['result'], 'N/A')
        self.assertEqual(ecology.check(None, living=False)['result'], 'N/A')
        self.assertEqual(ecology.check(None, reason='Manufactured prop')['result'], 'N/A')
        self.assertEqual(ecology.check(None)['result'], 'FAIL')

    def test_budget_not_set_and_no_implied_minimum(self):
        self.assertEqual(report.budget(240, None)['result'], 'NOT SET')
        self.assertEqual(report.budget(240, 12000)['result'], 'PASS')
        self.assertEqual(report.budget(12001, 12000)['result'], 'FAIL')
        args = parser().parse_args(['model.glb', '--budget-tris', 'not-set', '--ecology', 'none',
                                   '--reason', 'Non-living', '--out', 'out'])
        self.assertIsNone(args.budget_tris)
        self.assertEqual(args.timeout, 90)

    def test_states_are_not_coerced_to_pass(self):
        states = ['N/A', 'NOT SET', 'INFO', 'UNMEASURED']
        rows = [report.row('ecology', state, state) for state in states]
        self.assertEqual([r['result'] for r in rows], states)
        data = {'models': [{'model': 'sample', 'lod': 0, 'file': 'sample.glb', 'sha256': 'test',
                            'checks': [report.row(c, 'UNMEASURED', 'no measurement') for c in report.CHECKS]}],
                'settings': {}, 'errors': ['resource failure']}
        self.assertEqual(report.write(data, self.root)['result'], 'UNMEASURED')
        self.assertIn('UNMEASURED', (self.root/'REPORT.md').read_text())

    def test_ground_contact_and_clump_preserve_raw_failures(self):
        pieces = [box((1, 1, 1), (0, .5, 0)), box((1, 1, 1), (3, .5, 0))]
        if importlib.util.find_spec('mathutils'):  # attachment gaps use Blender's BVH
            self.assertEqual(attachment.static(pieces)['result'], 'FAIL')
        self.assertEqual(attachment.ground(pieces)['result'], 'PASS')
        for height, expected in ((.5029, 'PASS'), (.5031, 'FAIL'), (-.5031, 'FAIL')):
            self.assertEqual(attachment.ground([box((1, 1, 1), (0, height, 0))])['result'], expected)
        raw = {'result': 'FAIL', 'major': 2, 'minor': 0, 'clipping': []}
        row = report.overlaps([raw], 'clump')
        self.assertEqual(row['result'], 'INFO')
        self.assertEqual(row['details']['poses'][0]['major'], 2)
        self.assertEqual(report.overlaps([raw], 'assembly')['result'], 'FAIL')
        self.assertEqual(report.overlaps([raw], 'scatter')['result'], 'FAIL')

    def test_manifest_default_and_explicit_declaration(self):
        p = self.root/'model.glb'; p.write_bytes(b'fixture')
        self.assertEqual(discover([p])[0]['manifest']['structure'], 'assembly')
        (self.root/'model-qa.json').write_text(json.dumps({'schema_version': 1, 'living': False,
                                                       'structure': 'clump', 'ground_y_m': 0.0}))
        family = discover([p])[0]
        self.assertEqual(family['manifest']['structure'], 'clump')
        self.assertFalse(family['manifest']['living'])
        (self.root/'model-qa.json').write_text('{"structure": "anything"}')
        with self.assertRaises(ValueError): discover([p])
        # A bare string would exempt every part name containing one of its letters.
        for allow in ('"Satchel"', '[""]', '[3]'):
            (self.root/'model-qa.json').write_text('{"symmetry": {"allow": %s}}' % allow)
            with self.assertRaises(ValueError): discover([p])
        (self.root/'model-qa.json').write_text('{"symmetry": {"allow": ["Satchel"]}}')
        self.assertEqual(discover([p])[0]['manifest']['symmetry']['allow'], ['Satchel'])

    def test_missing_worker_is_unmeasured(self):
        p = self.root/'model.glb'; p.write_bytes(b'fixture')
        out = self.root/'out'
        with contextlib.redirect_stdout(io.StringIO()):
            code = main([str(p), '--budget-tris', 'not-set', '--ecology', 'none', '--reason', 'Stone',
                         '--out', str(out), '--blender', str(self.root/'absent')])
        self.assertEqual(code, 1)
        data = json.loads((out/'report.json').read_text())
        self.assertEqual(data['result'], 'UNMEASURED')
        rows = {r['check']: r for r in data['models'][0]['checks']}
        self.assertEqual(rows['M12']['result'], 'UNMEASURED')
        self.assertEqual(rows['ecology']['result'], 'N/A')
        self.assertEqual(rows['triangles']['result'], 'NOT SET')

    def test_geometry_does_not_decode_or_copy_materials(self):
        import trimesh
        from PIL import Image
        mesh = box((1, 1, 1), (0, .5, 0))
        mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)),
                         image=Image.new('RGB', (32, 32), 'red'))
        p = self.root/'textured.glb'; export(p, [('textured', mesh)])
        with patch('PIL.Image.open', side_effect=MemoryError('Texture decode forbidden')) as image_open:
            tm, _, _, _ = geometry.load(p)
        image_open.assert_not_called()
        self.assertEqual(len(tm.faces), 12)

    def test_quantized_signed_positions_and_scene_transform(self):
        p = self.root/'quantized.glb'; export(p, [('body', box((1, 1, 1), (0, 0, 0)))])
        g = GLTF2().load(str(p)); primitive = g.meshes[0].primitives[0]
        original = acc(g, primitive.attributes.POSITION)
        quant = (original * 32767 * 2).astype('<i2')
        quant[quant == -32767] = -32768
        primitive.attributes.POSITION = accessor(g, quant, 'VEC3', 5122, True)
        g.extensionsRequired = ['KHR_mesh_quantization']
        node = next(n for n in g.nodes if n.mesh is not None)
        node.scale = [.5, .5, .5]; node.translation = [2, 0, 0]
        g.save(str(p)); tm, _, _, _ = geometry.load(p)
        np.testing.assert_allclose(tm.bounds, [[1.5, -.5, -.5], [2.5, .5, .5]], atol=1e-6)

    def test_step_and_cubic_skin_sampling(self):
        p = self.root/'animated.glb'; skinned(p)
        g = GLTF2().load(str(p)); sampler = g.animations[0].samplers[0]
        sampler.interpolation = 'STEP'; g.save(str(p))
        m = geometry.load(p)[3]; target = g.animations[0].channels[0].target.node
        np.testing.assert_allclose(m.sample('detach', .75)[target, 'translation'], [0, 0, 0])
        np.testing.assert_allclose(m.sample('detach', 1)[target, 'translation'], [0, .4, 0])
        sampler.interpolation = 'CUBICSPLINE'
        # Nonzero outgoing tangent makes the midpoint different from a linear interpolation.
        values = np.array([[0,0,0], [0,0,0], [0,.8,0], [0,0,0], [0,.4,0], [0,0,0]], dtype='<f4')
        sampler.output = accessor(g, values, 'VEC3'); g.save(str(p)); m = geometry.load(p)[3]
        np.testing.assert_allclose(m.sample('detach', .5)[target, 'translation'], [0, .3, 0], atol=1e-7)
        self.assertEqual(len(m.poses(6)), 7)  # rest plus six samples, as M12-M14 use

    def test_vertex_owner_is_the_heaviest_joint_in_any_slot(self):
        p = self.root/'animated.glb'; skinned(p)
        g = GLTF2().load(str(p))
        tip = next(n for n in g.nodes if n.name == 'tip')
        primitive = g.meshes[tip.mesh].primitives[0]
        count = g.accessors[primitive.attributes.POSITION].count
        joints = np.zeros((count, 4), dtype='<u2'); joints[:, 1] = 1        # slot 0: body joint at weight 0
        weights = np.zeros((count, 4), dtype='<f4'); weights[:, 1] = 1
        primitive.attributes.JOINTS_0 = accessor(g, joints, 'VEC4', 5123)
        primitive.attributes.WEIGHTS_0 = accessor(g, weights, 'VEC4')
        g.save(str(p))
        m = geometry.load(p)[3]
        self.assertEqual({m.owner_names[o] for o in m.owner}, {'body-joint', 'tip-joint'})

    def test_independently_animated_rigid_nodes_stay_separate_parts(self):
        from pygltflib import Node, Animation, AnimationSampler, AnimationChannel, AnimationChannelTarget
        p = self.root/'panels.glb'
        # Two panels sharing an edge under one pivot: one part while only the pivot moves them together.
        import trimesh
        def panel(x0):
            v = np.array([[x0, 0, 0], [x0 + 1, 0, 0], [x0 + 1, 1, 0], [x0, 1, 0]], float)
            return trimesh.Trimesh(v, [[0, 1, 2], [0, 2, 3]], process=False)
        export(p, [('left', panel(0)), ('right', panel(1))])
        g = GLTF2().load(str(p))
        right = next(i for i, n in enumerate(g.nodes) if n.name == 'right')
        pivot = len(g.nodes)
        g.nodes.append(Node(name='pivot', children=list(g.scenes[0].nodes)))
        g.scenes[0].nodes = [pivot]
        g.animations = [Animation(name='swing', samplers=[AnimationSampler(
            input=accessor(g, np.array([[0], [1]], dtype='<f4'), 'SCALAR'),
            output=accessor(g, np.array([[0, 0, 0, 1], [0, .7071, 0, .7071]], dtype='<f4'), 'VEC4'))],
            channels=[AnimationChannel(sampler=0, target=AnimationChannelTarget(node=pivot, path='rotation'))])]
        g.save(str(p))
        self.assertEqual(int(attachment.part_labels(geometry.load(p)[3]).max()) + 1, 1)
        g.animations[0].channels[0].target.node = right   # now the right box turns on its own
        g.save(str(p))
        self.assertEqual(int(attachment.part_labels(geometry.load(p)[3]).max()) + 1, 2)

    def test_rigid_faces_own_no_joint_and_wind_per_pose(self):
        from pygltflib import Animation, AnimationSampler, AnimationChannel, AnimationChannelTarget
        p = self.root/'mirror.glb'; export(p, [('prop', box((1, 1, 1), (0, .5, 0)))])
        g = GLTF2().load(str(p))
        prop = next(i for i, n in enumerate(g.nodes) if n.name == 'prop')
        g.animations = [Animation(name='mirror', samplers=[AnimationSampler(
            input=accessor(g, np.array([[0], [1]], dtype='<f4'), 'SCALAR'),
            output=accessor(g, np.array([[1, 1, 1], [-1, 1, 1]], dtype='<f4'), 'VEC3'), interpolation='STEP')],
            channels=[AnimationChannel(sampler=0, target=AnimationChannelTarget(node=prop, path='scale'))])]
        g.save(str(p))
        m = geometry.load(p)[3]
        self.assertTrue((m.face_owner() == -1).all())      # rigid: never a joint-crease fold
        np.testing.assert_array_equal(m.faces('mirror', 0), m.idx)
        np.testing.assert_array_equal(m.faces('mirror', 1), m.idx[:, ::-1])

    def test_seam_split_closed_surface_counts_as_closed(self):
        cube = box((1, 1, 1), (0, 0, 0))
        split = SimpleNamespace(pos=cube.vertices[cube.faces].reshape(-1, 3), idx=np.arange(len(cube.faces) * 3).reshape(-1, 3))
        self.assertFalse(attachment._closed(split.idx))
        self.assertTrue(attachment._closed(attachment.welded(split).faces))

    def test_empty_symmetry_declaration_is_measured(self):
        request = {"settings": {"budget_tris": None}, "ecology": None,
                   "families": [{"name": "m", "manifest": {"structure": "assembly", "symmetry": {}},
                                 "files": [{"path": "m.glb", "lod": 0, "sha256": "0"}]}]}
        rows = {r["check"]: r["result"] for r in report.initial(request)["models"][0]["checks"]}
        self.assertEqual(rows["M17"], "UNMEASURED")

    def test_morph_base_is_measured_and_limitation_recorded(self):
        p = self.root/'morph.glb'; export(p, [('body', box((1, 1, 1), (0, .5, 0)))])
        g = GLTF2().load(str(p)); primitive = g.meshes[0].primitives[0]
        delta = np.ones_like(acc(g, primitive.attributes.POSITION), dtype='<f4') * 100
        primitive.targets = [Attributes(POSITION=accessor(g, delta, 'VEC3'))]
        g.meshes[0].weights = [1.0]; g.save(str(p)); tm, _, _, _ = geometry.load(p)
        np.testing.assert_allclose(tm.bounds, [[-.5, 0, -.5], [.5, 1, .5]])
        self.assertIn('Morph targets were not checked', tm.metadata['qa_notes'])

    @unittest.skipUnless(importlib.util.find_spec('mathutils'), "The worker's geometry runs on Blender's BVH; run inside Blender's Python")
    def test_memory_failure_retains_metadata_and_completed_checks(self):
        from studio_tools.model_qa.worker import execute
        p = self.root/'body.glb'; export(p, [('body', box((1,1,1), (0,.5,0)))])
        family = discover([p])[0]
        family['manifest']['living'] = False
        settings = dict(budget_tris=None, samples=6, switch_distances=None, width=1920, height=1080,
                        fov=75, max_pixel_difference=.05, part_match_mm=3)
        fake = SimpleNamespace(SIDES=('front', 'right', 'back', 'left'),
                               render=lambda *a: (_ for _ in ()).throw(MemoryError('render allocation failed')),
                               contact_sheet=lambda *a: None)
        for phase in ('geometry', 'render'):
            out = self.root/phase; out.mkdir()
            request = dict(families=[family], settings=settings, out=str(out), ecology=None, ecology_sha256=None)
            with patch.dict(sys.modules, {'bpy': SimpleNamespace(app=SimpleNamespace(version_string='fixture')),
                                          'studio_tools.model_qa.clipping': SimpleNamespace(check=lambda *a: dict(result='PASS', major=0, minor=0, clipping=[])),
                                          'studio_tools.model_qa.silhouettes': fake}):
                with contextlib.redirect_stderr(io.StringIO()):
                    if phase == 'geometry':
                        with patch.object(geometry, 'load', side_effect=MemoryError('geometry allocation failed')):
                            result = execute(request)
                    else:
                        result = execute(request)
            self.assertEqual(result['result'], 'UNMEASURED')
            checks = {r['check']: r for r in result['models'][0]['checks']}
            self.assertEqual(checks['ecology']['result'], 'N/A')
            self.assertEqual(checks['triangles']['result'], 'NOT SET')
            self.assertEqual(checks['M5']['result'], 'UNMEASURED')
            self.assertEqual(checks['M12']['result'], 'PASS' if phase == 'render' else 'UNMEASURED')
            self.assertIn('allocation failed', ' '.join(result['errors']))
            self.assertTrue((out/'report.json').is_file())

    def test_non_pass_rows_survive_summary_and_markdown(self):
        states = ['PASS', 'INFO', 'PASS', 'NOT SET', 'N/A']
        model = dict(model='sample', lod=0, file='sample.glb', sha256='fixture',
                     checks=[report.row(c, state, state) for c, state in zip(report.CHECKS, states)])
        data = report.write(dict(models=[model], settings={}, errors=[]), self.root)
        self.assertEqual(data['result'], 'NOT SET')
        self.assertEqual([r['result'] for r in data['models'][0]['checks']], states)
        for state in ('INFO', 'NOT SET', 'N/A'):
            self.assertIn('| '+state+' |', (self.root/'REPORT.md').read_text())

    def test_manifest_disappears_during_failed_worker_still_writes_report(self):
        from studio_tools.common import StudioError
        p = self.root/'body.glb'; p.write_bytes(b'fixture')
        blender = self.root/'blender.exe'; blender.write_bytes(b'fixture')
        manifest = self.root/'model-qa.json'; manifest.write_text('{"living": false}')
        out = self.root/'out'
        def failed(*args, **kwargs):
            manifest.unlink()
            raise StudioError('Worker resource failure')
        with patch('studio_tools.model_qa.__main__.prelaunch_baseline', return_value=None), \
                patch('studio_tools.model_qa.__main__.run', side_effect=failed), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(p), '--budget-tris', 'not-set', '--out', str(out), '--blender', str(blender)]), 1)
        data = json.loads((out/'report.json').read_text())
        self.assertEqual(data['result'], 'UNMEASURED')
        self.assertTrue(any('manifest' in error.lower() for error in data['errors']))


if __name__ == '__main__':
    unittest.main()
