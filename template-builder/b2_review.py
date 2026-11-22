"""Versioned records for contact review and template handoff."""

from hashlib import sha256
import json
from math import isfinite

from b2_faces import load_candidates, validate_pair
from OCP.TopoDS import TopoDS
from propose_contacts import measure_contact


def open_review(bundle_digest, parts, candidate_path, draft_path):
    candidate_digest = sha256(candidate_path.read_bytes()).hexdigest()
    candidates = load_candidates(candidate_path, bundle_digest, parts)
    identity = {
        "schema_version": 1,
        "manifest_sha256": bundle_digest,
        "candidates_sha256": candidate_digest,
    }
    if draft_path.exists():
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        if any(draft.get(key) != value for key, value in identity.items()):
            raise ValueError("Review belongs to a different B1 bundle or candidate list")
        expected = list(range(1, len(candidates) + 1))
        if [item["candidate_id"] for item in draft["reviews"]] != expected:
            raise ValueError("Review rows do not match the candidate list")
        for item in draft["reviews"]:
            validate_decision(item, parts)
    else:
        draft = {
            **identity, "simplification_notes": "",
            "reviews": [
                {"candidate_id": index, "faces": pair, "decision": "pending", "condition": None}
                for index, (pair, _, _) in enumerate(candidates, 1)
            ],
        }
    return candidates, draft


def validate_decision(item, parts):
    pair = validate_pair(item["faces"], parts)
    decision, condition = item["decision"], item["condition"]
    if decision in ("pending", "rejected") and condition is None:
        return pair
    if decision != "accepted" or not isinstance(condition, dict):
        raise ValueError("Invalid review decision or contact condition")
    mode = condition["mode"]
    target, tolerance = condition["target_gap_mm"], condition["tolerance_mm"]
    if type(target) not in (int, float) or type(tolerance) not in (int, float):
        raise ValueError("隙間と許容差は数値で入力してください。")
    if not isfinite(target) or not isfinite(tolerance) or tolerance < 0:
        raise ValueError("許容差には0以上の有限値を指定してください。")
    if not (mode == "close" and target == 0 or mode == "keep_gap" and target > 0):
        raise ValueError("隙間を残す場合は、正の目標隙間を指定してください。")
    if mode == "keep_gap" and tolerance >= target:
        raise ValueError("隙間を残す場合、許容差は目標隙間より小さくしてください。")
    return pair


def make_handoff(draft, parts):
    constraints = []
    used_pairs = set()
    for item in draft["reviews"]:
        pair = validate_decision(item, parts)
        if item["decision"] == "pending":
            raise ValueError(f"Candidate {item['candidate_id']} is pending")
        if item["decision"] == "rejected":
            continue
        signature = frozenset(pair)
        if signature in used_pairs:
            raise ValueError(f"Duplicate accepted face pair at candidate {item['candidate_id']}")
        used_pairs.add(signature)
        measurement = measure_contact(*(TopoDS.Face_s(parts[p][1].FindKey(i)) for p, i in pair))
        if measurement is None:
            raise ValueError(f"Unsupported or non-overlapping accepted faces at candidate {item['candidate_id']}")
        constraints.append({
            "candidate_id": item["candidate_id"],
            "faces": pair,
            **item["condition"],
            "contact_type": measurement["contact_type"],
            "source_measurement": measurement,
        })
    return {
        "schema_version": 1,
        "manifest_sha256": draft["manifest_sha256"],
        "candidates_sha256": draft["candidates_sha256"],
        "length_unit": "mm",
        "simplification_guidance": {
            "typical_part_dimension_mm": [5, 200],
            "small_feature_review_threshold_mm": 5,
            "rule": "Consider omitting features at or below the threshold. Preserve required features regardless of size.",
            "notes": draft["simplification_notes"],
        },
        "contact_constraints": constraints,
    }
