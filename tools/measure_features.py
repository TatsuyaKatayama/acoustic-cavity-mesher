"""Measure minimum face area and nondegenerate edge length in a BREP."""

import argparse
import json
from math import isfinite
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape


def measure_features(shape, *, min_face_area_mm2=None, min_edge_length_mm=None, inclusive=False):
    thresholds = {'min_face_area_mm2': min_face_area_mm2, 'min_edge_length_mm': min_edge_length_mm}
    report = {'thresholds': thresholds, 'below_threshold': [], 'degenerate_edges_skipped': 0}
    for kind, key, code, unit, properties_fn, limit in (
        (TopAbs_FACE, 'faces', 'small_face', 'mm2', BRepGProp.SurfaceProperties_s, min_face_area_mm2),
        (TopAbs_EDGE, 'edges', 'small_edge', 'mm', BRepGProp.LinearProperties_s, min_edge_length_mm),
    ):
        if limit is not None and (type(limit) not in (int, float) or not isfinite(limit) or limit < 0):
            raise ValueError(f'{key} threshold must be finite and nonnegative')
        features = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, kind, features)
        smallest, count = None, 0
        for index in range(1, features.Extent() + 1):
            feature = features.FindKey(index)
            if kind == TopAbs_EDGE and BRep_Tool.Degenerated_s(TopoDS.Edge_s(feature)):
                report['degenerate_edges_skipped'] += 1
                continue
            props = GProp_GProps()
            properties_fn(feature, props)
            value = props.Mass()
            count += 1
            if smallest is None or value < smallest['value']:
                smallest = {'index': index, 'value': value, 'unit': unit, 'centroid_mm': props.CentreOfMass().Coord()}
            if limit is not None and (value < limit or inclusive and value == limit):
                report['below_threshold'].append({'code': code, 'index': index, 'value': value,
                                                  'minimum': limit, 'unit': unit})
        report[key] = {'count': count, 'minimum': smallest}
    return report


def main():
    from b3_check import read_brep

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('brep', type=Path)
    parser.add_argument('--min-face-area-mm2', type=float)
    parser.add_argument('--min-edge-length-mm', type=float)
    args = parser.parse_args()
    try:
        report = measure_features(read_brep(args.brep), min_face_area_mm2=args.min_face_area_mm2,
                                  min_edge_length_mm=args.min_edge_length_mm)
        print(json.dumps(report, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Feature measurement failed: {exc}\n')


if __name__ == '__main__':
    main()
