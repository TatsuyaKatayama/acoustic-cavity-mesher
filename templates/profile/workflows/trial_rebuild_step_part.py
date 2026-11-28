"""Run one provisional part through ACP B3, diagnostic B4/B5 and B6 candidate.

This workflow composes existing single-function operations. It never registers
a template, approves B2, edits worker geometry or turns an NG into an OK.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

# Both templates/profile and local/profile use the same repository-relative layout.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

from b3_acp import run_workflow as run_acp, validate_config
from b3_task import load_task
from b3_build import json_bytes
from b3_check import check_task
from b4_check_rebuild import check_rebuild, positive_limit
from b5_check_rebuild import check_reassembly
from b5_build_rebuild_space import build_spaces
from b6_create_candidate import package_candidate


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, record):
    Path(path).write_bytes(json_bytes(record))


def _hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _snapshot(directory):
    directory=Path(directory)
    return {str(p.relative_to(directory)):_hash(p) for p in directory.rglob('*') if p.is_file()}


def _guard(task_path, task, artifact, snapshot, space_config, config_hash):
    if load_task(task_path)!=task:
        raise ValueError('Trial task changed during workflow')
    if _snapshot(artifact)!=snapshot:
        raise ValueError('Worker artifact changed during diagnostic workflow')
    if _hash(space_config)!=config_hash:
        raise ValueError('Trial space configuration changed during workflow')


def run_trial(task_path, provider_config, space_config, output, *, max_error_mm3, max_bbox_difference_mm=None):
    """One assigned provisional part; final human review remains pending."""
    task_path, space_config, output=Path(task_path).resolve(),Path(space_config).resolve(),Path(output).resolve()
    task=load_task(task_path)
    if task.get('review_mode')!='provisional_trial':
        raise ValueError('Full trial workflow requires an explicitly provisional_trial B2 assignment')
    positive_limit(max_error_mm3,'max_error_mm3')
    if max_bbox_difference_mm is not None:
        positive_limit(max_bbox_difference_mm,'max_bbox_difference_mm')
    config=validate_config(_read(provider_config) if isinstance(provider_config,(str,Path)) else provider_config)
    _read(space_config)
    config_hash=_hash(space_config)
    if output.exists():
        raise ValueError('Use a new workflow output directory; preserve previous trial attempts')
    output.mkdir(parents=True)
    summary={'schema_version':1,'stage':'B_trial_workflow','part_id':task['part_id'],
        'review_mode':'provisional_trial','status':'running','registered':False,
        'human_review_pending':True,'roles':task['roles'],'stages':{},
        'task_sha256':sha256(json_bytes(task)).hexdigest(),
        'space_configuration_sha256':config_hash,
        'criteria':{'max_error_mm3':max_error_mm3,'max_bbox_difference_mm':max_bbox_difference_mm},
        'rule':'B3 agent workflow then B4 two-stage checks and B5 diagnostic checks; B6 is an unapproved candidate only.'}
    _write(output/'task.json',task)
    _write(output/'space-config.json',_read(space_config))
    try:
        acp=run_acp(task_path,config,output/'b3-acp')
        summary['stages']['B3']={'status':acp.get('status'),'workflow':'b3-acp/workflow.json'}
        summary['b3_requires_rework']=acp.get('status')=='return_to_worker'
        if acp.get('status') not in ('checked','review_required','return_to_worker') or not acp.get('artifact'):
            summary.update(status='stopped_at_B3',reason='Agent workflow did not produce an eligible checked/review-required artifact',
                next_action='Resolve B3 provider or missing-artifact findings before another trial')
            return summary
        artifact=Path(acp['artifact']).resolve()
        if not artifact.is_relative_to((output/'b3-acp').resolve()) or not artifact.is_dir():
            raise ValueError('B3 artifact must belong to this exact ACP run')
        before=_snapshot(artifact)
        _guard(task_path,task,artifact,before,space_config,config_hash)
        # Fresh independent evidence is bound to this artifact, not agent prose.
        b3=check_task(task_path,artifact)
        summary['stages']['B3']['independent_status']=b3['status']
        summary['b3_requires_rework']=summary['b3_requires_rework'] or b3['status']=='ng'
        if b3['task_sha256']!=summary['task_sha256']:
            raise ValueError('B3 report does not belong to this assigned task')
        artifact_hash=_hash(artifact/'artifact.json')
        if b3['artifact_sha256']!=artifact_hash:
            raise ValueError('B3 artifact/report mismatch')
        _write(output/'b3-report.json',b3)
        b4=check_rebuild(task_path,artifact,max_error_mm3=max_error_mm3,max_bbox_difference_mm=max_bbox_difference_mm)
        _write(output/'b4-report.json',b4)
        summary['stages']['B4']={'status':b4['status'],'report':'b4-report.json',
            'fit_reachability':b4['fit_reachability']['status'],
            'simplification_suitability':b4['simplification_suitability']['status']}
        _guard(task_path,task,artifact,before,space_config,config_hash)

        def diagnostic(stage, function, path):
            try:
                result=function()
            except (ValueError,OSError,RuntimeError,KeyError,TypeError) as error:
                # A failed measurement must remain review evidence, never OK.
                # Source integrity failures cannot be packaged as diagnostics.
                _guard(task_path,task,artifact,before,space_config,config_hash)
                result={'schema_version':1,'stage':stage,'provisional':True,'status':'needs_review',
                    'part_id':task['part_id'],'task_sha256':b3['task_sha256'],
                    'artifact_sha256':b3['artifact_sha256'],'measurement_status':'failed',
                    'measurement_error':{'type':type(error).__name__,'message':str(error)},
                    'coordinate_frame':'world','human_review_pending':True,'b6_ready':False,
                    'note':'This stage was attempted but did not complete. No successful measurement is claimed.'}
                if stage=='B5_space':
                    result.update(configuration_sha256=config_hash,files={})
            _write(path,result)
            summary['stages'][stage]={'status':result['status'],'report':str(path.relative_to(output)),
                'measurement_status':result.get('measurement_status','completed')}
            return result

        diagnostic('B5_contacts',lambda:check_reassembly(task_path,artifact),output/'b5-contacts-report.json')
        space_dir=output/'b5-space'
        diagnostic('B5_space',lambda:build_spaces(task_path,artifact,space_config,space_dir),output/'b5-space-report.json')
        _guard(task_path,task,artifact,before,space_config,config_hash)
        reports={'B3':output/'b3-report.json','B4':output/'b4-report.json',
                 'B5_contacts':output/'b5-contacts-report.json','B5_space':output/'b5-space-report.json'}
        agent_check=_read(output/'b3-acp'/'agent-check.json')
        workflow_evidence={'schema_version':1,'task_sha256':b3['task_sha256'],
            'artifact_sha256':b3['artifact_sha256'],'status':acp['status'],
            'agent_check':agent_check,'b3_requires_rework':summary['b3_requires_rework'] or agent_check.get('status')=='ng',
            'source_acp_workflow_sha256':_hash(output/'b3-acp'/'workflow.json'),
            'source_agent_check_sha256':_hash(output/'b3-acp'/'agent-check.json')}
        summary['b3_requires_rework']=workflow_evidence['b3_requires_rework']
        candidate=package_candidate(task_path,artifact,reports,output/'b6-candidate',
            space_dir=space_dir if (space_dir/'space-report.json').is_file() else None,
            workflow_evidence=workflow_evidence)
        if candidate.get('registered') is not False or candidate.get('status')!='pending_human_review':
            raise ValueError('B6 trial packaging must remain unregistered and pending human review')
        _guard(task_path,task,artifact,before,space_config,config_hash)
        summary['stages']['B6']={'status':candidate['status'],'candidate':'b6-candidate/candidate.json',
                                 'blocking_checks':candidate['blocking_checks']}
        stage_statuses=[b3['status'],b4['status']]+[summary['stages'][s]['status'] for s in ('B5_contacts','B5_space')]
        summary['conformance_status']='ng' if summary['b3_requires_rework'] or 'ng' in stage_statuses else 'needs_review'
        summary.update(status='candidate_pending_human_review',candidate=str(output/'b6-candidate'),
            next_action='Review B2 trial decisions, B3 strategy, B4 fit/suitability and B5 measurements together; no final registration was performed')
        return summary
    except (ValueError,OSError,RuntimeError,KeyError,TypeError) as error:
        summary.update(status='failed',error={'type':type(error).__name__,'message':str(error)},
            next_action='Resolve the recorded stage/integrity error; no successful downstream completion is claimed')
        return summary
    except KeyboardInterrupt:
        summary.update(status='cancelled',next_action='Inspect preserved partial trial evidence before starting a new run')
        return summary
    finally:
        _write(output/'workflow.json',summary)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('task','provider_config','space_config','output'):
        parser.add_argument(name,type=Path)
    parser.add_argument('--max-error-mm3',type=float,required=True)
    parser.add_argument('--max-bbox-difference-mm',type=float)
    parser.add_argument('--run',action='store_true',help='Launch configured agents and diagnostic B3-B6 trial; otherwise validate inputs only')
    args=parser.parse_args()
    try:
        if not args.run:
            task=load_task(args.task)
            if task.get('review_mode')!='provisional_trial':raise ValueError('provisional_trial assignment required')
            validate_config(_read(args.provider_config));_read(args.space_config)
            positive_limit(args.max_error_mm3,'max_error_mm3')
            if args.max_bbox_difference_mm is not None:positive_limit(args.max_bbox_difference_mm,'max_bbox_difference_mm')
            print(json.dumps({'status':'validated_only','part_id':task['part_id'],'registered':False}))
            return 0
        result=run_trial(args.task,args.provider_config,args.space_config,args.output,
            max_error_mm3=args.max_error_mm3,max_bbox_difference_mm=args.max_bbox_difference_mm)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status']=='candidate_pending_human_review' else 2
    except (ValueError,OSError,RuntimeError,KeyError,TypeError) as error:
        parser.exit(1,f'B trial workflow failed: {error}\n')


if __name__=='__main__':raise SystemExit(main())
