"""Independently inspect B3 artifacts; never repair or rewrite worker outputs."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from math import isfinite
from pathlib import Path

import cadquery as cq

from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.gp import gp_Lin,gp_Vec

from b2_faces import load_parts
from propose_contacts import bounds


def indexed(shape, kind):
    result = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, result)
    return result


def measure(shape, volume=False):
    props = GProp_GProps()
    (BRepGProp.VolumeProperties_s if volume else BRepGProp.SurfaceProperties_s)(shape, props)
    return abs(props.Mass())


def read_brep(path):
    shape = TopoDS_Shape()
    BRepTools.Read_s(shape, BytesIO(Path(path).read_bytes()), BRep_Builder())
    if shape.IsNull():
        raise ValueError('Empty BREP artifact')
    return shape


def same_direction(source, target):
    """A coincident wall facing the opposite material side is not retained."""
    a, b = BRepAdaptor_Surface(source), BRepAdaptor_Surface(target)
    if a.GetType() != b.GetType():
        return False
    if a.GetType() == GeomAbs_Plane:
        def normal(surface, face):
            plane = surface.Plane()
            vector = plane.Axis().Direction()
            if (face.Orientation() == TopAbs_REVERSED) != (not plane.Direct()):
                vector.Reverse()
            return vector
        return normal(a, source).Dot(normal(b, target)) > 1 - 1e-10
    if a.GetType() == GeomAbs_Cylinder:
        # Handedness and face orientation jointly determine inner/outer wall.
        return ((source.Orientation() != TopAbs_REVERSED) == a.Cylinder().Direct()) == ((target.Orientation() != TopAbs_REVERSED) == b.Cylinder().Direct())
    return False



def same_support(source, target, linear_mm):
    """Only coincident supporting surfaces can cover a retained patch."""
    a,b=BRepAdaptor_Surface(source),BRepAdaptor_Surface(target)
    if a.GetType()!=b.GetType():
        return False
    if a.GetType()==GeomAbs_Plane:
        p,q=a.Plane(),b.Plane()
        return p.Axis().Direction().IsParallel(q.Axis().Direction(),1e-10) and abs(gp_Vec(p.Location(),q.Location()).Dot(gp_Vec(p.Axis().Direction())))<=linear_mm
    if a.GetType()==GeomAbs_Cylinder:
        p,q=a.Cylinder(),b.Cylinder()
        return abs(p.Radius()-q.Radius())<=linear_mm and p.Axis().Direction().IsParallel(q.Axis().Direction(),1e-10) and gp_Lin(p.Axis()).Distance(q.Location())<=linear_mm
    return False


def retained_coverage(source, target, linear_mm, area_mm2):
    """Subtract boundary patches, allowing larger faces and split faces."""
    surface_type = BRepAdaptor_Surface(source).GetType()
    if surface_type not in (GeomAbs_Plane, GeomAbs_Cylinder):
        return {'status': 'needs_review', 'reason': 'Retained surface type is not supported by the B3 coverage checker'}
    residual = source
    for i in range(1, target.Extent()+1):
        face = TopoDS.Face_s(target.FindKey(i))
        if not same_support(source, face, linear_mm) or not same_direction(source, face):
            continue
        cut = BRepAlgoAPI_Cut(residual, face)
        cut.SetFuzzyValue(linear_mm)
        cut.Build()
        if not cut.IsDone():
            return {'status': 'needs_review', 'reason': 'OCCT face coverage operation failed'}
        residual = cut.Shape()
        if measure(residual) <= area_mm2:
            break
    area, missing = measure(source), measure(residual)
    return {'status': 'ok' if missing <= area_mm2 else 'ng', 'source_area_mm2': area,
            'uncovered_area_mm2': missing, 'coverage_ratio': max(0, 1-missing/area) if area else 0,
            'rule': 'Source trimmed surface must be included in equally oriented output boundary; edges may extend'}


def check_geometry(task, source, generated, plan):
    tolerances = task['tolerances']
    linear, area = tolerances['linear_mm'], tolerances['area_mm2']
    if any(type(v) not in (float, int) or not isfinite(v) or v <= 0 for v in (linear, area)):
        raise ValueError('Positive finite linear_mm and area_mm2 tolerances required')
    checks = []
    valid = BRepCheck_Analyzer(generated).IsValid() and indexed(generated, TopAbs_SOLID).Extent() == 1 and measure(generated, True) > 0
    checks.append({'item': 'single_valid_solid', 'status': 'ok' if valid else 'ng'})
    source_faces, generated_faces = indexed(source, TopAbs_FACE), indexed(generated, TopAbs_FACE)
    groups = task['face_sets']
    owners = {tuple(ref): group for group in groups for ref in group['faces']}
    for constraint in task['contact_constraints']:
        for ref in constraint['faces']:
            if ref[0] == task['part_id'] and (tuple(ref) not in owners or owners[tuple(ref)]['decision'] != 'keep'):
                checks.append({'item': 'protected_contact', 'face': ref, 'status': 'ng'})
    for group in groups:
        if group['decision'] == 'keep':
            for ref in group['faces']:
                result = retained_coverage(TopoDS.Face_s(source_faces.FindKey(ref[1])), generated_faces, linear, area)
                checks.append({'item': 'retained_face', 'face': ref, 'set_id': group['id'], **result})
    omitted = {tuple(ref) for group in groups if group['decision'] == 'omit' for ref in group['faces']}
    referenced = {tuple(ref) for operation in plan['operations'] for ref in operation.get('source_faces', [])}
    unknown = referenced - set(owners)
    checks.append({'item': 'known_construction_references', 'status': 'ng' if unknown else 'ok',
                   'unknown_references': [list(ref) for ref in sorted(unknown)]})
    checks.append({'item': 'omitted_construction_references', 'status': 'ng' if omitted & referenced else 'ok',
                   'forbidden_references': [list(ref) for ref in sorted(omitted & referenced)]})
    if omitted:
        checks.append({'item': 'omission_semantics', 'status': 'needs_review',
            'reason': 'Construction provenance can exclude omitted references; geometric feature intent still requires human review'})
    policy_specs = plan.get('policy_checks', [])
    if not isinstance(policy_specs, list):
        raise ValueError('policy_checks must be a list')
    for group in groups:
        if group['decision'] != 'simplify':
            continue
        policy = group['approximation']['policy']
        notes = group['approximation'].get('notes', '')
        if notes.strip():
            checks.append({'item': 'policy_notes', 'set_id': group['id'], 'status': 'needs_review',
                'notes': notes,
                'reason': 'Freeform simplification instructions require a separate strategy or human assessment; numerical policy checks do not establish that these instructions were followed'})
        specs = [spec for spec in policy_specs if spec.get('set_id') == group['id']]
        result = {'item': 'simplification_policy', 'set_id': group['id'], 'policy': policy, 'status': 'needs_review'}
        if policy == 'unspecified' or len(specs) != 1 or specs[0].get('scope') != 'whole_part':
            result['reason'] = 'Define one explicit whole_part policy evaluation scope and tolerance; no arbitrary set volume is inferred'
        else:
            spec = specs[0]
            key = {'preserve_volume': 'max_volume_difference_mm3', 'preserve_envelope': 'max_envelope_difference_mm'}.get(policy)
            tolerance = spec.get(key) if key else None
            if type(tolerance) not in (int, float) or not isfinite(tolerance) or tolerance < 0:
                result['reason'] = 'Policy tolerance is missing or invalid'
            else:
                difference = abs(measure(source, True)-measure(generated, True)) if policy == 'preserve_volume' else max(abs(a-b) for a,b in zip(bounds(source).Get(), bounds(generated).Get()))
                result.update(status='ok' if difference <= tolerance else 'ng', scope='whole_part', difference=difference, tolerance=tolerance,
                              unit='mm3' if policy == 'preserve_volume' else 'mm')
        checks.append(result)
    status = 'ng' if any(c['status'] == 'ng' for c in checks) else 'needs_review' if any(c['status'] == 'needs_review' for c in checks) else 'ok'
    return {'schema_version': 1, 'stage': 'B3', 'part_id': task['part_id'], 'status': status,
            'checks': checks, 'checker_modifies_geometry': False,
            'detail_policy_verification_scope': 'Only explicit operation labels and provenance are inspected for chamfer/fillet instructions. Hidden features inside specialized construction code are not certified. Semantic identification of all detailed CAD features and whether their omission satisfies intent is not automatically proved.',
            'next_stage': 'B4 remains a separate fit and suitability evaluation'}



class UnsupportedPrimitive(ValueError):
    """Replay scope limitation, not permission to execute worker Python."""


def replay_plan(plan):
    """Independent bounded interpreter; does not import or execute worker code."""
    model = None
    for index, operation in enumerate(plan['operations']):
        kind = operation['operation']
        if kind not in ('box', 'cylinder'):
            raise UnsupportedPrimitive('No independent checker replay interpreter for primitive: '+str(kind))
        combine = operation['combine']
        if combine not in (('new',) if index == 0 else ('union', 'cut')):
            raise ValueError('Invalid primitive combination in checker replay')
        p, frame = operation['parameters'], operation['frame']
        keys = {'length_mm', 'width_mm', 'height_mm'} if kind == 'box' else {'radius_mm', 'height_mm'}
        if set(p) != keys or any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in p.values()):
            raise ValueError('Invalid dimensions in checker replay')
        for key in ('origin_mm', 'x_direction', 'normal'):
            value = frame[key]
            if not isinstance(value, list) or len(value) != 3 or any(type(v) not in (int, float) or not isfinite(v) for v in value):
                raise ValueError('Invalid coordinate frame in checker replay')
        workplane = cq.Workplane(cq.Plane(origin=frame['origin_mm'], xDir=frame['x_direction'], normal=frame['normal']))
        # Explicit dimensional primitive construction, independent of b3_build.
        if kind == 'box':
            tool = workplane.rect(p['length_mm'], p['width_mm']).extrude(p['height_mm']).val()
        else:
            tool = workplane.circle(p['radius_mm']).extrude(p['height_mm']).val()
        if model is None:
            model = tool
        elif combine == 'union':
            model = model.fuse(tool).clean()
        else:
            model = model.cut(tool).clean()
        yield model.wrapped


def replay_checks(plan, artifact, artifact_dir, task):
    try:
        expected_history = list(replay_plan(plan))
    except UnsupportedPrimitive as error:
        return [{'item':'independent_plan_replay','status':'needs_review','reason':str(error),
                 'scope':'Artifact hashes, valid history solids, source face coverage and policies are checked separately; unsupported construction code is never executed'}]
    if len(expected_history) != len(artifact['history']):
        raise ValueError('Replay operation count does not match history')
    checks = []
    for expected, step in zip(expected_history, artifact['history']):
        actual = read_brep(checked_path(artifact_dir, step['geometry']))
        differences = []
        for a, b in ((expected, actual), (actual, expected)):
            cut = BRepAlgoAPI_Cut(a, b)
            cut.Build()
            if not cut.IsDone():
                raise ValueError('Independent replay difference operation failed')
            differences.append(measure(cut.Shape(), True))
        # A linear boundary tolerance converted to a conservative volume shell.
        tolerance = max(task['tolerances']['linear_mm']**3,
                        task['tolerances']['linear_mm']*max(measure(expected), measure(actual)))
        error = sum(differences)
        checks.append({'item': 'independent_plan_replay', 'operation_id': step['operation_id'],
                       'status': 'ok' if error <= tolerance else 'ng',
                       'symmetric_difference_mm3': error, 'tolerance_mm3': tolerance,
                       'tolerance_rule': 'linear_mm times maximum surface area of expected/actual solid'})
    return checks


def checked_path(root, reference):
    result = (root/reference).resolve()
    if not result.is_relative_to(root.resolve()) or not result.is_file():
        raise ValueError('Artifact file path must resolve inside the artifact directory')
    return result


def check_task(task_path, artifact_dir):
    from b3_task import load_task
    task_path, artifact_dir = Path(task_path), Path(artifact_dir)
    task = load_task(task_path)
    artifact = json.loads((artifact_dir/'artifact.json').read_text(encoding='utf-8'))
    canonical = lambda value: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
    task_digest = sha256(canonical(task)).hexdigest()
    if artifact['schema_version'] != 1 or artifact['stage'] != 'B3' or artifact['coordinate_frame'] != 'world' or artifact['length_unit'] != 'mm':
        raise ValueError('Expected a world-coordinate B3 artifact in mm')
    if artifact['task_sha256'] != task_digest or artifact['part_id'] != task['part_id'] or artifact['manifest_sha256'] != task['manifest_sha256'] or artifact['handoff_sha256'] != task['handoff_sha256'] or artifact['contact_constraints'] != task['contact_constraints']:
        raise ValueError('Artifact belongs to a different B3 task')
    required = [(artifact['geometry'], artifact['geometry_sha256']), (artifact['code'], artifact['code_sha256']),
                ('task.json', task_digest), ('plan.json', artifact['plan_sha256'])]
    required += [(step['geometry'], step['sha256']) for step in artifact['history']]
    for reference, digest in required:
        if sha256(checked_path(artifact_dir, reference).read_bytes()).hexdigest() != digest:
            raise ValueError('Artifact file hash mismatch: '+reference)
    plan = json.loads(checked_path(artifact_dir, 'plan.json').read_text(encoding='utf-8'))
    if len(plan['operations']) != len(artifact['history']):
        raise ValueError('Construction history does not match operation plan')
    for operation, step in zip(plan['operations'], artifact['history']):
        if operation['id'] != step['operation_id'] or operation['source_faces'] != step['source_faces']:
            raise ValueError('Construction reference provenance mismatch')
        historical = read_brep(checked_path(artifact_dir, step['geometry']))
        if not BRepCheck_Analyzer(historical).IsValid() or indexed(historical, TopAbs_SOLID).Extent() != 1:
            raise ValueError('Invalid historical construction solid')
    if not artifact['history'] or artifact['history'][-1]['sha256'] != artifact['geometry_sha256']:
        raise ValueError('Final geometry does not match final history step')
    _, parts = load_parts(Path(task['bundle']))
    if artifact.get('roles') != task['roles'] or artifact.get('worker') != task['roles']['worker']:
        raise ValueError('Worker and checker role provenance does not match assignment')
    result = check_geometry(task, parts[task['part_id']][0], read_brep(checked_path(artifact_dir, artifact['geometry'])), plan)
    result['checks'].extend(replay_checks(plan, artifact, artifact_dir, task))
    result['status'] = 'ng' if any(c['status'] == 'ng' for c in result['checks']) else 'needs_review' if any(c['status'] == 'needs_review' for c in result['checks']) else 'ok'
    result['reproducibility_scope'] = 'Supported declarative box/cylinder steps are independently replayed when the full plan is supported; otherwise replay is explicitly needs_review. Generated Python hash is audited but arbitrary code is never executed.'
    result.update(roles=task['roles'], checker=task['roles']['checker'])
    result.update(task_sha256=artifact['task_sha256'], artifact_sha256=sha256((artifact_dir/'artifact.json').read_bytes()).hexdigest())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', type=Path)
    parser.add_argument('artifact', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    try:
        if args.report.exists() or args.report.resolve().is_relative_to(args.artifact.resolve()):
            raise ValueError('Checker report must be a new file outside worker artifact directory')
        report = check_task(args.task, args.artifact)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['status'] == 'ok' else 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        parser.exit(1, f'B3 check failed: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
