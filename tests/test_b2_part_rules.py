"""Reusable policies retain provenance and cannot cross geometry or approval gates."""
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
import json
from b2_part_rules import save_rule, find_rules
from b2_propose_part import propose_part
import test_b2_web as fixtures


class PartRuleTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebReviewTests(methodName='test_pending_handoff_blocked')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=Path(self.temp.name)
        self.policy=dict(instruction='接合面を保護し、局所的な凹凸だけ省略候補にする。',
            interpretation=[dict(target='local_detail',action='omit_candidate',reason='主要壁の基本形状を維持する')],
            open_questions=['凹凸の許容差は未指定'])

    def test_versions_are_immutable_and_draft_does_not_change_proposals(self):
        before=propose_part(self.f.bundle,self.f.candidates,self.f.review,'1/1',rule_store=self.store)
        first,_=save_rule(self.f.bundle,'1/1',self.policy,self.store)
        original=first.read_bytes()
        second,_=save_rule(self.f.bundle,'1/1',self.policy,self.store)
        self.assertNotEqual(first,second)
        self.assertEqual(first.read_bytes(),original)
        rules=find_rules(self.f.bundle,'1/1',self.store)
        self.assertEqual(rules[0]['revision'],2)
        self.assertEqual(rules[0]['instruction'],self.policy['instruction'])
        after=propose_part(self.f.bundle,self.f.candidates,self.f.review,'1/1',rule_store=self.store)
        self.assertEqual([r['suggestion'] for r in before['faces']],[r['suggestion'] for r in after['faces']])
        self.assertFalse(after['approved'])

    def test_same_name_alone_cannot_match_family_or_geometry(self):
        save_rule(self.f.bundle,'1/1',self.policy,self.store)
        self.assertFalse(find_rules(self.f.bundle,'1/3',self.store))
        save_rule(self.f.bundle,'1/1',self.policy,self.store,family='housing')
        self.assertFalse(find_rules(self.f.bundle,'1/3',self.store))
        rules=find_rules(self.f.bundle,'1/3',self.store,family='housing')
        self.assertEqual(len(rules),1)
        self.assertFalse(rules[0]['face_bindings_applicable'])

    def test_approved_bindings_apply_but_cannot_omit_pending_contact(self):
        baseline=propose_part(self.f.bundle,self.f.candidates,self.f.review,'1/1',rule_store=self.store)
        protected=next(ref[1] for ref in self.f.original_pair if ref[0]=='1/1')
        other=next(r['face'][1] for r in baseline['faces'] if r['face'][1]!=protected)
        policy=deepcopy(self.policy)
        policy['face_overrides']=[dict(face_index=i,decision='omit',reason='explicit bound exception') for i in (protected,other)]
        save_rule(self.f.bundle,'1/1',policy,self.store,status='approved')
        proposal=propose_part(self.f.bundle,self.f.candidates,self.f.review,'1/1',rule_store=self.store)
        faces={r['face'][1]:r for r in proposal['faces']}
        self.assertEqual(faces[protected]['suggestion'],'keep')
        self.assertEqual(faces[other]['suggestion'],'omit')
        self.assertTrue(faces[other]['rule_sources'])
        self.assertFalse(proposal['approved'])
        self.assertFalse(self.f.review.exists())

    def test_retirement_and_invalid_bindings(self):
        save_rule(self.f.bundle,'1/1',self.policy,self.store,status='approved')
        save_rule(self.f.bundle,'1/1',self.policy,self.store,status='retired')
        self.assertFalse(find_rules(self.f.bundle,'1/1',self.store))
        policy={**self.policy,'face_overrides':[dict(face_index=999,decision='omit',reason='invalid')]}
        with self.assertRaises(ValueError):save_rule(self.f.bundle,'1/1',policy,self.store)

    def test_same_name_reuses_semantic_history_across_changed_geometry_only(self):
        save_rule(self.f.bundle,'1/1',self.policy,self.store,status='approved')
        path=self.f.bundle/'assembly.json'
        manifest=json.loads(path.read_text())
        first=next(n for n in manifest['nodes'] if n['id']=='1/1')
        changed=next(n for n in manifest['nodes'] if n['id']=='1/3')
        changed['definition_name']=first['definition_name']
        path.write_text(json.dumps(manifest))
        rules=find_rules(self.f.bundle,'1/3',self.store)
        self.assertEqual(len(rules),1)
        self.assertEqual(rules[0]['scope']['kind'],'part_name')
        self.assertFalse(rules[0]['face_bindings_applicable'])
        policy=dict(instruction='必要な開口も保護する',interpretation=[dict(target='opening',action='protect',reason='keep flow path')])
        _,record=save_rule(self.f.bundle,'1/3',policy,self.store)
        self.assertEqual(record['revision'],2)
        self.assertEqual(len(record['instruction_history']),2)
        self.assertEqual(len(record['interpretation']),2)


if __name__=='__main__':unittest.main()
