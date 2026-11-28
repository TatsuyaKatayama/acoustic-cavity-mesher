"""Independent geometry checks for B3 retention and policy compliance."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS

from b3_check import check_geometry, check_task, indexed, retained_coverage
from b3_build import build_task, json_bytes
from b3_task import create_task
from b2_review import make_handoff
from b2_simplification import build_proposal
import test_b2_web as fixtures
from b1_step import brep_bytes


class B3CheckerTests(unittest.TestCase):
    def task(self, source, decision='keep', policy='preserve_volume'):
        count = indexed(source, TopAbs_FACE).Extent()
        return {'part_id': 'part-1', 'tolerances': {'linear_mm': 1e-6, 'area_mm2': 1e-6},
                'contact_constraints': [], 'face_sets': [{'id': 'test-set', 'decision': decision,
                'faces': [['part-1', i] for i in range(1, count+1)],
                'approximation': {'policy': policy} if decision == 'simplify' else None}]}

    def plan(self):
        return {'operations': [{'source_faces': []}]}

    def test_retained_patch_can_extend_without_preserving_original_edges(self):
        small = cq.Workplane('XY').box(2, 2, 2, centered=(True, True, False)).val()
        large = cq.Workplane('XY').box(4, 4, 2, centered=(True, True, False)).val()
        # Bottom planar patch is retained in a larger bottom face.
        face = min(small.Faces(), key=lambda f:f.Center().z).wrapped
        result = retained_coverage(face, indexed(large.wrapped, TopAbs_FACE), 1e-6, 1e-6)
        self.assertEqual(result['status'], 'ok')
        self.assertAlmostEqual(result['coverage_ratio'], 1)

    def test_missing_retained_patch_is_ng(self):
        source = cq.Workplane('XY').box(2,2,2).val().wrapped
        target = cq.Workplane('XY').box(1,1,2).val().wrapped
        report = check_geometry(self.task(source), source, target, self.plan())
        self.assertEqual(report['status'], 'ng')
        self.assertTrue(any(c.get('uncovered_area_mm2', 0) > 0 for c in report['checks']))

    def test_identical_solid_is_ok_and_not_modified(self):
        source = cq.Workplane('XY').box(2,2,2).val().wrapped
        before = source.HashCode(2147483647) if hasattr(source, 'HashCode') else hash(source)
        self.assertEqual(check_geometry(self.task(source), source, source, self.plan())['status'], 'ok')
        self.assertEqual(before, source.HashCode(2147483647) if hasattr(source, 'HashCode') else hash(source))

    def test_cylindrical_retained_patch_can_extend_axially(self):
        small = cq.Workplane('XY').circle(2).extrude(2).val()
        tall = cq.Workplane('XY').workplane(offset=-1).circle(2).extrude(4).val()
        face = next(f.wrapped for f in small.Faces() if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Cylinder)
        self.assertEqual(retained_coverage(face, indexed(tall.wrapped, TopAbs_FACE), 1e-6, 1e-6)['status'], 'ok')
        wrong = cq.Workplane('XY').circle(3).extrude(2).val()
        self.assertEqual(retained_coverage(face, indexed(wrong.wrapped, TopAbs_FACE), 1e-6, 1e-6)['status'], 'ng')

    def test_opposite_side_coincident_wall_is_not_retained(self):
        source = cq.Workplane('XY').box(2,2,2,centered=(True,True,False)).val()
        other = cq.Workplane('XY').workplane(offset=-2).box(2,2,2,centered=(True,True,False)).val()
        bottom = min(source.Faces(),key=lambda f:f.Center().z).wrapped
        self.assertEqual(retained_coverage(bottom,indexed(other.wrapped,TopAbs_FACE),1e-6,1e-6)['status'],'ng')

    def test_omitted_reference_is_ng_and_semantics_require_review(self):
        source = cq.Workplane('XY').box(2,2,2).val().wrapped
        task = self.task(source, 'omit')
        plan = self.plan()
        plan['operations'][0]['source_faces'] = [['part-1',1]]
        self.assertEqual(check_geometry(task,source,source,plan)['status'],'ng')
        plan['operations'][0]['source_faces'] = []
        self.assertEqual(check_geometry(task,source,source,plan)['status'],'needs_review')

    def test_approximation_requires_policy_scope_and_tolerance(self):
        source = cq.Workplane('XY').box(2,2,2).val().wrapped
        task = self.task(source,'simplify')
        self.assertEqual(check_geometry(task,source,source,self.plan())['status'],'needs_review')
        plan = {**self.plan(),'policy_checks':[{'set_id':'test-set','scope':'whole_part','max_volume_difference_mm3':0.001}]}
        self.assertEqual(check_geometry(task,source,source,plan)['status'],'ok')
        larger = cq.Workplane('XY').box(3,2,2).val().wrapped
        self.assertEqual(check_geometry(task,source,larger,plan)['status'],'ng')
        plan['policy_checks'][0]['scope']='face_set'
        self.assertEqual(check_geometry(task,source,source,plan)['status'],'needs_review')

    def test_freeform_policy_notes_require_separate_semantic_assessment(self):
        source = cq.Workplane('XY').box(2,2,2).val().wrapped
        task = self.task(source,'simplify')
        task['face_sets'][0]['approximation']['notes'] = 'Keep the opening connected while simplifying the side'
        plan = {**self.plan(),'policy_checks':[{'set_id':'test-set','scope':'whole_part','max_volume_difference_mm3':0.001}]}
        report = check_geometry(task,source,source,plan)
        self.assertEqual(report['status'],'needs_review')
        self.assertTrue(any(c['item']=='simplification_policy' and c['status']=='ok' for c in report['checks']))
        note = next(c for c in report['checks'] if c['item']=='policy_notes')
        self.assertEqual(note['status'],'needs_review')
        self.assertEqual(note['notes'],task['face_sets'][0]['approximation']['notes'])
        self.assertIn('not automatically proved',report['detail_policy_verification_scope'])

    def test_envelope_policy_is_independent_of_equal_volume(self):
        source = cq.Workplane('XY').box(2,2,2).val().wrapped
        target = cq.Workplane('XY').box(4,1,2).val().wrapped
        task = self.task(source,'simplify','preserve_envelope')
        plan = {**self.plan(),'policy_checks':[{'set_id':'test-set','scope':'whole_part','max_envelope_difference_mm':0.01}]}
        self.assertEqual(check_geometry(task,source,target,plan)['status'],'ng')

    def test_contact_face_cannot_be_relabeled_simplify(self):
        source = cq.Workplane('XY').box(2,2,2).val().wrapped
        task = self.task(source,'simplify')
        task['contact_constraints']=[{'faces':[['part-1',1],['mate',1]]}]
        self.assertEqual(check_geometry(task,source,source,self.plan())['status'],'ng')


class B3ArtifactCheckerTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.WebReviewTests(methodName='test_pending_handoff_blocked')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        state = fixture.session.save(fixture.accepted())
        simplification = build_proposal(fixture.session.parts, state['draft'])
        for row in simplification['proposals']:
            row['decision'] = 'keep'
        simplification['confirmed'] = True
        simple_path = fixture.bundle/'review.simplification.json'
        simple_path.write_bytes(json_bytes(simplification))
        handoff_path = fixture.bundle/'handoff.json'
        handoff_path.write_bytes(json_bytes(make_handoff(state['draft'], fixture.session.parts, simplification)))
        task = create_task(fixture.bundle, handoff_path, '1/1',
            {'coordinator':'coordinator-agent', 'worker':'worker-agent', 'checker':'checker-agent'},
            candidates=fixture.candidates, review=fixture.review, simplification_review=simple_path)
        self.task_path = fixture.bundle/'task.json'
        self.task_path.write_bytes(json_bytes(task))
        self.artifact = fixture.bundle/'artifact'
        plan = {'schema_version':1, 'operations':[{'id':'body', 'operation':'box', 'combine':'new',
            'parameters':{'length_mm':4, 'width_mm':4, 'height_mm':2},
            'frame':{'origin_mm':[0,0,-2], 'x_direction':[1,0,0], 'normal':[0,0,1]},
            'source_faces':[], 'rationale':'Independent dimension fixture'}]}
        build_task(task, plan, self.artifact)

    def snapshot(self):
        return {str(path.relative_to(self.fixture.bundle)):sha256(path.read_bytes()).hexdigest()
                for path in self.fixture.bundle.rglob('*') if path.is_file()}

    def test_checked_artifact_replays_and_preserves_all_files(self):
        before = self.snapshot()
        report = check_task(self.task_path, self.artifact)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['checker'], 'checker-agent')
        self.assertTrue(any(c['item']=='independent_plan_replay' and c['status']=='ok' for c in report['checks']))
        self.assertEqual(before, self.snapshot())

    def test_unknown_primitive_is_reported_without_executing_code(self):
        artifact_path=self.artifact/'artifact.json'
        artifact=json.loads(artifact_path.read_text(encoding='utf-8'))
        plan_path=self.artifact/'plan.json'
        plan=json.loads(plan_path.read_text(encoding='utf-8'))
        plan['operations'][0]['operation']='specialized_fh_template_step'
        plan_path.write_bytes(json_bytes(plan))
        artifact['plan_sha256']=sha256(plan_path.read_bytes()).hexdigest()
        artifact_path.write_bytes(json_bytes(artifact))
        before=self.snapshot()
        report=check_task(self.task_path,self.artifact)
        self.assertEqual(report['status'],'needs_review')
        replay=next(c for c in report['checks'] if c['item']=='independent_plan_replay')
        self.assertIn('specialized_fh_template_step',replay['reason'])
        self.assertEqual(before,self.snapshot())

    def test_tampered_code_hash_fails_without_repair(self):
        with (self.artifact/'generated.py').open('a',encoding='utf-8') as stream:
            stream.write('# tampered fixture\n')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            check_task(self.task_path, self.artifact)
        self.assertEqual(before,self.snapshot())

    def test_self_consistent_geometry_hashes_do_not_replace_replay(self):
        geometry = brep_bytes(cq.Workplane('XY').box(1,1,1).val().wrapped)
        (self.artifact/'final.brep').write_bytes(geometry)
        (self.artifact/'history-001.brep').write_bytes(geometry)
        artifact_path = self.artifact/'artifact.json'
        artifact = json.loads(artifact_path.read_text(encoding='utf-8'))
        artifact['geometry_sha256'] = sha256(geometry).hexdigest()
        artifact['history'][0]['sha256'] = sha256(geometry).hexdigest()
        artifact_path.write_bytes(json_bytes(artifact))
        before = self.snapshot()
        report = check_task(self.task_path,self.artifact)
        self.assertEqual(report['status'],'ng')
        self.assertTrue(any(c['item']=='independent_plan_replay' and c['status']=='ng' for c in report['checks']))
        self.assertEqual(before,self.snapshot())


if __name__ == '__main__':
    unittest.main()
