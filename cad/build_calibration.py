"""Rebuild the calibration kit with FreeCAD's OpenCascade solid kernel.

Coordinates: X across the slot, Y along the laptop, Z up; hinge at (0,0,0).
Left rotates +theta about Y, right -theta. All dimensions are millimetres.
Run from the repository root: bash scripts/freecad_python.sh cad/build_calibration.py
"""
from pathlib import Path
import json
import math
import sys

import FreeCAD as App
import Part
import MeshPart
from band_geometry import band_centerline

ROOT = Path(__file__).resolve().parents[1]
P = json.loads((ROOT / 'cad/parameters.json').read_text())
OUT = ROOT / 'exports/calibration'
EVIDENCE = ROOT / 'docs/evidence'
V = App.Vector


def prism(points, y, depth):
    pts = [V(x, y, z) for x, z in points]
    wire = Part.makePolygon(pts + [pts[0]])
    return Part.Face(wire).extrude(V(0, depth, 0))


def cylinder(radius, y, length, x=0, z=0):
    return Part.makeCylinder(radius, length, V(x, y, z), V(0, 1, 0))


def join(*parts):
    result = parts[0]
    for shape in parts[1:]:
        result = result.fuse(shape)
    return result.removeSplitter()


def mirror(shape):
    return shape.mirror(V(0,0,0), V(1,0,0))


def capsule(radius, half_span, y, length, x, z):
    """Horizontal obround extruded into the stand; span excludes round ends."""
    assert radius > 0 and half_span > 0 and length > 0
    return join(cylinder(radius,y,length,x-half_span,z),
                Part.makeBox(2*half_span,length,2*radius,V(x-half_span,y,z-radius)),
                cylinder(radius,y,length,x+half_span,z))


def make_hook(x):
    """Wide capsule neck supports a thicker, softly rounded retaining head."""
    span=P['hook_capsule_half_span']
    neck=capsule(P['hook_neck_radius'],span,P['hook_mount_y'],
                 P['hook_neck_end_y']-P['hook_mount_y'],x,P['hook_z'])
    head=capsule(P['hook_head_radius'],span,P['hook_neck_end_y'],
                 P['hook_head_end_y']-P['hook_neck_end_y'],x,P['hook_z'])
    rims=[e for e in head.Edges if e.BoundBox.YLength<1e-6]
    head=head.makeFillet(P['hook_head_edge_fillet'],rims)
    return join(neck,head)


def make_hook_backing(x):
    """One continuous leg-to-hook outline, with tangent curved transitions.

    The former capsule-shaped patch is replaced by a web whose lower edge
    leaves the foot tangent to its slope and joins the flat backing smoothly.
    """
    radius=P['hook_head_radius']+P['hook_backing_margin']
    span=P['hook_capsule_half_span']
    ax=-P['hook_backing_blend_x']
    slope=(P['foot_drop']-3)/(P['foot_x']-25)
    az=-P['foot_drop']+(ax+P['foot_x']-12)*slope
    bottom=P['hook_z']-radius
    a=(ax,az)
    b=(x-span,bottom)
    c=(x+span,bottom)
    d=(0,P['opening_stop_bottom_z'])
    def point(p):
        return V(p[0],0,p[1])
    def bezier(points):
        curve=Part.BezierCurve()
        curve.setPoles([point(p) for p in points])
        # Equivalent B-spline representation keeps OpenCascade's Boolean
        # self-interference checker stable on the tangent extruded surfaces.
        return curve.toBSpline().toShape()
    edges=[bezier([a,(ax+4,az+4*slope),(b[0]-5,bottom),b]),
           Part.makeLine(point(b),point(c)),
           bezier([c,(c[0]+3,bottom),(0,bottom+0.4),d])]
    upper=[d,(0,P['opening_stop_top_z']),(x,P['opening_stop_top_z']),
           (-13,-2),(-18,-4),a]
    edges.extend(Part.makeLine(point(p),point(q)) for p,q in zip(upper,upper[1:]))
    return Part.Face(Part.Wire(edges)).extrude(V(0,P['hook_mount_y'],0))


def make_half(left):
    d, r = P['depth'], P['barrel_radius']
    end_length, gap = 8.0, P['axial_clearance']
    assert 0 < gap < d/2-end_length, 'Invalid hinge end-face clearance'
    # A rigid foot and upright, a load shelf above the axis, and a neck into the barrel.
    fx, fd = P['foot_x'], P['foot_drop']
    wi, wt, wh = P['wall_inner_x'], P['wall_thickness'], P['wall_top']
    profile = [(-fx,-fd),(-fx+12,-fd),(-13,-3),(-13,1),(-2.5,1),
               (-2.5,5),(-2.5,9),(-wi,9),(-wi,wh),(-wi-wt,wh),
               (-wi-wt,0),(-fx+7,-fd+4),(-fx,-fd+4)]
    body = prism(profile, 0, d)
    # Soften the visible outside perimeter, retaining the load-contact corner,
    # the felt seating plane, and all bearing/mating dimensions.
    long_corners=[(-fx,-fd),(-fx,-fd+4),(-fx+7,-fd+4),
                  (-wi-wt,0),(-wi-wt,wh)]
    perimeter=[]
    for edge in body.Edges:
        b=edge.BoundBox
        longitudinal=(b.YLength>d-1e-6 and b.XLength<1e-6 and b.ZLength<1e-6
                      and any(abs(b.XMin-x)<1e-6 and abs(b.ZMin-z)<1e-6 for x,z in long_corners))
        end_plane=(b.YLength<1e-6 and (abs(b.YMin)<1e-6 or abs(b.YMin-d)<1e-6))
        outside_end=end_plane and (b.XMax<=-12.9 or b.ZMin>wh-1e-6)
        # Round the front after joining the web, so no old fillet seam remains
        # buried in the new leg-to-backing transition.
        if longitudinal or (outside_end and b.YMin>d-1e-6):
            perimeter.append(edge)
    body=body.makeFillet(P['outer_edge_fillet'],perimeter)
    if left:
        body = body.cut(cylinder(r + 0.35, end_length, d-2*end_length))
        body = join(body, cylinder(r, 0, end_length),
                    cylinder(r, d-end_length, end_length))
    else:
        # Leave a real axial gap at BOTH supported end faces. Shorten only the
        # central barrel so existing left bodies, axles and caps remain usable.
        body = body.cut(cylinder(r + 0.35, -0.1, end_length+gap+0.1))
        body = body.cut(cylinder(r + 0.35, d-end_length-gap, end_length+gap+0.1))
        body = join(body, cylinder(r, end_length+gap, d-2*(end_length+gap)))
    body = body.cut(cylinder((P['pin_diameter'] + P['mechanism_clearance']) / 2,
                             -0.2, d + 0.4))
    # One shallow felt pocket on the inside face, not on the load-bearing root.
    body = body.cut(Part.makeBox(0.4, d-6, wh-30, V(-wi-0.4, 3, 30)))
    # Keep the front lower crossbar, and reverse its posts: shafts point +Y
    # from the back face into the stand. No lower platform or upright posts.
    hooks = [make_hook(-x) for x in P['hook_x']]
    # The integral web also carries the original X=0 opening-stop face.
    backings=[make_hook_backing(-x) for x in P['hook_x']]
    body = join(body, *backings, *hooks)
    front=[]
    for edge in body.Edges:
        b=edge.BoundBox
        if b.YLength<1e-6 and abs(b.YMin)<1e-6:
            if b.XMax<=-12.9 or b.ZMin>wh-1e-6 or (b.ZMax<-6 and b.XMax<-2):
                front.append(edge)
    body=body.makeFillet(P['outer_edge_fillet'],front)
    rear=[e for e in body.Edges if e.BoundBox.YLength<1e-6
          and abs(e.BoundBox.YMin-P['hook_mount_y'])<1e-6
          and e.BoundBox.XMax<-2 and e.BoundBox.ZMax<-6
          and not isinstance(e.Curve,(Part.BezierCurve,Part.BSplineCurve))]
    body=body.makeFillet(P['hook_backing_edge_fillet'],rear)
    # Tangent edge chains can carry the cosmetic rim fillet onto the stop.
    # Restore its full, flat contact face after rounding the visible outline.
    body=join(body,Part.makeBox(1.5,P['opening_stop_depth'],
              P['opening_stop_top_z']-P['opening_stop_bottom_z'],
              V(-1.5,0,P['opening_stop_bottom_z'])))
    if not left:
        body = mirror(body)
    return body.cut(cylinder((P['pin_diameter']+P['mechanism_clearance'])/2,
                              -0.2,d+0.4)).removeSplitter()


def band_path(index,theta):
    """Rubber centerline behind the front rail, around inward-directed posts."""
    return [V(*point) for point in band_centerline(P,index,theta)]


def make_pin(length=None):
    # A flange on one end; an accessible transverse key slot at the other end.
    length=P['depth'] if length is None else length
    r = P['pin_diameter']/2
    flange=cylinder(5,-2,2)
    flange=flange.makeFillet(0.35,[e for e in flange.Edges if isinstance(e.Curve,Part.Circle)])
    pin = join(flange, cylinder(r, 0, length + 4.5))
    keyslot = Part.makeBox(8, 2.3, 2.0, V(-4, length+0.9, -1))
    pin=pin.cut(keyslot).removeSplitter()
    return pin


def make_key():
    """One-piece round end cap with an invisible transverse locking tongue.

    Local Y=0 is the back of the stand. Insert laterally from -X; only the
    trailing bridge joins the tongue to the cap, leaving a clear insertion path.
    """
    xy=[(-4.2,2.05-1.20),(4.2,2.05-0.82),
        (4.2,2.05+0.82),(-4.2,2.05+1.20)]
    vertices=[V(x,y,-0.9) for x,y in xy]
    tongue=Part.Face(Part.makePolygon(vertices+[vertices[0]])).extrude(V(0,0,1.8))
    bridge=Part.makeBox(1.5,4.56,2.6,V(-4.8,0.84,-1.3))
    # A C-shaped skirt brings the visible edge close to the back bearing.
    # Its +X opening clears the axle during lateral insertion; the back face stays round.
    skirt=cylinder(5,0.25,5.15).cut(cylinder(3.3,0.15,5.35))
    skirt=skirt.cut(Part.makeBox(6,6,6.4,V(0,0,-3.2)))
    cap=cylinder(5,4.7,2)
    circular=[edge for edge in cap.Edges if isinstance(edge.Curve,Part.Circle)]
    cap=cap.makeFillet(0.35,circular)
    return join(tongue,bridge,skirt,cap)


def key_in_assembly():
    key=make_key()
    key.translate(V(0,P['depth'],0))
    return key


def coupon(clearance):
    # Ring axis is vertical in the print STL. Raised dots identify 1 / 2 / 3.
    ring = cylinder(6, 0, 8).cut(cylinder((P['pin_diameter']+clearance)/2, -1, 10))
    handle = Part.makeBox(11, 8, 9, V(4, 0, -4.5))
    body = join(ring, handle)
    count = P['diametral_clearances'].index(clearance) + 1
    for i in range(count):
        body = join(body, cylinder(0.6, 8, 0.6, 7+i*2.5, 0))
    return body


def to_print(shape, back=False):
    result = shape.copy()
    result.rotate(V(0,0,0), V(1,0,0), -90 if back else 90)
    # Trimmed spheres have a conservative BoundBox extending below the cut plane.
    # Use the exact bounds so the real underside, not the enclosing sphere, sits on Z=0.
    b = result.optimalBoundingBox(False)
    result.translate(V(-b.XMin, -b.YMin, -b.ZMin))
    return result


def export_shape(shape, path, linear=0.035):
    assert shape.isValid(), f'Invalid solid: {path}'
    assert len(shape.Solids) == 1, f'Disconnected solids: {path}: {len(shape.Solids)}'
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=linear,
                                  AngularDeflection=0.13, Relative=False)
    mesh.write(str(path))
    bounds=shape.optimalBoundingBox(False)
    return {'file': path.name, 'volume_mm3': shape.Volume,
            'size_mm': [bounds.XLength, bounds.YLength, bounds.ZLength],
            'triangles': mesh.CountFacets}


def assembly_pose(shape, theta, left):
    result = shape.copy()
    result.rotate(V(0,0,0), V(0,1,0), theta if left else -theta)
    h = P['foot_drop']*math.cos(math.radians(theta))-(P['foot_x']-12)*math.sin(math.radians(theta))
    result.translate(V(0,0,h))
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    left, right = make_half(True), make_half(False)
    parts = {'mechanism-left': left, 'mechanism-right': right,
             'axle-6mm': make_pin(), 'axle-key': make_key()}
    for c in P['diametral_clearances']:
        parts[f'fit-{int(c*100):02d}'] = coupon(c)
    doc = App.newDocument('Calibration')
    manifest = {'freecad_version': '.'.join(App.Version()[:3]), 'parts': []}
    print_shapes = []
    for name, shape in parts.items():
        if not name.startswith('fit-'):
            obj = doc.addObject('PartDesign::Feature', name.replace('-', '_'))
            obj.Label = name
            obj.Shape = shape
            obj.addProperty('App::PropertyString', 'Purpose').Purpose = 'PLA prototype; physical performance unverified'
        # The now-flat front face sits on the bed, so inward posts grow upward.
        # The end cap prints on its smooth outside face; internal tongue is supported.
        printshape = to_print(shape,back=name=='axle-key')
        # A finer body mesh avoids crossed chords at the new curved rim.
        record = export_shape(printshape, OUT / f'{name}.stl',
                              linear=0.02 if name.startswith('mechanism-') else 0.035)
        record['name'] = name
        manifest['parts'].append(record)
        print_shapes.append((name, printshape))
    # Deliberately fixed, separate footprints, with 10mm outside margin.
    placements = [(24,34), (100,34), (175,34), (197,34)]
    plate = []
    # Assembly collection contains only the four parts used in the stand.
    # Clearance coupons remain individual files and on the separate fit plate.
    for (name, original), (x,y) in zip(print_shapes[:4], placements):
        shape = original.copy()
        shape.translate(V(x,y,0))
        plate.append(shape)
        doc.getObject(name.replace('-','_')).Shape=shape
        for item in manifest['parts']:
            if item['name'] == name:
                item['plate_origin_mm'] = [x,y,0]
    mesh = MeshPart.meshFromShape(Shape=Part.makeCompound(plate),
                                  LinearDeflection=0.02, AngularDeflection=0.13, Relative=False)
    mesh.write(str(OUT / 'calibration-plate.stl'))
    doc.recompute()
    doc.saveAs(str(ROOT / 'cad/calibration.FCStd'))
    Part.export([o for o in doc.Objects if hasattr(o,'Shape')], str(OUT / 'calibration.step'))
    fit_plate = []
    fit_positions = [(24,14),(44,14),(24,40),(55,40),(86,40)]
    for (name, original), (x,y) in zip(print_shapes[2:],fit_positions):
        shape=original.copy()
        shape.translate(V(x,y,0))
        fit_plate.append(shape)
    MeshPart.meshFromShape(Shape=Part.makeCompound(fit_plate),
        LinearDeflection=0.035,AngularDeflection=0.13,Relative=False).write(str(OUT/'fit-plate.stl'))
    for name, angle in [('open',0),('loaded',P['sample_loaded_angle_deg'])]:
        for side, shape in [('left',left),('right',right)]:
            export_shape(assembly_pose(shape, angle, side=='left'),
                         EVIDENCE / f'assembly-{name}-{side}.stl',linear=0.02)
        h=P['foot_drop']*math.cos(math.radians(angle))-(P['foot_x']-12)*math.sin(math.radians(angle))
        axle=make_pin()
        axle.translate(V(0,0,h))
        export_shape(axle,EVIDENCE/f'assembly-{name}-axle.stl')
        key=key_in_assembly()
        key.translate(V(0,0,h))
        export_shape(key,EVIDENCE/f'assembly-{name}-main-key.stl')
    assembly=App.newDocument('MechanismAssembly')
    for name,shape in [('Left',left),('Right',right),('Axle',make_pin()),
                       ('MainKey',key_in_assembly())]:
        obj=assembly.addObject('PartDesign::Feature',name)
        obj.Shape=assembly_pose(shape,0,True)
    assembly.recompute()
    assembly.saveAs(str(ROOT/'cad/mechanism-assembly.FCStd'))
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
