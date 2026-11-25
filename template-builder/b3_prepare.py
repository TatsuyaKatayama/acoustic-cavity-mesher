"""Assign one approved B2 part to a B3 coordinator, worker and checker."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from b3_task import create_task


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
        for role, instructions in {
            'coordinator': 'Assign this one part. Dispatch worker, then a different checker. Collect reports. On NG, send findings back to worker with a new artifact directory, then recheck. Do not approve B2 or advance B4. Preserve every attempt.',
            'worker': 'Read task.json and B2 face_sets. Measure source faces as references, develop a dimensioned plan.json, then use b3_build.py. Build new CadQuery solids from primitives and history. Keep source face regions on final boundary; extensions are allowed and exact edges are not required. Use simplify sets and their optional policies. Minimize faces, edges and unnecessary features subject to retained surface regions, openings, contacts and declared tolerances. Extend retained faces and use draft where required to connect them. Explain any remaining step. Before submission compare source and result counts, synchronized views and relevant sections, and record findings. Do not use omitted-only faces/edges as construction references. State uncertainty and request strategy help if needed. Do not approve your own work.',
            'checker': 'Read task.json, original B1 and worker artifacts independently. Run b3_check.py. Check retained/contact surface coverage and orientation, reference provenance, simplify policies, omission treatment, new solid validity and reproducibility. Report OK/NG/needs_review with evidence. Do not edit model, plan, source reviews or worker code. A report does not approve B4.'
        }.items():
            (directory/(role+'.txt')).write_text(f'Assigned agent: {roles[role]}\nPart: {part_id}\n{instructions}\n',encoding='utf-8')
        if roles.get('strategy'):
            (directory/'strategy.txt').write_text(
                f"Assigned agent: {roles['strategy']}\nPart: {part_id}\n"
                'Propose a construction strategy from the approved face sets, datums and policy. '
                'Report unsupported geometry and missing evaluation criteria to coordinator. '
                'Do not change B2 decisions, approve the model or act as checker.\n', encoding='utf-8')
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
