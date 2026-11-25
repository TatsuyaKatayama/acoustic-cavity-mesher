"""Build one dimension-driven FH trial artifact; check it separately."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from b1_step import brep_bytes
from b3_task import load_task,validate_task
from b2_faces import load_parts
from b2_sets import surface_reference
import cadquery as cq
import fh_template


def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
def digest(data):return sha256(data).hexdigest()


def build_task(task,dimensions,output):
    validate_task(task)
    p=fh_template.parameters(dimensions)
    output=Path(output)
    if output.exists():raise ValueError('Output already exists')
    _,parts=load_parts(Path(task['bundle']))
    allowed={tuple(r) for g in task['face_sets'] if g['decision'] in ('keep','simplify') for r in g['faces']}
    surfaces={r[1]:surface_reference(list(r),parts) for r in allowed}
    def refs(predicate):return [[task['part_id'],i] for i,s in sorted(surfaces.items()) if predicate(i,s)]
    def cylinders(*radii):return refs(lambda i,s:s['surface_type']=='cylindrical' and any(abs(s['radius_mm']-r)<1e-5 for r in radii))
    def planes(z):return refs(lambda i,s:s['surface_type']=='planar' and abs(s['origin_mm'][2]-z)<1e-5)
    approximate=[r for g in task['face_sets'] if g['decision']=='simplify' for r in g['faces']]
    sourcevol=cq.Shape.cast(parts[task['part_id']][0]).Volume()
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temporary:
        work=Path(temporary)/'artifact';work.mkdir();history=[];operations=[]
        for index,(name,model) in enumerate(fh_template.build_history(p),1):
            shape=model.val()
            if not shape.isValid() or len(shape.Solids())!=1:raise ValueError('Invalid shape after '+name)
            if name=='same_domain_cleanup':source=[]
            elif name in ('flange','flange_ring_stock'):source=planes(p['world_z_mm'])+cylinders(p['flange_radius_mm'])
            elif name=='lower_boss':source=cylinders(p['lower_boss_radius_mm'])+planes(p['world_z_mm']-p['lower_boss_depth_mm'])
            elif name=='center_boss':source=cylinders(p['boss_radius_mm'])+planes(p['world_z_mm']+p['flange_height_mm']+p['boss_height_mm'])
            elif name=='shaft_bore':source=cylinders(p['bore_radius_mm'])
            elif name.startswith(('arc_opening','upper_opening','drafted_arc_opening')):source=cylinders(p['slot_center_radius_mm']-p['slot_width_mm']/2,p['slot_center_radius_mm']+p['slot_width_mm']/2,p['slot_width_mm']/2)
            elif name.startswith('bolt'):source=cylinders(p['bolt_radius_mm'])
            elif name.startswith('aux'):source=cylinders(*[h['radius_mm'] for h in p['aux_holes']])
            elif name in ('sector_pocket','drafted_sector_pocket'):source=approximate+planes(p['world_z_mm']+p['pocket_floor_mm'])
            else:source=cylinders(p['ring_inner_radius_mm'],p['flange_radius_mm'])+planes(p['world_z_mm']+p['ring_top_mm'])
            source=[list(r) for r in sorted(set(map(tuple,source)))]
            data=brep_bytes(shape.wrapped);filename=f'history-{index:03d}.brep';(work/filename).write_bytes(data)
            history.append({'operation_id':name,'geometry':filename,'sha256':digest(data),'source_faces':source,'volume_mm3':shape.Volume()})
            operations.append({'id':name,'operation':'fh_'+name.split('_')[0],'combine':'new' if index==1 else 'cut' if name.startswith(('shaft','arc','upper','bolt','aux','sector','drafted')) else 'union','source_faces':source,'rationale':'Dimension-driven FH feature; source surfaces used as reference, no detailed solid editing.'})
        final=brep_bytes(shape.wrapped);(work/'final.brep').write_bytes(final)
        plan={'schema_version':1,'template_id':fh_template.TEMPLATE_ID,'template_version':fh_template.TEMPLATE_VERSION,
            'parameters':p,'operations':operations,
            'objective':{'priority':'Reduce faces, edges and construction features subject to retained-surface and explicit volume constraints','slot_ledges':'Eliminate horizontal upper-opening ledges using ruled draft for construction version 3'},
            'complexity':{'source_faces':len(cq.Shape.cast(parts[task['part_id']][0]).Faces()),'source_edges':len(cq.Shape.cast(parts[task['part_id']][0]).Edges()),'rebuilt_faces':len(shape.Faces()),'rebuilt_edges':len(shape.Edges()),'construction_operations':len(operations)},
            'policy_checks':[{'set_id':g['id'],'scope':'whole_part','max_volume_difference_mm3':sourcevol*.01} for g in task['face_sets'] if g['decision']=='simplify'],
            'trial_criteria':{'source_volume_mm3':sourcevol,'volume_relative_tolerance':.01,'human_approval':'pending'},
            'strategy':'Omit C/R while retaining functional rounded opening ends. Version 3 replaces upper slot ledges with ruled draft and defines radial/angular pocket draft from source surface datums. Common stock and pocket-before-boss construction avoid artificial overlaps. Earlier construction versions remain reproducible.'}
        code=Path(fh_template.__file__).read_bytes()+b'\nPARAMETERS = '+repr(p).encode()+b'\nresult = build(PARAMETERS)\n'
        for filename,data in [('task.json',encoded(task)),('plan.json',encoded(plan)),('generated.py',code),('parameters.json',encoded(p))]:(work/filename).write_bytes(data)
        artifact={'schema_version':1,'stage':'B3','status':'awaiting_check','length_unit':'mm','coordinate_frame':'world','part_id':task['part_id'],
            'manifest_sha256':task['manifest_sha256'],'handoff_sha256':task['handoff_sha256'],'task_sha256':digest(encoded(task)),'plan_sha256':digest(encoded(plan)),
            'roles':task['roles'],'worker':task['roles']['worker'],'code':'generated.py','code_sha256':digest(code),'geometry':'final.brep','geometry_sha256':digest(final),
            'history':history,'contact_constraints':task['contact_constraints'],'template_id':fh_template.TEMPLATE_ID,'parameters':p,'note':'Specialized FH trial, not registered or human-approved.'}
        (work/'artifact.json').write_bytes(encoded(artifact));work.rename(output)
    return artifact


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('task',type=Path);p.add_argument('dimensions',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    try:
        artifact=build_task(load_task(a.task),json.loads(a.dimensions.read_text(encoding='utf-8')),a.output)
        print(json.dumps({'status':artifact['status'],'history_steps':len(artifact['history']),'output':str(a.output)}))
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:p.exit(1,f'FH build failed: {e}\n')
if __name__=='__main__':main()
