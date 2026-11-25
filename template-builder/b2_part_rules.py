"""Versioned, reusable part policies; stored separately from B2 case approvals."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import unicodedata

DEFAULT_STORE = Path(__file__).resolve().parent/'b1-output'/'part-rules'
ACTIONS = {'protect', 'preserve', 'approximate', 'omit_candidate', 'ask'}


def source_part(bundle, part_id):
    manifest = json.loads((Path(bundle)/'assembly.json').read_text(encoding='utf-8-sig'))
    node = next((n for n in manifest['nodes'] if n['id']==part_id and n['kind']=='part'), None)
    if node is None:
        raise ValueError('Unknown part placement')
    geometry = Path(bundle)/node['geometry']
    digest = sha256(geometry.read_bytes()).hexdigest()
    if digest != geometry.stem:
        raise ValueError('B1 geometry hash mismatch')
    return node, digest, manifest


def name_key(name):
    return unicodedata.normalize('NFKC',name).strip().casefold()


def save_rule(bundle, part_id, policy, store=DEFAULT_STORE, *, family=None, status='draft', exact_geometry=False):
    node, geometry, manifest = source_part(bundle, part_id)
    if status not in ('draft','approved','retired'):
        raise ValueError('Invalid rule status')
    if not isinstance(policy,dict) or set(policy)-{'instruction','interpretation','face_overrides','open_questions'}:
        raise ValueError('Expected instruction, interpretation and optional face_overrides/open_questions')
    if not isinstance(policy.get('instruction'),str) or not policy['instruction'].strip():
        raise ValueError('Preserve the original natural-language instruction')
    rules = policy.get('interpretation')
    if not isinstance(rules,list) or not rules:
        raise ValueError('Record the interpretation as nonempty rules')
    for rule in rules:
        if not isinstance(rule,dict) or not {'target','action','reason'}<=rule.keys() or rule['action'] not in ACTIONS:
            raise ValueError('Each rule requires a semantic target, action and reason')
        if any(not isinstance(rule[k],str) or not rule[k].strip() for k in ('target','reason')):
            raise ValueError('Rule target and reason must be nonempty text')
    overrides = policy.get('face_overrides',[])
    seen=set()
    from b2_faces import load_parts
    _, parts = load_parts(Path(bundle))
    for override in overrides:
        if not isinstance(override,dict) or set(override)!={'face_index','decision','reason'}:
            raise ValueError('Face overrides require face_index, decision and reason')
        index=override['face_index']
        if type(index) is not int or not 1<=index<=parts[part_id][1].Extent() or index in seen:
            raise ValueError('Unknown or duplicate B1 face index')
        if override['decision'] not in ('keep','simplify','omit') or not isinstance(override['reason'],str) or not override['reason'].strip():
            raise ValueError('Invalid face override')
        seen.add(index)
    if family is not None and (not isinstance(family,str) or not family.strip()):
        raise ValueError('Explicit nonempty family key required')
    # Face numbering is valid only for this exact geometry, even for family policies.
    scope = ({'kind':'family','family_key':family} if family else
             {'kind':'geometry','geometry_sha256':geometry} if exact_geometry else
             {'kind':'part_name','name_key':name_key(node.get('definition_name') or node['name'])})
    key = sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()[:24]
    folder = Path(store)/key
    folder.mkdir(parents=True,exist_ok=True)
    versions = [int(p.stem.split('-')[-1]) for p in folder.glob('revision-*.json')]
    revision = max(versions,default=0)+1
    previous=json.loads((folder/f'revision-{revision-1:04d}.json').read_text(encoding='utf-8')) if versions else None
    inherited={name_key(r['target']):r for r in previous['interpretation']} if previous else {}
    inherited.update({name_key(r['target']):r for r in rules})
    history=list(previous.get('instruction_history',[])) if previous else []
    history.append(dict(revision=revision,instruction=policy['instruction'],status=status,
                        geometry_sha256=geometry,part_id=part_id))
    record = dict(schema_version=1,rule_id=key,revision=revision,status=status,
        created_utc=datetime.now(timezone.utc).isoformat(),scope=scope,
        part_name=node.get('definition_name') or node['name'],
        source=dict(bundle=str(Path(bundle).resolve()),part_id=part_id,geometry_sha256=geometry,
                    step_sha256=manifest['source_sha256']),
        instruction=policy['instruction'],instruction_history=history,interpretation=list(inherited.values()),face_overrides=overrides,
        open_questions=policy.get('open_questions',previous.get('open_questions',[]) if previous else []),
        approval_scope='Reusable policy only; does not approve a B2 case or start B3')
    path=folder/f'revision-{revision:04d}.json'
    with path.open('x',encoding='utf-8') as f:
        json.dump(record,f,ensure_ascii=False,indent=2)
    return path,record


def find_rules(bundle, part_id, store=DEFAULT_STORE, *, family=None):
    node, geometry, _ = source_part(bundle,part_id)
    latest=[]
    for folder in sorted(Path(store).glob('*')):
        paths=sorted(folder.glob('revision-*.json'))
        if not paths:
            continue
        path=paths[-1]
        rule=json.loads(path.read_text(encoding='utf-8'))
        scope=rule['scope']
        match=(scope['kind']=='geometry' and scope['geometry_sha256']==geometry or
               scope['kind']=='part_name' and scope['name_key']==name_key(node.get('definition_name') or node['name']) or
               scope['kind']=='family' and family is not None and scope['family_key']==family)
        if match and rule['status']!='retired':
            latest.append({**rule,'record_path':str(path.resolve()),'record_sha256':sha256(path.read_bytes()).hexdigest(),
                'face_bindings_applicable':rule['source']['geometry_sha256']==geometry})
    return latest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=('save','show','list'))
    p.add_argument('--store',type=Path,default=DEFAULT_STORE)
    p.add_argument('--bundle',type=Path)
    p.add_argument('--part')
    p.add_argument('--policy',type=Path)
    p.add_argument('--family',help='Explicit opt-in family key; never inferred from part name')
    p.add_argument('--exact-geometry',action='store_true',help='Limit a saved rule to this BREP; default groups revisions by part name')
    p.add_argument('--status',choices=('draft','approved','retired'),default='draft')
    a=p.parse_args()
    try:
        if a.operation=='list':
            result=[str(path.resolve()) for path in sorted(a.store.glob('*/revision-*.json'))]
        else:
            if a.bundle is None or a.part is None:
                raise ValueError('--bundle and --part required')
            if a.operation=='show':
                result=find_rules(a.bundle,a.part,a.store,family=a.family)
            else:
                if a.policy is None:raise ValueError('--policy required')
                path,record=save_rule(a.bundle,a.part,json.loads(a.policy.read_text(encoding='utf-8-sig')),a.store,family=a.family,status=a.status,exact_geometry=a.exact_geometry)
                result={'path':str(path.resolve()),'rule':record}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,TypeError) as error:
        p.exit(1,f'Part rule operation failed: {error}\n')


if __name__=='__main__':main()
