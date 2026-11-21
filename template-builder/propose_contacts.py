"""Propose pairs of opposing planar faces from the placed B1 geometry."""

import argparse
from itertools import combinations
import json
from math import isfinite
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from b2_faces import load_parts

LINEAR_TOLERANCE_MM = 1e-7
ANGULAR_TOLERANCE_RAD = 1e-7


def bounds(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return box


def planar_faces(faces):
    for index in range(1, faces.Extent() + 1):
        face = TopoDS.Face_s(faces.FindKey(index))
        surface = BRepAdaptor_Surface(face)
        orientation = face.Orientation()
        if surface.GetType() != GeomAbs_Plane:
            continue
        if orientation not in (TopAbs_FORWARD, TopAbs_REVERSED):
            continue
        plane = surface.Plane()
        normal = plane.Axis().Direction()
        if orientation == TopAbs_REVERSED:
            normal.Reverse()
        yield index, face, plane.Location(), normal, bounds(face)


def common_area(first, second, normal, gap):
    translation = gp_Trsf()
    translation.SetTranslation(gp_Vec(normal).Multiplied(-gap))
    projected = second.Moved(TopLoc_Location(translation))
    common = BRepAlgoAPI_Common(first, projected)
    if not common.IsDone():
        raise RuntimeError("Failed to measure overlap of planar faces")
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(common.Shape(), properties)
    return properties.Mass()


def propose(parts, max_gap, min_overlap):
    candidates = []
    boxes = {part_id: bounds(shape) for part_id, (shape, _) in parts.items()}
    faces = {part_id: list(planar_faces(index)) for part_id, (_, index) in parts.items()}
    for first_id, second_id in combinations(parts, 2):
        if boxes[first_id].Distance(boxes[second_id]) > max_gap + LINEAR_TOLERANCE_MM:
            continue
        for i, first, first_origin, normal, first_box in faces[first_id]:
            for j, second, second_origin, other_normal, second_box in faces[second_id]:
                if not normal.IsOpposite(other_normal, ANGULAR_TOLERANCE_RAD):
                    continue
                if first_box.Distance(second_box) > max_gap + LINEAR_TOLERANCE_MM:
                    continue
                gap = gp_Vec(first_origin, second_origin).Dot(gp_Vec(normal))
                if not -LINEAR_TOLERANCE_MM <= gap <= max_gap + LINEAR_TOLERANCE_MM:
                    continue
                area = common_area(first, second, normal, gap)
                if area >= min_overlap:
                    candidates.append({
                        "faces": [[first_id, i], [second_id, j]],
                        "gap_mm": max(0.0, gap),
                        "overlap_mm2": area,
                    })
    return sorted(candidates, key=lambda item: (item["gap_mm"], -item["overlap_mm2"], item["faces"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path, help="New candidate JSON file")
    parser.add_argument("--max-gap-mm", type=float, required=True)
    parser.add_argument("--min-overlap-mm2", type=float, required=True)
    args = parser.parse_args()
    if not isfinite(args.max_gap_mm) or args.max_gap_mm < 0:
        parser.error("--max-gap-mm must be finite and non-negative")
    if not isfinite(args.min_overlap_mm2) or args.min_overlap_mm2 <= 0:
        parser.error("--min-overlap-mm2 must be finite and positive")
    try:
        digest, parts = load_parts(args.bundle)
        record = {
            "schema_version": 1,
            "manifest_sha256": digest,
            "max_gap_mm": args.max_gap_mm,
            "min_overlap_mm2": args.min_overlap_mm2,
            "candidates": propose(parts, args.max_gap_mm, args.min_overlap_mm2),
        }
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(record, indent=2) + "\n")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        parser.exit(1, f"Contact proposal failed: {error}\n")


if __name__ == "__main__":
    main()
