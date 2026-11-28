"""Assign one approved B2 part to a B3 coordinator, worker and checker."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from b3_task import create_task
from agent_roles import B3_ROLES, load_role


def prepare(bundle, handoff, part_id, output, roles, **sources):
    task = create_task(bundle, handoff, part_id, roles, **sources)
    output = Path(output)
    if output.exists():
        raise ValueError('Workflow output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmp:
        directory = Path(tmp)/'workflow'
        directory.mkdir()
        (directory/'task.json').write_text(json.dumps(task, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        for role in roles:
            if role in B3_ROLES:
                instructions = load_role(B3_ROLES[role])
                (directory/(role+'.txt')).write_text(
                    f'Assigned agent: {roles[role]}\nPart: {part_id}\n{instructions}\n',
                    encoding='utf-8')
        directory.rename(output)
    return task


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','handoff','part_id','output'):
        p.add_argument(name,type=str if name=='part_id' else Path)
    for name in ('candidates','review','simplification-review'):
        p.add_argument('--'+name,type=Path,required=True)
    for role in ('coordinator','worker','checker'):
        p.add_argument('--'+role,required=True)
    p.add_argument('--strategy')
    p.add_argument('--linear-mm',type=float,default=1e-6)
    p.add_argument('--area-mm2',type=float,default=1e-6)
    a=p.parse_args()
    try:
        roles={r:getattr(a,r) for r in ('coordinator','worker','checker','strategy') if getattr(a,r)}
        prepare(a.bundle,a.handoff,a.part_id,a.output,roles,candidates=a.candidates,review=a.review,
            simplification_review=a.simplification_review,linear_mm=a.linear_mm,area_mm2=a.area_mm2)
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:
        p.exit(1,f'B3 assignment failed: {e}\n')

if __name__=='__main__':
    main()
