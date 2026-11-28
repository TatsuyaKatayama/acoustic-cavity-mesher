"""Compare detailed/rebuilt assembly air spaces within an explicit trial cylinder."""
import argparse,json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.TopTools import TopTools_ListOfShape
from OCP.TopAbs import TopAbs_SOLID,TopAbs_FACE,TopAbs_EDGE
from OCP.BRepCheck import BRepCheck_Analyzer
from b1_step import brep_bytes
from b2_faces import load_parts
from b3_task import load_task
from b3_check import read_brep,indexed,measure,checked_path
from b5_geometry import cylinder


def subtract(envelope,solids,*,diagnostics=None,label='space',linear_mm=1e-6):
    args,tools=TopTools_ListOfShape(),TopTools_ListOfShape();args.Append(envelope)
    for shape in solids:tools.Append(shape)
    for fuzzy in (0.,linear_mm):
        operation=BRepAlgoAPI_Cut();operation.SetArguments(args);operation.SetTools(tools)
        operation.SetFuzzyValue(fuzzy);operation.Build()
        success=operation.IsDone() and not operation.Shape().IsNull()
        if diagnostics is not None:diagnostics.append({'operation':label,'fuzzy_mm':fuzzy,'is_done':success})
        if success:return operation.Shape()
    raise ValueError('Assembly space boolean failed: '+label)


def build_spaces(task_path,artifact_dir,config_path,output):
    task=load_task(task_path);artifact_dir=Path(artifact_dir);output=Path(output)
    if output.exists():raise ValueError('Output already exists')
    from b3_check import check_task
    checked=check_task(task_path,artifact_dir)
    artifact=json.loads((artifact_dir/'artifact.json').read_text(encoding='utf-8'))
    rebuilt=read_brep(checked_path(artifact_dir,artifact['geometry']))
    _,parts=load_parts(Path(task['bundle']))
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    if config.get('outside_fill_breps'):raise ValueError('Outside fillers need a separately reviewed configuration')
    envelope=cylinder(config)
    diagnostics=[]
    def difference(a,b,label):return subtract(a,b,diagnostics=diagnostics,label=label,linear_mm=task['tolerances']['linear_mm'])
    detailed=difference(envelope,[s for s,_ in parts.values()],'detailed_air')
    simplified=difference(envelope,[rebuilt if pid==task['part_id'] else s for pid,(s,_) in parts.items()],'rebuilt_air')
    increase=difference(simplified,[detailed],'air_increase');decrease=difference(detailed,[simplified],'air_decrease')
    valid=all(BRepCheck_Analyzer(s).IsValid() for s in (detailed,simplified,increase,decrease))
    report={'schema_version':1,'stage':'B5_space','provisional':True,'status':'needs_review' if valid else 'ng',
        'part_id':task['part_id'],'task_sha256':checked['task_sha256'],'artifact_sha256':checked['artifact_sha256'],
        'coordinate_frame':'world','length_unit':'mm','scope':config['cylinder'],
        'configuration_sha256':sha256(Path(config_path).read_bytes()).hexdigest(),
        'boolean_operations':diagnostics,
        'detailed_air_mm3':measure(detailed,True),'rebuilt_air_mm3':measure(simplified,True),
        'air_increase_mm3':measure(increase,True),'air_decrease_mm3':measure(decrease,True),
        'detailed_components':indexed(detailed,TopAbs_SOLID).Extent(),
        'rebuilt_components':indexed(simplified,TopAbs_SOLID).Extent(),
        'rebuilt_faces':indexed(simplified,TopAbs_FACE).Extent(),
        'rebuilt_edges':indexed(simplified,TopAbs_EDGE).Extent(),
        'geometry_valid':valid,'human_review_pending':True,'b6_ready':False,
        'pending_checks':['Review trial cylinder and outer fill requirements','Define region/probe connectivity and leak expectations','Review air increase/decrease tolerance','Review small faces and edges for meshing'],
        'files':{}}
    residual = (report['rebuilt_air_mm3']-report['detailed_air_mm3'])-(report['air_increase_mm3']-report['air_decrease_mm3'])
    consistency_tolerance = max(1e-6, max(report['detailed_air_mm3'],report['rebuilt_air_mm3'])*1e-8)
    report['volume_conservation'] = {'status':'ok' if abs(residual)<=consistency_tolerance else 'ng',
        'residual_mm3':residual,'tolerance_mm3':consistency_tolerance,
        'rule':'rebuilt air - detailed air = air increase - air decrease'}
    report['difference_measurements_trusted'] = valid and abs(residual)<=consistency_tolerance
    if not report['difference_measurements_trusted']:
        report['status']='ng'
        report['pending_checks'].append('Resolve inconsistent boolean difference volumes; raw differences are diagnostic only')
    from check_trial_space import measure_space_features, check_probes
    from b5_geometry import solids
    report['feature_measurements'] = {
        'detailed': measure_space_features(detailed, config),
        'rebuilt': measure_space_features(simplified, config),
    }
    if 'min_face_area_mm2' in config or 'min_edge_length_mm' in config:
        report['small_features_detailed'] = report['feature_measurements']['detailed']['below_threshold']
        report['small_features_rebuilt'] = report['feature_measurements']['rebuilt']['below_threshold']
        report['feature_thresholds'] = {key:config[key] for key in ('min_face_area_mm2','min_edge_length_mm') if key in config}
        if report['small_features_rebuilt']:
            report['status'] = 'ng'
    if config.get('air_regions'):
        report['air_probes'], report['connectivity_issues'] = check_probes(config,envelope,solids(simplified))
        if report['connectivity_issues']:
            report['status']='ng'
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        work=Path(temp)/'space';work.mkdir()
        for name,shape in [('detailed-air',detailed),('rebuilt-air',simplified),('air-increase',increase),('air-decrease',decrease)]:
            data=brep_bytes(shape);(work/(name+'.brep')).write_bytes(data)
            report['files'][name+'.brep']=sha256(data).hexdigest()
        (work/'space-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        work.rename(output)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('task','artifact','config','output'):p.add_argument(name,type=Path)
    a=p.parse_args()
    try:
        result=build_spaces(a.task,a.artifact,a.config,a.output)
        print(json.dumps({k:result[k] for k in ('status','detailed_air_mm3','rebuilt_air_mm3','air_increase_mm3','air_decrease_mm3','detailed_components','rebuilt_components')}))
        return 0 if result['status']=='ok' else 2
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:p.exit(1,f'B5 rebuild space failed: {e}\n')

if __name__=='__main__':raise SystemExit(main())
