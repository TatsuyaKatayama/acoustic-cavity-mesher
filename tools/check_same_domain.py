"""Trial-fuse two placed BREP solids and check cross-part same-domain merges."""

import argparse
import json
from pathlib import Path

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopTools import TopTools_ListOfShape
from OCP.TopoDS import TopoDS

from b1_step import brep_bytes
from b3_check import indexed, measure, read_brep
from propose_contacts import bounds


def face_info(shape):
    faces = indexed(shape, TopAbs_FACE)
    for index in range(1, faces.Extent() + 1):
        face = TopoDS.Face_s(faces.FindKey(index))
        surface = BRepAdaptor_Surface(face)
        info = {'face_id': index, 'type': surface.GetType().name,
                'bounds_mm': bounds(face).Get()}
        if surface.GetType() == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            info.update(radius_mm=cylinder.Radius(), axis=cylinder.Axis().Direction().Coord(),
                        axis_point_mm=cylinder.Location().Coord())
        yield face, info


def transfer_faces(result, inputs, history):
    faces = indexed(result, TopAbs_FACE)
    labels = {}
    for face, sources in inputs:
        for changed in (face, *history.Modified(face)):
            index = faces.FindIndex(changed)
            if index:
                labels.setdefault(index, set()).update(sources)
    return labels


def describe(shape):
    return {'valid': BRepCheck_Analyzer(shape).IsValid(),
            'solids': indexed(shape, TopAbs_SOLID).Extent(),
            'faces': indexed(shape, TopAbs_FACE).Extent(),
            'edges': indexed(shape, TopAbs_EDGE).Extent(),
            'volume_mm3': measure(shape, True)}


def check_same_domain(first, second):
    source_info = [describe(shape) for shape in (first, second)]
    if any(not row['valid'] or row['solids'] != 1 for row in source_info):
        raise ValueError('Each input must contain one valid solid')
    original = []
    for name, shape, record in zip(('first', 'second'), (first, second), source_info):
        geometry = list(face_info(shape))
        record['face_geometry'] = [info for _, info in geometry]
        original.extend((face, {(name, info['face_id'])}) for face, info in geometry)
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(first)
    tools.Append(second)
    fuse = BRepAlgoAPI_Fuse()
    fuse.SetArguments(arguments)
    fuse.SetTools(tools)
    fuse.SetNonDestructive(True)
    fuse.Build()
    report = {'inputs': source_info, 'fuse_done': fuse.IsDone(), 'cross_part_face_merges': []}
    if not fuse.IsDone() or fuse.Shape().IsNull():
        return report, None
    fused = fuse.Shape()
    report['fused'] = describe(fused)
    report['solid_fusion_possible'] = report['fused']['valid'] and report['fused']['solids'] == 1
    if not report['solid_fusion_possible']:
        return report, None
    fused_sources = transfer_faces(fused, original, fuse)
    fused_faces = indexed(fused, TopAbs_FACE)
    unify = ShapeUpgrade_UnifySameDomain(fused, True, True, False)
    unify.SetSafeInputMode(True)
    unify.Build()
    unified = unify.Shape()
    report['unified'] = describe(unified)
    output_sources = transfer_faces(unified, ((fused_faces.FindKey(index), labels)
        for index, labels in fused_sources.items()), unify.History())
    report['cross_part_face_merges'] = [
        {'result_face': index, 'source_faces': sorted(labels)}
        for index, labels in sorted(output_sources.items()) if len({name for name, _ in labels}) > 1]
    report['unification_volume_delta_mm3'] = report['unified']['volume_mm3'] - report['fused']['volume_mm3']
    report['merged_geometry_valid'] = report['unified']['valid'] and report['unified']['solids'] == 1
    report['untraced_output_face_ids'] = sorted(set(range(1, report['unified']['faces'] + 1)) - output_sources.keys())
    return report, unified if report['merged_geometry_valid'] else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--trial-brep', type=Path)
    args = parser.parse_args()
    report, shape = check_same_domain(read_brep(args.first), read_brep(args.second))
    report['paths'] = [str(args.first.resolve()), str(args.second.resolve())]
    if args.trial_brep and shape is not None:
        with args.trial_brep.open('xb') as stream:
            stream.write(brep_bytes(shape))
    if args.report:
        with args.report.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
    else:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
