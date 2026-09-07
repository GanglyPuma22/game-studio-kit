"""Bounded follow-up controls; all media/actions/reviewer evidence are TEST only."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import test_final_review as prior
from test_validation_loop import ReviewFixture
from studio_tools import validation as v, review_media as m, review_records as reviews, review_video as video
from studio_tools.common import StudioError, file_record, read_json, sha256, write_json


class ActionAndPromptCorrections(ReviewFixture):
    def test_R10_ordering_is_scoped_to_selected_actions(self):
        self.root.joinpath('source.txt').write_text('SIMULATED two independent input/outcome records')
        actions = [{'id': key, 'input_seconds': .5, 'outcome_seconds': outcome,
                    'before_state': 'idle', 'after_state': 'active'} for key, outcome in [('walk', 1), ('look', .5005)]]
        trace = {'run_sha256': 'run', 'clip_sha256': 'clip', 'observer': 'test generator', 'provenance': 'synthetic',
            'input_route': 'synthetic', 'clock': {'offset_seconds':0,'uncertainty_seconds':0,'precision_seconds':.001},
            'source_evidence': file_record(self.root,self.root/'source.txt'), 'actions':actions}
        write_json(self.root/'trace.json', trace)
        for ids, status in [(['walk'],'pass'), (['look'],'unverified'), (['walk','look'],'unverified')]:
            criterion = {'action_ids':ids, 'expected_state':'active', 'interval':[0,2]}
            result, _ = v.action_trace(self.root,file_record(self.root,self.root/'trace.json'),
                {'sha256':'run','input_route':'synthetic'},'clip',criterion)
            self.assertEqual(result['status'],status)
            self.assertEqual(result['evidence_scope'],'test')

    def test_R12_equal_neutral_cards_have_identical_prompt_and_schema_bytes(self):
        card = {'prompt_contract_id':reviews.PROMPT_CONTRACT_ID, **copy.deepcopy(reviews.NEUTRAL_QUESTIONS)}
        identity = {'run_id':'a'*32,'candidate_id':'b'*32,'clip_sha256':'c'*64}
        original = video.request_questions(card, identity)
        def variant(value):
            if isinstance(value,dict): return {k:variant(v) for k,v in reversed(list(value.items()))}
            if isinstance(value,list): return [variant(v) for v in value]
            if type(value) is int: return float(value)
            return value
        changed = variant(card)
        reviews.validate_neutral_run({'card':changed,'run_id':identity['run_id'],'candidate':{'candidate_id':identity['candidate_id']}})
        altered = video.request_questions(changed,dict(reversed(list(identity.items()))))
        self.assertEqual(json.dumps(original),json.dumps(altered))
        self.assertEqual(card['criteria'][0]['interval'],[0,2])
        self.assertEqual(changed['criteria'][0]['interval'],[0.0,2.0])

    def test_R12_answer_cards_rejected_and_ordinary_questions_preserved(self):
        card = {'prompt_contract_id':reviews.PROMPT_CONTRACT_ID, **copy.deepcopy(reviews.NEUTRAL_QUESTIONS)}
        identity = {'run_id':'a'*32,'candidate_id':'b'*32,'clip_sha256':'c'*64}
        card['criteria'][0]['expected'] = 'M02 disappears at 0.9 seconds'
        with self.assertRaisesRegex(StudioError,'neutral'):
            video.request_questions(card,identity)
        card.pop('prompt_contract_id')
        self.assertIn('M02 disappears',video.request_questions(card,identity)[1])

    def test_R12_replay_rejects_noncanonical_schema_representation(self):
        card = {'prompt_contract_id':reviews.PROMPT_CONTRACT_ID, **copy.deepcopy(reviews.NEUTRAL_QUESTIONS)}
        identity = {'run_id':'a'*32,'candidate_id':'b'*32,'clip_sha256':'c'*64}
        run = {'card':card,'run_id':identity['run_id'],'candidate':{'candidate_id':identity['candidate_id']}}
        schema, prompt = video.request_questions(card,identity)
        payload = {'model':'test','input':[{'type':'video','mime_type':'video/mp4','data':'','processing':{'type':'static','fps':1}},
                    {'type':'text','text':prompt}], 'store':False,'generation_config':{},
                    'response_format':{'type':'text','mime_type':'application/json','schema':schema}}
        video.validate_neutral_request(run,payload,identity,[])
        for mutation in ('key_order','float'):
            altered = copy.deepcopy(payload)
            if mutation == 'key_order':
                altered['response_format']['schema'] = dict(reversed(list(schema.items())))
            else:
                altered['response_format']['schema']['properties']['findings']['items']['properties']['interval']['minItems'] = 2.0
            with self.subTest(mutation=mutation),self.assertRaisesRegex(StudioError,'neutral'):
                video.validate_neutral_request(run,altered,identity,[])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'installed media tools required')
class MediaAndAttemptCorrections(ReviewFixture):
    source = prior.MediaFinalCorrections.source
    captured = prior.MediaFinalCorrections.captured
    facts = prior.MediaFinalCorrections.facts
    timing = prior.MediaFinalCorrections.timing
    performance_card = prior.MediaFinalCorrections.performance_card

    def test_R09_file_receipt_uses_portable_identity(self):
        name = self.captured();folder = self.root/name
        original = read_json(folder/'capture.original.json')
        self.assertNotIn(str(self.root),json.dumps(original))
        self.assertNotIn('source',original['profile'])
        self.assertEqual(original['profile']['source_identity'],original['capture']['source'])
        self.assertTrue(v.validate_run(self.root,name,current=False,config=self.config))
        with tempfile.TemporaryDirectory() as temporary:
            relocated = Path(temporary)/'relocated-project'
            shutil.copytree(self.root,relocated)
            self.assertTrue(v.validate_run(relocated,name,current=False,config=self.config))

    def failed_attempt(self):
        self.performance_card();name = self.captured();folder = self.root/name
        facts = self.facts(name);facts['timing'] = self.timing(name,[0,1]);facts['timing']['method'] = 'encoded_fps'
        write_json(folder/'facts.json',facts)
        with self.assertRaises(StudioError): v.assess(self.root,name,name+'/facts.json',config=self.config)
        return name, facts

    def test_R11_deleted_failed_input_cannot_be_replaced_and_recheck_is_allowed(self):
        name, facts = self.failed_attempt();folder = self.root/name
        original = (folder/'observations.original.json').read_bytes()
        write_json(folder/'observations.original.json',dict(facts, extra='changed failed input'))
        with self.assertRaisesRegex(StudioError,'Reserved assessment input'):
            v.assess(self.root,name,_recompute=True,config=self.config)
        (folder/'observations.original.json').write_bytes(original)  # disposable adverse control reset
        (folder/'observations.original.json').unlink()
        facts.pop('timing');write_json(folder/'replacement.json',facts)
        with self.assertRaisesRegex(StudioError,'attempt|retained'):
            v.assess(self.root,name,name+'/replacement.json',config=self.config)
        marker = read_json(folder/'assessment-attempt.json')
        self.assertEqual(marker['input_sha256'],sha256(folder/'facts.json'))
        self.assertFalse((folder/'assessment.json').exists())
        with self.assertRaisesRegex(StudioError,'input|retained'):
            v.assess(self.root,name,_recompute=True,config=self.config)
        recheck = v.prepare_run(self.root,self.card,self.candidate,role='after',previous=name,affected=['P1','P2'])
        m.capture(self.config,self.root,recheck,{'route':'file','source':str(self.root/'artifacts/full.mp4')})
        self.assertIn('pending',v.assess(self.root,recheck,config=self.config))

    def test_R11_changed_input_is_detected_and_successful_recompute_is_read_only(self):
        name = self.captured();folder = self.root/name;facts = self.facts(name)
        write_json(folder/'facts.json',facts)
        result = v.assess(self.root,name,name+'/facts.json',config=self.config)
        marker = (folder/'assessment-attempt.json').read_bytes()
        self.assertEqual(v.assess(self.root,name,_recompute=True,config=self.config),result)
        self.assertEqual((folder/'assessment-attempt.json').read_bytes(),marker)
        changed = dict(facts, ignored='changed bytes');write_json(folder/'observations.original.json',changed)
        with self.assertRaisesRegex(StudioError,'hash|input|changed'):
            v.assess(self.root,name,_recompute=True,config=self.config)

    def test_R11_input_reserved_before_run_validation(self):
        name = self.captured();folder = self.root/name
        facts = self.facts(name);write_json(folder/'facts.json',facts)
        with patch('studio_tools.validation.validate_run',side_effect=StudioError('controlled run validation error')):
            with self.assertRaises(StudioError):v.assess(self.root,name,name+'/facts.json',config=self.config)
        marker = read_json(folder/'assessment-attempt.json')
        self.assertEqual(marker['run_sha256'],sha256(folder/'run.json'))
        self.assertEqual(marker['input_sha256'],sha256(folder/'facts.json'))
        self.assertEqual((folder/'observations.original.json').read_bytes(),(folder/'facts.json').read_bytes())

    def test_R11_no_input_and_concurrent_attempts_are_reserved_once(self):
        from concurrent.futures import ThreadPoolExecutor
        name = self.captured();folder = self.root/name
        def attempt():
            try: return v.assess(self.root,name,config=self.config)
            except StudioError: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sum(result is not None for result in results),1)
        marker = read_json(folder/'assessment-attempt.json')
        self.assertFalse(marker['input_supplied']);self.assertIsNone(marker['input_sha256'])
        original = (folder/'assessment-attempt.json').read_bytes()
        with self.assertRaises(StudioError):v.assess(self.root,name,config=self.config)
        self.assertEqual((folder/'assessment-attempt.json').read_bytes(),original)

    def test_R11_unreadable_input_reserves_failed_attempt(self):
        name = self.captured();folder = self.root/name
        with self.assertRaises(StudioError):v.assess(self.root,name,name+'/missing.json',config=self.config)
        self.assertTrue((folder/'assessment-attempt.json').exists())
        with self.assertRaises(StudioError):v.assess(self.root,name,config=self.config)

    def test_R09_native_grant_profile_is_retained_unchanged(self):
        name = v.prepare_run(self.root,self.card,self.candidate)
        profile = {'route':'windows_ddagrab','host':'test-host','operator':'test-operator','target':'test-window',
                   'authorization':{'receipt':'existing-test-grant','capture':{'fps':30}}}
        def cancelled(*args, **kwargs):
            job = kwargs['job_dir'];job.mkdir()
            process = {'status':'cancelled','stop_reason':'cancelled_before_start'}
            write_json(job/'process.json',process);(job/'stdout.log').write_text('TEST: no native process started')
            return process
        with patch('studio_tools.review_media._native_args',return_value=[]), patch('studio_tools.review_media.run',return_value={'stdout':'h264_nvenc'}), patch('studio_tools.review_media.record',side_effect=cancelled):
            result = m.capture(self.config,self.root,name,profile)
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(read_json(self.root/name/'capture.original.json')['profile'],profile)
        self.assertEqual(result['source']['authorization'],profile['authorization'])

    def test_R11_legacy_assessment_recompute_does_not_create_marker(self):
        name = self.captured();folder = self.root/name
        result = v.assess(self.root,name,config=self.config)
        # Construct the historical schema in this disposable test only.
        result['files'] = [item for item in result['files'] if not item['path'].endswith('assessment-attempt.json')]
        write_json(folder/'assessment.json',result);(folder/'assessment-attempt.json').unlink()
        before = (folder/'assessment.json').read_bytes()
        self.assertTrue(v.validate_run(self.root,name,current=False,config=self.config))
        self.assertEqual(v.assess(self.root,name,_recompute=True,config=self.config),result)
        self.assertFalse((folder/'assessment-attempt.json').exists())
        self.assertEqual((folder/'assessment.json').read_bytes(),before)
