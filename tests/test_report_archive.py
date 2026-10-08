import json
from pathlib import Path
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
            'result_files': [{'path': 'report.json', 'present': True,
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
        verify_archive(self.archive)
        self.assertFalse(json.loads(self.exit.read_text())['ok'])

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
