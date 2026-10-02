"""A passing receipt cannot reinterpret a failed or absent adapter verdict."""
import copy
import json
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

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

    def native_receipt(self):
        self.plan.update({'id': 'fixture', 'script': 'fixture.gd', 'engine': {'sha256': 'e'*64},
                          'thresholds': {'frame_p95_ms': 16.67, 'gpu_p95_ms': 12,
                                         'controller_cpu_p95_ms': 1, 'max_relative_frame_cost': 1.2}})
        self.plan_digest = digest(self.plan)
        self.record.update({'plan_digest': self.plan_digest})
        write_json(self.root / 'qualification.json', self.record)
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1920, 1080, 8, 2, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress((b'\x00' + b'\x00'*5760)*1080)) + chunk(b'IEND', b'')
        files, observations, runs = [], [], []
        kit = {'version': 'fixture'}
        for role in ('baseline', 'candidate'):
            label = 'native-' + role
            folder = self.root / 'artifacts/qualification' / label
            folder.mkdir(parents=True, exist_ok=True)
            item = self.plan['attempt' if role == 'candidate' else 'baseline']
            identity = {'role': role, 'attempt_id': item['attempt_id'], 'glb_sha256': item['sha256'],
                        'plan_digest': self.plan_digest}
            replay = folder / 'replay.jsonl'
            replay.write_text(''.join(json.dumps({'frame': i, 'identity': identity})+'\n' for i in range(3)))
            picture = folder / 'frame-0001.png'
            picture.write_bytes(png)
            result = {'identity': identity, 'native_rendered': True, 'automated_checks': 'passed',
                      'timing': {'frame_ms': [10]*120, 'controller_cpu_ms': [.1]*120, 'viewport_gpu_ms': [3]*120},
                      'replay': {**file_record(self.root, replay), 'frames': 3},
                      'captures': [{**file_record(self.root, picture), 'frame': 1, 'dimensions': [1920, 1080]}]}
            write_json(folder / 'result.json', result)
            result_pin = file_record(self.root, folder / 'result.json')
            launched = {'schema_version': 1, 'kind': 'launch-exit', 'kit': kit, 'label': label,
                        'scope': 'fixture', 'ok': True, 'verdict': 'completed', 'status': 'completed',
                        'returncode': 0, 'timed_out': False, 'cleanup': None,
                        'result_files': [{**result_pin, 'present': True, 'stale': False, 'unreadable': False, 'escaped': False}]}
            lifecycle = self.root / 'artifacts/launches' / label
            write_json(lifecycle / 'exit.json', launched)
            owned = {'kind': 'owned-launch', 'kit': kit, 'label': label, 'scope': 'fixture', 'mode': 'native',
                     'script': 'res://fixture.gd', 'project': str(self.root),
                     'engine': {'sha256': 'e'*64, 'sha256_after_exit': 'e'*64},
                     'expected_results': [result_pin['path']]}
            write_json(lifecycle / 'owned-launch.json', owned)
            bench = {'schema_version': 1, 'kind': 'cleanroom-bench', 'kit': kit, 'label': label,
                     'scope': 'fixture', 'scope_check': 'match', 'ok': True, 'attributable': True,
                     'performance_class': 'clean_qualification', 'reasons': [],
                     'capture': {'status': 'completed', 'returncode': 0, 'cleanup': None, 'failure': None,
                                 'verdict': launched}}
            bench_path = self.root / 'artifacts/bench' / label / 'cleanroom.json'
            write_json(bench_path, bench)
            observations.append(result)
            runs.append({'role': role, 'launch': launched,
                         'cleanroom': {**bench, 'record': str(bench_path), 'bench_dir': str(bench_path.parent)}})
            files.extend(file_record(self.root, p) for p in (replay, picture, folder / 'result.json',
                                                           lifecycle / 'exit.json', lifecycle / 'owned-launch.json', bench_path))
        receipt = {'kind': 'animation-qualification-run', 'kit': kit, 'plan_digest': self.plan_digest,
                   'attempt_id': 'selected', 'glb_sha256': 'a'*64, 'files': files, 'phase': 'native',
                   'automated_checks': 'passed', 'performance_qualification': 'passed', 'evidence_complete': True,
                   'observations': observations, 'runs': runs, 'performance': q.compare_timing(observations, self.plan['thresholds'])}
        write_json(self.root / 'receipt.json', receipt)
        return receipt

    def test_cpu_adapter_pair_cannot_publish_edited_performance_pass(self):
        self.receipt('passed')
        path = self.root / 'receipt.json'
        receipt = json.loads(path.read_bytes())
        receipt['performance_qualification'] = 'passed'
        write_json(path, receipt)
        with patch.object(q, 'request') as api:
            with self.assertRaisesRegex(StudioError, 'passing native qualification'):
                q.attach(self.root, 'http://fixture', 'receipt.json', 'fixture')
            api.assert_not_called()

    def test_passing_native_timing_and_attributable_pair_attach(self):
        self.native_receipt()
        with patch.object(q, 'request', side_effect=self.api):
            self.assertTrue(q.attach(self.root, 'http://fixture', 'receipt.json', 'fixture')['ok'])

    def test_native_pass_requires_actual_timing_and_pinned_cleanroom_pair(self):
        for case in ('stored_timings', 'missing_timings', 'slow_timings', 'missing_run', 'duplicate_role',
                     'missing_bench_hash', 'missing_bench', 'edited_bench', 'not_attributable',
                     'wrong_scope', 'wrong_label', 'foreign_capture', 'wrong_engine', 'wrong_result', 'diagnostic'):
            with self.subTest(case=case):
                receipt = self.native_receipt()
                run = receipt['runs'][1]
                bench_path = self.root / 'artifacts/bench/native-candidate/cleanroom.json'
                if case == 'stored_timings': receipt['performance']['candidate']['frame_ms_p95'] = 1
                elif case in ('missing_timings', 'slow_timings'):
                    result_path = self.root / 'artifacts/qualification/native-candidate/result.json'
                    observed = receipt['observations'][1]
                    observed['timing']['frame_ms'] = [] if case == 'missing_timings' else [20]*120
                    write_json(result_path, observed)
                elif case == 'missing_run': receipt['runs'].pop()
                elif case == 'duplicate_role': run['role'] = 'baseline'
                elif case == 'missing_bench_hash':
                    receipt['files'] = [p for p in receipt['files'] if p['path'] != bench_path.relative_to(self.root).as_posix()]
                elif case == 'missing_bench': bench_path.unlink()
                elif case == 'edited_bench': run['cleanroom']['attributable'] = False
                elif case == 'diagnostic': receipt['reservation'] = {'bounded_diagnostic_authorization': {'instruction': 'diagnostic'}}
                elif case == 'wrong_engine':
                    owned_path = self.root / 'artifacts/launches/native-candidate/owned-launch.json'
                    owned = json.loads(owned_path.read_bytes())
                    owned['engine']['sha256'] = 'f'*64
                    write_json(owned_path, owned)
                else:
                    bench = {k: v for k, v in run['cleanroom'].items() if k not in ('record', 'bench_dir')}
                    if case == 'not_attributable': bench['attributable'] = False
                    elif case == 'wrong_scope': bench['scope'] = 'foreign'
                    elif case == 'wrong_label': bench['label'] = 'foreign'
                    elif case == 'foreign_capture': bench['capture']['verdict'] = {'ok': True}
                    elif case == 'wrong_result':
                        run['launch']['result_files'][0]['sha256'] = 'f'*64
                        write_json(self.root / 'artifacts/launches/native-candidate/exit.json', run['launch'])
                    run['cleanroom'].update(bench)
                    write_json(bench_path, bench)
                # Model an edited receipt with internally updated file hashes:
                # aggregate pass still must be independently established.
                receipt['files'] = [file_record(self.root, self.root / p['path']) if (self.root / p['path']).is_file() else p
                                    for p in receipt['files']]
                if case == 'missing_bench':
                    receipt['files'] = [p for p in receipt['files'] if p['path'] != bench_path.relative_to(self.root).as_posix()]
                write_json(self.root / 'receipt.json', receipt)
                with patch.object(q, 'request') as api:
                    with self.assertRaises(StudioError):
                        q.attach(self.root, 'http://fixture', 'receipt.json', 'fixture')
                    api.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
