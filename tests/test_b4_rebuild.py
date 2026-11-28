"""Independent tests of B4 reachability versus suitability for generic rebuilds."""
from hashlib import sha256
import unittest
import json
from unittest.mock import patch
import cadquery as cq
from b4_check_rebuild import compare_rebuild,check_rebuild,MeasurementError
from b3_check import indexed
from OCP.TopAbs import TopAbs_FACE
import test_b3_check as b3_fixture


class B4RebuildTests(unittest.TestCase):
    def task(self,source,keep=True):
        return {'part_id':'part-1','tolerances':{'linear_mm':1e-6,'area_mm2':1e-6},'contact_constraints':[],
                'face_sets':[{'id':'keep-part-1','decision':'keep','faces':[['part-1',i] for i in range(1,indexed(source,TopAbs_FACE).Extent()+1)],'approximation':None}] if keep else []}

    def plan(self):
        return {'operations':[{'source_faces':[]}]}

    def test_exact_source_rebuild_has_zero_space_error(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        report=compare_rebuild(self.task(source),source,source,self.plan(),max_error_mm3=0,max_bbox_difference_mm=0)
        self.assertEqual(report['fit_reachability']['status'],'ok')
        self.assertEqual(report['simplification_suitability']['status'],'ok')
        self.assertEqual(report['space_added_mm3'],0)
        self.assertEqual(report['space_removed_mm3'],0)
        self.assertTrue(report['provisional'])
        self.assertFalse(report['b6_ready'])

    def test_equal_total_volume_can_have_both_space_errors(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        shifted=cq.Workplane('XY').box(2,2,2).translate((1,0,0)).val().wrapped
        report=compare_rebuild(self.task(source,False),source,shifted,self.plan(),max_error_mm3=1)
        self.assertAlmostEqual(report['source_volume_mm3'],report['generated_volume_mm3'])
        self.assertAlmostEqual(report['space_added_mm3'],4)
        self.assertAlmostEqual(report['space_removed_mm3'],4)
        self.assertAlmostEqual(report['space_added_cc'],.004)
        self.assertEqual(report['fit_reachability']['status'],'ok')
        self.assertEqual(report['simplification_suitability']['status'],'ng')

    def test_suitability_pass_does_not_establish_fit_optimality(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        reduced=cq.Workplane('XY').box(1,1,1).val().wrapped
        report=compare_rebuild(self.task(source,False),source,reduced,self.plan(),max_error_mm3=8)
        self.assertEqual(report['simplification_suitability']['status'],'ok')
        self.assertEqual(report['fit_reachability']['optimization_status'],'not_established')
        self.assertEqual(report['status'],'ok')
        self.assertEqual(report['human_review_status'],'pending')

    def test_missing_retained_surface_is_ng_even_with_large_error_limit(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        reduced=cq.Workplane('XY').box(1,1,1).val().wrapped
        report=compare_rebuild(self.task(source),source,reduced,self.plan(),max_error_mm3=100)
        self.assertEqual(report['fit_reachability']['status'],'ng')
        self.assertEqual(report['status'],'ng')

    def test_bbox_criterion_is_separate(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        shifted=cq.Workplane('XY').box(2,2,2).translate((1,0,0)).val().wrapped
        report=compare_rebuild(self.task(source,False),source,shifted,self.plan(),max_error_mm3=100,max_bbox_difference_mm=.01)
        self.assertEqual(report['simplification_suitability']['checks'][0]['status'],'ok')
        self.assertEqual(next(c for c in report['simplification_suitability']['checks'] if c['item']=='world_bbox_difference')['status'],'ng')

    def test_kernel_failure_preserves_unknown_measurement(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        with patch('b4_check_rebuild.solid_difference',side_effect=MeasurementError('IsDone=False')):
            report=compare_rebuild(self.task(source),source,source,self.plan(),max_error_mm3=1000)
        self.assertEqual(report['status'],'needs_review')
        self.assertEqual(report['measurement_status'],'failed')
        self.assertIsNone(report['symmetric_difference_mm3'])
        self.assertIsNone(report['space_added_mm3'])
        self.assertEqual(report['source_volume_mm3'],report['generated_volume_mm3'])
        self.assertEqual(report['simplification_suitability']['status'],'needs_review')

    def test_valid_but_nonconservative_boolean_measurements_are_ng(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        with patch('b4_check_rebuild.solid_difference',side_effect=[1,2]):
            report=compare_rebuild(self.task(source),source,source,self.plan(),max_error_mm3=1000)
        self.assertEqual(report['status'],'ng')
        self.assertEqual(report['measurement_status'],'inconsistent')
        self.assertEqual(report['difference_conservation_residual_mm3'],1)

    def test_invalid_criteria_rejected(self):
        source=cq.Workplane('XY').box(2,2,2).val().wrapped
        for value in (-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):
                compare_rebuild(self.task(source),source,source,self.plan(),max_error_mm3=value)

    def test_specialized_plan_keeps_b3_and_human_review_separate(self):
        fixture=b3_fixture.B3ArtifactCheckerTests(methodName='test_checked_artifact_replays_and_preserves_all_files')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan_path=fixture.artifact/'plan.json'
        plan=json.loads(plan_path.read_text(encoding='utf-8'))
        plan['operations'][0]['operation']='specialized_fh_template_step'
        plan_path.write_text(json.dumps(plan),encoding='utf-8')
        artifact_path=fixture.artifact/'artifact.json'
        artifact=json.loads(artifact_path.read_text(encoding='utf-8'))
        artifact['plan_sha256']=sha256(plan_path.read_bytes()).hexdigest()
        artifact_path.write_text(json.dumps(artifact),encoding='utf-8')
        before=fixture.snapshot()
        report=check_rebuild(fixture.task_path,fixture.artifact,max_error_mm3=0)
        self.assertEqual(report['simplification_suitability']['status'],'ok')
        self.assertEqual(report['b3_independent_status'],'needs_review')
        self.assertEqual(report['status'],'ok')
        self.assertEqual(report['human_review_status'],'pending')
        self.assertEqual(before,fixture.snapshot())

    def test_worker_artifact_and_sources_unchanged_by_b4(self):
        fixture=b3_fixture.B3ArtifactCheckerTests(methodName='test_checked_artifact_replays_and_preserves_all_files')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before=fixture.snapshot()
        report=check_rebuild(fixture.task_path,fixture.artifact,max_error_mm3=0)
        self.assertEqual(report['status'],'ok')
        self.assertEqual(before,fixture.snapshot())


if __name__=='__main__':
    unittest.main()
