"""Dimension-driven FH trial template, rebuilt without source CAD or C/R details.

Local datum is the large flange underside; placement is explicit world_z_mm.
Version 3 uses ruled slot and pocket drafts; earlier trial versions remain
reproducible for comparison. No detailed CAD is imported or directly edited.
"""
from copy import deepcopy
from math import asin,cos,degrees,radians,sin,tan
import cadquery as cq

TEMPLATE_ID='fh_casting_trial'
TEMPLATE_VERSION=3
_REQUIRED=('world_z_mm', 'flange_radius_mm', 'flange_height_mm', 'lower_boss_radius_mm', 'lower_boss_depth_mm', 'boss_radius_mm', 'boss_height_mm', 'bore_radius_mm', 'ring_inner_radius_mm', 'ring_bottom_mm', 'ring_top_mm', 'slot_center_radius_mm', 'slot_width_mm', 'slot_sweep_deg', 'slot_count', 'slot_first_angle_deg', 'bolt_circle_radius_mm', 'bolt_radius_mm', 'bolt_angles_deg', 'aux_holes', 'pocket_inner_radius_mm', 'pocket_outer_radius_mm', 'pocket_start_angle_deg', 'pocket_end_angle_deg', 'pocket_floor_mm', 'pocket_inner_overlap_mm', 'slot_upper_clearance_mm', 'slot_upper_floor_mm')


def polar(r,a,z=0):
    return cq.Vector(r*cos(radians(a)),r*sin(radians(a)),z)


def radial_arc(r,a,b,z):
    return cq.Edge.makeThreePointArc(polar(r,a,z),polar(r,(a+b)/2,z),polar(r,b,z))


def annular_sector(inner,outer,start,end,z,height):
    # Parameterized sketch with two arcs and two radial lines, then extrusion.
    wire=cq.Wire.assembleEdges([
        radial_arc(outer,start,end,z),
        cq.Edge.makeLine(polar(outer,end,z),polar(inner,end,z)),
        radial_arc(inner,end,start,z),
        cq.Edge.makeLine(polar(inner,start,z),polar(outer,start,z))])
    return cq.Workplane(obj=cq.Solid.extrudeLinear(wire,[],cq.Vector(0,0,height)))


def round_arc_slot(p,angle,z,height,end_radius=None):
    radius,half_width=p['slot_center_radius_mm'],p['slot_width_mm']/2
    half_angle=p['slot_sweep_deg']/2-degrees(asin(half_width/radius))
    start,end=angle-half_angle,angle+half_angle
    # A swept annular-sector sketch with circular end caps. This is an opening,
    # not an edge fillet; the original opening wall regions are retained.
    sector=annular_sector(radius-half_width,radius+half_width,start,end,z,height)
    for a in (start,end):
        c=polar(radius,a)
        sector=sector.union(cylinder(end_radius or half_width,z,height,c.x,c.y))
    return sector


def cylinder(r,z,height,x=0,y=0):
    return cq.Workplane('XY').workplane(offset=z).center(x,y).circle(r).extrude(height)


def parameters(values=None):
    if not isinstance(values,dict) or not set(_REQUIRED)<=set(values) or set(values)-set(_REQUIRED)-{'construction_version','pocket_radial_draft_deg','pocket_start_spread_deg','pocket_end_spread_deg','clean_final'}:
        raise ValueError('Provide the complete dimensional FH parameter record')
    p=deepcopy(values)
    version=p.get('construction_version',1)
    if type(version) is not int or version not in (1,2,3):raise ValueError('Unsupported FH construction version')
    from math import isfinite
    if type(p['world_z_mm']) not in (int,float) or not isfinite(p['world_z_mm']):raise ValueError('Finite world datum required')
    for key in ('slot_sweep_deg','slot_first_angle_deg','pocket_start_angle_deg','pocket_end_angle_deg'):
        if type(p[key]) not in (int,float) or not isfinite(p[key]):raise ValueError('Finite angle required: '+key)
    if not isinstance(p['bolt_angles_deg'],list) or any(type(a) not in (int,float) or not isfinite(a) for a in p['bolt_angles_deg']):raise ValueError('Finite bolt angles required')
    if not isinstance(p['aux_holes'],list):raise ValueError('Hole pattern must be a list')
    for hole in p['aux_holes']:
        if not isinstance(hole,dict) or set(hole)!={'radius_mm','polar_radius_mm','angle_deg'} or any(type(v) not in (int,float) or not isfinite(v) for v in hole.values()) or hole['radius_mm']<=0 or hole['polar_radius_mm']<0:raise ValueError('Invalid auxiliary hole')
    positive=[k for k in p if k.endswith('_mm') and k not in ('world_z_mm','ring_bottom_mm','pocket_inner_overlap_mm')]
    from math import isfinite
    for key in positive:
        if type(p[key]) not in (int,float) or not isfinite(p[key]) or p[key]<=0:
            raise ValueError('Positive finite FH dimension required: '+key)
    if not p['bore_radius_mm']<p['boss_radius_mm']<p['lower_boss_radius_mm']<p['flange_radius_mm']:
        raise ValueError('Invalid radial boss nesting')
    if not 0<p['ring_inner_radius_mm']<p['flange_radius_mm'] or not 0<=p['ring_bottom_mm']<p['flange_height_mm']<p['ring_top_mm']:
        raise ValueError('Invalid ring')
    if not 0<p['pocket_floor_mm']<p['flange_height_mm'] or not 0<p['pocket_inner_radius_mm']<p['pocket_outer_radius_mm']<p['ring_inner_radius_mm']:
        raise ValueError('Invalid pocket')
    if type(p['slot_count']) is not int or p['slot_count']<1 or not 0<p['slot_width_mm']/2<p['slot_center_radius_mm']:
        raise ValueError('Invalid slot pattern')
    if not 0<p['slot_upper_floor_mm']<p['flange_height_mm'] or not (0 if version in (2,3) else 1e-15)<=p['pocket_inner_overlap_mm']<p['pocket_inner_radius_mm']:raise ValueError('Invalid step floor or pocket overlap')
    if not 2*degrees(asin((p['slot_width_mm']/2)/p['slot_center_radius_mm']))<p['slot_sweep_deg']<360/p['slot_count']:raise ValueError('Invalid nonoverlapping slot sweep')
    if not 0<p['pocket_end_angle_deg']-p['pocket_start_angle_deg']<360:raise ValueError('Invalid pocket sweep')
    if version in (2,3) and (p['pocket_inner_overlap_mm']!=0 or abs(p['ring_bottom_mm']-p['slot_upper_floor_mm'])>1e-9):raise ValueError('Version 2 requires zero pocket overlap and matching ring/upper-step floor')
    if version!=3 and any(key in p for key in ('pocket_radial_draft_deg','pocket_start_spread_deg','pocket_end_spread_deg')):raise ValueError('Pocket draft parameters require construction version 3')
    if 'clean_final' in p and (version!=3 or type(p['clean_final']) is not bool):raise ValueError('Final cleanup flag is supported only for version 3')
    if version==3:
        for key in ('pocket_radial_draft_deg','pocket_start_spread_deg','pocket_end_spread_deg'):
            if key not in p or type(p[key]) not in (int,float) or not isfinite(p[key]) or not 0<=p[key]<45:raise ValueError('Explicit bounded pocket draft required: '+key)
        floor_radius=p['pocket_outer_radius_mm']-(p['flange_height_mm']-p['pocket_floor_mm'])*tan(radians(p['pocket_radial_draft_deg']))
        if floor_radius<=p['pocket_inner_radius_mm'] or p['pocket_start_angle_deg']+p['pocket_start_spread_deg']>=p['pocket_end_angle_deg']-p['pocket_end_spread_deg']:raise ValueError('Draft collapses pocket floor')
    return p


def build_history(values=None):
    p=parameters(values)
    if p.get('construction_version',1)==3:
        yield from build_history_v3(p)
        return
    if p.get('construction_version',1)==2:
        yield from build_history_v2(p)
        return
    z=p['world_z_mm'];h=p['flange_height_mm'];lower=p['lower_boss_depth_mm']
    model=cylinder(p['flange_radius_mm'],z,h)
    yield 'flange',model
    model=model.union(cylinder(p['lower_boss_radius_mm'],z-lower,lower))
    yield 'lower_boss',model
    model=model.union(cylinder(p['boss_radius_mm'],z+h,p['boss_height_mm']))
    yield 'center_boss',model
    model=model.cut(cylinder(p['bore_radius_mm'],z-lower-1,lower+h+p['boss_height_mm']+2))
    yield 'shaft_bore',model
    for index in range(p['slot_count']):
        angle=p['slot_first_angle_deg']+index*360/p['slot_count']
        model=model.cut(round_arc_slot(p,angle,z-1,h+2))
        yield f'arc_opening_{index+1}',model
    # A constant upper end relief extends the preserved R55 ring wall.
    # Its end stations come from retained opening walls; no C/R edge is copied.
    for index in range(p['slot_count']):
        angle=p['slot_first_angle_deg']+index*360/p['slot_count']
        model=model.cut(round_arc_slot(p,angle,z+p['slot_upper_floor_mm'],
            h-p['slot_upper_floor_mm'],end_radius=p['slot_width_mm']/2+p['slot_upper_clearance_mm']))
        yield f'upper_opening_step_{index+1}',model
    for index,a in enumerate(p['bolt_angles_deg'],1):
        point=polar(p['bolt_circle_radius_mm'],a)
        model=model.cut(cylinder(p['bolt_radius_mm'],z-lower-1,lower+h+2,point.x,point.y))
        yield f'bolt_opening_{index}',model
    for index,hole in enumerate(p['aux_holes'],1):
        point=polar(hole['polar_radius_mm'],hole['angle_deg'])
        model=model.cut(cylinder(hole['radius_mm'],z-lower-1,lower+h+2,point.x,point.y))
        yield f'aux_opening_{index}',model
    model=model.cut(annular_sector(p['pocket_inner_radius_mm']-p['pocket_inner_overlap_mm'],p['pocket_outer_radius_mm'],
        p['pocket_start_angle_deg'],p['pocket_end_angle_deg'],z+p['pocket_floor_mm'],h-p['pocket_floor_mm']))
    yield 'sector_pocket',model
    ring=(cq.Workplane('XY').workplane(offset=z+p['ring_bottom_mm'])
          .circle(p['flange_radius_mm']).circle(p['ring_inner_radius_mm']).extrude(p['ring_top_mm']-p['ring_bottom_mm']))
    model=model.union(ring,clean=False)
    yield 'outer_ring',model


def build_history_v2(p):
    """Cut recesses from common stock, avoiding coincident late ring unions.

    The pocket is cut before adding the center boss. This removes the artificial
    inner overlap required by the version-1 operation order and its tiny edges.
    """
    z=p['world_z_mm'];h=p['flange_height_mm'];lower=p['lower_boss_depth_mm']
    model=cylinder(p['flange_radius_mm'],z,p['ring_top_mm'])
    yield 'flange_ring_stock',model
    model=model.cut(cylinder(p['ring_inner_radius_mm'],z+h,p['ring_top_mm']-h+1))
    yield 'ring_recess',model
    model=model.union(cylinder(p['lower_boss_radius_mm'],z-lower,lower))
    yield 'lower_boss',model
    model=model.cut(cylinder(p['bore_radius_mm'],z-lower-1,lower+h+2))
    yield 'shaft_bore',model
    for index in range(p['slot_count']):
        angle=p['slot_first_angle_deg']+index*360/p['slot_count']
        model=model.cut(round_arc_slot(p,angle,z-1,h+2))
        yield f'arc_opening_{index+1}',model
    floor=z+p['slot_upper_floor_mm'];depth=h-p['slot_upper_floor_mm']
    for index in range(p['slot_count']):
        angle=p['slot_first_angle_deg']+index*360/p['slot_count']
        tool=round_arc_slot(p,angle,floor,depth,
            end_radius=p['slot_width_mm']/2+p['slot_upper_clearance_mm'])
        tool=tool.intersect(cylinder(p['ring_inner_radius_mm'],floor,depth))
        model=model.cut(tool)
        yield f'upper_opening_step_{index+1}',model
    for index,a in enumerate(p['bolt_angles_deg'],1):
        point=polar(p['bolt_circle_radius_mm'],a)
        model=model.cut(cylinder(p['bolt_radius_mm'],z-lower-1,lower+h+2,point.x,point.y))
        yield f'bolt_opening_{index}',model
    for index,hole in enumerate(p['aux_holes'],1):
        point=polar(hole['polar_radius_mm'],hole['angle_deg'])
        model=model.cut(cylinder(hole['radius_mm'],z-lower-1,lower+h+2,point.x,point.y))
        yield f'aux_opening_{index}',model
    model=model.cut(annular_sector(p['pocket_inner_radius_mm'],p['pocket_outer_radius_mm'],
        p['pocket_start_angle_deg'],p['pocket_end_angle_deg'],z+p['pocket_floor_mm'],h-p['pocket_floor_mm']),clean=False)
    yield 'sector_pocket',model
    boss=(cq.Workplane('XY').workplane(offset=z+h)
        .circle(p['boss_radius_mm']).circle(p['bore_radius_mm']).extrude(p['boss_height_mm']))
    model=model.union(boss,clean=False)
    yield 'center_boss',model


def annular_sector_wire(inner,outer,start,end,z):
    return cq.Wire.assembleEdges([
        radial_arc(outer,start,end,z),
        cq.Edge.makeLine(polar(outer,end,z),polar(inner,end,z)),
        radial_arc(inner,end,start,z),
        cq.Edge.makeLine(polar(inner,start,z),polar(outer,start,z))])


def curved_slot_wire(p,angle,z,half_width):
    radius=p['slot_center_radius_mm']
    half_angle=p['slot_sweep_deg']/2-degrees(asin((p['slot_width_mm']/2)/radius))
    start,end=angle-half_angle,angle+half_angle
    return cq.Wire.assembleEdges([
        radial_arc(radius+half_width,start,end,z),
        cq.Edge.makeThreePointArc(polar(radius+half_width,end,z),
            polar(radius,end,z)+polar(half_width,end+90),polar(radius-half_width,end,z)),
        radial_arc(radius-half_width,end,start,z),
        cq.Edge.makeThreePointArc(polar(radius-half_width,start,z),
            polar(radius,start,z)+polar(half_width,start-90),polar(radius+half_width,start,z))])


def build_history_v3(p):
    """No slot ledges: one through opening with a ruled upper draft per slot."""
    z=p['world_z_mm'];h=p['flange_height_mm'];lower=p['lower_boss_depth_mm']
    model=cylinder(p['flange_radius_mm'],z,p['ring_top_mm'])
    yield 'flange_ring_stock',model
    model=model.cut(cylinder(p['ring_inner_radius_mm'],z+h,p['ring_top_mm']-h+1),clean=False)
    yield 'ring_recess',model
    model=model.union(cylinder(p['lower_boss_radius_mm'],z-lower,lower),clean=False)
    yield 'lower_boss',model
    model=model.cut(cylinder(p['bore_radius_mm'],z-lower-1,lower+h+2),clean=False)
    yield 'shaft_bore',model
    floor=z+p['slot_upper_floor_mm'];depth=h-p['slot_upper_floor_mm']
    half=p['slot_width_mm']/2
    for index in range(p['slot_count']):
        angle=p['slot_first_angle_deg']+index*360/p['slot_count']
        base=cq.Solid.extrudeLinear(curved_slot_wire(p,angle,z-1,half),[],cq.Vector(0,0,floor-z+1))
        draft=cq.Solid.makeLoft([curved_slot_wire(p,angle,floor,half),
            curved_slot_wire(p,angle,z+h,half+p['slot_upper_clearance_mm'])],ruled=True)
        tool=cq.Workplane(obj=base).union(cq.Workplane(obj=draft),clean=False)
        tool=tool.intersect(cylinder(p['ring_inner_radius_mm'],z-1,h+1),clean=False)
        model=model.cut(tool,clean=False)
        yield f'drafted_arc_opening_{index+1}',model
    for index,a in enumerate(p['bolt_angles_deg'],1):
        point=polar(p['bolt_circle_radius_mm'],a)
        model=model.cut(cylinder(p['bolt_radius_mm'],z-lower-1,lower+h+2,point.x,point.y),clean=False)
        yield f'bolt_opening_{index}',model
    for index,hole in enumerate(p['aux_holes'],1):
        point=polar(hole['polar_radius_mm'],hole['angle_deg'])
        model=model.cut(cylinder(hole['radius_mm'],z-lower-1,lower+h+2,point.x,point.y),clean=False)
        yield f'aux_opening_{index}',model
    floor_radius=p['pocket_outer_radius_mm']-(h-p['pocket_floor_mm'])*tan(radians(p['pocket_radial_draft_deg']))
    pocket=cq.Solid.makeLoft([
        annular_sector_wire(p['pocket_inner_radius_mm'],floor_radius,
            p['pocket_start_angle_deg']+p['pocket_start_spread_deg'],
            p['pocket_end_angle_deg']-p['pocket_end_spread_deg'],z+p['pocket_floor_mm']),
        annular_sector_wire(p['pocket_inner_radius_mm'],p['pocket_outer_radius_mm'],
            p['pocket_start_angle_deg'],p['pocket_end_angle_deg'],z+h)],ruled=True)
    model=model.cut(cq.Workplane(obj=pocket),clean=False)
    yield 'drafted_sector_pocket',model
    boss=(cq.Workplane('XY').workplane(offset=z+h)
        .circle(p['boss_radius_mm']).circle(p['bore_radius_mm']).extrude(p['boss_height_mm']))
    model=model.union(boss,clean=False)
    yield 'center_boss',model
    if p.get('clean_final',False):
        model=model.clean()
        yield 'same_domain_cleanup',model


def build(values=None):
    return list(build_history(values))[-1][1]
