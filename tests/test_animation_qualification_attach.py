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
from studio_tools.cleanroom import compare as compare_cleanroom
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
        engine_path = self.root / 'godot.exe'
        pe = bytearray(68)
        pe[:2] = b'MZ'
        pe[60:64] = (64).to_bytes(4, 'little')
        pe[64:] = b'PE\x00\x00'
        engine_path.write_bytes(pe)
        engine_hash = sha256(engine_path)
        self.plan.update({'id': 'fixture', 'script': 'fixture.gd', 'engine': {'sha256': engine_hash},
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
        preflight_path = self.root / 'host-preflight.json'
        reservation_path = self.root / 'reservation.json'
        write_json(preflight_path, {'ready': True, 'window': {'start_utc': '2026-10-02T10:00:00Z',
                                                           'end_utc': '2026-10-02T11:00:00Z'}})
        reservation = {'plan_digest': self.plan_digest, 'coordinator': 'fixture',
                       'start_utc': '2026-10-02T10:00:00Z', 'end_utc': '2026-10-02T11:00:00Z',
                       'host_preflight': str(preflight_path), 'host_preflight_sha256': sha256(preflight_path),
                       'competing_heavy_jobs_verified': True}
        write_json(reservation_path, reservation)
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
            survivors = {'status': 'ok', 'pids': [], 'stopped': True, 'unverified': [], 'unstopped_pids': []}
            launched = {'schema_version': 1, 'kind': 'launch-exit', 'kit': kit, 'label': label,
                        'scope': 'fixture', 'ok': True, 'verdict': 'completed', 'status': 'completed',
                        'returncode': 0, 'timed_out': False, 'cleanup': None, 'elapsed_seconds': 10,
                        'finished_utc': '2026-10-02T10:01:20Z', 'survivors': survivors,
                        'result_files': [{**result_pin, 'present': True, 'stale': False, 'unreadable': False, 'escaped': False}]}
            lifecycle = self.root / 'artifacts/launches' / label
            write_json(lifecycle / 'exit.json', launched)
            owned = {'kind': 'owned-launch', 'kit': kit, 'label': label, 'scope': 'fixture', 'mode': 'native',
                     'pid': 42, 'process_record': 'process/process.json', 'survivors': survivors,
                     'started_utc': '2026-10-02T10:01:00Z', 'cutoff_utc': '2026-10-02T10:02:00Z',
                     'script': 'res://fixture.gd', 'project': str(self.root),
                     'engine': {'name': 'godot.exe', 'sha256': engine_hash, 'sha256_after_exit': engine_hash},
                     'expected_results': [result_pin['path']]}
            write_json(lifecycle / 'owned-launch.json', owned)
            process_path = lifecycle / 'process/process.json'
            write_json(process_path, {'schema_version': 1, 'pid': 42, 'status': 'completed', 'returncode': 0,
                'cleanup': None, 'elapsed_seconds': 10, 'started_utc': '2026-10-02T10:01:05Z',
                'finished_utc': '2026-10-02T10:01:15Z', 'windows_ownership': {'status': 'ok',
                    'identity': {'pid': 42, 'name': 'godot.exe', 'created_filetime': '100', 'exited_filetime': '200'}}})
            bench_folder = self.root / 'artifacts/bench' / label
            window = {'started_utc': '2026-10-02T10:00:55Z', 'finished_utc': '2026-10-02T10:01:25Z', 'elapsed_seconds': 30}
            before = {'process_status': 'ok', 'processes': [], 'gpu': {'status': 'ok', 'compute_apps': []},
                      'power_scheme': 'fixture', 'battery': {'status': 'ok', 'on_ac': True}, 'recorder': []}
            after = copy.deepcopy(before)
            during = {'sampler': {'pid': 99}, 'samples': 3, 'failed_samples': 0, 'recorders': [],
                      'newcomers': [], 'identity_unknown': []}
            for name, snapshot in (('before', before), ('after', after), ('during', during)):
                write_json(bench_folder / (name + '.json'), snapshot)
            comparison = compare_cleanroom(before, after, window, busy_cpu_seconds=1,
                                          heavy_working_set_bytes=200*1024*1024, self_pid=99, during=during)
            comparison['during']['record'] = file_record(self.root, bench_folder / 'during.json')
            bench = {'schema_version': 1, 'kind': 'cleanroom-bench', 'kit': kit, 'label': label,
                     'window': window, 'before': {'record': file_record(self.root, bench_folder / 'before.json')},
                     'after': {'record': file_record(self.root, bench_folder / 'after.json')}, **comparison,
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
                     lifecycle / 'exit.json', lifecycle / 'owned-launch.json', process_path, bench_path,
                     bench_folder / 'before.json', bench_folder / 'after.json', bench_folder / 'during.json'))
        receipt = {'kind': 'animation-qualification-run', 'kit': kit, 'plan_digest': self.plan_digest,
                   'attempt_id': 'selected', 'glb_sha256': 'a'*64, 'files': files, 'phase': 'native',
                   'automated_checks': 'passed', 'performance_qualification': 'passed', 'evidence_complete': True,
                   'observations': observations, 'runs': runs, 'performance': q.compare_timing(observations, self.plan['thresholds'])}
        receipt.update({'reservation': reservation, 'reservation_record': {'path': str(reservation_path),
                                                                          'sha256': sha256(reservation_path)},
                        'engine_record': {'path': str(engine_path), 'sha256': engine_hash}})
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

    def test_diagnostic_native_evidence_remains_publishable(self):
        receipt = self.native_receipt()
        receipt['performance_qualification'] = 'unverified-host-preflight-diagnostic'
        receipt['reservation']['bounded_diagnostic_authorization'] = {'instruction': 'diagnostic'}
        receipt.pop('reservation_record')
        receipt.pop('engine_record')
        write_json(self.root / 'receipt.json', receipt)
        with patch.object(q, 'request', side_effect=self.api):
            self.assertTrue(q.attach(self.root, 'http://fixture', 'receipt.json', 'fixture')['ok'])

    def test_performance_platform_uses_original_engine_bytes(self):
        for case in ('missing_engine_pin', 'changed_engine', 'renamed_windows_engine', 'posix_pair'):
            with self.subTest(case=case):
                receipt = self.native_receipt()
                engine_path = self.root / 'godot.exe'
                if case == 'missing_engine_pin': receipt.pop('engine_record')
                elif case == 'changed_engine': engine_path.write_bytes(b'\x7fELF' + b'\x00'*60)
                else:
                    engine_path = self.root / 'godot'
                    engine_path.write_bytes((self.root / 'godot.exe').read_bytes() if case == 'renamed_windows_engine'
                                            else b'\x7fELF' + b'\x00'*60)
                    engine_hash = sha256(engine_path)
                    self.plan['engine']['sha256'] = engine_hash
                    self.plan_digest = digest(self.plan)
                    receipt['plan_digest'] = self.plan_digest
                    self.record['plan_digest'] = self.plan_digest
                    write_json(self.root / 'qualification.json', self.record)
                    receipt['reservation']['plan_digest'] = self.plan_digest
                    write_json(self.root / 'reservation.json', receipt['reservation'])
                    receipt['reservation_record']['sha256'] = sha256(self.root / 'reservation.json')
                    receipt['engine_record'] = {'path': str(engine_path), 'sha256': engine_hash}
                    # Exercise only the lifecycle verifier; the unchanged replay
                    # retains its own original plan and is not republished.
                    for role in ('baseline', 'candidate'):
                        folder = self.root / 'artifacts/launches' / ('native-' + role)
                        owned = json.loads((folder / 'owned-launch.json').read_bytes())
                        owned['engine'] = {'name': 'godot', 'sha256': engine_hash, 'sha256_after_exit': engine_hash}
                        write_json(folder / 'owned-launch.json', owned)
                        process = json.loads((folder / 'process/process.json').read_bytes())
                        process.pop('windows_ownership')
                        write_json(folder / 'process/process.json', process)
                    receipt['files'] = [file_record(self.root, self.root / p['path']) for p in receipt['files']]
                observations = {run['role']: (receipt['observations'][index],
                    self.root / 'artifacts/qualification' / ('native-' + run['role']) / 'result.json')
                    for index, run in enumerate(receipt['runs'])}
                if case == 'posix_pair': q._performance_attachment(self.root, self.record, receipt, observations)
                else:
                    with self.assertRaises(StudioError):
                        q._performance_attachment(self.root, self.record, receipt, observations)

    def test_original_reservation_and_preflight_are_required_before_api(self):
        for case in ('missing_reservation', 'missing_pin', 'changed_reservation', 'failed_preflight',
                     'missing_preflight', 'wrong_plan', 'unverified_jobs', 'wrong_window', 'removed_diagnostic'):
            with self.subTest(case=case):
                receipt = self.native_receipt()
                reservation = receipt['reservation']
                if case == 'missing_reservation': receipt.pop('reservation')
                elif case == 'missing_pin': receipt.pop('reservation_record')
                elif case == 'changed_reservation': reservation['coordinator'] = 'changed'
                elif case == 'missing_preflight': (self.root / 'host-preflight.json').unlink()
                elif case == 'failed_preflight':
                    preflight = json.loads((self.root / 'host-preflight.json').read_bytes())
                    preflight['ready'] = False
                    write_json(self.root / 'host-preflight.json', preflight)
                    reservation['host_preflight_sha256'] = sha256(self.root / 'host-preflight.json')
                elif case == 'wrong_plan': reservation['plan_digest'] = 'f'*64
                elif case == 'unverified_jobs': reservation['competing_heavy_jobs_verified'] = False
                elif case == 'wrong_window': reservation['end_utc'] = '2026-10-02T10:01:10Z'
                elif case == 'removed_diagnostic':
                    retained = {**reservation, 'bounded_diagnostic_authorization': {'instruction': 'diagnostic'}}
                    write_json(self.root / 'reservation.json', retained)
                    receipt['reservation_record']['sha256'] = sha256(self.root / 'reservation.json')
                if case not in ('missing_reservation', 'missing_pin', 'changed_reservation', 'removed_diagnostic'):
                    write_json(self.root / 'reservation.json', reservation)
                    receipt['reservation_record']['sha256'] = sha256(self.root / 'reservation.json')
                write_json(self.root / 'receipt.json', receipt)
                with patch.object(q, 'request') as api:
                    with self.assertRaises(StudioError):
                        q.attach(self.root, 'http://fixture', 'receipt.json', 'fixture')
                    api.assert_not_called()

    def test_clean_summary_cannot_override_retained_snapshot_contamination(self):
        for case in ('busy_cpu', 'transient_recorder', 'missing_snapshot', 'missing_snapshot_hash', 'missing_sampler'):
            with self.subTest(case=case):
                receipt = self.native_receipt()
                bench_dir = self.root / 'artifacts/bench/native-candidate'
                bench = receipt['runs'][1]['cleanroom']
                if case == 'busy_cpu':
                    for name, cpu in (('before', 0), ('after', 20)):
                        path = bench_dir / (name + '.json')
                        snapshot = json.loads(path.read_bytes())
                        snapshot['processes'] = [{'pid': 100, 'name': 'heavy.exe', 'cpu_seconds': cpu,
                                                  'working_set_bytes': 10, 'created_filetime': '50'}]
                        write_json(path, snapshot)
                        bench[name]['record'] = file_record(self.root, path)
                elif case in ('transient_recorder', 'missing_sampler'):
                    path = bench_dir / 'during.json'
                    snapshot = json.loads(path.read_bytes())
                    if case == 'transient_recorder': snapshot['recorders'] = [{'pid': 100, 'name': 'ffmpeg.exe'}]
                    else: snapshot.pop('sampler')
                    write_json(path, snapshot)
                    bench['during']['record'] = file_record(self.root, path)
                elif case == 'missing_snapshot': (bench_dir / 'before.json').unlink()
                elif case == 'missing_snapshot_hash':
                    receipt['files'] = [p for p in receipt['files'] if not p['path'].endswith('native-candidate/before.json')]
                # Preserve the edited all-clear summaries and their refreshed pins.
                write_json(bench_dir / 'cleanroom.json', {k: v for k, v in bench.items() if k not in ('record', 'bench_dir')})
                receipt['files'] = [file_record(self.root, self.root / p['path']) for p in receipt['files']
                                    if (self.root / p['path']).is_file()]
                write_json(self.root / 'receipt.json', receipt)
                with patch.object(q, 'request') as api:
                    with self.assertRaises(StudioError):
                        q.attach(self.root, 'http://fixture', 'receipt.json', 'fixture')
                    api.assert_not_called()

    def test_process_ownership_and_descendant_cleanup_are_required_before_api(self):
        for case in ('missing_process', 'missing_pin', 'foreign_pid', 'missing_declaration',
                     'missing_windows_ownership', 'unavailable_ownership', 'wrong_identity',
                     'missing_exit_identity', 'process_cleanup', 'unverified_descendants', 'unstopped_descendants'):
            with self.subTest(case=case):
                receipt = self.native_receipt()
                lifecycle = self.root / 'artifacts/launches/native-candidate'
                path = lifecycle / 'process/process.json'
                process = json.loads(path.read_bytes())
                if case == 'missing_process': path.unlink()
                elif case == 'missing_pin': receipt['files'] = [p for p in receipt['files'] if p['path'] != path.relative_to(self.root).as_posix()]
                elif case == 'foreign_pid': process['pid'] = 43
                elif case == 'missing_windows_ownership': process.pop('windows_ownership')
                elif case == 'unavailable_ownership': process['windows_ownership']['status'] = 'unavailable'
                elif case == 'wrong_identity': process['windows_ownership']['identity']['pid'] = 43
                elif case == 'missing_exit_identity': process['windows_ownership']['identity'].pop('exited_filetime')
                elif case == 'process_cleanup': process['cleanup'] = {'stopped': False}
                elif case == 'missing_declaration':
                    owned = json.loads((lifecycle / 'owned-launch.json').read_bytes())
                    owned.pop('process_record')
                    write_json(lifecycle / 'owned-launch.json', owned)
                else:
                    owned = json.loads((lifecycle / 'owned-launch.json').read_bytes())
                    survivors = owned['survivors']
                    survivors['unverified' if case == 'unverified_descendants' else 'unstopped_pids'] = [43]
                    write_json(lifecycle / 'owned-launch.json', owned)
                    receipt['runs'][1]['launch']['survivors'] = survivors
                    write_json(lifecycle / 'exit.json', receipt['runs'][1]['launch'])
                    receipt['runs'][1]['cleanroom']['capture']['verdict'] = receipt['runs'][1]['launch']
                    bench = receipt['runs'][1]['cleanroom']
                    write_json(self.root / 'artifacts/bench/native-candidate/cleanroom.json',
                               {k: v for k, v in bench.items() if k not in ('record', 'bench_dir')})
                if case not in ('missing_process', 'missing_pin', 'missing_declaration', 'unverified_descendants', 'unstopped_descendants'):
                    write_json(path, process)
                receipt['files'] = [file_record(self.root, self.root / p['path']) for p in receipt['files']
                                    if (self.root / p['path']).is_file()]
                write_json(self.root / 'receipt.json', receipt)
                with patch.object(q, 'request') as api:
                    with self.assertRaises(StudioError):
                        q.attach(self.root, 'http://fixture', 'receipt.json', 'fixture')
                    api.assert_not_called()

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
