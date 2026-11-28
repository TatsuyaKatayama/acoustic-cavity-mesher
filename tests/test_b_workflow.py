"""Workflow routing checks without external providers or real CAD."""
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import trial_rebuild_step_part as workflow
from b3_build import json_bytes


class TrialWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.task={'schema_version':1,'part_id':'1/1','review_mode':'provisional_trial',
            'roles':{'coordinator':'c','worker':'w','checker':'i'}}
        self.task_path=self.root/'task.json';self.task_path.write_bytes(json_bytes(self.task))
        self.config={'schema_version':1,'roles':{role:{'argv':[sys.executable]} for role in ('coordinator','worker','checker')}}
        self.space=self.root/'space.json';self.space.write_text('{}',encoding='utf-8')
        self.output=self.root/'run'
        self.events=[]
        for name in ('load_task','run_acp','check_task','check_rebuild','check_reassembly','build_spaces','package_candidate'):
            mock=patch.object(workflow,name).start();self.addCleanup(patch.stopall);setattr(self,name,mock)
        self.load_task.return_value=self.task
        self.run_acp.side_effect=self.acp
        self.check_task.side_effect=lambda *a:self.record('B3')
        self.check_rebuild.side_effect=lambda *a,**k:self.b4()
        self.check_reassembly.side_effect=lambda *a,**k:self.record('B5_contacts')
        self.build_spaces.side_effect=lambda *a,**k:self.record('B5_space')
        self.package_candidate.side_effect=self.package

    def acp(self,task,config,output):
        self.events.append('ACP')
        directory=Path(output)/'attempt-001';directory.mkdir(parents=True)
        (directory/'artifact.json').write_text('{"synthetic":true}',encoding='utf-8')
        (directory/'final.brep').write_bytes(b'synthetic-placeholder-not-read-by-routing-test')
        (Path(output)/'agent-check.json').write_text(json.dumps({'status':'needs_review','findings':['Synthetic routing test']}),encoding='utf-8')
        (Path(output)/'workflow.json').write_text(json.dumps({'status':'review_required'}),encoding='utf-8')
        self.artifact=directory
        return {'status':'review_required','artifact':str(directory)}

    def record(self,stage,status='needs_review'):
        self.events.append(stage)
        return {'stage':stage,'status':status,'task_sha256':sha256(json_bytes(self.task)).hexdigest(),
                'artifact_sha256':sha256((self.artifact/'artifact.json').read_bytes()).hexdigest()}

    def b4(self):
        result=self.record('B4','ng')
        result.update(fit_reachability={'status':'needs_review'},simplification_suitability={'status':'ng'})
        return result

    def package(self,task,artifact,reports,output,**kwargs):
        self.events.append('B6')
        self.assertEqual(set(reports),{'B3','B4','B5_contacts','B5_space'})
        self.assertTrue(all(Path(path).is_file() for path in reports.values()))
        return {'registered':False,'status':'pending_human_review','blocking_checks':[{'stage':'B4','status':'ng'}]}

    def run_trial(self):
        return workflow.run_trial(self.task_path,self.config,self.space,self.output,max_error_mm3=5,max_bbox_difference_mm=1)

    def test_single_part_routing_keeps_two_stage_b4_and_ng_as_candidate_evidence(self):
        result=self.run_trial()
        self.assertEqual(self.events,['ACP','B3','B4','B5_contacts','B5_space','B6'])
        self.assertEqual(result['status'],'candidate_pending_human_review')
        self.assertFalse(result['registered']);self.assertTrue(result['human_review_pending'])
        self.assertEqual(result['stages']['B4']['fit_reachability'],'needs_review')
        self.assertEqual(result['stages']['B4']['simplification_suitability'],'ng')
        self.assertEqual(result['stages']['B6']['blocking_checks'],[{'stage':'B4','status':'ng'}])

    def test_provider_failure_permission_or_b3_ng_never_advances(self):
        for index,status in enumerate(('failed','permission_required','cancelled','return_to_worker')):
            with self.subTest(status=status):
                self.output=self.root/('failed-'+str(index))
                self.run_acp.side_effect=None;self.run_acp.return_value={'status':status}
                result=self.run_trial()
                self.assertEqual(result['status'],'stopped_at_B3')
        self.check_rebuild.assert_not_called();self.package_candidate.assert_not_called()

    def test_b3_ng_artifact_continues_as_explicitly_nonconforming_diagnostic_trial(self):
        original=self.acp
        def ng(*args):
            result=original(*args);result['status']='return_to_worker';return result
        self.run_acp.side_effect=ng
        result=self.run_trial()
        self.assertEqual(self.events,['ACP','B3','B4','B5_contacts','B5_space','B6'])
        self.assertTrue(result['b3_requires_rework'])
        self.assertEqual(result['conformance_status'],'ng')
        self.assertFalse(result['registered'])
        self.assertTrue(result['human_review_pending'])

    def test_full_workflow_requires_explicit_provisional_scope(self):
        self.task['review_mode']='approved'
        with self.assertRaisesRegex(ValueError,'provisional_trial'):self.run_trial()
        self.run_acp.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failed_b5_measurement_is_honest_bound_candidate_evidence(self):
        self.build_spaces.side_effect=RuntimeError('OCCT boolean failed')
        result=self.run_trial()
        self.assertEqual(result['status'],'candidate_pending_human_review')
        report=json.loads((self.output/'b5-space-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['status'],'needs_review')
        self.assertEqual(report['measurement_status'],'failed')
        self.assertEqual(report['measurement_error']['message'],'OCCT boolean failed')
        self.assertEqual(report['task_sha256'],result['task_sha256'])
        self.assertEqual(report['configuration_sha256'],sha256(self.space.read_bytes()).hexdigest())
        self.assertEqual(report['files'],{})
        self.assertIsNone(self.package_candidate.call_args.kwargs['space_dir'])

    def test_artifact_changes_during_measurement_cannot_be_packaged(self):
        def tamper(*args,**kwargs):
            (self.artifact/'final.brep').write_bytes(b'modified')
            raise RuntimeError('measurement failed after modification')
        self.check_reassembly.side_effect=tamper
        result=self.run_trial()
        self.assertEqual(result['status'],'failed')
        self.assertIn('artifact changed',result['error']['message'])
        self.package_candidate.assert_not_called()

    def test_source_report_binding_mismatch_stops_before_b4(self):
        def wrong(*args):
            report=self.record('B3');report['task_sha256']='wrong-task';return report
        self.check_task.side_effect=wrong
        result=self.run_trial()
        self.assertEqual(result['status'],'failed')
        self.check_rebuild.assert_not_called();self.package_candidate.assert_not_called()

    def test_space_configuration_change_stops_without_candidate(self):
        def changed(*args,**kwargs):
            self.space.write_text('{"changed":true}',encoding='utf-8')
            return self.record('B5_space')
        self.build_spaces.side_effect=changed
        result=self.run_trial()
        self.assertEqual(result['status'],'failed')
        self.assertIn('space configuration changed',result['error']['message'])
        self.package_candidate.assert_not_called()


if __name__=='__main__':unittest.main()
