"""B6 provisional evidence cannot become an approved registration."""
import json,unittest
from b3_test_support import assigned_fixture,box_plan
from b3_build import build_task
from b3_check import check_task
from b4_check_rebuild import check_rebuild
from b5_check_rebuild import check_reassembly
from b5_build_rebuild_space import build_spaces
from b6_create_candidate import package_candidate

class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.f,self.workflow,self.task=assigned_fixture(self)
        self.artifact=self.workflow/'attempt'
        build_task(self.task,box_plan(),self.artifact)

    def test_all_evidence_still_requires_human_review(self):
        task=self.workflow/'task.json'
        reports={}
        for stage,result in [('B3',check_task(task,self.artifact)),
                ('B4',check_rebuild(task,self.artifact,max_error_mm3=.001)),
                ('B5_contacts',check_reassembly(task,self.artifact))]:
            path=self.workflow/(stage+'.json');path.write_text(json.dumps(result),encoding='utf-8');reports[stage]=path
        config=self.workflow/'config.json';config.write_text(json.dumps({'schema_version':1,'length_unit':'mm','cylinder':{'origin_mm':[0,0,-3],'axis':[0,0,1],'radius_mm':5,'height_mm':6}}),encoding='utf-8')
        space=self.workflow/'space';build_spaces(task,self.artifact,config,space)
        reports['B5_space']=space/'space-report.json'
        output=self.workflow/'candidate'
        result=package_candidate(task,self.artifact,reports,output,space_dir=space)
        self.assertFalse(result['registered']);self.assertEqual(result['status'],'pending_human_review')
        self.assertTrue(result['blocking_checks'])
        self.assertTrue((output/'artifact'/'generated.py').exists())
        with self.assertRaises(ValueError):package_candidate(task,self.artifact,reports,output,space_dir=space)

    def test_missing_evidence_rejected(self):
        with self.assertRaises(ValueError):package_candidate(self.workflow/'task.json',self.artifact,{},self.workflow/'bad')
        self.assertFalse((self.workflow/'bad').exists())

if __name__=='__main__':unittest.main()
