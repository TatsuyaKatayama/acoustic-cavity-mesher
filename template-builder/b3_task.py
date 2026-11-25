"""Immutable one-part B3 assignment bound to completed B2 source reviews."""
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from b2_faces import load_scene
from b2_review import open_review, make_handoff


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def create_task(bundle, handoff, part_id, roles, *, candidates, review,
                simplification_review, linear_mm=1e-6, area_mm2=1e-6):
    bundle, handoff = Path(bundle).resolve(), Path(handoff).resolve()
    digest, parts, nodes = load_scene(bundle)
    if part_id not in parts:
        raise ValueError('Unknown assigned part')
    sources = {'candidates': Path(candidates).resolve(), 'contacts': Path(review).resolve(),
               'simplification': Path(simplification_review).resolve()}
    _, draft = open_review(digest, parts, sources['candidates'], sources['contacts'])
    approved = make_handoff(draft, parts, read_json(sources['simplification']))
    if read_json(handoff) != json.loads(json.dumps(approved)):
        raise ValueError('Handoff differs from current completed B2 reviews; export again')
    node = next(n for n in nodes if n['id'] == part_id)
    task = {'schema_version': 1, 'length_unit': 'mm', 'part_id': part_id,
        'bundle': str(bundle), 'handoff': str(handoff), 'manifest_sha256': digest,
        'handoff_sha256': file_hash(handoff),
        'review_sources': {name: {'path': str(path), 'sha256': file_hash(path)} for name, path in sources.items()},
        'face_sets': [deepcopy(g) for g in approved['simplification_guidance']['face_review']['sets'] if g['faces'][0][0] == part_id],
        'contact_constraints': [deepcopy(c) for c in approved['contact_constraints'] if any(r[0] == part_id for r in c['faces'])],
        'source_world_transform': node['world_transform'],
        'source_name': node.get('definition_name') or node['name'],
        'roles': deepcopy(roles), 'status': 'assigned',
        'review_mode': draft.get('review_mode', 'source_review'),
        'tolerances': {'linear_mm': linear_mm, 'area_mm2': area_mm2},
        'preservation_rule': 'Source trimmed face region must be included in output boundary; face extension and changed edges are allowed.',
        'checker_rule': 'Report findings only. Never modify worker artifacts. Unresolved checks require review; no automatic B4.'}
    _validate_roles_tolerances(task)
    return json.loads(json.dumps(task, allow_nan=False))


def _validate_roles_tolerances(task):
    roles = task['roles']
    if not isinstance(roles, dict) or not {'coordinator', 'worker', 'checker'} <= roles.keys() or not roles.keys() <= {'coordinator', 'worker', 'checker', 'strategy'}:
        raise ValueError('Assign coordinator, worker and checker; strategy is optional')
    if any(not isinstance(v, str) or not v.strip() for v in roles.values()) or len(set(roles.values())) != len(roles):
        raise ValueError('Role agents must have distinct nonempty identities')
    tolerances = task['tolerances']
    if set(tolerances) != {'linear_mm', 'area_mm2'} or any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in tolerances.values()):
        raise ValueError('Finite positive geometric tolerances required')


def validate_task(task):
    _validate_roles_tolerances(task)
    if task['schema_version'] != 1 or task['length_unit'] != 'mm' or task['status'] != 'assigned':
        raise ValueError('Expected an assigned B3 task in mm')
    for source in task['review_sources'].values():
        if file_hash(source['path']) != source['sha256']:
            raise ValueError('B2 source review changed; assign a new workflow')
    sources = task['review_sources']
    expected = create_task(task['bundle'], task['handoff'], task['part_id'], task['roles'],
        candidates=sources['candidates']['path'], review=sources['contacts']['path'],
        simplification_review=sources['simplification']['path'], **task['tolerances'])
    if task != expected:
        raise ValueError('B3 assignment differs from its approved source data')
    return task


def load_task(path):
    return validate_task(read_json(path))
