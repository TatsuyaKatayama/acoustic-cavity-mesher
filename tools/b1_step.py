"""STEP input and local BREP serialization for B1."""

from hashlib import sha256
from io import BytesIO

from OCP.BRepTools import BRepTools
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool


def label_name(label):
    name = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), name):
        return name.Get().ToExtString()
    return ""


def matrix(location):
    transform = location.Transformation()
    return [[transform.Value(row, column) for column in range(1, 5)]
            for row in range(1, 4)]


def brep_bytes(shape):
    stream = BytesIO()
    BRepTools.Write_s(shape, stream)
    return stream.getvalue()


def walk(label, instance_id, parent_id, parent_location, nodes, definitions):
    tool = XCAFDoc_ShapeTool
    definition = TDF_Label()
    if not tool.GetReferredShape_s(label, definition):
        definition = label
    shape = tool.GetShape_s(label)
    if shape.IsNull():
        raise ValueError(f"Missing STEP shape at {instance_id}")
    local = shape.Location()
    world = parent_location.Multiplied(local)
    is_assembly = tool.IsAssembly_s(definition)
    node = {
        "id": instance_id,
        "parent_id": parent_id,
        "kind": "assembly" if is_assembly else "part",
        "name": label_name(label) or label_name(definition),
        "definition_name": label_name(definition),
        "local_transform": matrix(local),
        "world_transform": matrix(world),
    }
    nodes.append(node)
    if is_assembly:
        children = TDF_LabelSequence()
        if not tool.GetComponents_s(definition, children) or children.Length() == 0:
            raise ValueError(f"Empty STEP assembly at {instance_id}")
        for index in range(1, children.Length() + 1):
            walk(children.Value(index), f"{instance_id}/{index}", instance_id,
                 world, nodes, definitions)
        return

    data = brep_bytes(shape.Located(TopLoc_Location()))
    digest = sha256(data).hexdigest()
    definitions[digest] = data
    node["geometry"] = f"parts/{digest}.brep"


def read_assembly(source):
    source_hash = sha256(source.read_bytes()).hexdigest()
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    XCAFDoc_DocumentTool.SetLengthUnit_s(document, 0.001)
    reader = STEPCAFControl_Reader()
    if reader.ReadFile(str(source)) != IFSelect_RetDone or not reader.Transfer(document):
        raise ValueError(f"STEP transfer failed: {source}")
    roots = TDF_LabelSequence()
    XCAFDoc_DocumentTool.ShapeTool_s(document.Main()).GetFreeShapes(roots)
    if roots.Length() == 0:
        raise ValueError(f"No shapes in STEP file: {source}")
    nodes, definitions = [], {}
    for index in range(1, roots.Length() + 1):
        walk(roots.Value(index), str(index), None, TopLoc_Location(), nodes, definitions)
    if source_hash != sha256(source.read_bytes()).hexdigest():
        raise ValueError(f"STEP changed while reading: {source}")
    return {
        "schema_version": 1,
        "source_sha256": source_hash,
        "length_unit": "mm",
        "nodes": nodes,
    }, definitions
