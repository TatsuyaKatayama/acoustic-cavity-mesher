"""Check the fitted part against the B2 contact conditions and its neighbors."""

import argparse
import json
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.gp import gp_Vec
from OCP.TopoDS import TopoDS

from b2_faces import validate_pair, write_json
from b2_review import validate_decision
from b4_geometry import ANGULAR_TOL_RAD, indexed_faces, plane_and_normal, volume
from b5_geometry import load_reassembly, nonnegative, require_solids
from propose_contacts import bounds, common_area


def face_measurement(face, mate):
    plane, normal = plane_and_normal(face)
    mate_plane, mate_normal = plane_and_normal(mate)
    if not normal.IsOpposite(mate_normal, ANGULAR_TOL_RAD):
        return None, 0
    gap = gp_Vec(plane.Location(), mate_plane.Location()).Dot(gp_Vec(normal))
    return gap, common_area(face, mate, normal, gap)


def check_contacts(parts, fit, fitted, min_overlap_ratio):
    source_id = fit["source_part_id"]
    faces = indexed_faces(fitted)
    records = []
    if not fit["contact_constraints"]:
        raise ValueError("B5 requires at least one B2 contact constraint")
    for contact in fit["contact_constraints"]:
        own, mate = validate_pair([contact["detailed_face"], contact["mate_face"]], parts)
        if own[0] != source_id:
            raise ValueError("B2 contact must refer to the fitted part")
        condition = {key: contact[key] for key in ("mode", "target_gap_mm", "tolerance_mm")}
        validate_decision({"faces": [own, mate], "decision": "accepted", "condition": condition}, parts)
        face_index = fit["named_faces"][contact["template_face"]]
        if type(face_index) is not int or not 1 <= face_index <= faces.Extent():
            raise ValueError("Invalid fitted face reference")
        original_face = TopoDS.Face_s(parts[source_id][1].FindKey(own[1]))
        fitted_face = TopoDS.Face_s(faces.FindKey(face_index))
        mate_face = TopoDS.Face_s(parts[mate[0]][1].FindKey(mate[1]))
        _, original_area = face_measurement(original_face, mate_face)
        gap, area = face_measurement(fitted_face, mate_face)
        ratio = area / original_area if original_area > 0 else None
        issues = []
        if ratio is None:
            issues.append("no_reference_overlap")
        elif ratio + 1e-9 < min_overlap_ratio or area <= 0:
            issues.append("insufficient_overlap")
        if gap is None:
            issues.append("faces_not_opposed")
        elif abs(gap - condition["target_gap_mm"]) > condition["tolerance_mm"] + 1e-9:
            issues.append("contact_gap_out_of_tolerance")
        records.append({
            "candidate_id": contact["candidate_id"], "mate_face": mate,
            "fitted_face_index": face_index, **condition, "signed_gap_mm": gap,
            "overlap_mm2": area, "original_overlap_mm2": original_area,
            "overlap_ratio": ratio, "issues": issues,
        })
    return records


def check_interference(parts, fit, fitted, max_interference):
    fitted_box = bounds(fitted)
    collisions = []
    for part_id, (shape, _) in parts.items():
        if part_id == fit["source_part_id"] or fitted_box.IsOut(bounds(shape)):
            continue
        require_solids(shape, f"neighbor {part_id}")
        common = BRepAlgoAPI_Common(fitted, shape)
        if not common.IsDone():
            raise RuntimeError(f"Could not measure interference with {part_id}")
        overlap = volume(common.Shape())
        if overlap > max_interference:
            collisions.append({"part_id": part_id, "overlap_mm3": overlap})
    return collisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("fit", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-overlap-ratio", type=float, required=True)
    parser.add_argument("--max-interference-mm3", type=float, required=True)
    args = parser.parse_args()
    try:
        if not 0 < args.min_overlap_ratio <= 1:
            raise ValueError("Minimum overlap ratio must be in (0, 1]")
        nonnegative(args.max_interference_mm3, "Maximum interference")
        digest, parts, fit, fit_digest, fitted = load_reassembly(args.bundle, args.fit)
        contacts = check_contacts(parts, fit, fitted, args.min_overlap_ratio)
        collisions = check_interference(parts, fit, fitted, args.max_interference_mm3)
        passed = not collisions and not any(item["issues"] for item in contacts)
        report = {
            "schema_version": 1, "status": "ok" if passed else "ng",
            "manifest_sha256": digest, "fit_sha256": fit_digest,
            "min_overlap_ratio": args.min_overlap_ratio,
            "max_interference_mm3": args.max_interference_mm3,
            "contacts": contacts, "interferences": collisions,
        }
        write_json(args.report, report)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Reassembly check failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
