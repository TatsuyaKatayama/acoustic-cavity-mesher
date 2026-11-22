"""Propose opposing planar and coaxial cylindrical faces from placed B1 geometry."""

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
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Trsf, gp_Vec, gp_Lin
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
    BRepGProp.SurfaceProperties_s(common.Shape(), properties, 1e-9)
    return properties.Mass()


def surface_area_common(first, second):
    common = BRepAlgoAPI_Common(first, second)
    if not common.IsDone():
        raise RuntimeError("Failed to measure trimmed contact overlap")
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(common.Shape(), properties, 1e-9)
    return properties.Mass()


def measure_contact(first, second):
    """Exact trimmed overlap; cylinders use the smaller radius as area reference.

    Only parallel opposing planes and coaxial inward/outward cylinders are
    supported. Interference is rejected, not converted to a positive gap.
    """
    orientations = (first.Orientation(), second.Orientation())
    if any(o not in (TopAbs_FORWARD, TopAbs_REVERSED) for o in orientations):
        return None
    surfaces = (BRepAdaptor_Surface(first), BRepAdaptor_Surface(second))
    types = tuple(s.GetType() for s in surfaces)
    if types == (GeomAbs_Plane, GeomAbs_Plane):
        planes = [s.Plane() for s in surfaces]
        normals = [p.Axis().Direction() for p in planes]
        for normal, plane, orientation in zip(normals, planes, orientations):
            if (orientation == TopAbs_REVERSED) != (not plane.Direct()):
                normal.Reverse()
        if not normals[0].IsOpposite(normals[1], ANGULAR_TOLERANCE_RAD):
            return None
        gap = gp_Vec(planes[0].Location(), planes[1].Location()).Dot(gp_Vec(normals[0]))
        if gap < -LINEAR_TOLERANCE_MM:
            return None
        area = common_area(first, second, normals[0], gap)
        kind = "planar"
    elif types == (GeomAbs_Cylinder, GeomAbs_Cylinder):
        cylinders = [s.Cylinder() for s in surfaces]
        outward = [(o == TopAbs_FORWARD) == c.Direct() for o, c in zip(orientations, cylinders)]
        if outward[0] == outward[1]:
            return None
        axes = [c.Axis() for c in cylinders]
        if not axes[0].Direction().IsParallel(axes[1].Direction(), ANGULAR_TOLERANCE_RAD):
            return None
        if gp_Lin(axes[0]).Distance(axes[1].Location()) > LINEAR_TOLERANCE_MM:
            return None
        radii = [c.Radius() for c in cylinders]
        outer = outward.index(True)
        inner = 1 - outer
        gap = radii[inner] - radii[outer]
        if gap < -LINEAR_TOLERANCE_MM:
            return None
        projected = [first, second]
        larger = 0 if radii[0] > radii[1] else 1
        difference = min(radii) - radii[larger]
        if abs(difference) > 1e-12:
            # Offset follows oriented face normals. This preserves trimmed wires,
            # including openings, without scaling the axial coordinate.
            offset = BRepOffsetAPI_MakeOffsetShape()
            offset.PerformBySimple(projected[larger], difference * (1 if outward[larger] else -1))
            if not offset.IsDone():
                raise RuntimeError("Failed to project cylindrical contact face")
            projected[larger] = offset.Shape()
        area = surface_area_common(*projected)
        kind = "cylindrical"
    else:
        return None
    if area <= 1e-12:
        return None
    return {"contact_type": kind, "gap_mm": max(0.0, gap), "overlap_mm2": area}


def propose(parts, max_gap, min_overlap):
    candidates = []
    boxes = {part_id: bounds(shape) for part_id, (shape, _) in parts.items()}
    faces = {}
    for part_id, (_, index) in parts.items():
        faces[part_id] = []
        for i in range(1, index.Extent() + 1):
            face = TopoDS.Face_s(index.FindKey(i))
            if BRepAdaptor_Surface(face).GetType() in (GeomAbs_Plane, GeomAbs_Cylinder):
                faces[part_id].append((i, face, bounds(face)))
    for first_id, second_id in combinations(parts, 2):
        if boxes[first_id].Distance(boxes[second_id]) > max_gap + LINEAR_TOLERANCE_MM:
            continue
        for i, first, first_box in faces[first_id]:
            for j, second, second_box in faces[second_id]:
                if first_box.Distance(second_box) > max_gap + LINEAR_TOLERANCE_MM:
                    continue
                measurement = measure_contact(first, second)
                if measurement and measurement["gap_mm"] <= max_gap + LINEAR_TOLERANCE_MM and measurement["overlap_mm2"] >= min_overlap:
                    candidates.append({
                        "faces": [[first_id, i], [second_id, j]],
                        **measurement,
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
