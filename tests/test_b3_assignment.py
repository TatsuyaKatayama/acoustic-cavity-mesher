"""Coordinator assignment integrity and B2 gating tests."""
from copy import deepcopy
import json
import unittest
from b3_task import load_task, validate_task
from b3_test_support import assigned_fixture

class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.f,self.directory,self.task=assigned_fixture(self)

    def test_single_part_roles_and_face_partition(self):
        task=load_task(self.directory/'task.json')
        self.assertEqual(task['part_id'],'1/1')
        self.assertEqual(len(set(task['roles'].values())),3)
        refs=[tuple(r) for g in task['face_sets'] for r in g['faces']]
        self.assertEqual(len(refs),6)
        self.assertEqual(len(set(refs)),6)
        self.assertEqual(len(task['contact_constraints']),1)
        self.assertTrue((self.directory/'checker.txt').is_file())

    def test_changed_b2_review_invalidates_assignment(self):
        data=json.loads(self.f.review.read_text(encoding='utf-8'))
        data['reviews'][0]['decision']='pending';data['reviews'][0]['condition']=None
        self.f.review.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError):load_task(self.directory/'task.json')

    def test_changed_handoff_or_face_classification_rejected(self):
        task=deepcopy(self.task);task['face_sets'][0]['decision']='omit'
        with self.assertRaises(ValueError):validate_task(task)
        path=self.f.bundle/'handoff.json'
        handoff=json.loads(path.read_text(encoding='utf-8'));handoff['contact_constraints']=[]
        path.write_text(json.dumps(handoff),encoding='utf-8')
        with self.assertRaises(ValueError):load_task(self.directory/'task.json')

    def test_role_self_check_forbidden(self):
        task=deepcopy(self.task);task['roles']['checker']=task['roles']['worker']
        with self.assertRaises(ValueError):validate_task(task)

    def test_pending_simplification_never_assigned(self):
        from b3_task import create_task
        record=json.loads(self.f.session.simplification_path.read_text(encoding='utf-8'))
        record['confirmed']=False
        self.f.session.simplification_path.write_text(json.dumps(record),encoding='utf-8')
        with self.assertRaises(ValueError):
            create_task(self.f.bundle,self.f.bundle/'handoff.json','1/1',self.task['roles'],
                candidates=self.f.candidates,review=self.f.review,simplification_review=self.f.session.simplification_path)

if __name__=='__main__':unittest.main()
