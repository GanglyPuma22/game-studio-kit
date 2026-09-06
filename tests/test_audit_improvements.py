"""Original offline regressions for the independent production audit boundaries."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools.common import StudioError, digest, file_record, read_json
from studio_tools.config import load
from studio_tools.evidence import new_candidate, inventory, canonical_inventory
from studio_tools.records import validate
from studio_tools.adapters import audio, blender


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'scene.gd').write_text('original scene')
        (self.root / 'Z.txt').write_text('case-sensitive order')
        (self.root / 'a.txt').write_text('lowercase')
        (self.root / 'artifacts').mkdir()

    def candidate(self):
        return new_candidate(self.root, 'candidate', '4.5.1', 'test')

    def evidence(self, candidate, method='native_capture_review'):
        p = self.root / 'artifacts/review.txt'
        p.write_text('Original review fixture, no perceptual claim')
        return {**file_record(self.root, p), 'content_digest': candidate['content_digest'],
                'method': method, 'observer': 'offline fixture'}

    def test_legacy_host_order_validates_without_rewriting_digest(self):
        c = self.candidate()
        c.pop('inventory_version', None)
        c['content_files'].reverse()
        c['content_digest'] = digest(c['content_files'])
        original = copy.deepcopy(c)
        self.assertTrue(validate(c, self.root)['ok'])
        self.assertEqual(c, original)

    def test_new_inventory_declares_canonical_version_and_order(self):
        c = self.candidate()
        self.assertEqual(c['inventory_version'], 2)
        self.assertEqual([f['path'] for f in c['content_files']], ['Z.txt', 'a.txt', 'scene.gd'])
        c['content_files'].reverse()
        c['content_digest'] = digest(c['content_files'])
        with self.assertRaisesRegex(StudioError, 'canonical'):
            validate(c, self.root)

    def test_case_collisions_rejected_in_portable_inventory(self):
        for names in [('A.txt', 'a.txt'), ('Dir/one.txt', 'dir/two.txt')]:
            with self.subTest(names=names), self.assertRaisesRegex(StudioError, '[Cc]ase'):
                canonical_inventory([{'path': name, 'sha256': '0'*64} for name in names])

    @unittest.skipIf(os.name == 'nt', 'Legacy reserved/case-distinct files require their original POSIX host')
    def test_legacy_safe_host_paths_keep_original_bytes_and_digest(self):
        c = self.candidate()
        c.pop('inventory_version')
        for name in ('NUL.txt', 'A.txt'):
            (self.root / name).write_text('legacy ' + name)
        c['content_files'] = [file_record(self.root, p) for p in sorted(self.root.iterdir()) if p.is_file()]
        c['content_digest'] = digest(c['content_files'])
        c['workflow_files'] = [{'path': 'NUL.txt', 'sha256': '0'*64}, {'path': 'a.txt', 'sha256': '1'*64}, {'path': 'A.txt', 'sha256': '2'*64}]
        c['workflow_digest'] = digest(c['workflow_files'])
        original = copy.deepcopy(c)
        self.assertTrue(validate(c, self.root)['ok'])
        self.assertEqual(c, original)

    def test_legacy_workflow_host_names_and_safety_rules(self):
        c = self.candidate()
        c.pop('inventory_version')
        c['workflow_files'] = [{'path': p, 'sha256': '0'*64} for p in ('NUL.txt', 'A.txt', 'a.txt')]
        c['workflow_digest'] = digest(c['workflow_files'])
        self.assertTrue(validate(c, self.root)['ok'])
        for field in ('content_files', 'workflow_files'):
            for path in ('../escape', '/absolute', 'C:/file', 'a\\b', 'folder//file', 'folder/./file'):
                bad = copy.deepcopy(c)
                bad[field] = [{'path': path, 'sha256': '0'*64}]
                bad[field.replace('_files', '_digest')] = digest(bad[field])
                with self.subTest(field=field, path=path), self.assertRaises(StudioError):
                    validate(bad, self.root)
            bad = copy.deepcopy(c)
            bad[field].append(bad[field][0])
            bad[field.replace('_files', '_digest')] = digest(bad[field])
            with self.subTest(field=field, duplicate=True), self.assertRaisesRegex(StudioError, 'Duplicate'):
                validate(bad, self.root)

    def test_all_evidence_statuses_and_nested_attachments_verify(self):
        for status in ['not_run', 'unverified', 'not_applicable', 'fail', 'pass']:
            with self.subTest(status=status):
                c = self.candidate()
                e = self.evidence(c)
                p = self.root / 'artifacts/attached.txt'
                p.write_text('original')
                e['attachments'] = [file_record(self.root, p)]
                c['verdicts']['visual'] = dict(status=status, reason='fixture', evidence=[e])
                p.write_text('changed')
                with self.assertRaisesRegex(StudioError, 'Hash mismatch'):
                    validate(c, self.root)
                e.pop('attachments')
                e['sha256'] = '0' * 64
                with self.assertRaisesRegex(StudioError, 'Hash mismatch'):
                    validate(c, self.root)

    def test_capture_review_alone_cannot_pass_audio(self):
        c = self.candidate()
        c['verdicts']['audio'] = dict(status='pass', evidence=[self.evidence(c)])
        with self.assertRaisesRegex(StudioError, '[Ll]istening'):
            validate(c, self.root)
        e = c['verdicts']['audio']['evidence'][0]
        e['listening'] = dict(performed=True, playback_route='offline fixture route', interval_seconds=[0, 4])
        self.assertTrue(validate(c, self.root)['ok'])
        e['listening']['interval_seconds'] = [4, 0]
        with self.assertRaises(StudioError):
            validate(c, self.root)

    def test_unique_archived_capture_identity_and_hash(self):
        from studio_tools.evidence import archive_capture
        c = self.candidate()
        source = self.root / 'artifacts/raw.txt'
        source.write_text('capture fixture')
        first = archive_capture(self.root, source, c, 'arrival')
        second = archive_capture(self.root, source, c, 'arrival')
        self.assertNotEqual(first['capture_id'], second['capture_id'])
        self.assertNotEqual(first['path'], second['path'])
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertEqual(first['content_digest'], c['content_digest'])
        source.write_text('later capture')
        self.assertEqual((self.root / first['path']).read_text(), 'capture fixture')

    def test_imported_loop_uses_decoded_frames_not_qoa_bytes(self):
        from studio_tools.adapters.audio import imported_loop
        for encoding, byte_count in [('pcm16', 2304000), ('qoa', 465328)]:
            info = imported_loop(dict(format=encoding, data_bytes=byte_count,
                                     sample_rate=24000, channels=2,
                                     duration_seconds=24.0), 0, 24)
            self.assertEqual(info['loop_end_frame'], 576000)
            self.assertEqual(info['loop_begin_frame'], 0)
            self.assertEqual(info['listening'], 'not_run')
        for bad in [dict(sample_rate=0, duration_seconds=24),
                    dict(sample_rate=24000, data_bytes=465328),
                    dict(sample_rate=24000, duration_seconds=float('nan'))]:
            with self.assertRaises(StudioError):
                imported_loop(bad)
        with self.assertRaises(StudioError):
            imported_loop(dict(sample_rate=24000, duration_seconds=24), 0, 25)

    def test_endpoint_fades_do_not_claim_crossfade_or_listening(self):
        src = self.root / 'artifacts/source.wav'
        audio.synthesize(src, duration=0.1)
        result = audio.prepare(src, self.root / 'artifacts/runtime.wav', loop=True)
        self.assertEqual(result['boundary_treatment'], 'endpoint_fades')
        self.assertFalse(result['crossfade_applied'])
        self.assertEqual(result['listening'], 'not_run')

    def test_blender_export_rejects_source_alias_before_launch(self):
        source = self.root / 'edited.blend'
        source.write_bytes(b'original edited source')
        with patch('studio_tools.adapters.blender.run') as run:
            with self.assertRaises(StudioError):
                blender.export(load(), source, 'RuntimeAsset', source)
            run.assert_not_called()
        self.assertEqual(source.read_bytes(), b'original edited source')

    def test_export_routes_edited_source_without_generator_and_preserves_bytes(self):
        import sys
        source = self.root / 'edited.blend'
        source.write_bytes(b'hand edited source')
        output = self.root / 'assets/edited.glb'
        cfg = load(overrides={'executables': {'blender': sys.executable}})
        def fake_run(cmd, **kwargs):
            self.assertIn(str(source.resolve()), cmd)
            self.assertTrue(any(str(x).endswith('export.py') for x in cmd))
            self.assertFalse(any(str(x).endswith('fixture.py') for x in cmd))
            output.parent.mkdir(exist_ok=True)
            output.write_bytes(b'export fixture')
        with patch('studio_tools.adapters.blender.run', side_effect=fake_run), \
             patch('studio_tools.adapters.blender.glb_info', return_value={}), \
             patch('studio_tools.adapters.blender.inspect', return_value={}):
            result = blender.export(cfg, source, 'RuntimeAsset', output)
        self.assertEqual(source.read_bytes(), b'hand edited source')
        self.assertEqual(result['source']['sha256'], file_record(self.root, source)['sha256'])

    def test_legacy_content_map_ignores_optional_entry_metadata(self):
        c = self.candidate()
        c.pop('inventory_version')
        for item in c['content_files']:
            item['bytes'] = (self.root/item['path']).stat().st_size
        c['content_digest'] = digest(c['content_files'])
        self.assertTrue(validate(c, self.root)['ok'])

    def test_workflow_paths_reject_nonportable_absolute_names(self):
        for path in ['/absolute/file', 'C:/file', '../file', 'folder//file', 'folder/./file']:
            c = self.candidate()
            c['workflow_files'] = [{'path':path, 'sha256':'0'*64}]
            c['workflow_digest'] = digest(c['workflow_files'])
            with self.subTest(path=path), self.assertRaises(StudioError):
                validate(c, self.root)

    def test_capture_payload_cannot_alias_receipt(self):
        from studio_tools.evidence import archive_capture
        c = self.candidate()
        source = self.root/'artifacts/original.json'
        source.write_text('{"original":true}')
        result = archive_capture(self.root, source, c, 'capture')
        self.assertEqual(file_record(self.root, self.root/result['path'])['sha256'], result['sha256'])
        self.assertEqual((self.root/result['path']).read_text(), source.read_text())

    def test_capture_rejects_escaping_artifacts_before_writing(self):
        from studio_tools.evidence import archive_capture
        c = self.candidate()
        with tempfile.TemporaryDirectory() as external:
            (self.root/'artifacts').rmdir()
            try:
                (self.root/'artifacts').symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest('Host cannot create directory symlinks')
            with self.assertRaises(StudioError):
                archive_capture(self.root, self.root/'scene.gd', c, 'capture')
            self.assertEqual(list(Path(external).iterdir()), [])

    def test_portable_inventory_rejects_windows_reserved_components(self):
        from studio_tools.evidence import canonical_inventory
        for name in ['NUL.txt', 'foo.', 'foo ', 'dir/a?b.txt', 'CON', 'COM1.log', 'a<b']:
            with self.subTest(name=name), self.assertRaises(StudioError):
                canonical_inventory([{'path':name, 'sha256':'0'*64}])

    def test_blender_export_rejects_hardlink_source_alias(self):
        import sys
        config = load(overrides={"executables": {"blender": sys.executable}})
        source = self.root/'edited.blend'
        source.write_bytes(b'edited source')
        target = self.root/'runtime.glb'
        try:
            os.link(source, target)
        except OSError:
            self.skipTest('Host does not support hard links')
        with patch('studio_tools.adapters.blender.run') as run:
            with self.assertRaises(StudioError):
                blender.export(config, source, 'RuntimeAsset', target)
            run.assert_not_called()
        self.assertEqual(source.read_bytes(), b'edited source')
