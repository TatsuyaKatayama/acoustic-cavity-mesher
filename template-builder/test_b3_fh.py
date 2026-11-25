"""Synthetic dimensional checks for the reusable FH feature family."""
import unittest
from copy import deepcopy
import cadquery as cq
import fh_template


def dimensions():
    return {'world_z_mm':9.0,'flange_radius_mm':30.,'flange_height_mm':8.,
        'lower_boss_radius_mm':18.,'lower_boss_depth_mm':2.,'boss_radius_mm':7.,
        'boss_height_mm':12.,'bore_radius_mm':4.,'ring_inner_radius_mm':27.,
        'ring_bottom_mm':5.,'ring_top_mm':11.,'slot_center_radius_mm':23.,
        'slot_width_mm':4.,'slot_sweep_deg':30.,'slot_count':3,'slot_first_angle_deg':90.,
        'bolt_circle_radius_mm':12.,'bolt_radius_mm':1.,'bolt_angles_deg':[0.,90.,180.,270.],
        'aux_holes':[{'radius_mm':1.,'polar_radius_mm':9.,'angle_deg':50.}],
        'pocket_inner_radius_mm':7.,'pocket_outer_radius_mm':14.,
        'pocket_start_angle_deg':20.,'pocket_end_angle_deg':110.,'pocket_floor_mm':2.,
        'pocket_inner_overlap_mm':.0001,'slot_upper_clearance_mm':.5,'slot_upper_floor_mm':5.}


class FHFamilyTests(unittest.TestCase):
    def test_every_stage_is_a_valid_single_solid(self):
        history=list(fh_template.build_history(dimensions()))
        self.assertTrue(all(model.val().isValid() and len(model.val().Solids())==1 for _,model in history))
        self.assertGreater(len(history),10)

    def test_required_openings_remain_open(self):
        p=dimensions();solid=fh_template.build(p).val()
        self.assertFalse(solid.isInside(cq.Vector(0,0,p['world_z_mm']+4)))
        self.assertFalse(solid.isInside(cq.Vector(12,0,p['world_z_mm']+1)))
        self.assertFalse(solid.isInside(cq.Vector(0,23,p['world_z_mm']+1)))
        self.assertTrue(solid.isInside(cq.Vector(0,10,p['world_z_mm']+1)))

    def test_world_placement_comes_from_the_datum(self):
        p=dimensions();first=fh_template.build(p).val().BoundingBox();p['world_z_mm']+=13
        moved=fh_template.build(p).val().BoundingBox()
        self.assertAlmostEqual(moved.zmin-first.zmin,13)
        self.assertAlmostEqual(moved.zmax-first.zmax,13)

    def test_common_stock_order_avoids_artificial_pocket_overlap(self):
        p=dimensions();p.update(construction_version=2,pocket_inner_overlap_mm=0.)
        history=list(fh_template.build_history(p))
        self.assertTrue(all(m.val().isValid() for _,m in history))
        self.assertTrue(history[-1][1].val().isInside(cq.Vector(0,10,p['world_z_mm']+1)))
        self.assertFalse(history[-1][1].val().isInside(cq.Vector(0,0,p['world_z_mm']+12)))
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        equivalent=fh_template.build(dimensions()).val()
        difference=BRepAlgoAPI_Cut(equivalent.wrapped,history[-1][1].val().wrapped)
        difference.Build()
        self.assertTrue(difference.IsDone())

    def test_drafted_openings_have_no_horizontal_upper_ledge(self):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane
        p=dimensions();p.update(construction_version=3,pocket_inner_overlap_mm=0.,
            pocket_radial_draft_deg=15.,pocket_start_spread_deg=10.,pocket_end_spread_deg=10.)
        history=list(fh_template.build_history(p));solid=history[-1][1].val()
        self.assertTrue(all(m.val().isValid() and m.val().Volume()>0 for _,m in history))
        self.assertFalse(any(name.startswith('upper_opening_step') for name,_ in history))
        for face in solid.Faces():
            surface=BRepAdaptor_Surface(face.wrapped)
            if surface.GetType()==GeomAbs_Plane and abs(abs(surface.Plane().Axis().Direction().Z())-1)<1e-6:
                self.assertGreater(abs(surface.Plane().Location().Z()-(p['world_z_mm']+p['slot_upper_floor_mm'])),1e-6)
        p['clean_final']=True
        cleaned=fh_template.build(p).val()
        self.assertTrue(cleaned.isValid())
        self.assertLessEqual(len(cleaned.Faces()),len(solid.Faces()))

    def test_rejects_invalid_supported_domain(self):
        for key,value in [('world_z_mm',float('nan')),('slot_upper_floor_mm',20),
            ('slot_sweep_deg',180),('pocket_inner_overlap_mm',20),('bolt_angles_deg',[float('inf')])]:
            with self.subTest(key=key):
                p=dimensions();p[key]=value
                with self.assertRaises(ValueError):fh_template.parameters(p)
        with self.assertRaises(ValueError):fh_template.parameters({})

if __name__=='__main__':unittest.main()
