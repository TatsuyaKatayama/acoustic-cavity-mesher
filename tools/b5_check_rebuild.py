"""B5 world-coordinate contact and interference inspection for a rebuilt part."""
import argparse,json
from pathlib import Path
from hashlib import sha256
from math import isfinite
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from b2_faces import load_parts
from b3_task import load_task
from b3_check import read_brep,indexed,measure,checked_path
from propose_contacts import measure_contact,bounds


def check_reassembly(task_path,artifact_dir,*,min_overlap_ratio=.95,max_interference_mm3=.01):
    if not 0<min_overlap_ratio<=1 or not isfinite(max_interference_mm3) or max_interference_mm3<0:
        raise ValueError('Explicit valid B5 tolerances required')
    task=load_task(task_path);artifact_dir=Path(artifact_dir)
    artifact=json.loads((artifact_dir/'artifact.json').read_text(encoding='utf-8'))
    from b3_check import check_task
    prior=check_task(task_path,artifact_dir)
    generated=read_brep(checked_path(artifact_dir,artifact['geometry']))
    _,parts=load_parts(Path(task['bundle']));faces=indexed(generated,TopAbs_FACE)
    records=[]
    for contact in task['contact_constraints']:
        own=next(r for r in contact['faces'] if r[0]==task['part_id'])
        mate=next(r for r in contact['faces'] if r[0]!=task['part_id'])
        mateface=TopoDS.Face_s(parts[mate[0]][1].FindKey(mate[1]))
        original=measure_contact(TopoDS.Face_s(parts[own[0]][1].FindKey(own[1])),mateface)
        matches=[]
        for i in range(1,faces.Extent()+1):
            m=measure_contact(TopoDS.Face_s(faces.FindKey(i)),mateface)
            if m:matches.append((i,m))
        if matches:
            closest=min(abs(m['gap_mm']-contact['target_gap_mm']) for _,m in matches)
            candidates=[(i,m) for i,m in matches if abs(abs(m['gap_mm']-contact['target_gap_mm'])-closest)<1e-7]
            gap=candidates[0][1]['gap_mm'];overlap=sum(m['overlap_mm2'] for _,m in candidates)
            ratio=overlap/original['overlap_mm2'] if original else 0
            issues=[]
            if abs(gap-contact['target_gap_mm'])>contact['tolerance_mm']+1e-7:issues.append('gap_outside_trial_tolerance')
            if ratio<min_overlap_ratio:issues.append('insufficient_overlap')
        else:gap=None;overlap=0;ratio=0;candidates=[];issues=['no_supported_overlapping_face']
        records.append({'candidate_id':contact['candidate_id'],'source_face':own,'mate_face':mate,
            'generated_faces':[i for i,_ in candidates],'gap_mm':gap,'target_gap_mm':contact['target_gap_mm'],
            'tolerance_mm':contact['tolerance_mm'],'overlap_mm2':overlap,'source_overlap_mm2':original['overlap_mm2'] if original else None,
            'overlap_ratio':ratio,'issues':issues})
    interferences=[];all_intersections=[]
    original=parts[task['part_id']][0]
    for pid,(neighbor,_) in parts.items():
        if pid==task['part_id']:continue
        cut=BRepAlgoAPI_Common(generated,neighbor);cut.Build()
        if not cut.IsDone():raise ValueError('Interference operation failed: '+pid)
        volume=measure(cut.Shape(),True)
        baseline=BRepAlgoAPI_Common(original,neighbor);baseline.Build()
        if not baseline.IsDone():raise ValueError('Reference interference operation failed: '+pid)
        base=measure(baseline.Shape(),True)
        row={'part_id':pid,'interference_mm3':volume,'source_interference_mm3':base,'increase_mm3':volume-base}
        all_intersections.append(row)
        if volume>max_interference_mm3:interferences.append(row)
    status='ng' if any(r['issues'] for r in records) or interferences else 'ok'
    return {'schema_version':1,'stage':'B5_contacts','provisional':True,'status':status,'part_id':task['part_id'],
        'coordinate_frame':'world','placement':'B1 absolute coordinates retained; no extra placement applied',
        'contacts':records,'interferences':interferences,'neighbor_checks':all_intersections,
        'min_overlap_ratio':min_overlap_ratio,'max_interference_mm3':max_interference_mm3,
        'b3_status':prior['status'],'task_sha256':prior['task_sha256'],'artifact_sha256':prior['artifact_sha256'],
        'human_review_pending':True,'b6_ready':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('task','artifact','report'):p.add_argument(name,type=Path)
    p.add_argument('--min-overlap-ratio',type=float,default=.95)
    p.add_argument('--max-interference-mm3',type=float,default=.01)
    a=p.parse_args()
    try:
        if a.report.exists() or a.report.resolve().is_relative_to(a.artifact.resolve()):raise ValueError('Use a new report outside worker artifacts')
        result=check_reassembly(a.task,a.artifact,min_overlap_ratio=a.min_overlap_ratio,max_interference_mm3=a.max_interference_mm3)
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':result['status'],'contacts':len(result['contacts']),'interferences':len(result['interferences'])}))
        return 0 if result['status']=='ok' else 2
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:p.exit(1,f'B5 rebuild check failed: {e}\n')

if __name__=='__main__':raise SystemExit(main())
