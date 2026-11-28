"""Synthetic generic B5 rebuild checks."""
import json,unittest
from b3_test_support import assigned_fixture,box_plan
from b3_build import build_task
from b5_check_rebuild import check_reassembly
from b5_build_rebuild_space import build_spaces

class B5RebuildTests(unittest.TestCase):
    def setUp(self):
        self.f,self.workflow,self.task=assigned_fixture(self)
        self.artifact=self.workflow/'attempt'

    def test_world_contact_and_neighbors(self):
        build_task(self.task,box_plan(),self.artifact)
        r=check_reassembly(self.workflow/'task.json',self.artifact)
        self.assertEqual(r['status'],'ok');self.assertFalse(r['b6_ready'])
        self.assertAlmostEqual(r['contacts'][0]['gap_mm'],0)
        self.assertEqual(len(r['neighbor_checks']),2)

    def test_missing_contact_detected(self):
        build_task(self.task,box_plan(height=1),self.artifact)
        r=check_reassembly(self.workflow/'task.json',self.artifact)
        self.assertEqual(r['status'],'ng')
        self.assertTrue(r['contacts'][0]['issues'])

    def test_space_identity_is_not_a_leak_approval(self):
        build_task(self.task,box_plan(),self.artifact)
        config=self.workflow/'space-config.json'
        config.write_text(json.dumps({'schema_version':1,'length_unit':'mm','cylinder':{'origin_mm':[0,0,-3],'axis':[0,0,1],'radius_mm':5,'height_mm':6}}),encoding='utf-8')
        r=build_spaces(self.workflow/'task.json',self.artifact,config,self.workflow/'space')
        self.assertEqual(r['status'],'needs_review')
        self.assertAlmostEqual(r['air_increase_mm3'],0)
        self.assertAlmostEqual(r['air_decrease_mm3'],0)
        self.assertTrue(r['pending_checks'])

if __name__=='__main__':unittest.main()
