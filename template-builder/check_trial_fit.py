"""Verify B4 placement and simplified volume against the detailed CAD."""

import argparse
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.TopoDS import TopoDS

from b2_faces import load_parts, write_json
from b4_geometry import (
    ANGULAR_TOL_RAD, bounds, fitting_frame, indexed_faces, measurements, plane_and_normal,
    read_brep, read_record, template_source, to_local, volume,
)


def check_fit(bundle_digest, parts, template_path, result, length_tol, max_error_cc):
    template, template_digest, source, source_face = template_source(template_path, bundle_digest, parts)
    record, fit_digest = read_record(result / "fit.json")
    if (
        record["schema_version"] != 1 or record["length_unit"] != "mm"
        or record["manifest_sha256"] != bundle_digest or record["template_sha256"] != template_digest
        or record["source_part_id"] != template["source_part_id"]
        or record["contact_constraints"] != template["contact_constraints"]
    ):
        raise ValueError("B4 fit metadata does not match B1/B3 inputs")
    data = (result / "fitted.brep").read_bytes()
    if sha256(data).hexdigest() != record["geometry_sha256"]:
        raise ValueError("Fitted BREP does not match the B4 record")
    fitted = read_brep(data)
    faces = indexed_faces(fitted)
    index = record["named_faces"]["mounting_plane"]
    if type(index) is not int or not 1 <= index <= faces.Extent():
        raise ValueError("Invalid fitted mounting_plane reference")
    fitted_face = TopoDS.Face_s(faces.FindKey(index))
    source_plane, source_normal = plane_and_normal(source_face)
    fitted_plane, fitted_normal = plane_and_normal(fitted_face)

    frame = fitting_frame(source, source_face, record["world_x_direction"])
    local_source, local_fitted = to_local(source, frame), to_local(fitted, frame)
    reference = measurements(local_source)
    measured = measurements(local_fitted)
    parameter_errors = {key: abs(value - measured[key]) for key, value in reference.items()}
    bounds_error = max(abs(a - b) for a, b in zip(bounds(local_source), bounds(local_fitted)))
    plane_error = source_plane.Distance(fitted_plane.Location())
    angle = source_normal.Angle(fitted_normal)
    fit_ok = max(*parameter_errors.values(), bounds_error, plane_error) <= length_tol and angle <= ANGULAR_TOL_RAD

    common = BRepAlgoAPI_Common(local_source, local_fitted)
    if not common.IsDone():
        raise RuntimeError("Failed to compute common geometry for the volume check")
    common_volume = volume(common.Shape())
    source_volume, fitted_volume = volume(local_source), volume(local_fitted)
    added_air = max(0, source_volume - common_volume) / 1000
    removed_air = max(0, fitted_volume - common_volume) / 1000
    shape_ok = added_air + removed_air < max_error_cc
    return {
        "schema_version": 1,
        "status": "ok" if fit_ok and shape_ok else "ng",
        "manifest_sha256": bundle_digest,
        "template_sha256": template_digest,
        "fit_sha256": fit_digest,
        "source_part_id": template["source_part_id"],
        "fit": {
            "status": "ok" if fit_ok else "ng",
            "parameter_errors_mm": parameter_errors,
            "bounds_max_error_mm": bounds_error,
            "mounting_plane_offset_mm": plane_error,
            "mounting_plane_normal_error_rad": angle,
            "length_tolerance_mm": length_tol,
            "angle_tolerance_rad": ANGULAR_TOL_RAD,
        },
        "simplification": {
            "status": "ok" if shape_ok else "ng",
            "source_solid_cc": source_volume / 1000,
            "fitted_solid_cc": fitted_volume / 1000,
            "added_air_cc": added_air,
            "removed_air_cc": removed_air,
            "symmetric_difference_cc": added_air + removed_air,
            "max_error_cc": max_error_cc,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("result", type=Path)
    parser.add_argument("--length-tolerance-mm", required=True, type=float)
    parser.add_argument("--max-error-cc", required=True, type=float)
    parser.add_argument("--report", type=Path, help="Also save the checker JSON to this path")
    args = parser.parse_args()
    for value in (args.length_tolerance_mm, args.max_error_cc):
        if not isfinite(value) or value <= 0:
            parser.error("Tolerances must be finite and positive")
    try:
        digest, parts = load_parts(args.bundle)
        report = check_fit(digest, parts, args.template, args.result,
                           args.length_tolerance_mm, args.max_error_cc)
        if args.report is not None:
            write_json(args.report, report)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=True))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
