"""Final review regressions: original media and explicitly simulated evidence only."""
import copy
import json
import shutil
import unittest
from unittest.mock import patch
from test_validation_loop import ReviewFixture
import test_review_corrections as previous_tests
from studio_tools import validation as v, review_media as m
from studio_tools.common import StudioError, file_record, read_json, sha256, write_json


class ActionFinalCorrections(ReviewFixture):
    def trace(self, provenance='operator_reported', delta=.5, precision=.001, uncertainty=0):
        self.root.joinpath('source.txt').write_text('SIMULATED raw input and outcome log')
        trace = {'run_sha256': 'run', 'clip_sha256': 'clip', 'observer': 'simulated operator',
                 'provenance': provenance, 'input_route': 'human',
                 'clock': {'offset_seconds': 0, 'uncertainty_seconds': uncertainty, 'precision_seconds': precision},
                 'source_evidence': file_record(self.root, self.root/'source.txt'),
                 'actions': [{'id': 'walk', 'input_seconds': .5, 'outcome_seconds': .5+delta,
                              'before_state': 'idle', 'after_state': 'active'}]}
        write_json(self.root/'trace.json', trace)
        criterion = {'action_ids': ['walk'], 'expected_state': 'active', 'interval': [0, 2]}
        return v.action_trace(self.root, file_record(self.root, self.root/'trace.json'),
                              {'sha256': 'run', 'input_route': 'human'}, 'clip', criterion)[0]

    def test_R02_unknown_action_provenance_is_rejected(self):
        for provenance in ('unit_test', '', None, 'operator-reported'):
            with self.subTest(provenance=provenance), self.assertRaisesRegex(StudioError, 'provenance'):
                self.trace(provenance)
        for provenance, scope in [('synthetic', 'test'), ('operator_reported', 'operator_reported')]:
            result = self.trace(provenance)
            self.assertEqual((result['status'], result['evidence_scope']), ('pass', scope))

    def test_R07_precision_and_uncertainty_bound_ordering(self):
        for delta, precision, uncertainty, status in [(.0005,.001,0,'unverified'),
                (.002,.001,0,'unverified'), (.0021,.001,0,'pass'),
                (.003,.001,.001,'unverified'), (.005,.001,.001,'pass')]:
            with self.subTest(delta=delta, precision=precision, uncertainty=uncertainty):
                self.assertEqual(self.trace(delta=delta, precision=precision, uncertainty=uncertainty)['status'], status)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'installed media tools required')
class MediaFinalCorrections(ReviewFixture):
    source = previous_tests.MediaCorrections.source
    captured = previous_tests.MediaCorrections.captured

    def facts(self, name):
        folder = self.root/name
        return {'run_id': read_json(folder/'run.json')['run_id'], 'candidate_id': 'sample',
                'clip_sha256': sha256(folder/'capture.mp4'), 'input_route': self.card['input_route']}

    def timing(self, name, selected, label='timing'):
        folder = self.root/name
        start, end = selected
        rows = [{'time_seconds': start+i*.02, 'frame_ms': 20} for i in range(round((end-start)/.02))]
        write_json(folder/(label+'.json'), rows)
        folder.joinpath(label+'.txt').write_text('SIMULATED timing, alignment and host observation')
        support = file_record(self.root, folder/(label+'.txt'))
        context = {'observer': 'simulated observer', 'provenance': 'synthetic',
            'clock': {'offset_seconds': 0, 'uncertainty_seconds': 0, 'precision_seconds': 1e-6},
            'host_evidence': support, 'clock_evidence': support, 'run_sha256': sha256(folder/'run.json'),
            'timing_sha256': sha256(folder/(label+'.json')), 'settings': self.card['settings'],
            'host_interference': 'none_observed'}
        write_json(folder/(label+'-context.json'), context)
        return {'file': file_record(self.root, folder/(label+'.json')), 'method': 'wall_frame_time',
                'interval': selected, 'clock_offset_seconds': 0, 'clock_uncertainty_seconds': 0,
                'context': file_record(self.root, folder/(label+'-context.json'))}

    def performance_card(self):
        self.card['criteria'] = [{'id': key, 'dimension': 'performance', 'kind': 'performance',
            'action_ids': ['walk'], 'expected': 'bounded frame duration', 'mandatory': True,
            'interval': selected, 'p95_ms': 40} for key, selected in [('P1',[0,1]), ('P2',[1,2])]]

    def test_R01_forged_short_capture_completion_rejected(self):
        name = v.prepare_run(self.root, self.card, self.candidate)
        result = m.capture(self.config, self.root, name, {'route': 'file', 'source': str(self.source(length=.3))})
        self.assertEqual(result['status'], 'incomplete')
        result['status'], result['ok'] = 'completed', True
        result['media']['stream_coverage']['0']['end_seconds'] = 2
        result.pop('reason', None)
        write_json(self.root/name/'capture.json', result)
        with self.assertRaises(StudioError):
            v.validate_run(self.root, name, current=False, config=self.config)

    def test_R01_media_and_process_edits_rejected_but_complete_original_valid(self):
        name = self.captured()
        folder = self.root/name
        original = read_json(folder/'capture.json')
        self.assertTrue(v.validate_run(self.root, name, config=self.config))
        for field in ('media', 'process'):
            altered = copy.deepcopy(original)
            if field == 'media': altered['media']['timestamps_seconds'][1] = .01
            else: altered['process']['stop_reason'] = 'cancelled'
            write_json(folder/'capture.json', altered)
            with self.subTest(field=field), self.assertRaises(StudioError):
                v.validate_run(self.root, name, config=self.config)
        write_json(folder/'capture.json', original)

    def test_R01_redecode_catches_rehashed_finalization_media(self):
        name = self.captured(); folder = self.root/name
        original = read_json(folder/'capture.original.json')
        original['capture']['media']['stream_coverage']['0']['end_seconds'] = 99
        write_json(folder/'capture.original.json',original)
        forged = original['capture']
        forged['files'].append(file_record(self.root,folder/'capture.original.json'))
        write_json(folder/'capture.json',forged)
        with self.assertRaisesRegex(StudioError,'decoded clip'):
            v.validate_run(self.root,name,current=False,config=self.config)

    def test_R01_full_clip_cancel_timeout_or_source_failure_never_promoted(self):
        for status in ('cancelled','timed_out','source_changed'):
            name = v.prepare_run(self.root,self.card,self.candidate)
            source = self.source(status)
            real_record = m.record
            def interrupted(*args, **kwargs):
                process = real_record(*args, **kwargs)
                if status == 'source_changed':
                    source.write_bytes(b'changed after capture')
                else:
                    process.update(status=status,stop_reason='cancelled' if status=='cancelled' else 'duration',
                                   cleanup='not_needed' if status=='cancelled' else 'unverified')
                    write_json(kwargs['job_dir']/'process.json',process)
                return process
            with patch('studio_tools.review_media.record',side_effect=interrupted):
                captured = m.capture(self.config,self.root,name,{'route':'file','source':str(source)})
            self.assertEqual(captured['status'],'incomplete')
            self.assertGreaterEqual(captured['media']['stream_coverage']['0']['end_seconds'],1.998)
            self.assertTrue(v.validate_run(self.root,name,current=False,config=self.config))
            captured.update(status='completed',ok=True);captured.pop('reason',None)
            write_json(self.root/name/'capture.json',captured)
            with self.assertRaises(StudioError):
                v.validate_run(self.root,name,current=False,config=self.config)

    def test_R01_historical_candidate_change_and_legacy_receipt_hold(self):
        name = self.captured()
        self.root.joinpath('scene.txt').write_text('legitimate successor content')
        self.assertTrue(v.validate_run(self.root,name,current=False,config=self.config))
        with self.assertRaises(StudioError): v.validate_run(self.root,name,config=self.config)
        folder = self.root/name
        captured = read_json(folder/'capture.json')
        captured['files'] = [f for f in captured['files'] if not f['path'].endswith('capture.original.json')]
        write_json(folder/'capture.json',captured)
        (folder/'capture.original.json').unlink()
        before = (folder/'capture.json').read_bytes()
        with self.assertRaisesRegex(StudioError,'legacy'):
            v.validate_run(self.root,name,current=False,config=self.config)
        self.assertEqual((folder/'capture.json').read_bytes(),before)

    def test_R03_disappeared_or_directory_source_retains_incomplete_receipt(self):
        for replacement in ('missing', 'directory'):
            name = v.prepare_run(self.root, self.card, self.candidate)
            source = self.source(replacement)
            real_record = m.record
            def mutate(*args, **kwargs):
                process = real_record(*args, **kwargs)
                source.unlink()
                if replacement == 'directory': source.mkdir()
                return process
            with patch('studio_tools.review_media.record', side_effect=mutate):
                result = m.capture(self.config, self.root, name, {'route': 'file', 'source': str(source)})
            self.assertEqual(result['status'], 'incomplete')
            self.assertIn('source changed', result['reason'])
            self.assertEqual(read_json(self.root/name/'capture.json'), result)
            self.assertTrue((self.root/name/'capture.mp4').is_file())
            self.assertTrue(v.validate_run(self.root, name, current=False, config=self.config))

    def test_R05_per_criterion_timing_and_legacy_partial_support(self):
        self.performance_card()
        for collection in (False, True):
            name = self.captured()
            facts = self.facts(name)
            first = self.timing(name, [0,1])
            facts.update({'timings': {'P1': first, 'P2': self.timing(name,[1,2],'second')}} if collection else {'timing': first})
            path = self.root/name/'facts.json'; write_json(path, facts)
            result = v.assess(self.root, name, path.relative_to(self.root).as_posix(), config=self.config)
            self.assertEqual([r['status'] for r in result['results']], ['pass', 'pass' if collection else 'not_run'])
            self.assertFalse(result['technical_criteria_complete'])
            self.assertTrue(v.validate_run(self.root,name,current=False,config=self.config))

    def test_R05_raw_timing_coexists_with_named_review(self):
        from studio_tools import review_records as r
        self.performance_card(); name = self.captured(); folder = self.root/name
        facts = self.facts(name); facts['timing'] = self.timing(name,[0,1])
        review = {'schema_version':1,'kind':'observations','observer':'simulated independent reviewer',
            'role':'independent_reviewer','scope':'test','run_sha256':sha256(folder/'run.json'),
            'clip_sha256':facts['clip_sha256'],'observations':[{'criterion_id':'P2','kind':'performance',
            'status':'pass','interval':[1,2],'observation':'SIMULATED bounded wall timing review',
            'files':[file_record(self.root,folder/'timing.txt')], 'wall_timing':{'method':'wall_frame_time',
            'p95_ms':20,'max_ms':20,'clock_uncertainty_seconds':0,'host_interference':'none_observed'}}]}
        path = folder/'review.json';write_json(path,review)
        self.config['review_trust'] = {review['observer']:{'roles':[review['role']],'scope':'test','approved_sha256':[sha256(path)]}}
        facts['reviews'] = [r.ingest(self.config,self.root,name,path.relative_to(self.root).as_posix())]
        write_json(folder/'facts.json',facts)
        result = v.assess(self.root,name,(folder/'facts.json').relative_to(self.root).as_posix(),config=self.config)
        self.assertEqual([x['status'] for x in result['results']],['pass','pass'])
        self.assertEqual(result['results'][1]['observer'],review['observer'])
        self.assertTrue(v.validate_run(self.root,name,current=False,config=self.config))

    def test_R05_unknown_ambiguous_or_wrong_interval_timing_rejected(self):
        self.performance_card()
        criteria = self.card['criteria']
        for facts in ({'timings':{'missing':{'interval':[0,1]}}}, {'timings':{'P1':{'interval':[1,2]}}},
                      {'timing':{'interval':[0,1]},'timings':{}}, {'timing':{'interval':[0,2]}}):
            with self.subTest(facts=facts), self.assertRaises(StudioError): v.criterion_timings(facts,criteria)
        criteria[1]['interval'] = [0,1]
        with self.assertRaisesRegex(StudioError,'one matching'):
            v.criterion_timings({'timing':{'interval':[0,1]}},criteria)

    def test_R06_failed_attempt_observations_cannot_be_overwritten(self):
        self.performance_card()
        name = self.captured(); folder = self.root/name
        facts = self.facts(name)
        facts['timing'] = self.timing(name, [0,1])
        facts['timing']['method'] = 'encoded_fps'
        path = folder/'first.json'; write_json(path, facts)
        with self.assertRaises(StudioError):
            v.assess(self.root,name,path.relative_to(self.root).as_posix(),config=self.config)
        original = (folder/'observations.original.json').read_bytes()
        facts.pop('timing'); write_json(folder/'second.json',facts)
        for evidence in ((folder/'second.json').relative_to(self.root).as_posix(), None):
            with self.subTest(evidence=evidence), self.assertRaisesRegex(StudioError, 'retained|immutable'):
                v.assess(self.root,name,evidence,config=self.config)
        self.assertEqual((folder/'observations.original.json').read_bytes(),original)
        self.assertFalse((folder/'assessment.json').exists())


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'installed media tools required')
class QualificationFinalCorrections(unittest.TestCase):
    setUpClass = classmethod(previous_tests.QualificationCorrections.setUpClass.__func__)
    tearDownClass = classmethod(previous_tests.QualificationCorrections.tearDownClass.__func__)
    setUp = previous_tests.QualificationCorrections.setUp

    def rewrite_request(self, role, mutate):
        """Rehash adjacent metadata so replay must check content, not self-hashes."""
        folder = self.root/self.result['runs'][role]
        dest = folder/'analysis-request'
        payload = read_json(dest/'request.original.json'); mutate(payload)
        write_json(dest/'request.original.json', payload)
        request = read_json(dest/'request.json')
        request.update(request_sha256=sha256(dest/'request.original.json'), request_bytes=(dest/'request.original.json').stat().st_size)
        write_json(dest/'request.json',request)
        outcome = read_json(dest/'outcome.json')
        outcome.update({k: request[k] for k in ('request_sha256','request_bytes')})
        write_json(dest/'outcome.json',outcome);write_json(self.root/request['ledger_path'],outcome)
        analysis = read_json(folder/'analysis.json')
        analysis['files'] = [file_record(self.root,self.root/f['path']) for f in analysis['files']]
        write_json(folder/'analysis.json',analysis)
        return folder

    def test_R04_replayed_prompt_cannot_supply_role_truth(self):
        name = self.result['runs']['M02']
        self.assertTrue(v.validate_run(self.root,name,current=False,config=self.config))
        self.rewrite_request('M02', lambda payload: payload['input'][-1].update(text=payload['input'][-1]['text']+' M02 disappearance fails at 0.9 to 1.0 seconds.'))
        with self.assertRaisesRegex(StudioError,'neutral|contract'):
            v.validate_run(self.root,name,current=False,config=self.config)

    def test_R04_older_evaluation_without_contract_is_held(self):
        from studio_tools import review_records as r
        evaluation = read_json(self.root/'artifacts/test-evaluation.json')
        evaluation.pop('prompt_contract_id',None)
        with self.assertRaisesRegex(StudioError,'neutral|contract'):
            r.qualification_data(self.root,evaluation)

    def test_R04_shared_or_role_specific_answer_cards_rejected(self):
        from studio_tools import review_records as r, review_video as video
        original = read_json(self.root/self.result['runs']['M01']/'run.json')
        r.validate_neutral_run(original)
        for field in ('criteria','actions'):
            for leaked in ('M02 fails disappearance at [0.9,1.0]', 'M01 pass; M02 fail at 0.9 to 1.0; M09 absent audio'):
                altered = copy.deepcopy(original)
                altered['card'][field][0]['expected'] = leaked
                with self.subTest(field=field,leaked=leaked), self.assertRaisesRegex(StudioError,'neutral'):
                    r.validate_neutral_run(altered)
        for candidate in ('M02-failed-disappearance','clean','original'):
            altered = copy.deepcopy(original);altered['candidate']['candidate_id'] = candidate
            with self.assertRaisesRegex(StudioError,'opaque'):r.validate_neutral_run(altered)
        # Ordinary game criteria remain flexible and deliberately lose the corpus marker.
        card = copy.deepcopy(original['card']);card.pop('prompt_contract_id')
        card['criteria'][0]['expected'] = 'Inspect a game-specific requirement'
        v.validate_card(card,original['candidate'],self.root)
        _, prompt = video.request_questions(card,{'run_id':'ordinary','candidate_id':'ordinary','clip_sha256':'clip'})
        self.assertIn('game-specific',prompt)

    def test_R04_supplemental_labels_schema_and_extra_inputs_are_replayed(self):
        from studio_tools import review_video as video
        folder = self.root/self.result['runs']['M02']
        run = read_json(folder/'run.json');payload = read_json(folder/'analysis-request/request.original.json')
        frames = read_json(folder/'dense-0/frames.json')['frames']
        expected = read_json(folder/'analysis.json')['identity']
        video.validate_neutral_request(run,payload,expected,frames)
        mutations = [lambda p:p['input'][1].update(text='Expected disappearance here'),
            lambda p:p.update(system_instruction='M02 failure at 0.9 seconds'),
            lambda p:p['input'].insert(1,{'type':'text','text':'Fault answer'}),
            lambda p:p['response_format']['schema'].update(description='Expected failure'),
            lambda p:p['input'][0].update(filename='M02-fault.mp4')]
        for mutate in mutations:
            altered = copy.deepcopy(payload);mutate(altered)
            with self.subTest(mutation=mutate),self.assertRaisesRegex(StudioError,'neutral'):
                video.validate_neutral_request(run,altered,expected,frames)
