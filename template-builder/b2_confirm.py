"""One per-placement confirmation binds contacts and simplification together."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from b2_propose_part import propose_part
from b2_sets import effective_sets


def fill_references(session):
    path = session.bundle / 'fill-preview.json'
    if not path.exists():
        return set()
    from b2_sets import validate_face
    data = json.loads(path.read_text(encoding='utf-8'))
    return {validate_face([pid, index], session.parts)
            for pid, indices in data.items() for index in indices}


def part_plan(session, part_id):
    state=session.state()
    proposal=propose_part(session.bundle,session.candidate_path,session.review_path,part_id)
    saved_groups=effective_sets(state['simplification']) if state['simplification'] else []
    saved={tuple(ref):g['decision'] for g in saved_groups for ref in g['faces']}
    approximation={tuple(ref):g['approximation'] for g in saved_groups if g['decision']=='simplify' for ref in g['faces']}
    contacts=[]
    protected=set()
    filled = fill_references(session)
    moved_to_close = set()
    closure_path = session.bundle / 'contact-closures.json'
    closures = json.loads(closure_path.read_text(encoding='utf-8')) if closure_path.exists() else {}
    for c in proposal['contacts']:
        row=next(r for r in state['draft']['reviews'] if r['candidate_id']==c['candidate_id'])
        measurement=c['measurement']
        decision=row['decision']
        condition=row['condition']
        if any(tuple(ref) in filled for ref in row['faces']):
            decision, condition = 'rejected', None
        elif closures.get(str(row['candidate_id'])) == row['faces']:
            if measurement is None:
                raise ValueError('隙間を埋める接合候補を再計測できません。')
            decision = 'accepted'
            condition = dict(mode='close', target_gap_mm=0, tolerance_mm=0)
            moved_to_close.add(tuple(row['faces'][0]))
        elif decision=='pending':
            if measurement is None:
                raise ValueError('対応できない接合候補があります。チャットで修正を指示してください。')
            gap=max(0,measurement['gap_mm'])
            decision='accepted'
            condition=dict(mode='close' if gap<=1e-7 else 'keep_gap',target_gap_mm=0 if gap<=1e-7 else gap,tolerance_mm=0)
        contact = dict(candidate_id=row['candidate_id'],faces=row['faces'],decision=decision,condition=condition)
        if decision == 'accepted' and closures.get(str(row['candidate_id'])) == row['faces']:
            contact['adjust_face'] = row['faces'][0]
        contacts.append(contact)
        if decision=='accepted':protected.update(map(tuple,row['faces']))
    faces=[]
    for face in proposal['faces']:
        ref = tuple(face['face'])
        if ref in filled:
            decision = 'omit'
        elif ref in moved_to_close:
            decision = 'simplify'
        elif ref in protected:
            decision = 'keep'
        else:
            decision = saved.get(ref, face['suggestion'])
        if decision!='keep' and face['face'] in session.unrendered_faces:
            raise ValueError('描画できない省略・近似対象面があります。チャットで確認してください。')
        policy=approximation.get(tuple(face['face']),dict(policy='preserve_volume',notes='必要な開口と接合を優先する。',detail_policy='omit_chamfers_and_fillets')) if decision=='simplify' else None
        if ref in moved_to_close:
            policy = dict(policy='unspecified', notes='軸側を基準に軸受内径側を延長し、すき間を0 mmにする。',
                          detail_policy='omit_chamfers_and_fillets')
        faces.append(dict(face=face['face'],decision=decision,approximation=policy))
    plan=dict(part_id=part_id,part_name=proposal['part_name'],contacts=contacts,faces=faces,
        rules=[dict(rule_id=r['rule_id'],revision=r['revision'],record_sha256=r['record_sha256']) for r in proposal['part_rules']],
        manifest_sha256=proposal['manifest_sha256'])
    revision=sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return plan,revision,proposal


def confirmation_path(session):
    return session.review_path.with_name(session.review_path.stem+'.part-confirmations.json')


def read_confirmations(session):
    path=confirmation_path(session)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(schema_version=1,parts={})


def confirmation_state(session, part_id):
    plan,revision,proposal=part_plan(session,part_id)
    saved=read_confirmations(session)
    approved=[]
    for pid,record in saved['parts'].items():
        if pid in session.parts and part_plan(session,pid)[1]==record['proposal_revision']:
            approved.append(pid)
    return dict(plan=plan,proposal_revision=revision,proposal=proposal,
        approved=part_id in approved,approved_parts=approved,total_parts=len(session.parts))


def approve_part(session,request):
    part_id=request['part_id']
    plan,revision,_=part_plan(session,part_id)
    if request.get('proposal_revision')!=revision:
        raise ValueError('提案または判断が変わりました。表示を更新して再確認してください。')
    path=confirmation_path(session)
    saved=read_confirmations(session)
    if path.exists():
        old=path.read_bytes()
        archive=path.with_name(path.stem+'.previous-'+sha256(old).hexdigest()[:16]+'.json')
        if not archive.exists():archive.write_bytes(old)
    saved['parts'][part_id]=dict(proposal_revision=revision,plan=plan,
        approved_utc=datetime.now(timezone.utc).isoformat(),approval_source='human_part_confirmation')
    from b2_faces import write_json
    write_json(path,saved)
    result=confirmation_state(session,part_id)
    # Keep the existing guarded B3 handoff format. Only after every placement's
    # combined plan is current do we materialize the approved decisions.
    if len(result['approved_parts'])==len(session.parts):
        draft=deepcopy(session.state()['draft'])
        pairs={}
        all_faces={}
        all_policies={}
        for entry in saved['parts'].values():
            for c in entry['plan']['contacts']:
                previous=pairs.setdefault(c['candidate_id'],c)
                if previous!=c:raise ValueError('両部品の接合条件が一致しません。再確認してください。')
            all_faces.update({tuple(r['face']):r['decision'] for r in entry['plan']['faces']})
            all_policies.update({tuple(r['face']):r.get('approximation') for r in entry['plan']['faces']})
        for i,row in enumerate(draft['reviews']):draft['reviews'][i]={**row,**pairs[row['candidate_id']]}
        from b2_simplification import build_proposal,validate_review
        record=build_proposal(session.parts,draft)
        groups=[]
        for pid in session.parts:
            for d in ('keep','simplify','omit'):
                refs=[list(ref) for ref,decision in all_faces.items() if ref[0]==pid and decision==d]
                if not refs:continue
                buckets={}
                for ref in refs:
                    key=json.dumps(all_policies[tuple(ref)],sort_keys=True,ensure_ascii=False)
                    buckets.setdefault(key,[]).append(ref)
                for number,(key,members) in enumerate(buckets.items()):
                    groups.append(dict(id=d+'-'+pid.replace('/','_')+'-'+str(number),name=d,decision=d,faces=members,approximation=json.loads(key)))
        record['sets']=groups
        for row in record['proposals']:row['decision']=all_faces[tuple(row['face'])]
        record['confirmed']=True
        validate_review(record,draft,session.parts,require_complete=True)
        directory=session.bundle/('confirmed-b2-'+uuid4().hex[:12])
        directory.mkdir()
        from b2_review import make_handoff
        write_json(directory/'review.json',draft)
        write_json(directory/'review.simplification.json',record)
        write_json(directory/'b3-input.json',make_handoff(draft,session.parts,record))
        result['confirmed_output']=str(directory.resolve())
    return result
