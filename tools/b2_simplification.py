"""B2 simplification proposals and contact-protected human review records."""

from hashlib import sha256
import json
from math import isfinite

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS

from b2_review import validate_decision


def contact_signature(draft):
    """Bind to reviewed references/conditions, independent of cached measurements."""
    identity = {key: draft[key] for key in ("manifest_sha256", "candidates_sha256")}
    identity["reviews"] = [{key: row[key] for key in
        ("candidate_id", "faces", "decision", "condition")} for row in draft["reviews"]]
    for identity_row, row in zip(identity["reviews"], draft["reviews"]):
        if "adjust_face" in row:
            identity_row["adjust_face"] = row["adjust_face"]
    return sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode()).hexdigest()


def protected_faces(draft, parts):
    protected = set()
    for row in draft["reviews"]:
        pair = validate_decision(row, parts)
        if row["decision"] == "pending":
            raise ValueError("接合面レビューを全件保存してから簡略化レビューへ進んでください。")
        if row["decision"] == "accepted":
            adjust = row.get("adjust_face")
            if adjust is not None and (tuple(adjust) not in pair or row["condition"]["mode"] != "close"):
                raise ValueError("Invalid adjustment face for contact closure")
            protected.update(ref for ref in pair if adjust is None or ref != tuple(adjust))
    return protected


def face_measurement(face):
    surface = BRepAdaptor_Surface(face)
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, properties, 1e-9)
    measurement = {"area_mm2": properties.Mass()}
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    if surface.GetType() == GeomAbs_Plane:
        measurement.update(surface_type="planar", planar_spans_mm=[u1-u0, v1-v0])
    elif surface.GetType() == GeomAbs_Cylinder:
        measurement.update(surface_type="cylindrical", diameter_mm=2*surface.Cylinder().Radius(),
                           axial_span_mm=v1-v0)
    else:
        measurement["surface_type"] = "other"
    return measurement


def proposal_reasons(measurement, threshold):
    """Heuristics suggest review only; a small face is not proof of a removable feature."""
    reasons = []
    if measurement["surface_type"] == "planar":
        if 0 < min(measurement["planar_spans_mm"]) <= threshold:
            reasons.append("平面の面内幅がしきい値以下。段差・細部の可能性を確認")
    elif measurement["surface_type"] == "cylindrical":
        if measurement["diameter_mm"] <= threshold:
            reasons.append("円筒径がしきい値以下。必要な穴・開口・軸でないか確認")
        if 0 < measurement["axial_span_mm"] <= threshold:
            reasons.append("円筒面の軸方向幅がしきい値以下。必要な内壁・段差でないか確認")
    return reasons


def build_proposal(parts, draft, threshold_mm=5):
    if type(threshold_mm) not in (int, float) or not isfinite(threshold_mm) or threshold_mm <= 0:
        raise ValueError("削除提案のしきい値は正の有限値で指定してください。")
    protected = protected_faces(draft, parts)
    proposals = []
    for part_id, (_, faces) in parts.items():
        for index in range(1, faces.Extent()+1):
            if (part_id, index) in protected:
                continue
            measurement = face_measurement(TopoDS.Face_s(faces.FindKey(index)))
            reasons = proposal_reasons(measurement, threshold_mm)
            if reasons:
                proposals.append({"id": len(proposals)+1, "face": [part_id, index],
                    "measurement": measurement, "reasons": reasons, "decision": "pending"})
    return {"schema_version": 1, "manifest_sha256": draft["manifest_sha256"],
            "candidates_sha256": draft["candidates_sha256"],
            "contact_review_sha256": contact_signature(draft), "threshold_mm": threshold_mm,
            "protected_faces": [list(ref) for ref in sorted(protected)],
            "default_policy": "preserve", "proposals": proposals, "sets": [], "notes": "", "confirmed": False}


def validate_review(record, draft, parts, require_complete=False):
    if not isinstance(record, dict):
        raise ValueError("簡略化レビューが必要です。")
    expected = build_proposal(parts, draft, record.get("threshold_mm"))
    for key in ("schema_version", "manifest_sha256", "candidates_sha256", "contact_review_sha256",
                "protected_faces", "default_policy"):
        if record.get(key) != expected[key]:
            raise ValueError("接合面レビューまたは保護面が変わっています。削除提案を作り直してください。")
    rows = record.get("proposals")
    if not isinstance(rows, list) or len(rows) != len(expected["proposals"]):
        raise ValueError("削除提案の欠落・追加があります。")
    for actual, reference in zip(rows, expected["proposals"]):
        if not isinstance(actual, dict) or any(actual.get(key) != reference[key] for key in
                                               ("id", "face", "measurement", "reasons")):
            raise ValueError("削除提案の面参照または計測値が変更されています。接合面は省略できません。")
        if actual.get("decision") not in ("pending", "keep", "simplify", "omit"):
            raise ValueError("簡略化の判断は未確認・残す・簡略化して残す・省略するから選んでください。")
        if require_complete and actual["decision"] == "pending":
            raise ValueError(f"削除提案 {actual['id']} は未確認です。")
    if not isinstance(record.get("notes"), str) or type(record.get("confirmed")) is not bool:
        raise ValueError("簡略化レビューのメモまたは確定状態が不正です。")
    if record["confirmed"] and any(row["decision"] == "pending" for row in rows):
        raise ValueError("未確認の削除提案があるため簡略化レビューは確定できません。")
    if require_complete and not record["confirmed"]:
        raise ValueError("簡略化レビューを確定してください。")
    from b2_sets import validate_sets
    validate_sets(record, draft, parts)
    return record


def handoff_guidance(record, draft, parts):
    validate_review(record, draft, parts, require_complete=True)
    from b2_sets import effective_sets, export_sets
    groups = effective_sets(record)
    return {"protected_contact_faces": record["protected_faces"],
            "threshold_mm": record["threshold_mm"],
            "omitted_faces": [ref for g in groups if g["decision"] == "omit" for ref in g["faces"]],
            "explicitly_preserved_faces": [ref for g in groups if g["decision"] == "keep" for ref in g["faces"]],
            "simplified_faces": [ref for g in groups if g["decision"] == "simplify" for ref in g["faces"]],
            "sets": export_sets(record, draft, parts),
            "default_face_policy": "preserve", "notes": record["notes"],
            "contact_review_sha256": record["contact_review_sha256"],
            "rule": "Rebuild a new parametric model. Do not delete faces from detailed CAD. Preserve contact faces and required openings."}
