"""Check B5 air connectivity, exterior probes and small topological features."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN, TopAbs_ON

from b2_faces import write_json
from b4_geometry import GEOMETRY_TOL_MM, read_brep, read_record, volume
from b5_geometry import cylinder, require_solids, solids, vector3
from measure_features import measure_features


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
    return measure_space_features(shape, config)['below_threshold']


def measure_space_features(shape, config):
    return measure_features(shape, min_face_area_mm2=config.get('min_face_area_mm2'),
                            min_edge_length_mm=config.get('min_edge_length_mm'))


def check(config_path, space_path):
    config, digest = read_record(config_path)
    envelope = cylinder(config)
    record, space_record_digest = read_record(space_path / "space.json")
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
    features = None
    try:
        require_solids(shape, "trial air space")
    except ValueError:
        issues.append({"code": "invalid_or_empty_air_space"})
    else:
        probes, issues = check_probes(config, envelope, regions)
        features = measure_space_features(shape, config)
        issues.extend(features['below_threshold'])
    return {
        "schema_version": 1, "status": "ng" if issues else "ok",
        "space_record_sha256": space_record_digest,
        "space_sha256": record["geometry_sha256"], "config_sha256": digest,
        "component_volumes_cc": [volume(region) / 1000 for region in regions],
        "air_probes": probes, "issues": issues, "feature_measurements": features,
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
