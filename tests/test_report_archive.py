import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from studio_tools.report_archive import archive_report, restore_report, verify_archive, linked_archive, digest


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'report.json'
        self.archive = self.root / 'report.json.gz'
        # Preserve unusual spelling, duplicate keys, UTF-8 and line endings too.
        self.data = b'{\r\n\t"x": 1.000000000000001, "x": -0.0, "text": "\xc3\xa9"\r\n}\n'
        self.source.write_bytes(self.data)

    def test_exact_roundtrip_and_original_preserved(self):
        archive_report(self.source, self.archive)
        output = self.root / 'restored.json'
        restore_report(self.archive, output)
        self.assertEqual(output.read_bytes(), self.data)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_refuses_overwrite(self):
        archive_report(self.source, self.archive)
        with self.assertRaises(FileExistsError):
            archive_report(self.source, self.archive)
        with self.assertRaises(FileExistsError):
            restore_report(self.archive, self.source)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_corrupt_archive_rejected_before_restore(self):
        archive_report(self.source, self.archive)
        self.archive.write_bytes(self.archive.read_bytes()[:-6])
        output = self.root / 'restored.json'
        with self.assertRaises(ValueError):
            restore_report(self.archive, output)
        self.assertFalse(output.exists())

    def test_incorrect_expansion_size_rejected(self):
        archive_report(self.source, self.archive)
        manifest = Path(str(self.archive) + '.manifest.json')
        record = json.loads(manifest.read_text())
        record['source_bytes'] -= 1
        manifest.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            verify_archive(self.archive)

    def test_failed_source_verification_removes_only_new_archive(self):
        with patch('studio_tools.report_archive.digest', return_value=(0, 'mismatch')):
            with self.assertRaises(ValueError):
                archive_report(self.source, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_empty_report_bytes_roundtrip(self):
        self.source.write_bytes(b'')
        archive_report(self.source, self.archive)
        output = self.root / 'empty.json'
        restore_report(self.archive, output)
        self.assertEqual(output.read_bytes(), b'')

    def receipts(self):
        self.exit = self.root / 'exit.json'
        self.launch = self.root / 'owned-launch.json'
        self.exit.write_text(json.dumps({'kind': 'launch-exit', 'label': 'run-1',
            'finished_utc': '2026-10-08T01:00:00Z', 'status': 'completed',
            'survivors': {'status': 'ok', 'stopped': True, 'unstopped_pids': [], 'unverified': []},
            'result_files': [{'path': 'report.json', 'present': True, 'stale': False,
                              'sha256': digest(self.source)[1]}]}))
        self.launch.write_text(json.dumps({'kind': 'owned-launch', 'label': 'run-1',
                                          'project': str(self.root)}))

    def test_link_survives_relocation_and_originals_unavailable(self):
        self.receipts()
        linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        self.source.unlink()
        self.exit.unlink()
        self.launch.unlink()
        verify_archive(self.archive)
        restore_report(self.archive, self.source)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_changed_result_rejected(self):
        self.receipts()
        self.source.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        self.assertFalse(self.archive.exists())

    def test_toolkit_output_rejected(self):
        from studio_tools.common import PACKAGE, StudioError
        with self.assertRaises(StudioError):
            archive_report(self.source, PACKAGE / 'must-not-write.json.gz')

    def test_running_receipt_rejected(self):
        self.receipts()
        record = json.loads(self.exit.read_text())
        record['status'] = 'running'
        self.exit.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            linked_archive(self.root, self.exit, self.source, self.archive, completed=True)

    def test_preserved_receipt_tampering_rejected(self):
        self.receipts()
        linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        manifest = Path(str(self.archive) + '.manifest.json')
        record = json.loads(manifest.read_text())
        record['provenance']['exit_receipt']['bytes_base64'] = 'e30='
        manifest.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            verify_archive(self.archive)

    def test_unverified_survivors_rejected(self):
        self.receipts()
        record = json.loads(self.exit.read_text())
        record['survivors']['unverified'] = [123]
        self.exit.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            linked_archive(self.root, self.exit, self.source, self.archive, completed=True)

    def test_receipt_pair_mismatch_rejected(self):
        self.receipts()
        record = json.loads(self.launch.read_text())
        record['label'] = 'another-run'
        self.launch.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            linked_archive(self.root, self.exit, self.source, self.archive, completed=True)

    def test_failed_experiment_evidence_can_be_preserved(self):
        self.receipts()
        record = json.loads(self.exit.read_text())
        record.update(status='failed', verdict='engine_errors', ok=False)
        self.exit.write_text(json.dumps(record))
        linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        verified = verify_archive(self.archive)
        self.assertFalse(json.loads(self.exit.read_text())['ok'])
        saved = json.loads(base64.b64decode(verified['provenance']['exit_receipt']['bytes_base64']))
        self.assertEqual(saved['status'], 'failed')
        self.assertEqual(saved['verdict'], 'engine_errors')
        self.assertIs(saved['ok'], False)

    def manifest(self):
        return Path(str(self.archive) + '.manifest.json')

    def rewrite_preserved(self, record, key, changes):
        embedded = json.loads(base64.b64decode(record['provenance'][key]['bytes_base64']))
        embedded.update(changes)
        raw = json.dumps(embedded).encode()
        record['provenance'][key]['bytes_base64'] = base64.b64encode(raw).decode()
        record['provenance'][key]['sha256'] = hashlib.sha256(raw).hexdigest()

    def test_rehashed_receipts_must_still_establish_terminal_pair(self):
        self.receipts()
        linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        original = self.manifest().read_text()
        for key, changes in (
            ('exit_receipt', {'status': 'running'}),
            ('exit_receipt', {'finished_utc': None}),
            ('exit_receipt', {'kind': 'wrong'}),
            ('owned_launch', {'kind': 'wrong'}),
            ('owned_launch', {'label': 'wrong'}),
            ('owned_launch', {'project': str(self.root / 'wrong-project')}),
            ('exit_receipt', {'survivors': {'status': 'failed', 'stopped': False,
                                          'unstopped_pids': [123], 'unverified': []}}),
            ('exit_receipt', {'survivors': {'status': 'ok', 'stopped': True,
                                          'unstopped_pids': [], 'unverified': [123]}}),
        ):
            for legacy in (False, True):
                with self.subTest(key=key, changes=changes, legacy=legacy):
                    record = json.loads(original)
                    if legacy:
                        del record['provenance']['expected_project']
                    self.rewrite_preserved(record, key, changes)
                    self.manifest().write_text(json.dumps(record))
                    with self.assertRaises(ValueError):
                        verify_archive(self.archive)

    def test_missing_or_false_freshness_is_not_inferred(self):
        self.receipts()
        original = self.exit.read_text()
        for field, value in (('stale', None), ('stale', True), ('stale', 0),
                             ('present', 1), ('present', False)):
            with self.subTest(field=field, value=value):
                record = json.loads(original)
                if value is None:
                    del record['result_files'][0][field]
                else:
                    record['result_files'][0][field] = value
                self.exit.write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
                self.assertFalse(self.archive.exists())

    def test_missing_preserved_freshness_rejected_after_rehash(self):
        self.receipts()
        linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        record = json.loads(self.manifest().read_text())
        embedded = json.loads(base64.b64decode(record['provenance']['exit_receipt']['bytes_base64']))
        del embedded['result_files'][0]['stale']
        self.rewrite_preserved(record, 'exit_receipt', {'result_files': embedded['result_files']})
        self.manifest().write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            verify_archive(self.archive)

    def test_expected_project_must_match_recorded_source(self):
        self.receipts()
        linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        record = json.loads(self.manifest().read_text())
        record['provenance']['expected_project'] = str(self.root / 'wrong-project')
        self.manifest().write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            verify_archive(self.archive)

    def test_legacy_project_derivation_is_lexical_on_other_hosts(self):
        self.receipts()
        linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        original = self.manifest().read_text()
        for project, source in (
            ('C:\\Original Game', 'c:/original game/report.json'),
            ('/original/game', '/original/game/report.json'),
            ('\\\\host\\share\\Original Game', '//host/share/Original Game/report.json'),
        ):
            with self.subTest(project=project):
                record = json.loads(original)
                del record['provenance']['expected_project']
                record['source_path'] = source
                self.rewrite_preserved(record, 'owned_launch', {'project': project})
                self.manifest().write_text(json.dumps(record))
                verify_archive(self.archive)
                record['source_path'] = source.replace('report.json', 'other.json')
                self.manifest().write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    verify_archive(self.archive)

    def test_archive_and_restore_use_resolved_guard_destination(self):
        from studio_tools import report_archive
        canonical = self.root / 'canonical'
        canonical.mkdir()
        true_guard = report_archive.outside_package
        def resolve_redirect(path):
            true_guard(path)
            return canonical / Path(path).name
        with patch.object(report_archive, 'outside_package', side_effect=resolve_redirect):
            archive_report(self.source, self.archive)
        actual_archive = canonical / self.archive.name
        self.assertTrue(actual_archive.exists())
        self.assertFalse(self.archive.exists())
        requested_output = self.root / 'restored.json'
        with patch.object(report_archive, 'outside_package', side_effect=resolve_redirect):
            restore_report(actual_archive, requested_output)
        self.assertFalse(requested_output.exists())
        self.assertEqual((canonical / requested_output.name).read_bytes(), self.data)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows junction regression')
    def test_windows_parent_junction_swap_cannot_redirect_archive_or_restore(self):
        from studio_tools import common, report_archive
        true_guard = common.outside_package
        for operation in ('archive', 'restore'):
            with self.subTest(operation=operation):
                base = self.root / operation
                base.mkdir()
                safe, kit, link = base / 'safe', base / 'synthetic-kit', base / 'destination'
                safe.mkdir()
                kit.mkdir()
                def junction(target):
                    command = ("New-Item -ItemType Junction -Path '" + str(link).replace("'", "''")
                               + "' -Target '" + str(target).replace("'", "''") + "' | Out-Null")
                    completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                                                '-Command', command], capture_output=True, timeout=15)
                    if completed.returncode:
                        self.skipTest('This host cannot create synthetic junctions')
                junction(safe)
                swapped = False
                def redirect_after_guard(path):
                    nonlocal swapped
                    resolved = true_guard(path)
                    if not swapped:
                        link.rename(base / 'preserved-original-junction')
                        junction(kit)
                        swapped = True
                    return resolved
                if operation == 'restore':
                    archive_report(self.source, self.archive)
                with patch.object(common, 'PACKAGE', kit), patch.object(report_archive, 'outside_package',
                                                                        side_effect=redirect_after_guard):
                    if operation == 'archive':
                        archive_report(self.source, link / 'output.json.gz')
                        self.assertTrue((safe / 'output.json.gz').exists())
                        self.assertTrue((safe / 'output.json.gz.manifest.json').exists())
                    else:
                        restore_report(self.archive, link / 'output.json')
                        self.assertEqual((safe / 'output.json').read_bytes(), self.data)
                self.assertEqual(list(kit.iterdir()), [])
                self.assertEqual(self.source.read_bytes(), self.data)

    def test_source_changed_after_precheck_leaves_no_archive(self):
        self.receipts()
        from studio_tools import report_archive
        original = report_archive.archive_report
        def changed(source, archive, **kwargs):
            source.write_bytes(b'{"changed":true}')
            return original(source, archive, **kwargs)
        with patch.object(report_archive, 'archive_report', side_effect=changed):
            with self.assertRaises(ValueError):
                linked_archive(self.root, self.exit, self.source, self.archive, completed=True)
        self.assertFalse(self.archive.exists())

    def test_cli_roundtrip(self):
        from studio_tools.cli import main
        self.receipts()
        with patch('sys.stdout'):
            self.assertEqual(main(['evidence', 'archive', '--project', str(self.root),
                '--receipt', str(self.exit), '--source', str(self.source),
                '--output', str(self.archive), '--completed']), 0)
            self.assertEqual(main(['evidence', 'archive-verify', '--archive', str(self.archive)]), 0)
            restored = self.root / 'restored.json'
            self.assertEqual(main(['evidence', 'restore', '--archive', str(self.archive),
                                   '--output', str(restored)]), 0)
        self.assertEqual(restored.read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
