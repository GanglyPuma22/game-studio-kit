"""No live requests: exercise provider dispatch, exact wire profiles and uncertainty."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio_tools.common import StudioError, read_json, sha256
from studio_tools.config import load

BUDGET = dict(authorized=True, work_card='offline test', rate_checked_at='2026-09-05',
              units='mock units', estimated=1, maximum=1)
BODY = dict(text='The beacon is visible.', model_id='s2-pro', reference_id='licensed-test-reference')

class Transport:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.failure:
            raise self.failure
        return b'ID3original mock audio', {'x-request-id':'offline', 'test':'secret-test-key'}

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = load()
        self.env = patch.dict(os.environ, {'FISH_AUDIO_API_KEY':'secret-test-key', 'ELEVENLABS_API_KEY':'secret-test-key'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def generate(self, provider='fish', capability='speech', body=None, budget=None, transport=None):
        from studio_tools.adapters.audio import generate
        return generate(self.config, provider, capability, body or BODY, self.root/'intent.json',
                        self.root/'original.mp3', budget or BUDGET,
                        {'rights':'original test text and authorized voice'}, transport=transport)

    def test_fish_explicit_model_header_reference_body_and_archive(self):
        t=Transport()
        r=self.generate(transport=t)
        self.assertEqual(len(t.calls),1)
        args,kw=t.calls[0]
        self.assertEqual(args[:2], ('POST','https://api.fish.audio/v1/tts'))
        self.assertEqual(args[2]['model'],'s2-pro')
        self.assertEqual(args[2]['Authorization'],'Bearer secret-test-key')
        self.assertEqual(args[3],dict(text=BODY['text'], reference_id=BODY['reference_id'], format='mp3', sample_rate=44100, mp3_bitrate=128))
        self.assertTrue(kw['binary'])
        self.assertEqual(r['status'],'ARCHIVED')
        self.assertEqual(r['output']['sha256'],sha256(self.root/'original.mp3'))
        self.assertEqual(r['live_quality'],'unverified')
        self.assertNotIn('secret-test-key',(self.root/'intent.json').read_text())

    def test_invalid_model_capability_fields_and_zero_budget_never_submit(self):
        cases=[('fish','effects',BODY,BUDGET), ('fish','music',BODY,BUDGET),
               ('fish','speech',{**BODY,'model_id':'latest'},BUDGET),
               ('fish','speech',{k:v for k,v in BODY.items() if k!='model_id'},BUDGET),
               ('fish','speech',{**BODY,'voice_id':'wrong'},BUDGET),
               ('fish','speech',{**BODY,'streaming':False},BUDGET),
               ('fish','speech',{**BODY,'format':'wav'},BUDGET),
               ('fish','speech',{**BODY,'model_id':'s2.1-pro-free'},{**BUDGET,'maximum':0}),
               ('elevenlabs','speech',dict(text='test',model_id='eleven_multilingual_v2',voice_id='test'),{**BUDGET,'maximum':0}),
               ('unknown','speech',BODY,BUDGET)]
        for provider,capability,body,budget in cases:
            with self.subTest(provider=provider,body=body,budget=budget):
                t=Transport()
                with self.assertRaises(StudioError):
                    self.generate(provider,capability,body,budget,t)
                self.assertEqual(t.calls,[])
                self.assertFalse((self.root/'intent.json').exists())

    def test_timeout_preserves_intent_no_retry_or_fallback(self):
        t=Transport(OSError('secret-test-key timeout'))
        with self.assertRaisesRegex(StudioError,'unknown'):
            self.generate(transport=t)
        self.assertEqual(read_json(self.root/'intent.json')['status'],'SUBMISSION_UNKNOWN')
        t.failure=None
        with self.assertRaisesRegex(StudioError,'already exists'):
            self.generate(transport=t)
        self.assertEqual(len(t.calls),1)
        self.assertFalse((self.root/'original.mp3').exists())
        self.assertNotIn('secret-test-key',(self.root/'intent.json').read_text())

    def test_existing_output_is_preserved_without_submission(self):
        p=self.root/'original.mp3';p.write_bytes(b'original')
        t=Transport()
        with self.assertRaises(StudioError):
            self.generate(transport=t)
        self.assertEqual(t.calls,[])
        self.assertEqual(p.read_bytes(),b'original')

    def test_invalid_binary_is_retained_for_manual_reconciliation(self):
        class Invalid(Transport):
            def request(self,*args,**kwargs):
                self.calls.append((args,kwargs))
                return b'{"error":"bad"}',{}
        t=Invalid()
        with self.assertRaises(StudioError):
            self.generate(transport=t)
        record = read_json(self.root/'intent.json')
        self.assertEqual(record['status'], 'RECEIVED_UNARCHIVED')
        recovery = self.root / record['recovery']['path']
        self.assertEqual(recovery.read_bytes(), b'{"error":"bad"}')
        self.assertEqual(record['recovery']['sha256'], sha256(recovery))
        self.assertFalse(record['recovery']['validated'])
        self.assertEqual(len(t.calls), 1)
        self.assertFalse((self.root/'original.mp3').exists())

    def test_existing_elevenlabs_alias_default_and_explicit_dispatch(self):
        from studio_tools.cli import parser
        old=parser().parse_args(['audio','speech','--project',str(self.root)])
        self.assertEqual(old.provider,'elevenlabs')
        t=Transport()
        r=self.generate('elevenlabs','speech',dict(text='test',voice_id='voice',model_id='eleven_multilingual_v2'),transport=t)
        args,_=t.calls[0]
        self.assertEqual(args[1],'https://api.elevenlabs.io/v1/text-to-speech/voice?output_format=mp3_44100_128')
        self.assertNotIn('voice_id',args[3])
        self.assertEqual(r['provider'],'elevenlabs')

    def test_metadata_write_failure_keeps_durable_unknown_and_original(self):
        t = Transport()
        with patch('studio_tools.adapters.requests.write_json', side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(StudioError, 'unknown'):
                self.generate(transport=t)
        self.assertEqual(read_json(self.root/'intent.json')['status'], 'SUBMISSION_UNKNOWN')
        self.assertTrue((self.root/'original.mp3').is_file())
        recovery = self.root / read_json(self.root/'intent.json')['recovery']['path']
        self.assertEqual(recovery.read_bytes(), (self.root/'original.mp3').read_bytes())
        with self.assertRaises(StudioError):
            self.generate(transport=t)
        self.assertEqual(len(t.calls), 1)

    def test_output_created_during_request_is_not_overwritten(self):
        target = self.root/'original.mp3'
        class Concurrent(Transport):
            def request(self, *args, **kwargs):
                target.write_bytes(b'another writer')
                return super().request(*args, **kwargs)
        t = Concurrent()
        with self.assertRaisesRegex(StudioError, 'recovery'):
            self.generate(transport=t)
        self.assertEqual(target.read_bytes(), b'another writer')
        record = read_json(self.root/'intent.json')
        self.assertEqual(record['status'], 'RECEIVED_UNARCHIVED')
        recovery = self.root / record['recovery']['path']
        self.assertEqual(recovery.read_bytes(), b'ID3original mock audio')
        self.assertEqual(record['recovery']['sha256'], sha256(recovery))
        self.assertEqual(record['recovery']['bytes'], len(recovery.read_bytes()))
        with self.assertRaises(StudioError):
            self.generate(transport=t)
        self.assertEqual(len(t.calls), 1)

    def test_unsupported_hardlinks_retain_received_original_and_redacted_identity(self):
        t = Transport()
        with patch('studio_tools.adapters.requests.os.link', side_effect=OSError('secret-test-key unsupported')):
            with self.assertRaisesRegex(StudioError, 'recovery') as error:
                self.generate(transport=t)
        record = read_json(self.root/'intent.json')
        self.assertEqual(record['status'], 'RECEIVED_UNARCHIVED')
        recovery = self.root / record['recovery']['path']
        self.assertEqual(recovery.read_bytes(), b'ID3original mock audio')
        self.assertEqual(record['recovery']['sha256'], sha256(recovery))
        self.assertTrue(record['recovery']['validated'])
        self.assertFalse((self.root/'original.mp3').exists())
        self.assertNotIn('secret-test-key', str(error.exception) + (self.root/'intent.json').read_text())
        with self.assertRaises(StudioError):
            self.generate(transport=t)
        self.assertEqual(len(t.calls), 1)

    def test_recovery_storage_is_reserved_before_submission(self):
        t = Transport()
        with patch('studio_tools.adapters.requests.tempfile.mkstemp', side_effect=OSError('storage unavailable')):
            with self.assertRaises(StudioError):
                self.generate(transport=t)
        self.assertEqual(t.calls, [])

    def test_received_fsync_failure_keeps_bytes_without_claiming_durability(self):
        from studio_tools.adapters import requests
        real_fsync = requests.os.fsync
        t = Transport()
        def fail_received(fd):
            if t.calls:
                raise OSError('secret-test-key disk failure')
            return real_fsync(fd)
        with patch('studio_tools.adapters.requests.os.fsync', side_effect=fail_received):
            with self.assertRaisesRegex(StudioError, 'durability') as error:
                self.generate(transport=t)
        record = read_json(self.root/'intent.json')
        self.assertEqual(record['status'], 'SUBMISSION_UNKNOWN')
        self.assertEqual((self.root / record['recovery']['path']).read_bytes(), b'ID3original mock audio')
        self.assertNotIn('secret-test-key', str(error.exception))
        self.assertEqual(len(t.calls), 1)

    def test_usage_metadata_retained_and_redacted(self):
        class Usage(Transport):
            def request(self, *args, **kwargs):
                data, _ = super().request(*args, **kwargs)
                return data, {'character-cost': '13', 'request-id': 'secret-test-key', 'debug': 'discard'}
        result = self.generate('elevenlabs', 'speech',
                               dict(text='test', voice_id='voice', model_id='eleven_multilingual_v2'),
                               transport=Usage())
        self.assertEqual(result['response_metadata'], {'character-cost':'13', 'request-id':'[REDACTED]'})

    def test_record_output_alias_never_submits(self):
        from studio_tools.adapters.audio import generate
        t = Transport()
        with self.assertRaises(StudioError):
            generate(self.config, 'fish', 'speech', BODY, self.root/'same.mp3',
                     self.root/'same.mp3', BUDGET, {'rights':'fixture'}, t)
        self.assertEqual(t.calls, [])
