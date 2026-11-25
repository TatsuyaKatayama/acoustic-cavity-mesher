"""Synthetic worker tests: dimensional history and prohibited provenance."""

from copy import deepcopy
import unittest

from b3_build import build_history, build_task, generated_code, validate_plan, digest, json_bytes


def task():
    return {'schema_version': 1, 'length_unit': 'mm', 'part_id': '1/1',
            'face_sets': [{'decision': 'keep', 'faces': [['1/1', 1]]},
                          {'decision': 'simplify', 'faces': [['1/1', 2]]},
                          {'decision': 'omit', 'faces': [['1/1', 3]]}]}


def operation(identifier='body', primitive='box', combine='new'):
    return {'id': identifier, 'operation': primitive, 'combine': combine,
            'parameters': {'length_mm': 10, 'width_mm': 8, 'height_mm': 4} if primitive == 'box' else {'radius_mm': 1, 'height_mm': 6},
            'frame': {'origin_mm': [12, 25, 30], 'x_direction': [0, 1, 0], 'normal': [1, 0, 0]},
            'source_faces': [['1/1', 1]], 'rationale': 'Synthetic dimensions in an explicit world datum'}


class B3BuildTests(unittest.TestCase):
    def test_world_frame_and_reproducible_code(self):
        plan = {'schema_version': 1, 'operations': [operation()]}
        validate_plan(task(), plan)
        shape = list(build_history(plan))[-1][1].val()
        self.assertAlmostEqual(shape.Volume(), 320)
        bb = shape.BoundingBox()
        self.assertAlmostEqual(bb.xmin, 12)
        self.assertAlmostEqual(bb.xmax, 16)
        self.assertAlmostEqual(bb.ymin, 20)
        self.assertAlmostEqual(bb.ymax, 30)
        namespace = {'__name__': 'regeneration_test'}
        exec(generated_code(plan), namespace)
        regenerated = namespace['build']().val()
        self.assertAlmostEqual(regenerated.Volume(), shape.Volume())
        self.assertLess(shape.cut(regenerated).Volume()+regenerated.cut(shape).Volume(), 1e-8)

    def test_cut_new_cylinder_from_new_box(self):
        box, hole = operation(), operation('hole', 'cylinder', 'cut')
        hole['frame']['origin_mm'] = [11, 25, 30]
        plan = {'schema_version': 1, 'operations': [box, hole]}
        history = list(build_history(validate_plan(task(), plan)))
        self.assertEqual(len(history), 2)
        from math import pi
        self.assertAlmostEqual(history[-1][1].val().Volume(), 320-4*pi, places=7)
        self.assertAlmostEqual(history[0][1].val().Volume(), 320)

    def test_omitted_and_foreign_face_provenance_rejected(self):
        for ref in (['1/1', 3], ['1/2', 1], ['1/1', 999]):
            op = operation()
            op['source_faces'] = [ref]
            with self.assertRaises(ValueError):
                validate_plan(task(), {'schema_version': 1, 'operations': [op]})

    def test_invalid_parameters_frames_and_operations_rejected(self):
        changes = [('parameters', {'length_mm': float('nan'), 'width_mm': 8, 'height_mm': 4}),
                   ('operation', 'import_brep'), ('combine', 'cut'),
                   ('frame', {'origin_mm': [0, 0, 0], 'x_direction': [1, 0, 0], 'normal': [1, 0, 0]})]
        for key, value in changes:
            op = operation()
            op[key] = value
            with self.assertRaises(ValueError):
                validate_plan(task(), {'schema_version': 1, 'operations': [op]})

    def test_disjoint_union_is_not_a_single_part(self):
        first, second = operation(), operation('detached', combine='union')
        second['frame']['origin_mm'] = [100, 100, 100]
        with self.assertRaises(ValueError):
            list(build_history({'schema_version': 1, 'operations': [first, second]}))

    def test_validation_does_not_modify_plan(self):
        plan = {'schema_version': 1, 'operations': [operation()]}
        copy = deepcopy(plan)
        normalized = validate_plan(task(), plan)
        self.assertEqual(plan, copy)
        normalized['operations'][0]['parameters']['height_mm'] = 100
        self.assertEqual(plan, copy)


class WorkerArtifactTests(unittest.TestCase):
    def setUp(self):
        from b3_test_support import assigned_fixture
        self.fixture, self.workflow, self.task = assigned_fixture(self)

    def test_artifact_hashes_history_and_no_overwrite(self):
        from b3_test_support import box_plan
        output = self.workflow/'worker'
        artifact = build_task(self.task, box_plan(), output)
        self.assertEqual(artifact['status'], 'awaiting_check')
        self.assertEqual(artifact['worker'], self.task['roles']['worker'])
        self.assertEqual(artifact['task_sha256'], digest(json_bytes(self.task)))
        for name, key in [('final.brep', 'geometry_sha256'), ('generated.py', 'code_sha256'), ('plan.json', 'plan_sha256')]:
            self.assertEqual(digest((output/name).read_bytes()), artifact[key])
        self.assertEqual(digest((output/artifact['history'][0]['geometry']).read_bytes()), artifact['history'][0]['sha256'])
        with self.assertRaises(ValueError):
            build_task(self.task, box_plan(), output)

    def test_changed_source_reviews_block_build_before_output(self):
        from b3_test_support import box_plan
        self.fixture.review.write_text('{}', encoding='utf-8')
        output = self.workflow/'blocked'
        with self.assertRaises(ValueError):
            build_task(self.task, box_plan(), output)
        self.assertFalse(output.exists())

    def test_failed_geometry_leaves_no_partial_artifact(self):
        from b3_test_support import box_plan
        plan = box_plan()
        detached = deepcopy(plan['operations'][0])
        detached.update(id='disjoint', combine='union')
        detached['frame']['origin_mm'] = [100, 100, 100]
        plan['operations'].append(detached)
        output = self.workflow/'failed'
        with self.assertRaises(ValueError):
            build_task(self.task, plan, output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
