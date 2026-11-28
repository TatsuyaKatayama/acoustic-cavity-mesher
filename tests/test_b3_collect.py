"""Coordinator collects reports without mutating artifacts or advancing stages."""
import json
from hashlib import sha256
import unittest
from b3_build import build_task
from b3_check import check_task
from b3_collect import collect
from b3_test_support import assigned_fixture, box_plan

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.f,self.workflow,self.task=assigned_fixture(self)
        self.artifact=self.workflow/'attempt-001'

    def run_attempt(self,plan):
        build_task(self.task,plan,self.artifact)
        report=check_task(self.workflow/'task.json',self.artifact)
        self.report=self.workflow/'check-001.json'
        self.report.write_text(json.dumps(report),encoding='utf-8')
        return report

    def test_checked_workflow_has_no_automatic_next_stage(self):
        report=self.run_attempt(box_plan())
        self.assertEqual(report['status'],'ok')
        before={p.name:sha256(p.read_bytes()).hexdigest() for p in self.artifact.iterdir()}
        result=collect(self.workflow/'task.json',self.artifact,self.report)
        self.assertEqual(result['status'],'checked')
        self.assertFalse(result['automatic_next_stage'])
        self.assertEqual(before,{p.name:sha256(p.read_bytes()).hexdigest() for p in self.artifact.iterdir()})

    def test_bad_model_returns_to_worker(self):
        self.run_attempt(box_plan(length=2))
        result=collect(self.workflow/'task.json',self.artifact,self.report)
        self.assertEqual(result['status'],'return_to_worker')

    def test_forged_pass_report_is_rejected(self):
        report=self.run_attempt(box_plan(length=2))
        report['status']='ok'
        self.report.write_text(json.dumps(report),encoding='utf-8')
        with self.assertRaises(ValueError):collect(self.workflow/'task.json',self.artifact,self.report)

    def test_unresolved_policy_returns_review_required(self):
        def decisions(record):
            row=next(r for r in record['proposals'] if r['face'][0]=='1/1')
            row['decision']='simplify'
            record['sets']=[{'id':'unresolved','name':'Policy pending','decision':'simplify',
                'faces':[row['face']], 'approximation':{'policy':'unspecified', 'notes':'',
                'detail_policy':'omit_chamfers_and_fillets'}}]
        self.f,self.workflow,self.task=assigned_fixture(self,decisions=decisions)
        self.artifact=self.workflow/'attempt-001'
        self.run_attempt(box_plan())
        self.assertEqual(collect(self.workflow/'task.json',self.artifact,self.report)['status'],'review_required')

if __name__=='__main__':unittest.main()
