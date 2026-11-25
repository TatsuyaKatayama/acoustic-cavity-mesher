"""Collect one B3 checker result without modifying the worker or advancing B4."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from b3_task import load_task
from b3_check import check_task


def collect(task_path, artifact_dir, report_path):
    task=load_task(task_path)
    report_path=Path(report_path)
    report=json.loads(report_path.read_text(encoding='utf-8'))
    independent=check_task(task_path,artifact_dir)
    if report != independent:
        raise ValueError('Report differs from independent inspection of this artifact')
    return {'schema_version':1,'stage':'B3','part_id':task['part_id'],
        'roles':task['roles'],'status':{'ok':'checked','ng':'return_to_worker','needs_review':'review_required'}[report['status']],
        'task_sha256':report['task_sha256'],'artifact_sha256':report['artifact_sha256'],
        'report_sha256':sha256(report_path.read_bytes()).hexdigest(),
        'report':str(report_path.resolve()),
        'next_action':{'ok':'Human review; B4 is a separate workflow',
            'ng':'Send findings to worker; build a new attempt and check again',
            'needs_review':'Resolve reported questions with human/strategy review before accepting'}[report['status']],
        'automatic_next_stage':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('task','artifact','report','output'):p.add_argument(name,type=Path)
    a=p.parse_args()
    try:
        if a.output.exists() or a.output.resolve().is_relative_to(a.artifact.resolve()):
            raise ValueError('Collection output must be new and outside worker artifacts')
        result=collect(a.task,a.artifact,a.report)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:p.exit(1,f'B3 collection failed: {e}\n')

if __name__=='__main__':main()
