"""Geometry measurements for the mounting-block trial fit."""

from hashlib import sha256
from io import BytesIO
import json
from math import isfinite
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopAbs import TopAbs_FACE, TopAbs_OUT, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopTools import TopTools_IndexedMapOfShape

from b2_faces import validate_pair
import mounting_block

GEOMETRY_TOL_MM = 1e-6
ANGULAR_TOL_RAD = 1e-6


def read_record(path):
    data = path.read_bytes()
    return json.loads(data), sha256(data).hexdigest()


def template_source(path, bundle_digest, parts):
    template, digest = read_record(path / "template.json")
    if (
        template["schema_version"] != 1
        or template["manifest_sha256"] != bundle_digest
        or template["length_unit"] != "mm"
        or template["template_id"] != mounting_block.TEMPLATE_ID
        or template["template_version"] != mounting_block.TEMPLATE_VERSION
    ):
        raise ValueError("Unsupported B3 template or mismatched B1 bundle")
    installed = sha256(Path(mounting_block.__file__).read_bytes()).hexdigest()
    if template["template_code_sha256"] != installed:
        raise ValueError("B3 template code does not match the installed mounting-block recipe")
    part_id = template["source_part_id"]
    shape, faces = parts[part_id]
    references = set()
    for contact in template["contact_constraints"]:
        face, _ = validate_pair([contact["detailed_face"], contact["mate_face"]], parts)
        if face[0] != part_id or contact["template_face"] != "mounting_plane":
            raise ValueError("Contact does not map the target part to mounting_plane")
        references.add(face[1])
    if len(references) != 1:
        raise ValueError("B4 needs exactly one detailed mounting face from B2/B3")
    return template, digest, shape, TopoDS.Face_s(faces.FindKey(references.pop()))


def indexed_faces(shape):
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
    return faces


def read_brep(data):
    shape = TopoDS_Shape()
    BRepTools.Read_s(shape, BytesIO(data), BRep_Builder())
    if shape.IsNull():
        raise ValueError("Empty BREP geometry")
    return shape


def bounds(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    if box.IsVoid() or box.IsOpen():
        raise ValueError("Expected finite part bounds")
    return box.Get()


def plane_and_normal(face):
    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        raise ValueError("The mounting face must be planar")
    plane = surface.Plane()
    normal = plane.Axis().Direction()
    if face.Orientation() == TopAbs_REVERSED:
        normal.Reverse()
    return plane, normal


def to_local(shape, frame):
    transform = gp_Trsf()
    transform.SetTransformation(frame)
    return shape.Moved(TopLoc_Location(transform))


def fitting_frame(shape, mounting_face, world_x):
    plane, outward = plane_and_normal(mounting_face)
    inward = outward.Reversed()
    if not all(isfinite(value) for value in world_x):
        raise ValueError("The world X direction must contain finite numbers")
    along = gp_Vec(*world_x)
    if along.Magnitude() <= GEOMETRY_TOL_MM:
        raise ValueError("Specify a nonzero world X direction")
    normal = gp_Vec(inward)
    along = along.Subtracted(normal.Multiplied(along.Dot(normal)))
    if along.Magnitude() <= GEOMETRY_TOL_MM:
        raise ValueError("World X direction must have a component along the mounting plane")
    axes = gp_Ax3(plane.Location(), inward, gp_Dir(along))
    xmin, ymin, zmin, xmax, ymax, zmax = bounds(to_local(shape, axes))
    if abs(zmin) > GEOMETRY_TOL_MM or zmax <= GEOMETRY_TOL_MM:
        raise ValueError("The detailed part must lie on the inward side of the mounting plane")
    origin = axes.Location().Translated(
        gp_Vec(axes.XDirection()).Multiplied((xmin + xmax) / 2)
        .Added(gp_Vec(axes.YDirection()).Multiplied((ymin + ymax) / 2))
    )
    axes.SetLocation(origin)
    return axes


def through_hole(shape, zmin, zmax):
    solids = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, solids)
    if solids.Extent() != 1:
        raise ValueError("B4 expects one detailed solid")
    solid = TopoDS.Solid_s(solids.FindKey(1))
    classifier = BRepClass3d_SolidClassifier(solid)
    faces = indexed_faces(solid)
    holes = []
    for index in range(1, faces.Extent() + 1):
        face = TopoDS.Face_s(faces.FindKey(index))
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_Cylinder:
            continue
        cylinder = surface.Cylinder()
        axis = cylinder.Axis()
        if not axis.Direction().IsParallel(gp_Dir(0, 0, 1), ANGULAR_TOL_RAD):
            continue
        _, _, bottom, _, _, top = bounds(face)
        if bottom > zmin + GEOMETRY_TOL_MM or top < zmax - GEOMETRY_TOL_MM:
            continue
        x, y = axis.Location().X(), axis.Location().Y()
        classifier.Perform(gp_Pnt(x, y, (zmin + zmax) / 2), GEOMETRY_TOL_MM)
        if classifier.State() != TopAbs_OUT:
            continue
        measurement = (2 * cylinder.Radius(), x, y)
        if not any(max(abs(a - b) for a, b in zip(measurement, known)) <= GEOMETRY_TOL_MM
                   for known in holes):
            holes.append(measurement)
    if len(holes) != 1:
        raise ValueError(f"Expected one axial through-hole, found {len(holes)}")
    return holes[0]


def measurements(local_shape):
    xmin, ymin, zmin, xmax, ymax, zmax = bounds(local_shape)
    diameter, x, y = through_hole(local_shape, zmin, zmax)
    return {
        "length": xmax - xmin,
        "width": ymax - ymin,
        "height": zmax - zmin,
        "hole_diameter": diameter,
        "hole_x": x,
        "hole_y": y,
    }
