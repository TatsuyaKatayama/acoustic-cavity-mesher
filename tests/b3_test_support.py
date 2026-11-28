"""Synthetic source-review fixture for the one-part B3 workflow tests."""
from copy import deepcopy
import json
from pathlib import Path
from b2_simplification import build_proposal
from b2_review import make_handoff
from b3_prepare import prepare
from test_b2_web import WebReviewTests


def assigned_fixture(test, *, decisions=None):
    f=WebReviewTests(methodName='test_pending_handoff_blocked')
    f.setUp()
    test.addCleanup(f.doCleanups)
    state=f.session.save(f.accepted())
    record=build_proposal(f.session.parts,state['draft'])
    for row in record['proposals']:
        row['decision']='keep'
    if decisions:
        decisions(record)
    record['confirmed']=True
    f.session.simplification_path.write_text(json.dumps(record),encoding='utf-8')
    handoff=make_handoff(state['draft'],f.session.parts,record)
    h=f.bundle/'handoff.json';h.write_text(json.dumps(handoff),encoding='utf-8')
    workflow=f.bundle/'workflow'
    task=prepare(f.bundle,h,'1/1',workflow,{'coordinator':'dispatcher','worker':'creator','checker':'inspector'},
        candidates=f.candidates,review=f.review,simplification_review=f.session.simplification_path)
    return f,workflow,task


def box_plan(*, length=4, width=4, height=2, origin=(0,0,-2)):
    return {'schema_version':1,'operations':[{'id':'body','operation':'box','combine':'new',
        'parameters':{'length_mm':length,'width_mm':width,'height_mm':height},
        'frame':{'origin_mm':list(origin),'x_direction':[1,0,0],'normal':[0,0,1]},
        'source_faces':[], 'rationale':'Synthetic dimensions independently specified for regression.'}]}
