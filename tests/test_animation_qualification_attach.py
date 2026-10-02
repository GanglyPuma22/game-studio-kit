"""A passing receipt cannot reinterpret a failed or absent adapter verdict."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import qualification as q
from studio_tools.common import StudioError, digest, file_record, sha256, write_json



class FailedCheckAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.attempt = {'id': 'selected', 'model_id': 'kite', 'sha256': 'a'*64, 'targets': ['glide'],
                        'label': 'selected', 'session': 'fixture'}
        identity = {'attempt_id': 'selected', 'model_id': 'kite', 'sha256': 'a'*64, 'target': 'glide'}
        self.plan = {'attempt': identity, 'baseline': {**identity, 'attempt_id': 'baseline', 'sha256': 'b'*64},
                     'replay': {'frames': 3, 'capture_frames': [1]}, 'settings': {'resolution': [1920, 1080]}}
        self.plan_digest = digest(self.plan)
        self.record = {'plan': self.plan, 'plan_digest': self.plan_digest, 'attempt': self.attempt, 'files': []}
        write_json(self.root / 'qualification.json', self.record)
        self.catalog = {'attempts': [self.attempt], 'reviews': {'selected:glide': {'status': 'selected'}},
                        'baselines': {'kite:glide': 'selected'}, 'models': [{'id': 'kite'}], 'cursor': 10}

    def receipt(self, status):
        files = []
        for role in ('baseline', 'candidate'):
            folder = self.root / role
            folder.mkdir(exist_ok=True)
            item = self.plan['attempt' if role == 'candidate' else 'baseline']
            identity = {'role': role, 'attempt_id': item['attempt_id'], 'glb_sha256': item['sha256'], 'plan_digest': self.plan_digest}
            replay = folder / 'replay.jsonl'
            replay.write_text(''.join(json.dumps({'frame': i, 'identity': identity})+'\n' for i in range(3)))
            result = {'identity': identity, 'native_rendered': False, 'captures': [],
                      'replay': {'path': replay.relative_to(self.root).as_posix(), 'sha256': sha256(replay), 'frames': 3}}
            if status is not None:
                result['automated_checks'] = status
            write_json(folder / 'result.json', result)
            files.extend([file_record(self.root, replay), file_record(self.root, folder / 'result.json')])
        write_json(self.root / 'receipt.json', {'kind': 'animation-qualification-run', 'plan_digest': self.plan_digest,
                   'attempt_id': 'selected', 'glb_sha256': 'a'*64, 'files': files, 'phase': 'cpu',
                   'automated_checks': 'passed', 'performance_qualification': 'unverified', 'evidence_complete': True})

    def api(self, url, route, body=None, token=None):
        if route == '/api/catalog': return copy.deepcopy(self.catalog)
        if route == '/api/session': return {'token': 'fixture'}
        if route == '/api/register': return {'existing': True, 'attempt': self.attempt}
        return {'events': []}

    def test_attach_refuses_failed_or_absent_adapter_verdict_before_api(self):
        for status in ('failed', None):
            with self.subTest(status=status):
                self.receipt(status)
                with patch.object(q, 'request', side_effect=self.api) as api:
                    with self.assertRaisesRegex(StudioError, 'adapter checks'):
                        q.attach(self.root, 'http://fixture', 'receipt.json', 'kit-fixture')
                    api.assert_not_called()

    def test_attach_preserves_complete_passing_adapter_evidence(self):
        self.receipt('passed')
        with patch.object(q, 'request', side_effect=self.api):
            self.assertTrue(q.attach(self.root, 'http://fixture', 'receipt.json', 'kit-fixture')['ok'])

    def test_performance_pass_requires_passed_adapters_even_when_aggregate_failed(self):
        for aggregate in ('failed', None):
            for status in ('failed', None):
                with self.subTest(aggregate=aggregate, adapter=status):
                    self.receipt(status)
                    path = self.root / 'receipt.json'
                    receipt = json.loads(path.read_bytes())
                    receipt['automated_checks'] = aggregate
                    receipt['performance_qualification'] = 'passed'
                    write_json(path, receipt)
                    with patch.object(q, 'request') as api:
                        with self.assertRaisesRegex(StudioError, 'adapter checks'):
                            q.attach(self.root, 'http://fixture', 'receipt.json', 'kit-fixture')
                        api.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
