"""B4 checker for any world-coordinate B3 rebuild; never fits or repairs it."""
import argparse
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepCheck import BRepCheck_Analyzer

from b2_faces import load_parts
from b3_check import check_task, check_geometry, read_brep, measure, checked_path
from b3_task import load_task
from propose_contacts import bounds


def positive_limit(value, name):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(name+' must be a finite nonnegative value')
    return value


class MeasurementError(ValueError):
    """Valid inputs could not be measured reliably by the kernel."""


def solid_difference(first, second):
    difference = BRepAlgoAPI_Cut(first, second)
    difference.SetNonDestructive(True)
    difference.Build()
    if not difference.IsDone():
        raise MeasurementError('B4 solid difference operation IsDone=False')
    if not BRepCheck_Analyzer(difference.Shape()).IsValid():
        raise MeasurementError('B4 solid difference produced an invalid result')
    return measure(difference.Shape(), True)


def compare_rebuild(task, source, generated, plan, *, max_error_mm3, max_bbox_difference_mm=None):
    """Separate fit reachability from whether the produced geometry is sufficient."""
    max_error_mm3 = positive_limit(max_error_mm3, 'max_error_mm3')
    if max_bbox_difference_mm is not None:
        positive_limit(max_bbox_difference_mm, 'max_bbox_difference_mm')
    if not BRepCheck_Analyzer(source).IsValid():
        raise ValueError('Detailed source is not valid; return to B1')
    b3_geometry = check_geometry(task, source, generated, plan)
    # Source material removed by simplification increases the surrounding space.
    measurement_failure = None
    source_volume, generated_volume = measure(source,True), measure(generated,True)
    try:
        space_added = solid_difference(source, generated)
        space_removed = solid_difference(generated, source)
        error = space_added+space_removed
    except MeasurementError as failure:
        space_added = space_removed = error = None
        measurement_failure = str(failure)
    conservation_tolerance = max(task['tolerances']['linear_mm']**3,
                                 task['tolerances']['linear_mm']*max(measure(source),measure(generated)))
    conservation_residual = abs((space_added-space_removed)-(source_volume-generated_volume)) if error is not None else None
    consistent = conservation_residual is not None and conservation_residual <= conservation_tolerance
    source_bounds, generated_bounds = list(bounds(source).Get()), list(bounds(generated).Get())
    bbox_error = max(abs(a-b) for a,b in zip(source_bounds, generated_bounds))
    fit_checks = [row for row in b3_geometry['checks'] if row['item'] in
                  ('single_valid_solid', 'retained_face', 'protected_contact')]
    constraint_status = 'ng' if any(row['status']=='ng' for row in fit_checks) else 'needs_review' if any(row['status']=='needs_review' for row in fit_checks) else 'ok'
    # Matching the source exactly proves zero possible improvement. Otherwise a
    # single candidate is not evidence of optimization over the template domain.
    zero_difference = error == 0 and consistent
    fit_status = 'ng' if constraint_status == 'ng' else 'ok' if zero_difference and constraint_status == 'ok' else 'needs_review'
    fit = {'status': fit_status, 'constraint_status': constraint_status, 'checks': fit_checks,
           'optimization_status': 'zero_source_difference' if zero_difference else 'not_established',
           'reason': 'No geometric improvement is possible on a zero symmetric-difference candidate' if zero_difference else
                     'Only this rebuild was measured. No search over the parameter domain or optimality certificate was supplied; a worker/strategy assessment remains required.'}
    suitability_checks = [{'item':'symmetric_difference',
                           'status':'needs_review' if error is None else 'ng' if not consistent else 'ok' if error<=max_error_mm3 else 'ng',
                           'value_mm3':error, 'limit_mm3':max_error_mm3,
                           'measurement_failure':measurement_failure},
                          {'item':'difference_volume_conservation','status':'needs_review' if error is None else 'ok' if consistent else 'ng',
                           'residual_mm3':conservation_residual,'tolerance_mm3':conservation_tolerance,
                           'rule':'space_added - space_removed must equal source_volume - generated_volume'}]
    if max_bbox_difference_mm is not None:
        suitability_checks.append({'item':'world_bbox_difference', 'status':'ok' if bbox_error<=max_bbox_difference_mm else 'ng',
                                   'value_mm':bbox_error, 'limit_mm':max_bbox_difference_mm})
    suitability = {'status':'ng' if any(row['status']=='ng' for row in suitability_checks) else 'needs_review' if any(row['status']=='needs_review' for row in suitability_checks) else 'ok',
                   'checks':suitability_checks, 'scope':'Single part material/space difference only; assembly contacts and connectivity belong to B5'}
    status = 'ng' if 'ng' in (fit['status'], suitability['status'], b3_geometry['status']) else 'needs_review' if 'needs_review' in (fit['status'],suitability['status'],b3_geometry['status']) else 'ok'
    return {'schema_version':1,'stage':'B4','part_id':task['part_id'],'length_unit':'mm','coordinate_frame':'world',
            'status':status,'provisional':True,'checker_modifies_geometry':False,'b6_ready':False,
            'fit_reachability':fit,'simplification_suitability':suitability,
            'space_added_mm3':space_added,'space_removed_mm3':space_removed,
            'space_added_cc':space_added/1000 if space_added is not None else None,'space_removed_cc':space_removed/1000 if space_removed is not None else None,
            'symmetric_difference_mm3':error,'source_volume_mm3':source_volume,
            'generated_volume_mm3':generated_volume,'net_space_increase_mm3':source_volume-generated_volume,
            'measurement_status':'failed' if error is None else 'ok' if consistent else 'inconsistent',
            'measurement_failure':measurement_failure,'difference_conservation_residual_mm3':conservation_residual,'source_bounds_world_mm':source_bounds,
            'generated_bounds_world_mm':generated_bounds,'max_bbox_difference_mm':bbox_error,
            'b3_policy_check_status':b3_geometry['status'],
            'limitations':['Fit constraints can pass without establishing that the template was fitted as far as possible.',
                           'Equal total volumes do not imply equal space: added and removed space are measured separately.',
                           'B5 assembly gaps/interference, openings/connectivity and final human review remain separate gates.']}


def check_rebuild(task_path, artifact_dir, *, max_error_mm3, max_bbox_difference_mm=None):
    task_path, artifact_dir = Path(task_path),Path(artifact_dir)
    task = load_task(task_path)
    b3_report = check_task(task_path,artifact_dir)
    artifact_path = artifact_dir/'artifact.json'
    artifact = json.loads(artifact_path.read_text(encoding='utf-8'))
    plan = json.loads(checked_path(artifact_dir,'plan.json').read_text(encoding='utf-8'))
    _, parts = load_parts(Path(task['bundle']))
    report = compare_rebuild(task,parts[task['part_id']][0],read_brep(checked_path(artifact_dir,artifact['geometry'])),plan,
                             max_error_mm3=max_error_mm3,max_bbox_difference_mm=max_bbox_difference_mm)
    if b3_report['status'] == 'ng':
        report['status'] = 'ng'
    elif b3_report['status'] == 'needs_review' and report['status']=='ok':
        report['status'] = 'needs_review'
    report.update(roles=task['roles'],checker=task['roles']['checker'],task_sha256=b3_report['task_sha256'],
                  artifact_sha256=sha256(artifact_path.read_bytes()).hexdigest(),
                  b3_independent_status=b3_report['status'],criteria={'max_error_mm3':max_error_mm3,'max_bbox_difference_mm':max_bbox_difference_mm})
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task',type=Path)
    parser.add_argument('artifact',type=Path)
    parser.add_argument('report',type=Path)
    parser.add_argument('--max-error-mm3',type=float,required=True)
    parser.add_argument('--max-bbox-difference-mm',type=float)
    args=parser.parse_args()
    try:
        if args.report.exists() or args.report.resolve().is_relative_to(args.artifact.resolve()):
            raise ValueError('Write a new checker report outside the worker artifact directory')
        report=check_rebuild(args.task,args.artifact,max_error_mm3=args.max_error_mm3,max_bbox_difference_mm=args.max_bbox_difference_mm)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
        return 0 if report['status']=='ok' else 2
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as error:
        parser.exit(1,f'B4 rebuild check failed: {error}\n')


if __name__=='__main__':
    raise SystemExit(main())
