"""Named face sets and reference policies for rebuilding simplified geometry."""

from copy import deepcopy
from math import isfinite
import re

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Circle
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape


def validate_plan(plan):
    # Old operation recipes remain readable as history, but are never exported
    # as construction instructions by normalize_plan().
    if isinstance(plan, dict) and "operations" not in plan:
        if set(plan) != {"policy", "notes", "detail_policy"} or plan["policy"] not in ("unspecified", "preserve_volume", "preserve_envelope") or not isinstance(plan["notes"], str) or len(plan["notes"]) > 4000 or plan["detail_policy"] != "omit_chamfers_and_fillets":
            raise ValueError("近似方針は未指定・体積維持・外形範囲維持から選び、メモを4000文字以内で指定してください。")
        return
    if not isinstance(plan, dict) or set(plan) != {"operations", "parameter_status"} or plan["parameter_status"] != "define_in_B3":
        raise ValueError("近似セットの方針データが必要です。方針は未指定でも保存できます。")
    steps = plan["operations"]
    if not isinstance(steps, list) or not 2 <= len(steps) <= 5:
        raise ValueError("スケッチと押出または切抜きから操作を定義してください。")
    names = []
    allowed = {"sketch": set(), "extrude": {"length_mm", "direction"}, "cut": {"length_mm", "direction"},
               "draft": {"angle_deg"}, "chamfer": {"distance_mm"}, "fillet": {"radius_mm"}}
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"operation", "parameters"}:
            raise ValueError("Invalid approximation operation")
        name, parameters = step["operation"], step["parameters"]
        if name not in allowed or not isinstance(parameters, dict) or not set(parameters) <= allowed[name]:
            raise ValueError("対応していない作成操作またはパラメータです。")
        names.append(name)
        for key, value in parameters.items():
            if key == "direction":
                if not isinstance(value, list) or len(value) != 3 or any(type(v) not in (int, float) or not isfinite(v) for v in value) or sum(v*v for v in value) == 0:
                    raise ValueError("押出方向は非ゼロの3成分で指定してください。")
            elif type(value) not in (int, float) or not isfinite(value) or (not -89 < value < 89 or value == 0 if key == "angle_deg" else value <= 0):
                raise ValueError("作成操作の寸法・角度が不正です。")
    if names[0] != "sketch" or names[1] not in ("extrude", "cut") or any(n not in ("draft", "chamfer", "fillet") for n in names[2:]) or len(set(names)) != len(names):
        raise ValueError("操作順はスケッチ、押出/切抜き、必要な勾配・C面・Rとしてください。")


def normalize_plan(plan):
    """Discard legacy operation instructions, retaining classification and faces."""
    validate_plan(plan)
    if "operations" in plan:
        return {"policy": "unspecified", "notes": "", "detail_policy": "omit_chamfers_and_fillets"}
    return deepcopy(plan)


def validate_face(ref, parts):
    if not isinstance(ref, list) or len(ref) != 2 or not isinstance(ref[0], str) or ref[0] not in parts or type(ref[1]) is not int or not 1 <= ref[1] <= parts[ref[0]][1].Extent():
        raise ValueError("Unknown source face in simplification set")
    return tuple(ref)


def canonicalize_sets(record):
    """Pure migration: one keep/omit owner per part; approximation groups stay."""
    result = deepcopy(record)
    groups = effective_sets(record)
    merged = {}
    retained = []
    for group in groups:
        if group['decision'] == 'simplify':
            retained.append(group)
            continue
        for ref in group['faces']:
            key = (ref[0], group['decision'])
            merged.setdefault(key, []).append(ref)
    for ref in record.get('protected_faces', []):
        merged.setdefault((ref[0], 'keep'), []).append(ref)
    for (part, decision), refs in sorted(merged.items()):
        retained.append({'id': decision+'-'+part.replace('/', '_'),
            'name': '残す' if decision == 'keep' else '省略する',
            'faces': [list(ref) for ref in sorted(set(map(tuple, refs)))],
            'decision': decision, 'approximation': None})
    result['sets'] = retained
    result['set_layout'] = 'single_keep_omit_per_part'
    return result


def validate_sets(record, draft, parts):
    from b2_simplification import protected_faces
    protected = protected_faces(draft, parts)
    sets = record.get("sets", [])
    if not isinstance(sets, list):
        raise ValueError("Invalid simplification sets")
    ids, owners, classes = set(), {}, set()
    for group in sets:
        if not isinstance(group, dict) or set(group) != {"id", "name", "faces", "decision", "approximation"}:
            raise ValueError("Invalid simplification set record")
        if not isinstance(group["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", group["id"]) or group["id"].startswith("implicit-") or group["id"] in ids:
            raise ValueError("簡略化セットIDが不正または重複しています。")
        ids.add(group["id"])
        if not isinstance(group["name"], str) or not group["name"].strip() or len(group["name"]) > 100:
            raise ValueError("簡略化セット名を100文字以内で指定してください。")
        if not isinstance(group["faces"], list) or not group["faces"]:
            raise ValueError("簡略化セットには1面以上が必要です。")
        members = [validate_face(ref, parts) for ref in group["faces"]]
        if len({p for p, _ in members}) != 1:
            raise ValueError("簡略化セットは同じ部品の面で定義してください。")
        key = (members[0][0], group['decision'])
        if record.get('set_layout') == 'single_keep_omit_per_part' and group['decision'] in ('keep', 'omit'):
            if key in classes:
                raise ValueError('残す・省略するセットは部品ごとに各1組です。')
            classes.add(key)
        for ref in members:
            if ref in protected and group['decision'] != 'keep':
                raise ValueError("接合面は保護されています。簡略化セットに変更できません。")
            if ref in owners:
                raise ValueError("同じ面を複数セットで所有することはできません。")
            owners[ref] = group
        if group["decision"] == "simplify":
            validate_plan(group["approximation"])
        elif group["decision"] not in ("keep", "omit") or group["approximation"] is not None:
            raise ValueError("セットの分類は残す・簡略化して残す・省略するから選んでください。")
    for row in record["proposals"]:
        owner = owners.get(tuple(row["face"]))
        if owner and row["decision"] != owner["decision"]:
            raise ValueError("面の判断と簡略化セットの分類が一致しません。")
        if row["decision"] == "simplify" and owner is None:
            raise ValueError("簡略化して残す面には名前付きセットが必要です。")
    return owners


def effective_sets(record):
    """Old keep/omit rows retain their meaning as implicit single-face sets."""
    groups = deepcopy(record.get("sets", []))
    owned = {tuple(ref) for group in groups for ref in group["faces"]}
    for row in record["proposals"]:
        if tuple(row["face"]) not in owned and row["decision"] in ("keep", "omit"):
            groups.append({"id": f"implicit-face-{row['id']}", "name": f"面判断 {row['id']}",
                           "faces": [row["face"]], "decision": row["decision"], "approximation": None})
    return groups


def surface_reference(ref, parts):
    face = TopoDS.Face_s(parts[ref[0]][1].FindKey(ref[1]))
    surface = BRepAdaptor_Surface(face)
    result = {"face": ref, "uv_bounds": list(BRepTools.UVBounds_s(face))}
    if surface.GetType() == GeomAbs_Plane:
        plane = surface.Plane()
        normal = plane.Axis().Direction()
        if (face.Orientation() == TopAbs_REVERSED) != (not plane.Direct()):
            normal.Reverse()
        result.update(surface_type="planar", origin_mm=list(plane.Location().Coord()),
                      normal=list(normal.Coord()), x_direction=list(plane.XAxis().Direction().Coord()))
    elif surface.GetType() == GeomAbs_Cylinder:
        cylinder = surface.Cylinder()
        result.update(surface_type="cylindrical", axis_origin_mm=list(cylinder.Location().Coord()),
                      axis_direction=list(cylinder.Axis().Direction().Coord()), radius_mm=cylinder.Radius(),
                      normal_sense="outward" if (face.Orientation() != TopAbs_REVERSED) == cylinder.Direct() else "inward")
    else:
        result["surface_type"] = str(surface.GetType())
    return result


def edge_references(refs, parts):
    part_id = refs[0][0]
    indexed = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(parts[part_id][0], TopAbs_EDGE, indexed)
    edges = {}
    for ref in refs:
        face_edges = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(parts[part_id][1].FindKey(ref[1]), TopAbs_EDGE, face_edges)
        for i in range(1, face_edges.Extent()+1):
            edge = TopoDS.Edge_s(face_edges.FindKey(i))
            index = indexed.FindIndex(edge)
            if not index:
                raise ValueError("Cannot resolve BREP edge reference")
            if index not in edges:
                if BRep_Tool.Degenerated_s(edge):
                    edges[index] = {"edge": [part_id, index], "curve_type": "degenerate",
                                    "length_mm": 0.0, "source_faces": []}
                    edges[index]["source_faces"].append(ref)
                    continue
                curve = BRepAdaptor_Curve(edge)
                props = GProp_GProps()
                BRepGProp.LinearProperties_s(edge, props)
                item = {"edge": [part_id, index], "curve_type": str(curve.GetType()),
                        "length_mm": props.Mass(), "source_faces": []}
                first, last = curve.FirstParameter(), curve.LastParameter()
                if isfinite(first) and isfinite(last):
                    item["endpoints_mm"] = [list(curve.Value(t).Coord()) for t in (first, last)]
                if curve.GetType() == GeomAbs_Circle:
                    circle = curve.Circle()
                    item.update(center_mm=list(circle.Location().Coord()), radius_mm=circle.Radius(),
                                axis=list(circle.Axis().Direction().Coord()))
                edges[index] = item
            edges[index]["source_faces"].append(ref)
    return [edges[index] for index in sorted(edges)]


def export_sets(record, draft, parts):
    from b2_simplification import validate_review
    validate_review(record, draft, parts, require_complete=True)
    groups = canonicalize_sets(record)['sets']
    owned = {tuple(ref) for group in groups for ref in group["faces"]}
    # Every unclassified face is still preserved; its edges remain usable.
    for part_id, (_, faces) in parts.items():
        refs = [[part_id, i] for i in range(1, faces.Extent()+1) if (part_id, i) not in owned]
        if refs:
            existing = next((g for g in groups if g['decision'] == 'keep' and g['faces'][0][0] == part_id), None)
            if existing:
                existing['faces'].extend(refs)
            else:
                groups.append({"id": "keep-"+part_id.replace("/", "_"), "name": "残す",
                               "faces": refs, "decision": "keep", "approximation": None})
    result = []
    for group in groups:
        item = {**group, "reference_policy": {"keep": "edges", "simplify": "surfaces_and_policy", "omit": "ignore"}[group["decision"]]}
        if group["decision"] == "simplify":
            item["approximation"] = normalize_plan(group["approximation"])
        item["edge_references"] = edge_references(group["faces"], parts) if group["decision"] == "keep" else []
        item["surface_references"] = [surface_reference(ref, parts) for ref in group["faces"]] if group["decision"] == "simplify" else []
        result.append(item)
    return result
