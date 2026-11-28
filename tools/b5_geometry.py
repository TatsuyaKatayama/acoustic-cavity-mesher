"""B5 inputs and common assembly geometry operations."""

from hashlib import sha256
from math import isfinite

from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

from b2_faces import load_parts
from b4_geometry import read_brep, read_record


def vector3(value, label):
    if not isinstance(value, list) or len(value) != 3 or any(
        type(number) not in (int, float) or not isfinite(number) for number in value
    ):
        raise ValueError(f"{label} must be an array of three finite numbers")
    return value


def nonnegative(value, label):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return value


def solids(shape):
    indexed = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, indexed)
    return [TopoDS.Solid_s(indexed.FindKey(index)) for index in range(1, indexed.Extent() + 1)]


def require_solids(shape, label):
    if not solids(shape) or not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError(f"Expected valid solid geometry: {label}")


def load_reassembly(bundle, fit_path):
    digest, parts = load_parts(bundle)
    fit, fit_digest = read_record(fit_path / "fit.json")
    geometry = (fit_path / "fitted.brep").read_bytes()
    if (
        fit["schema_version"] != 1
        or fit["length_unit"] != "mm"
        or fit["manifest_sha256"] != digest
        or fit["geometry_sha256"] != sha256(geometry).hexdigest()
        or fit["source_part_id"] not in parts
    ):
        raise ValueError("B4 fit does not match the B1 bundle")
    fitted = read_brep(geometry)
    require_solids(fitted, "B4 fitted geometry")
    return digest, parts, fit, fit_digest, fitted


def cylinder(config):
    if config["schema_version"] != 1 or config["length_unit"] != "mm":
        raise ValueError("Expected B5 configuration schema version 1 in mm")
    record = config["cylinder"]
    origin = vector3(record["origin_mm"], "cylinder.origin_mm")
    axis = vector3(record["axis"], "cylinder.axis")
    radius = nonnegative(record["radius_mm"], "cylinder.radius_mm")
    height = nonnegative(record["height_mm"], "cylinder.height_mm")
    if gp_Vec(*axis).Magnitude() == 0 or radius == 0 or height == 0:
        raise ValueError("Cylinder needs a nonzero axis and positive radius and height")
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*origin), gp_Dir(*axis)), radius, height).Solid()
