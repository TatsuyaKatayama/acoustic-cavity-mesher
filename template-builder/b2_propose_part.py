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


def propose_part(bundle,candidates,review,part_id,*,rule_store=None,rule_family=None):
    digest,parts,nodes=load_scene(Path(bundle))
    if part_id not in parts:raise ValueError('Unknown part')
    _,draft=open_review(digest,parts,Path(candidates),Path(review))
    return _propose_part(digest,parts,nodes,Path(candidates),Path(review),draft,part_id,bundle=bundle,rule_store=rule_store,rule_family=rule_family)


def _propose_part(digest,parts,nodes,candidates,review,draft,part_id,*,bundle=None,rule_store=None,rule_family=None):
    from b2_part_rules import find_rules, DEFAULT_STORE
    policies=find_rules(bundle,part_id,rule_store if rule_store is not None else DEFAULT_STORE,family=rule_family)
    overrides={}
    for policy in policies:
        if policy['status']=='approved' and policy['face_bindings_applicable']:
            for override in policy['face_overrides']:
                overrides.setdefault(override['face_index'],[]).append((override,policy))
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
        sources=[]
        choices=overrides.get(index,[])
        if choices and tuple(ref) not in protected and not (surface['surface_type']=='cylindrical' and surface['normal_sense']=='inward'):
            if len({choice[0]['decision'] for choice in choices})==1:
                suggestion=choices[0][0]['decision']
                reason='保存済み部品ルール：'+choices[0][0]['reason']
                sources=[{'rule_id':p['rule_id'],'revision':p['revision'],'record_sha256':p['record_sha256']} for _,p in choices]
            else:
                suggestion,reason='keep','保存済みルールが競合するため仮保持。自然言語で方針を確認する。'
        faces.append({'face':ref,'suggestion':suggestion,'reason':reason,'surface':surface,'rule_sources':sources})
    groups=[{'suggestion':decision,'faces':[r['face'] for r in faces if r['suggestion']==decision],
             'reason':reason} for decision,reason in (
        ('keep','接合候補・内壁・開口・解析的な主要壁面を保護する。'),
        ('simplify','曲面の近似を検討する。主要壁面か細部かを確認し、保持条件と許容差から作成戦略を決める。'),
        ('omit','接合候補以外の円錐・トーラスをC/R候補として省略を提案する。面種だけで機能の有無は確定できない。'))]
    questions=[{'face':r['face'],'suggestion':r['suggestion'],'reason':r['reason']}
               for r in faces if r['suggestion']!='keep']
    return {'schema_version':1,'stage':'B2_proposal','approved':False,'part_id':part_id,
        'manifest_sha256':digest,'candidates_sha256':sha256(Path(candidates).read_bytes()).hexdigest(),
        'review_sha256':sha256(Path(review).read_bytes()).hexdigest() if Path(review).exists() else 'new',
        'part_name':next(n.get('definition_name') or n['name'] for n in nodes if n['id']==part_id),
        'contacts':contacts,'faces':faces,'proposed_sets':[g for g in groups if g['faces']],
        'summary':{d:sum(r['suggestion']==d for r in faces) for d in ('keep','simplify','omit')},
        'human_questions':questions,
        'part_rules':policies,
        'rule_questions':[{'rule_id':p['rule_id'],'revision':p['revision'],'status':p['status'],
            'questions':p['open_questions'],'requires_feature_mapping':True} for p in policies],
        'rule_application':{'bound_face_count':sum(bool(f['rule_sources']) for f in faces),
            'semantic_rules_require_feature_mapping':bool(policies),
            'note':'自然言語の意味・フィーチャー対応は担当が確認する。承認済みで同一形状の面対応だけを自動適用し、接合候補・内向き円筒面の保護を優先する。部品名だけでは転用しない。'},
        'review_rule':'まず部品ごとの三分類案と理由を提示し、変更箇所・迷う箇所を人が判断する。未確定の接合候補は仮保護する。提案はレビュー保存・承認を変更せず、B3受け渡しには使用できない。'}


def propose_assembly(bundle,candidates,review,*,rule_store=None,rule_family=None):
    """One advisory B2 operation; no review decisions or CAD are modified."""
    candidates,review=Path(candidates),Path(review)
    digest,parts,nodes=load_scene(Path(bundle))
    _,draft=open_review(digest,parts,candidates,review)
    proposals=[_propose_part(digest,parts,nodes,candidates,review,draft,pid,bundle=bundle,rule_store=rule_store,rule_family=rule_family) for pid in parts]
    return {'schema_version':1,'stage':'B2_assembly_proposal','approved':False,
        'manifest_sha256':digest,'candidates_sha256':sha256(candidates.read_bytes()).hexdigest(),
        'review_sha256':sha256(review.read_bytes()).hexdigest() if review.exists() else 'new',
        'parts':proposals,
        'faces':[row for p in proposals for row in p['faces']],
        'contacts':[{'candidate_id':r['candidate_id'],'faces':r['faces'],'saved_decision':r['decision']} for r in draft['reviews']],
        'summary':{d:sum(p['summary'][d] for p in proposals) for d in ('keep','simplify','omit')},
        'pending_contact_ids':[r['candidate_id'] for r in draft['reviews'] if r['decision']=='pending'],
        'review_rule':'提案を先にまとめて提示する。接合候補・開口を保護し、迷う箇所は面参照と理由を添えて確認する。承認・B3開始は別操作。'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','candidates','review','part_id','output'):p.add_argument(name,type=str if name=='part_id' else Path)
    p.add_argument('--rule-store',type=Path)
    p.add_argument('--rule-family',help='Explicit family key; exact geometry rules are loaded automatically')
    a=p.parse_args()
    try:
        if a.output.exists():raise ValueError('Output already exists')
        options=dict(rule_store=a.rule_store,rule_family=a.rule_family)
        proposal=propose_assembly(a.bundle,a.candidates,a.review,**options) if a.part_id=='all' else propose_part(a.bundle,a.candidates,a.review,a.part_id,**options)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as e:p.exit(1,f'B2 part proposal failed: {e}\n')

if __name__=='__main__':main()
