"""Corrective adverse controls; all provider/observer fixtures are explicitly test-only."""
import copy
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_validation_loop import ReviewFixture, funded_budget
from studio_tools import validation as v, review_media as m, review_video as video
from studio_tools.common import StudioError, read_json, write_json, file_record, sha256
from studio_tools.config import load
from studio_tools.evidence import new_candidate



class CardCorrections(ReviewFixture):
    def test_C05_import_and_quiet_branches_do_not_mute_audible_game(self):
        (self.root/'scene.txt').write_text('godot --headless --editor --import --audio-driver Dummy\n# quiet: godot -Muted\ngodot --audio-driver WASAPI\n')
        self.candidate=new_candidate(self.root,'sample','fixture','test')
        self.card['content_digest']=self.candidate['content_digest']
        self.card['launch'].update(entrypoint_sha256=sha256(self.root/'scene.txt'),delivered_args=['--audio-driver','WASAPI'],effective_audio_backend='WASAPI')
        self.assertTrue(v.validate_card(self.card,self.candidate,self.root)['ok'])

    def test_C10_kind_cannot_certify_another_dimension(self):
        self.card['criteria'][0].update(kind='performance',dimension='audio',p95_ms=40)
        with self.assertRaises(StudioError):v.validate_card(self.card,self.candidate,self.root)
        self.card['criteria'][0].update(kind='interaction',dimension='interaction')
        with self.assertRaises(StudioError):v.validate_card(self.card,self.candidate,self.root)

    def test_C08_siblings_consume_lineage_budget(self):
        before=v.prepare_run(self.root,self.card,self.candidate,role='before')
        v.prepare_run(self.root,self.card,self.candidate,role='after',previous=before,affected=['TEMP'])
        with self.assertRaisesRegex(StudioError,'budget'):
            v.prepare_run(self.root,self.card,self.candidate,role='after',previous=before,affected=['TEMP'])

    def test_C08_concurrent_and_failed_attempts_consume_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        before=v.prepare_run(self.root,self.card,self.candidate,role='before')
        def attempt():
            try:return v.prepare_run(self.root,self.card,self.candidate,role='after',previous=before,affected=['TEMP'])
            except StudioError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        before=v.prepare_run(self.root,self.card,self.candidate,role='before')
        with patch('studio_tools.validation.shutil.copyfile',side_effect=OSError('controlled failed attempt')):
            with self.assertRaises(OSError):attempt()
        with self.assertRaisesRegex(StudioError,'budget'):v.prepare_run(self.root,self.card,self.candidate,role='after',previous=before,affected=['TEMP'])

    def test_C17_affected_without_baseline_rejected(self):
        with self.assertRaises(StudioError):v.prepare_run(self.root,self.card,self.candidate,affected=['TEMP'])

    def test_C02_rates_and_underfunding_rejected_before_transport(self):
        for mutate in (lambda b:b.pop('rates_usd_per_million'),lambda b:b.update(rate_verified_utc='yesterday'),lambda b:b.update(rate_verified_utc='2000-01-01T00:00:00Z'),lambda b:b.update(max_total_usd=.000001,reserve_per_request_usd=.000001)):
            budget=funded_budget();mutate(budget)
            with self.subTest(budget=budget),patch('studio_tools.review_video._submit') as submit:
                with self.assertRaises(StudioError):video.reserve(self.root,budget,'run','clip')
                submit.assert_not_called()

    def test_C14_missing_gemini_credential_needs_setup(self):
        from studio_tools.doctor import inspect
        config=load(overrides={'credentials':{'gemini':'TEST_ABSENT_REVIEW_KEY'}})
        with patch.dict('os.environ',{},clear=True):
            result=inspect(config)['capabilities']['review_video_analysis']
        self.assertEqual(result['status'],'needs_setup');self.assertFalse(result['credential_present'])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'installed media tools required')
class MediaCorrections(ReviewFixture):
    def source(self, name='media', length=2, delay=0):
        path=self.root/'artifacts'/f'{name}.mp4';path.parent.mkdir(exist_ok=True)
        args=['ffmpeg','-v','error','-n','-f','lavfi','-i',f'testsrc2=size=64x64:rate=30:duration={length}', '-f','lavfi','-i','anullsrc=r=16000:cl=mono']
        if delay:args+=['-vf',f'setpts=PTS+{delay}/TB','-vsync','vfr']
        subprocess.run(args+['-t','2','-c:v','mpeg4','-c:a','aac',str(path)],check=True,capture_output=True)
        return path

    def captured(self,role='standalone',previous=None):
        name=v.prepare_run(self.root,self.card,self.candidate,role=role,previous=previous,affected=['TEMP'] if previous else None)
        source=self.root/'artifacts/full.mp4'
        if not source.exists():source=self.source('full')
        self.assertEqual(m.capture(self.config,self.root,name,{'route':'file','source':str(source)})['status'],'completed')
        return name

    def test_C03_short_or_delayed_video_not_hidden_by_audio(self):
        for label,length,delay in [('short',.3,0),('delay',1,.5)]:
            name=v.prepare_run(self.root,self.card,self.candidate)
            result=m.capture(self.config,self.root,name,{'route':'file','source':str(self.source(label,length,delay))})
            self.assertEqual(result['status'],'incomplete')

    def test_C01_unapproved_dense_image_is_not_submitted(self):
        name=self.captured();dense=m.dense_frames(self.config,self.root,name,[.7,1.3])
        wrong=self.root/'artifacts/unrelated.png';wrong.write_bytes((self.root/dense['frames'][-1]['path']).read_bytes())
        dense['frames'][0].update(file_record(self.root,wrong));write_json(self.root/'artifacts/forged.json',dense)
        with self.assertRaises(StudioError):video.build_request(self.root,name,funded_budget(sha256(self.root/name/'capture.mp4')),'artifacts/forged.json')

    def test_C12_edited_assessment_rejected(self):
        name=self.captured();v.assess(self.root,name)
        target=self.root/name/'assessment.json';assessment=read_json(target);assessment['results'][0]['status']='pass';write_json(target,assessment)
        with self.assertRaises(StudioError):v.validate_run(self.root,name)

    def test_C09_different_baseline_not_comparable(self):
        first=self.captured('before');other=self.captured('before');after=self.captured('after',other)
        v.assess(self.root,first);v.assess(self.root,after)
        result=v.compare_runs(self.root,first,after)
        self.assertFalse(result['comparable'])

    def test_C18_malformed_probe_retains_failure_receipt(self):
        name=v.prepare_run(self.root,self.card,self.candidate)
        source=self.source()
        with patch('studio_tools.review_media.inspect_media',side_effect=ValueError('bad metadata')):
            result=m.capture(self.config,self.root,name,{'route':'file','source':str(source)})
        self.assertEqual(result['status'],'incomplete');self.assertTrue((self.root/name/'capture.json').exists())


    def test_C15_actual_transport_http_rejections_are_bounded_and_redacted(self):
        import urllib.error
        for code in (400,401,429):
            name=self.captured();budget=funded_budget(sha256(self.root/name/'capture.mp4'));budget['authorization_id']=f'http-{code}'
            error=urllib.error.HTTPError(video.ENDPOINT,code,'provider failure',{'Retry-After':'1','x-request-id':'test'},io.BytesIO(b'private-test-key'+b'x'*4000001))
            with patch.dict('os.environ',{'GEMINI_API_KEY':'private-test-key'}), patch('studio_tools.review_video.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect=error
                result=video.analyze(self.config,self.root,name,budget)
                self.assertEqual(opener.return_value.open.call_count,1)
            self.assertEqual(result['status'],'rejected');self.assertEqual(result['http_status'],code)
            raw=(self.root/name/'analysis-request/response.error.original').read_bytes()
            self.assertLessEqual(len(raw),4000000);self.assertNotIn(b'private-test-key',raw)
            state=read_json(self.root/name/'analysis-request/outcome.json')
            self.assertTrue(state['response_truncated']);self.assertEqual(state['response_headers']['Retry-After'],'1')
            with self.assertRaises(StudioError):video.analyze(self.config,self.root,name,budget)

    def test_C15_received_invalid_is_distinct_from_ambiguous(self):
        for kind in ('missing_usage','wrong_model','bad_json','oversized'):
            name=self.captured();budget=funded_budget(sha256(self.root/name/'capture.mp4'));budget['authorization_id']=kind.replace('_','-')
            identity={'run_id':read_json(self.root/name/'run.json')['run_id'],'candidate_id':'sample','clip_sha256':budget['approved_media_sha256'][0]}
            raw={'id':'received','model':budget['model'],'status':'completed','usage':{'total_tokens':100},'steps':[{'type':'model_output','content':[{'type':'text','text':json.dumps({**identity,'findings':[]})}]}]}
            if kind=='missing_usage':raw.pop('usage')
            if kind=='wrong_model':raw['model']='different'
            body=b'bad' if kind=='bad_json' else b'x'*4000001 if kind=='oversized' else json.dumps(raw).encode()
            with patch.dict('os.environ',{'GEMINI_API_KEY':'test'}),patch('studio_tools.review_video._submit',return_value=body) as submit:
                result=video.analyze(self.config,self.root,name,budget)
                submit.assert_called_once()
            self.assertEqual(result['status'],'received_invalid');self.assertFalse(result['ok'])
            self.assertTrue((self.root/name/'analysis-request/response.original.json').exists())

    def test_C11_raw_actions_need_bound_clock_source_and_scope(self):
        self.card['criteria']=[{'id':'INPUT','dimension':'interaction','kind':'interaction','action_ids':['walk'],'expected':'become active','expected_state':'active','mandatory':True,'interval':[0,2]}]
        name=self.captured();notes=self.root/'artifacts/action-clock.txt';notes.write_text('Synthetic .5s input marker then 1.0s state; generator clock and raw state log')
        trace={'run_sha256':sha256(self.root/name/'run.json'),'clip_sha256':sha256(self.root/name/'capture.mp4'),'observer':'test generator','provenance':'synthetic','input_route':'synthetic',
            'clock':{'offset_seconds':0,'uncertainty_seconds':.001,'precision_seconds':1e-6},'source_evidence':file_record(self.root,notes),
            'actions':[{'id':'walk','input_seconds':.5,'outcome_seconds':1,'before_state':'idle','after_state':'active'}]}
        path=self.root/'artifacts/actions.json';write_json(path,trace)
        facts={'run_id':read_json(self.root/name/'run.json')['run_id'],'candidate_id':'sample','clip_sha256':trace['clip_sha256'],'input_route':'synthetic','action_source':file_record(self.root,path)}
        fp=self.root/'artifacts/facts.json';write_json(fp,facts)
        result=v.assess(self.root,name,fp.relative_to(self.root).as_posix())
        self.assertEqual(result['results'][0]['status'],'pass');self.assertEqual(result['results'][0]['evidence_scope'],'test');self.assertFalse(result['technical_criteria_complete'])
        trace['clock']['uncertainty_seconds']=.3;write_json(path,trace)
        checked,_=v.action_trace(self.root,file_record(self.root,path),{'sha256':trace['run_sha256'],'input_route':'synthetic'},trace['clip_sha256'],self.card['criteria'][0])
        self.assertEqual(checked['status'],'unverified')
        trace['run_sha256']='stale';write_json(path,trace)
        with self.assertRaises(StudioError):v.action_trace(self.root,file_record(self.root,path),{'sha256':'actual','input_route':'synthetic'},trace['clip_sha256'],self.card['criteria'][0])

    def test_C11_performance_provenance_recorder_off_and_model_disagreement(self):
        self.card['criteria']=[{'id':'PERF','dimension':'performance','kind':'performance','action_ids':['walk'],'expected':'below floor','mandatory':True,'interval':[0,2],'p95_ms':40,'requires_recorder_off':True}]
        name=self.captured();folder=self.root/name
        on=[{'time_seconds':i*.02,'frame_ms':20} for i in range(100)]
        off=[{'time_seconds':i*.025,'frame_ms':25} for i in range(80)]
        write_json(folder/'on.json',on);write_json(folder/'off.json',off);(folder/'host.txt').write_text('TEST generator; clocks and no interference are deterministic synthetic facts')
        clock={'offset_seconds':0,'uncertainty_seconds':0,'precision_seconds':1e-6};support=file_record(self.root,folder/'host.txt')
        context={'observer':'test','provenance':'synthetic','clock':clock,'clock_evidence':support,'host_evidence':support,
            'run_sha256':sha256(folder/'run.json'),'timing_sha256':sha256(folder/'on.json'),'settings':self.card['settings'],'host_interference':'none_observed','measurement_id':'on','recording_active':True}
        write_json(folder/'on-context.json',context)
        off_context={**context,'measurement_id':'off','recording_active':False,'timing_sha256':sha256(folder/'off.json'),'route_id':self.card['route_id'],'candidate_digest':self.candidate['content_digest']}
        write_json(folder/'off-context.json',off_context)
        reference={'settings':self.card['settings'],'route_id':self.card['route_id'],'candidate_digest':self.candidate['content_digest'],'file':file_record(self.root,folder/'off.json'),'context':file_record(self.root,folder/'off-context.json')}
        facts={'run_id':read_json(folder/'run.json')['run_id'],'candidate_id':'sample','clip_sha256':sha256(folder/'capture.mp4'),'input_route':'synthetic',
            'timing':{'file':file_record(self.root,folder/'on.json'),'method':'wall_frame_time','interval':[0,2],'clock_offset_seconds':0,'clock_uncertainty_seconds':0,'context':file_record(self.root,folder/'on-context.json'),'recorder_off':reference}}
        # Analyzer disagreement cannot overrule measured performance.
        write_json(folder/'analysis.json',{'run_sha256':sha256(folder/'run.json'),'status':'observations_received','findings':[{'criterion_id':'PERF','status':'fail','interval':[0,2],'observation':'model proposal'}],'files':[]})
        write_json(folder/'facts.json',facts)
        result=v.assess(self.root,name,(folder/'facts.json').relative_to(self.root).as_posix())
        self.assertEqual(result['results'][0]['status'],'pass');self.assertEqual(result['results'][0]['recorder_off']['p95_delta_ms'],-5)
        # Same measurement relabeled off is rejected even after updating adjacent hashes.
        off_context['measurement_id']='on';write_json(folder/'off-context.json',off_context)
        facts['timing']['recorder_off']['context']=file_record(self.root,folder/'off-context.json')
        write_json(folder/'observations.original.json',facts)
        # Recompute deliberately bypasses stale assessment references only in this unit control.
        with patch('studio_tools.validation.validate_run',return_value=read_json(folder/'run.json')):
            with self.assertRaisesRegex(StudioError,'distinct'):v.assess(self.root,name,_recompute=True)

    def test_C03_audio_criterion_needs_audio_stream_coverage(self):
        self.card['criteria'].append({'id':'SOUND','dimension':'audio','kind':'audio','action_ids':['walk'],'expected':'cue','mandatory':True,'interval':[0,2]})
        full=self.source('with-audio');silent=self.root/'artifacts/no-audio.mp4'
        subprocess.run(['ffmpeg','-v','error','-n','-i',str(full),'-an','-c:v','copy',str(silent)],check=True,capture_output=True)
        name=v.prepare_run(self.root,self.card,self.candidate)
        self.assertEqual(m.capture(self.config,self.root,name,{'route':'file','source':str(silent)})['status'],'incomplete')

    def test_C18_duplicate_original_directory_is_clear_error(self):
        folder=self.root/'artifacts/exists';folder.mkdir(parents=True)
        with self.assertRaisesRegex(StudioError,'destination exists'):m.fixtures(self.config,folder)



class LifecycleCorrections(unittest.TestCase):
    def test_C16_cancel_before_start_is_a_barrier(self):
        from studio_tools.processes import record
        with tempfile.TemporaryDirectory() as root, patch('studio_tools.processes.subprocess.Popen') as start:
            result = record(['unused'], job_dir=Path(root)/'job', duration=.1, cancelled=lambda: True)
            start.assert_not_called()
            self.assertEqual(result['status'], 'cancelled')
            self.assertEqual(result['stop_reason'], 'cancelled_before_start')

    def test_C16_startup_budget_allows_natural_completion(self):
        import sys
        from studio_tools.processes import record
        with tempfile.TemporaryDirectory() as root:
            result = record([sys.executable, '-u', '-c', "import time; time.sleep(.1); print('ready'); time.sleep(.15); print('finalized')"],
                job_dir=Path(root)/'job', duration=.15, startup=.2, grace=.3)
            self.assertEqual(result['status'], 'completed')
            self.assertIsNone(result['stop_reason'])
            self.assertIn('ready', (Path(root)/'job/stdout.log').read_text())

    def test_C16_failed_cleanup_preserves_timeout(self):
        from studio_tools.processes import record
        from unittest.mock import MagicMock
        child=MagicMock();child.pid=123;child.returncode=None;child.poll.return_value=None
        child.wait.side_effect=subprocess.TimeoutExpired('test', .01)
        with tempfile.TemporaryDirectory() as root, patch('studio_tools.processes.subprocess.Popen', return_value=child), patch('studio_tools.processes._stop_owned', side_effect=OSError):
            result=record(['unused'], job_dir=Path(root)/'job', duration=.001, grace=.001)
            self.assertEqual(result['status'], 'timed_out');self.assertEqual(result['cleanup'], 'unverified')
            self.assertEqual(read_json(Path(root)/'job/process.json')['status'], 'timed_out')

    def test_C13_native_exact_scope_and_deadline(self):
        import platform
        keys=dict(output_index=0,offset_x=2,offset_y=3,width=64,height=64,fps=30,encoder='h264_nvenc',audio_device='Master',startup_seconds=2,finalize_seconds=2)
        profile={**keys,'host':platform.node(),'operator':'named','target':'original-window'}
        profile['authorization']={'permitted_recorder':'ffmpeg_ddagrab','operator':'named','target':'original-window','receipt':'explicit-test','deadline_utc':(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat(),'capture':keys.copy(),'audio_device':'Master'}
        with patch('studio_tools.review_media.os.name','nt'):
            args=m._native_args(profile,2);self.assertIn('passthrough',args)
            for key in keys:
                changed=copy.deepcopy(profile);changed[key]=None
                with self.subTest(key=key), self.assertRaises(StudioError):m._native_args(changed,2)
            for deadline in ('bad','2026-09-06T00:00:00',(datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat()):
                changed=copy.deepcopy(profile);changed['authorization']['deadline_utc']=deadline
                with self.assertRaises(StudioError):m._native_args(changed,2)

    def test_C07_complete_wall_interval_control_and_cumulative_holes(self):
        clean=[{'time_seconds':i*.01,'frame_ms':10} for i in range(200)]
        self.assertEqual(len(v.wall_rows(clean,[0,2],0,1e-6)),200)
        for i,row in enumerate(clean):row.update(time_seconds=i*.011,frame_ms=10)
        with self.assertRaises(StudioError):v.wall_rows(clean,[0,2.2],0,1e-6)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'installed media tools required')
class QualificationCorrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        cls.seed=tempfile.TemporaryDirectory()
        path=Path(__file__).resolve().parents[1]/'examples/review-loop/qualification.py'
        spec=importlib.util.spec_from_file_location('qualification_example',path);example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)
        cls.result=example.create(cls.seed.name)

    @classmethod
    def tearDownClass(cls):cls.seed.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);shutil.copytree(self.seed.name,self.root,dirs_exist_ok=True)
        self.config=read_json(self.root/'artifacts/test-host-config.json')
        self.target=self.result['runs']['M10']

    def approved(self, value, name='new-review'):
        path=self.root/'artifacts'/f'{name}.json';write_json(path,value)
        self.config['review_trust'][value['observer']]['approved_sha256'].append(sha256(path))
        return path.relative_to(self.root).as_posix()

    def test_C04_ten_roles_close_test_criteria_not_actual_capability(self):
        from studio_tools import review_records as r
        record=r.imported(self.root,self.result['qualification'],'review-qualification',config=self.config)
        self.assertTrue(record['qualified']);self.assertEqual(len(record['scores']),10)
        self.assertEqual(record['scores'][2]['status'],'unsupported')
        self.assertEqual(record['minimum_event_seconds'],.1);self.assertEqual(record['max_gap_seconds'],.0334)
        checked=v.validate_run(self.root,self.target,current=False,config=self.config)
        assessment=read_json(self.root/self.target/'assessment.json')
        self.assertEqual({x['criterion_id'] for x in assessment['results'] if x['status']=='pass'},{'TEMP','SOUND','WORLD'})
        self.assertFalse(assessment['technical_criteria_complete'])
        self.assertEqual(assessment['production_acceptance'],'pending_independent_review')
        self.assertEqual(checked['card']['input_route'],'synthetic')

    def test_C04_named_failures_and_timing_review_are_executable(self):
        from studio_tools import review_records as r
        card=read_json(self.root/self.target/'run.json')['card'];candidate=read_json(self.root/self.target/'run.json')['candidate']
        card['criteria']=[{'id':'PERF','dimension':'performance','kind':'performance','action_ids':['move'],'expected':'floor','mandatory':True,'interval':[0,2],'p95_ms':40}]
        name=v.prepare_run(self.root,card,candidate)
        m.capture(self.config,self.root,name,{'route':'file','source':str(self.root/'artifacts/originals/clean.mp4')})
        source=read_json(self.root/'artifacts/test-observations.json')
        source.update(run_sha256=sha256(self.root/name/'run.json'),clip_sha256=sha256(self.root/name/'capture.mp4'))
        source['observations']=[{'criterion_id':'PERF','kind':'performance','status':'pass','interval':[0,2],'observation':'Synthetic bounded wall timing review',
            'files':[file_record(self.root,self.root/'artifacts/originals/clean-timing.json')],
            'wall_timing':{'method':'wall_frame_time','p95_ms':33.334,'max_ms':33.334,'clock_uncertainty_seconds':0,'host_interference':'none_observed'}}]
        adopted=r.ingest(self.config,self.root,name,self.approved(source))
        facts={'run_id':read_json(self.root/name/'run.json')['run_id'],'candidate_id':candidate['candidate_id'],'clip_sha256':source['clip_sha256'],'input_route':'synthetic','reviews':[adopted]}
        path=self.root/'artifacts/performance-facts.json';write_json(path,facts)
        self.assertEqual(v.assess(self.root,name,path.relative_to(self.root).as_posix(),config=self.config)['results'][0]['status'],'pass')
        source['observations'][0]['wall_timing']['method']='encoded_fps'
        with self.assertRaises(StudioError):r.ingest(self.config,self.root,name,self.approved(source))
        temporal={'interval':[0,2],'max_gap_seconds':.0334}
        self.assertEqual(v.temporal_gate(temporal,[0,1],{},review={'status':'fail','reason':'Observed disappearance'})['status'],'fail')

    def test_C04_forged_receipt_cannot_bypass_host_checkpoint(self):
        from studio_tools import review_records as r
        receipt=read_json(self.root/self.result['review']['path'])
        original=self.root/receipt['files'][0]['path'];value=read_json(original)
        value['observations'][0]['observation']='Forged revised approval';write_json(original,value)
        receipt['review']=value;receipt['authorization']['approved_sha256']=sha256(original)
        checkpoint=self.root/receipt['files'][1]['path'];write_json(checkpoint,receipt['authorization'])
        receipt['files']=[file_record(self.root,original),file_record(self.root,checkpoint)]
        forged=self.root/'artifacts/forged-receipt.json';write_json(forged,receipt)
        with self.assertRaisesRegex(StudioError,'review_trust'):r.imported(self.root,file_record(self.root,forged),config=self.config)

    def test_C04_corpus_controls_tolerances_and_test_scope_enforced(self):
        from studio_tools import review_records as r
        evaluation=read_json(self.root/'artifacts/test-evaluation.json')
        for mutate in (lambda e:e['cases'].pop(),lambda e:e.update(scope='operational'),lambda e:e.update(observer='test generator')):
            altered=copy.deepcopy(evaluation);mutate(altered)
            with self.assertRaises(StudioError):r.qualification_data(self.root,altered)
        corpus=read_json(self.root/evaluation['corpus']['path']);corpus['roles']['M02']['tolerance_seconds']=1
        path=self.root/'artifacts/widened-corpus.json';write_json(path,corpus);evaluation['corpus']=file_record(self.root,path)
        with self.assertRaisesRegex(StudioError,'tolerances'):r.qualification_data(self.root,evaluation)

    def test_C04_model_profile_and_missing_raw_response_rejected(self):
        from studio_tools import review_records as r
        analysis=read_json(self.root/self.target/'analysis.json')
        for key,value in [('model','another-model'),('profile',{'max_output_tokens':1}),('analysis_tool',{'source_digest':'stale'})]:
            altered=copy.deepcopy(analysis);altered[key]=value
            with self.assertRaises(StudioError):r.qualified(self.root,self.result['qualification'],altered,config=self.config)
        raw=self.root/self.result['runs']['M02']/'analysis-request/response.original.json';raw.write_text('{}')
        with self.assertRaises(StudioError):r.qualified(self.root,self.result['qualification'],analysis,config=self.config)

    def test_C04_named_audio_stale_partial_source_and_route_rejected(self):
        from studio_tools import review_records as r
        source=read_json(self.root/'artifacts/test-observations.json')
        sound=next(o for o in source['observations'] if o['kind']=='audio')
        for mutate in (lambda o:o.update(interval=[.2,2]),lambda o:o['listening'].update(performed=False),lambda o:o['audio_relation'].update(source_sha256='stale'),lambda o:o['audio_relation'].update(capture_source='wrong'),lambda o:o['listening'].update(playback_route='other')):
            altered=copy.deepcopy(source);audio=next(o for o in altered['observations'] if o['kind']=='audio');mutate(audio)
            with self.assertRaises(StudioError):r.ingest(self.config,self.root,self.target,self.approved(altered))
        self.assertNotEqual(sound['audio_relation']['capture_source'],sound['audio_relation']['output_route'])
        self.assertTrue(r.ingest(self.config,self.root,self.target,self.approved(source)))

    def test_C12_all_derived_decision_fields_are_verified(self):
        target=self.root/self.target/'assessment.json';original=read_json(target)
        for key,value in [('pending',[]),('technical_criteria_complete',True),('next_decision','accept'),('files',[]),('production_acceptance','accepted')]:
            edited=copy.deepcopy(original);edited[key]=value
            if edited==original:continue
            write_json(target,edited)
            with self.subTest(key=key),self.assertRaises(StudioError):v.validate_run(self.root,self.target,current=False,config=self.config)
        write_json(target,original)
        self.assertTrue(v.validate_run(self.root,self.target,current=False,config=self.config))

    def test_C06_acquisition_fps_and_unknown_settings_but_not_realized_loss(self):
        # Source-free compare uses actual acquisition metadata; analysis isn't needed.
        root=self.root
        candidate=read_json(root/self.target/'run.json')['candidate'];card=read_json(root/self.target/'run.json')['card']
        before=v.prepare_run(root,card,candidate,role='before')
        after=v.prepare_run(root,card,candidate,role='after',previous=before,affected=['TEMP'])
        for run,case in ((before,'recorder_drop'),(after,'clean')):
            m.capture(self.config,root,run,{'route':'file','source':str(root/'artifacts/originals'/f'{case}.mp4')});v.assess(root,run)
        self.assertTrue(v.compare_runs(root,before,after)['comparable'])
        b30=v.prepare_run(root,card,candidate,role='before');a60=v.prepare_run(root,card,candidate,role='after',previous=b30,affected=['TEMP'])
        for run,case in ((b30,'clean'),(a60,'single')):
            m.capture(self.config,root,run,{'route':'file','source':str(root/'artifacts/originals'/f'{case}.mp4')});v.assess(root,run)
        self.assertIn('capture stream settings',v.compare_runs(root,b30,a60)['mismatches'])
        path=root/after/'capture.json';saved=read_json(path);changed=copy.deepcopy(saved);changed['media']['streams'][0]['r_frame_rate']='60/1';write_json(path,changed)
        # Assessment integrity notices capture drift before comparison can adopt it.
        with self.assertRaises(StudioError):v.compare_runs(root,before,after)
        write_json(path,saved)
        third=copy.deepcopy(card);third['settings']['renderer']='unknown'
        a=v.prepare_run(root,third,candidate,role='before');b=v.prepare_run(root,third,candidate,role='after',previous=a,affected=['TEMP'])
        self.assertIn('effective comparison settings unknown',v.compare_runs(root,a,b)['mismatches'])
