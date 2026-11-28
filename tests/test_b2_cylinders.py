"""Independent geometry regressions for B2 planar/cylindrical contact proposals.

Run with the project virtual environment and tools on PYTHONPATH: python -m unittest discover
-s tests -p test_b2_cylinders.py -v.
"""

import math
import unittest

import cadquery as cq

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax3, gp_Cylinder, gp_Dir, gp_Pln, gp_Pnt
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

from propose_contacts import measure_contact, propose


def cylinder(radius=10, *, inward=False, origin=(0, 0, 0), axis=(0, 0, 1),
             u=(0, 2 * math.pi), v=(0, 5)):
    surface = gp_Cylinder(gp_Ax3(gp_Pnt(*origin), gp_Dir(*axis)), radius)
    face = BRepBuilderAPI_MakeFace(surface, *u, *v).Face()
    return TopoDS.Face_s(face.Reversed()) if inward else face


class ContactGeometryTests(unittest.TestCase):
    def check_contact(self, first, second, gap=0, area=100 * math.pi, kind="cylindrical"):
        result = measure_contact(first, second)
        self.assertIsNotNone(result)
        self.assertEqual(result["contact_type"], kind)
        self.assertAlmostEqual(result["gap_mm"], gap, places=6)
        self.assertAlmostEqual(result["overlap_mm2"], area, places=5)
        return result

    def test_same_cylinder_outward_inward(self):
        self.check_contact(cylinder(), cylinder(inward=True))

    def test_indirect_cylinder_inward_differential_normal(self):
        axes = gp_Ax3()
        axes.YReverse()
        inward = BRepBuilderAPI_MakeFace(gp_Cylinder(axes, 10), 0, 2 * math.pi, 0, 5).Face()
        self.check_contact(cylinder(), inward)

    def test_indirect_cylinder_clearance(self):
        axes = gp_Ax3()
        axes.YReverse()
        inward = BRepBuilderAPI_MakeFace(gp_Cylinder(axes, 10.05), 0, 2 * math.pi, 0, 5).Face()
        self.check_contact(cylinder(), inward, gap=0.05)

    def test_indirect_cylinder_same_physical_normal_rejected(self):
        axes = gp_Ax3()
        axes.YReverse()
        outward = BRepBuilderAPI_MakeFace(gp_Cylinder(axes, 10), 0, 2 * math.pi, 0, 5).Face()
        outward = TopoDS.Face_s(outward.Reversed())
        self.assertIsNone(measure_contact(cylinder(), outward))

    def test_swapped_order(self):
        self.check_contact(cylinder(inward=True), cylinder())

    def test_opposite_axis_parameterization(self):
        self.check_contact(cylinder(), cylinder(inward=True, origin=(0, 0, 5), axis=(0, 0, -1)))

    def test_radial_clearance_smaller_radius_area(self):
        self.check_contact(cylinder(), cylinder(10.05, inward=True), gap=0.05)

    def test_radial_clearance_swapped(self):
        self.check_contact(cylinder(10.05, inward=True), cylinder(), gap=0.05)

    def test_radial_interference_rejected(self):
        self.assertIsNone(measure_contact(cylinder(10.05), cylinder(inward=True)))

    def test_clearance_opposite_axis_parameterization(self):
        self.check_contact(cylinder(), cylinder(10.05, inward=True, origin=(0, 0, 5), axis=(0, 0, -1)), gap=0.05)

    def test_clearance_partial_axial_overlap(self):
        self.check_contact(cylinder(), cylinder(10.05, inward=True, v=(3, 8)), gap=0.05, area=40 * math.pi)

    def test_clearance_periodic_seam_overlap(self):
        self.check_contact(cylinder(u=(-math.pi / 4, math.pi / 4)),
                           cylinder(10.05, inward=True, u=(0, math.pi / 2)), gap=0.05,
                           area=12.5 * math.pi)

    def test_clearance_preserves_trimmed_side_bore(self):
        # Independent expectation: cylindrical UV domain remains fixed under
        # radial projection, and area scales in direct proportion to radius.
        source = cq.Solid.makeCylinder(10.05, 5).cut(
            cq.Solid.makeCylinder(1, 30, cq.Vector(-15, 0, 2.5), cq.Vector(1, 0, 0)))
        faces = [f for f in source.Faces()
                 if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Cylinder
                 and abs(BRepAdaptor_Surface(f.wrapped).Cylinder().Radius() - 10.05) < 1e-7]
        self.assertEqual(len(faces), 1)
        trimmed = faces[0].wrapped
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(trimmed, props, 1e-10)
        expected_area = props.Mass() * 10 / 10.05
        inward = TopoDS.Face_s(trimmed.Reversed())
        self.check_contact(cylinder(), inward, gap=0.05, area=expected_area)
        self.check_contact(inward, cylinder(), gap=0.05, area=expected_area)

    def test_same_outward_orientation_rejected(self):
        self.assertIsNone(measure_contact(cylinder(), cylinder()))

    def test_same_inward_orientation_rejected(self):
        self.assertIsNone(measure_contact(cylinder(inward=True), cylinder(inward=True)))

    def test_axially_disjoint_rejected(self):
        self.assertIsNone(measure_contact(cylinder(), cylinder(inward=True, v=(6, 10))))

    def test_line_contact_has_no_area(self):
        result = measure_contact(cylinder(), cylinder(inward=True, v=(5, 10)))
        self.assertTrue(result is None or result["overlap_mm2"] < 1e-8)

    def test_partial_axial_overlap(self):
        self.check_contact(cylinder(), cylinder(inward=True, v=(3, 8)), area=40 * math.pi)

    def test_partial_angle_overlap(self):
        self.check_contact(cylinder(u=(0, math.pi)),
                           cylinder(inward=True, u=(math.pi / 2, 3 * math.pi / 2)),
                           area=25 * math.pi)

    def test_angularly_disjoint_rejected(self):
        result = measure_contact(cylinder(u=(0, math.pi / 2)),
                                 cylinder(inward=True, u=(math.pi, 3 * math.pi / 2)))
        self.assertTrue(result is None or result["overlap_mm2"] < 1e-8)

    def test_periodic_seam_overlap(self):
        self.check_contact(cylinder(u=(-math.pi / 4, math.pi / 4)),
                           cylinder(inward=True, u=(0, math.pi / 2)),
                           area=12.5 * math.pi)

    def test_offset_axes_rejected(self):
        self.assertIsNone(measure_contact(cylinder(), cylinder(inward=True, origin=(0.01, 0, 0))))

    def test_tilted_axes_rejected(self):
        self.assertIsNone(measure_contact(cylinder(), cylinder(inward=True, axis=(0.01, 0, 1))))

    def test_plane_regression(self):
        a = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 0, 3, 0, 4).Face()
        b = TopoDS.Face_s(a.Reversed())
        self.check_contact(a, b, area=12, kind="planar")

    def test_indirect_plane_normal(self):
        axes = gp_Ax3()
        axes.YReverse()
        a = BRepBuilderAPI_MakeFace(gp_Pln(gp_Ax3()), 0, 3, -4, 0).Face()
        b = BRepBuilderAPI_MakeFace(gp_Pln(axes), 0, 3, 0, 4).Face()
        self.check_contact(a, b, area=12, kind="planar")

    def test_indirect_plane_same_physical_normal_rejected(self):
        axes = gp_Ax3()
        axes.YReverse()
        a = BRepBuilderAPI_MakeFace(gp_Pln(gp_Ax3()), 0, 3, -4, 0).Face()
        b = BRepBuilderAPI_MakeFace(gp_Pln(axes), 0, 3, 0, 4).Face()
        self.assertIsNone(measure_contact(a, TopoDS.Face_s(b.Reversed())))

    def test_mixed_surface_types_rejected(self):
        plane = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 0, 3, 0, 4).Face()
        self.assertIsNone(measure_contact(plane, cylinder(inward=True)))

    def test_proposal_gap_and_overlap_thresholds(self):
        first, second = cylinder(), cylinder(10.05, inward=True)
        indexes = [TopTools_IndexedMapOfShape(), TopTools_IndexedMapOfShape()]
        indexes[0].Add(first)
        indexes[1].Add(second)
        parts = {"first": (first, indexes[0]), "second": (second, indexes[1])}
        rows = propose(parts, 0.1, 0.01)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["faces"], [["first", 1], ["second", 1]])
        self.assertEqual(propose(parts, 0.01, 0.01), [])
        self.assertEqual(propose(parts, 0.1, 400), [])


if __name__ == "__main__":
    unittest.main()
