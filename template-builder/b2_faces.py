"""Load placed B1 parts and persist face pairs for one extraction bundle."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Trsf
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Shape
from OCP.TopTools import TopTools_IndexedMapOfShape


def load_parts(bundle):
    manifest_bytes = (bundle / "assembly.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["schema_version"] != 1 or manifest["length_unit"] != "mm":
        raise ValueError("Expected a B1 schema 1 bundle in mm")
    parts = {}
    geometry = {}
    for node in manifest["nodes"]:
        if node["kind"] != "part":
            continue
        part_id = node["id"]
        if part_id in parts:
            raise ValueError(f"Duplicate part ID: {part_id}")
        reference = node["geometry"]
        if reference not in geometry:
            if not re.fullmatch(r"parts/[0-9a-f]{64}\.brep", reference):
                raise ValueError(f"Invalid geometry reference: {reference}")
            data = (bundle / reference).read_bytes()
            if reference != f"parts/{sha256(data).hexdigest()}.brep":
                raise ValueError(f"Invalid geometry reference: {reference}")
            shape = TopoDS_Shape()
            BRepTools.Read_s(shape, BytesIO(data), BRep_Builder())
            if shape.IsNull():
                raise ValueError(f"Empty part geometry: {reference}")
            geometry[reference] = shape
        transform = gp_Trsf()
        transform.SetValues(*(value for row in node["world_transform"] for value in row))
        shape = geometry[reference].Located(TopLoc_Location(transform))
        faces = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
        parts[part_id] = (shape, faces)
    if len(parts) < 2:
        raise ValueError("A face pair requires at least two part instances")
    return sha256(manifest_bytes).hexdigest(), parts


def validate_pair(pair, parts):
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise ValueError("Expected exactly two face references")
    for reference in pair:
        if not isinstance(reference, (list, tuple)) or len(reference) != 2:
            raise ValueError("Expected [part_id, face_index]")
        part_id, face_index = reference
        if (
            not isinstance(part_id, str)
            or part_id not in parts
            or type(face_index) is not int
            or not 1 <= face_index <= parts[part_id][1].Extent()
        ):
            raise ValueError(f"Unknown face: {reference}")
    if pair[0][0] == pair[1][0]:
        raise ValueError("Select faces on two different part instances")
    return [tuple(reference) for reference in pair]


def load_pair(path, manifest_digest, parts):
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["schema_version"] != 1 or record["manifest_sha256"] != manifest_digest:
        raise ValueError("The saved pair belongs to a different B1 bundle")
    return validate_pair(record["faces"], parts)


def load_candidates(path, manifest_digest, parts):
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["schema_version"] != 1 or record["manifest_sha256"] != manifest_digest:
        raise ValueError("The candidates belong to a different B1 bundle")
    return [
        (validate_pair(item["faces"], parts), float(item["gap_mm"]), float(item["overlap_mm2"]))
        for item in record["candidates"]
    ]


def save_pair(path, manifest_digest, pair, parts):
    record = {
        "schema_version": 1,
        "manifest_sha256": manifest_digest,
        "faces": validate_pair(pair, parts),
    }
    write_json(path, record)


def write_json(path, record):
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
