"""Print-in-place v14 hinge: both bodies print already assembled, no axle or cap.

The v14 long-barrel bodies are reused. Only the region within the barrel
clearance radius is rebuilt as surfaces of revolution: 45 degree cone faces
between knuckles and a short integral cone-tipped pin rising from each lower
knuckle into a blind socket of the upper one. In print orientation (v14
to_print, Y up) every downward face in that region is 45 degrees, not flat.
Coordinates and the motion convention are defined by build_calibration.
"""
from pathlib import Path
import hashlib
import json
import math

import FreeCAD as App
import Part
import MeshPart
import build_calibration as base

ROOT=Path(__file__).resolve().parents[1]
N=json.loads((ROOT/'cad/print-in-place-parameters.json').read_text())
P=base.P
V=App.Vector
OUT=ROOT/'exports/print-in-place'
EVIDENCE=ROOT/'docs/evidence/print-in-place'
BARREL=P['barrel_radius']
OUTER=N['socket_outer_radius']
GAP=N['cone_normal_gap']*math.sqrt(2)  # axial gap of a 45 degree cone pair
RP=N['pin_radius']
RH=RP+N['radial_clearance']


def joints():
    """(lower rim top, upper rim bottom) for the front and rear v14 joints."""
    end=8.0
    return [(end,end+GAP),(P['depth']-end-GAP,P['depth']-end)]


def pin_top(upper):
    return upper+N['pin_cylinder_above_upper_rim']


def revolve(points):
    # Polygon in the (radius, Y) half plane, revolved about the hinge axis.
    pts=[V(r,y,0) for r,y in points]
    face=Part.Face(Part.makePolygon(pts+[pts[0]]))
    return face.revolve(V(0,0,0),V(0,1,0),360)


def cone_line(rim,r):
    # Every cone face uses Y = rim + (barrel - r), i.e. 45 degrees.
    return rim+BARREL-r


def lower_with_pin(lower,upper,floor):
    top=pin_top(upper)
    return revolve([(0,floor),(OUTER,floor),(OUTER,cone_line(lower,OUTER)),
                    (RP,cone_line(lower,RP)),(RP,top),(0,top+RP)])


def upper_with_socket(upper,ceiling):
    top=pin_top(upper)
    # Socket = pin offset by the radial and normal gaps; its roof is a cone too.
    return revolve([(0,ceiling),(OUTER,ceiling),(OUTER,cone_line(upper,OUTER)),
                    (RH,cone_line(upper,RH)),(RH,top+RP-RH+GAP),(0,top+RP+GAP)])


def hinge_region(left):
    (front_lower,front_upper),(rear_lower,rear_upper)=joints()
    if left:
        return lower_with_pin(front_lower,front_upper,-1).fuse(
               upper_with_socket(rear_upper,P['depth']+1))
    socket=upper_with_socket(front_upper,P['depth']+1)
    return socket.common(lower_with_pin(rear_lower,rear_upper,-1))


def make_half(left):
    v14=base.make_half(left)
    clearance=base.cylinder(OUTER,-1,P['depth']+2)
    # The v14 profile's own sliver between the barrel and the clearance radius,
    # taken where it is uncut and extended over the full width.
    probe_y=4.0 if left else P['depth']/2
    slab=v14.common(base.cylinder(OUTER,probe_y,1)).cut(base.cylinder(BARREL,probe_y-1,3))
    faces=[f.copy() for f in slab.Faces if f.BoundBox.YLength<1e-7 and abs(f.BoundBox.YMin-probe_y)<1e-7]
    assert faces,'v14 profile does not reach the barrel clearance'
    for face in faces:
        face.translate(V(0,-probe_y-1,0))
    sliver=[face.extrude(V(0,P['depth']+2,0)) for face in faces]
    inner=base.join(base.cylinder(BARREL,-1,P['depth']+2),*sliver).common(hinge_region(left))
    body=v14.cut(clearance).fuse(inner).removeSplitter()
    body=body.common(Part.makeBox(400,P['depth'],400,V(-200,0,-200))).removeSplitter()
    assert body.isValid() and len(body.Solids)==1,f'Disconnected body (left={left})'
    return body


def print_transform(shapes,origin):
    # v14 to_print orientation (Y becomes Z), applied to the whole assembly.
    moved=[s.copy() for s in shapes]
    for s in moved:
        s.rotate(V(0,0,0),V(1,0,0),90)
    bounds=Part.makeCompound(moved).optimalBoundingBox(False)
    for s in moved:
        s.translate(V(origin[0]-bounds.XMin,origin[1]-bounds.YMin,-bounds.ZMin))
    return moved


def posed(bodies,angle):
    return [base.assembly_pose(bodies[0],angle,True),base.assembly_pose(bodies[1],angle,False)]


def trial_half(body,left):
    # Same crop as the snap-retainer trial: keep the neck to the profile.
    crop=Part.makeBox(29,N['trial_height'],22,V(-22 if left else -7,0,-8))
    shape=body.common(crop).removeSplitter()
    assert len(shape.Solids)==1,f'Trial half split into {len(shape.Solids)} solids'
    return shape


def write_mesh(shapes,path):
    mesh=MeshPart.meshFromShape(Shape=Part.makeCompound(shapes),
        LinearDeflection=N["body_mesh_deflection"],AngularDeflection=0.13,Relative=False)
    mesh.write(str(path))
    return mesh


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    bodies=[make_half(True),make_half(False)]
    angle=N['print_angle_deg']
    plate=print_transform(posed(bodies,angle),N['plate_origin'])
    trials=[trial_half(bodies[0],True),trial_half(bodies[1],False)]
    trial=print_transform(posed(trials,angle),N['trial_origin'])
    mesh=write_mesh(plate,OUT/'assembly-plate.stl')
    mesh.write(str(OUT/'assembly-plate.3mf'))
    write_mesh(trial,OUT/'hinge-trial.stl')
    doc=App.newDocument('PrintInPlace')
    for name,shape in zip(['body_left','body_right'],plate):
        obj=doc.addObject('Part::Feature',name)
        obj.Shape=shape
    doc.recompute()
    doc.saveAs(str(ROOT/'cad/print-in-place.FCStd'))
    Part.export(doc.Objects,str(OUT/'assembly-plate.step'))
    App.closeDocument(doc.Name)
    for state,a in [('open',0),('print',angle)]:
        for name,shape in zip(['body-left','body-right'],posed(bodies,a)):
            write_mesh([shape],EVIDENCE/f'{state}-{name}.stl')
    # Half section through the axis at the front joint shows cones, pin and socket.
    half=Part.makeBox(30,22,15,V(-15,0,0))
    for name,shape in zip(['section-left','section-right'],bodies):
        write_mesh([shape.common(half)],EVIDENCE/f'{name}.stl')
    (front_lower,front_upper),(rear_lower,rear_upper)=joints()
    manifest={'units':'mm',
              'base_parameters_sha256':hashlib.sha256((ROOT/'cad/parameters.json').read_bytes()).hexdigest(),
              'print_angle_deg':angle,
              'pin_diameter_mm':2*RP,'socket_diameter_mm':2*RH,
              'radial_clearance_mm':N['radial_clearance'],
              'cone_normal_gap_mm':N['cone_normal_gap'],'cone_axial_gap_mm':GAP,
              'joints_mm':[{'lower_rim':front_lower,'upper_rim':front_upper},
                           {'lower_rim':rear_lower,'upper_rim':rear_upper}],
              'assembly_quantities':{'body-left':1,'body-right':1},
              'plate_volume_mm3':sum(s.Volume for s in plate),
              'trial_volume_mm3':sum(s.Volume for s in trial),
              'files':['assembly-plate.stl','assembly-plate.3mf','assembly-plate.step','hinge-trial.stl']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
