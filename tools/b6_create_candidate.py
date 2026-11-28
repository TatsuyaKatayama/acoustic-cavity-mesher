"""Snapshot a provisional B6 candidate with evidence, never register/approve it."""
import argparse,json,shutil
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from b3_task import load_task
from b3_check import check_task


def package_candidate(task_path,artifact_dir,reports,output,*,space_dir=None,workflow_evidence=None):
    task=load_task(task_path);artifact_dir=Path(artifact_dir);output=Path(output)
    if output.exists():raise ValueError('Candidate output already exists')
    expected=check_task(task_path,artifact_dir)
    required={'B3','B4','B5_contacts','B5_space'}
    if set(reports)!=required:raise ValueError('Candidate requires B3/B4/B5 contact/space evidence')
    evidence={}
    blockers=[]
    for stage,path in reports.items():
        path=Path(path);record=json.loads(path.read_text(encoding='utf-8'))
        if record.get('task_sha256')!=expected['task_sha256'] or record.get('artifact_sha256')!=expected['artifact_sha256']:
            raise ValueError('Report belongs to another task/artifact: '+stage)
        if record.get('status') not in ('ok','ng','needs_review'):raise ValueError('Unknown report status')
        evidence[stage]={'file':stage+'.json','sha256':sha256(path.read_bytes()).hexdigest(),'status':record['status']}
        if record['status']!='ok':blockers.append({'stage':stage,'status':record['status']})
        if stage=='B3' and record!=expected:raise ValueError('B3 report differs from current independent inspection')
    agent_evidence=None
    requires_rework=expected['status']=='ng'
    if workflow_evidence is not None:
        if not isinstance(workflow_evidence,dict) or workflow_evidence.get('schema_version')!=1:
            raise ValueError('Invalid workflow evidence')
        if workflow_evidence.get('task_sha256')!=expected['task_sha256'] or workflow_evidence.get('artifact_sha256')!=expected['artifact_sha256']:
            raise ValueError('Workflow evidence belongs to another task/artifact')
        if workflow_evidence.get('status') not in ('checked','review_required','return_to_worker'):
            raise ValueError('Only completed ACP review evidence may accompany a candidate')
        agent=workflow_evidence.get('agent_check')
        if not isinstance(agent,dict) or agent.get('status') not in ('ok','ng','needs_review') or not isinstance(agent.get('findings'),list) or any(not isinstance(v,str) for v in agent['findings']):
            raise ValueError('Workflow evidence requires an independent agent status and findings')
        requires_rework=requires_rework or workflow_evidence['status']=='return_to_worker' or agent['status']=='ng'
        if workflow_evidence.get('b3_requires_rework') is not requires_rework:
            raise ValueError('Workflow rework flag contradicts its B3/agent findings')
        if agent['status']!='ok':blockers.append({'stage':'B3_agent','status':agent['status']})
        if workflow_evidence['status']=='return_to_worker':blockers.append({'stage':'B3_ACP','status':'ng'})
        agent_evidence=(json.dumps(workflow_evidence,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    if space_dir:
        space_dir=Path(space_dir)
        space=json.loads((space_dir/'space-report.json').read_text(encoding='utf-8'))
        if sha256((space_dir/'space-report.json').read_bytes()).hexdigest()!=evidence['B5_space']['sha256']:
            raise ValueError('Space report differs from candidate evidence')
        for name,digest in space['files'].items():
            file=(space_dir/name).resolve()
            if not file.is_relative_to(space_dir.resolve()) or sha256(file.read_bytes()).hexdigest()!=digest:
                raise ValueError('Space artifact hash mismatch')
    record={'schema_version':1,'stage':'B6_candidate','status':'pending_human_review','registered':False,
        'provisional':True,'part_id':task['part_id'],'template_id':'fh_casting_trial' if task['source_name']=='FH' else 'rebuilt_part_trial',
        'task_sha256':expected['task_sha256'],'artifact_sha256':expected['artifact_sha256'],
        'review_mode':task['review_mode'],'roles':task['roles'],'evidence':evidence,'blocking_checks':blockers,
        'diagnostic_only':True,'b3_requires_rework':requires_rework,
        'required_human_review':['B2 trial contact and simplification decisions','B3 reconstruction strategy and unsupported semantic checks','B4 fit arrival and trial suitability criteria','B5 region connectivity/leak/exterior-fill assumptions','B6 applicability/version and release approval'],
        'registration_rule':'This is a review candidate, not an approved template. Register only after required checks and explicit human approval.'}
    if agent_evidence is not None:
        record['workflow_evidence']={'file':'workflow-evidence.json','sha256':sha256(agent_evidence).hexdigest()}
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmp:
        directory=Path(tmp)/'candidate';directory.mkdir()
        shutil.copytree(artifact_dir,directory/'artifact')
        shutil.copyfile(task_path,directory/'task.json')
        for stage,path in reports.items():shutil.copyfile(path,directory/(stage+'.json'))
        if space_dir:shutil.copytree(space_dir,directory/'space')
        if agent_evidence is not None:(directory/'workflow-evidence.json').write_bytes(agent_evidence)
        (directory/'candidate.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        directory.rename(output)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('task','artifact','output'):p.add_argument(name,type=Path)
    for name in ('b3-report','b4-report','contact-report','space-report'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--space',type=Path)
    p.add_argument('--workflow-evidence',type=Path)
    a=p.parse_args()
    try:
        r=package_candidate(a.task,a.artifact,{'B3':a.b3_report,'B4':a.b4_report,'B5_contacts':a.contact_report,'B5_space':a.space_report},a.output,space_dir=a.space,
            workflow_evidence=json.loads(a.workflow_evidence.read_text(encoding='utf-8')) if a.workflow_evidence else None)
        print(json.dumps({'status':r['status'],'registered':False,'blocking_checks':r['blocking_checks']}))
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:p.exit(1,f'B6 candidate packaging failed: {e}\n')

if __name__=='__main__':main()
