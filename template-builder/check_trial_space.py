"""Check B5 air connectivity, exterior probes and small topological features."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

from b2_faces import write_json
from b4_geometry import GEOMETRY_TOL_MM, read_brep, read_record, volume
from b5_geometry import cylinder, nonnegative, require_solids, solids, vector3


def classify(classifier, point):
    classifier.Perform(point, GEOMETRY_TOL_MM)
    return classifier.State()


def check_probes(config, envelope, regions):
    inside_cylinder = BRepClass3d_SolidClassifier(envelope)
    classifiers = [BRepClass3d_SolidClassifier(solid) for solid in regions]
    issues = []
    assignments = {}
    defined = config["air_regions"]
    if not defined:
        raise ValueError("At least one expected air region is needed")
    probes_report = []
    groups = set()
    for group in defined:
        label = group["name"]
        if not isinstance(label, str) or not label or label in groups or not group["probes_mm"]:
            raise ValueError("Expected unique region names and at least one probe per region")
        groups.add(label)
        hits = set()
        for coordinates in group["probes_mm"]:
            point = gp_Pnt(*vector3(coordinates, label))
            states = [classify(classifier, point) for classifier in classifiers]
            components = [index for index, state in enumerate(states, 1) if state == TopAbs_IN]
            probes_report.append({"region": label, "point_mm": coordinates, "components": components})
            if len(components) != 1 or TopAbs_ON in states:
                issues.append({"code": "air_probe_not_inside_one_component", "region": label,
                               "point_mm": coordinates})
            else:
                hits.add(components[0])
        if len(hits) > 1:
            issues.append({"code": "expected_region_split", "region": label, "components": sorted(hits)})
        for component in sorted(hits):
            previous = assignments.setdefault(component, label)
            if previous != label:
                issues.append({"code": "unexpected_connection", "regions": [previous, label],
                               "component": component})
    for coordinates in config.get("exterior_probes_mm", []):
        point = gp_Pnt(*vector3(coordinates, "exterior probe"))
        if classify(inside_cylinder, point) != TopAbs_IN:
            raise ValueError(f"Exterior probes must be inside the cylinder: {coordinates}")
        states = [classify(classifier, point) for classifier in classifiers]
        if TopAbs_IN in states or TopAbs_ON in states:
            issues.append({"code": "exterior_probe_in_air_or_on_boundary", "point_mm": coordinates})
    for component in range(1, len(regions) + 1):
        if component not in assignments:
            issues.append({"code": "unclaimed_air_component", "component": component})
    return probes_report, issues


def small_features(shape, config):
    minimum_area = nonnegative(config["min_face_area_mm2"], "Minimum face area")
    minimum_length = nonnegative(config["min_edge_length_mm"], "Minimum edge length")
    issues = []
    for kind, limit in ((TopAbs_FACE, minimum_area), (TopAbs_EDGE, minimum_length)):
        if limit == 0:
            continue
        features = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, kind, features)
        for index in range(1, features.Extent() + 1):
            feature = features.FindKey(index)
            properties = GProp_GProps()
            if kind == TopAbs_FACE:
                BRepGProp.SurfaceProperties_s(feature, properties)
                code, unit = "small_face", "mm2"
            else:
                if BRep_Tool.Degenerated_s(TopoDS.Edge_s(feature)):
                    continue
                BRepGProp.LinearProperties_s(feature, properties)
                code, unit = "small_edge", "mm"
            if properties.Mass() < limit:
                issues.append({"code": code, "index": index, "value": properties.Mass(),
                               "minimum": limit, "unit": unit})
    return issues


def check(config_path, space_path):
    config, digest = read_record(config_path)
    envelope = cylinder(config)
    record, _ = read_record(space_path / "space.json")
    data = (space_path / "space.brep").read_bytes()
    if (
        record["schema_version"] != 1 or record["length_unit"] != "mm"
        or record["config_sha256"] != digest or record["geometry_sha256"] != sha256(data).hexdigest()
    ):
        raise ValueError("Space geometry or configuration does not match the B5 record")
    shape = read_brep(data)
    regions = solids(shape)
    issues = []
    probes = []
    try:
        require_solids(shape, "trial air space")
    except ValueError:
        issues.append({"code": "invalid_or_empty_air_space"})
    else:
        probes, issues = check_probes(config, envelope, regions)
        issues.extend(small_features(shape, config))
    return {
        "schema_version": 1, "status": "ng" if issues else "ok",
        "space_sha256": record["geometry_sha256"], "config_sha256": digest,
        "component_volumes_cc": [volume(region) / 1000 for region in regions],
        "air_probes": probes, "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("space", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        report = check(args.config, args.space)
        write_json(args.report, report)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Trial space check failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
