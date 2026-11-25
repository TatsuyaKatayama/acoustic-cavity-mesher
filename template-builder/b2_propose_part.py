"""Prepare unapproved, conservative per-part B2 review suggestions."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Torus
from OCP.TopoDS import TopoDS
from b2_faces import load_scene
from b2_review import open_review
from b2_sets import surface_reference
from review_contacts_web import measure_pair


def propose_part(bundle,candidates,review,part_id):
    digest,parts,nodes=load_scene(Path(bundle))
    if part_id not in parts:raise ValueError('Unknown part')
    _,draft=open_review(digest,parts,Path(candidates),Path(review))
    contacts=[];protected=set()
    for row in draft['reviews']:
        if not any(r[0]==part_id for r in row['faces']):continue
        measurement=measure_pair(row['faces'],parts)
        contacts.append({'candidate_id':row['candidate_id'],'faces':row['faces'],
            'saved_decision':row['decision'],'measurement':measurement,
            'recommendation':'review_contact' if measurement else 'review_unsupported',
            'reason':'幾何的な接合候補。実際の取付・摺動・必要隙間は人が確認する。目標隙間と許容差を自動承認しない。'})
        # Reserve every undecided contact face until human contact review.
        if row['decision']!='rejected':protected.update(tuple(r) for r in row['faces'] if r[0]==part_id)
    faces=[]
    for index in range(1,parts[part_id][1].Extent()+1):
        ref=[part_id,index];surface=surface_reference(ref,parts)
        kind=BRepAdaptor_Surface(TopoDS.Face_s(parts[part_id][1].FindKey(index))).GetType()
        if tuple(ref) in protected:
            suggestion,reason='keep','接合候補面。接合判断が完了するまで保護する。'
        elif surface['surface_type']=='cylindrical' and surface['normal_sense']=='inward':
            suggestion,reason='keep','内壁・穴・長穴の可能性。開口や流路を塞がないため保持を推奨。'
        elif kind in (GeomAbs_Cone,GeomAbs_Torus):
            suggestion,reason='omit','C/Rなどの遷移面候補。意図した穴・接合を壊さないか要確認。面種だけでは省略可と確定しない。'
        elif surface['surface_type'] in ('planar','cylindrical'):
            suggestion,reason='keep','基準・外壁・開口境界の候補。面の延長は可、元の面領域は保持する案。'
        else:
            suggestion,reason='simplify','曲面を含む近似の検討対象。面種から作成戦略を確定できないため個別レビュー。'
        faces.append({'face':ref,'suggestion':suggestion,'reason':reason,'surface':surface})
    return {'schema_version':1,'stage':'B2_proposal','approved':False,'part_id':part_id,
        'manifest_sha256':digest,'candidates_sha256':sha256(Path(candidates).read_bytes()).hexdigest(),
        'review_sha256':sha256(Path(review).read_bytes()).hexdigest() if Path(review).exists() else 'new',
        'part_name':next(n.get('definition_name') or n['name'] for n in nodes if n['id']==part_id),
        'contacts':contacts,'faces':faces,
        'review_rule':'接合面を先に承認し、その後に簡略化案をレビューする。これは未承認の提案でB3受け渡しには使用できない。'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','candidates','review','part_id','output'):p.add_argument(name,type=str if name=='part_id' else Path)
    a=p.parse_args()
    try:
        if a.output.exists():raise ValueError('Output already exists')
        proposal=propose_part(a.bundle,a.candidates,a.review,a.part_id)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:p.exit(1,f'B2 part proposal failed: {e}\n')

if __name__=='__main__':main()
