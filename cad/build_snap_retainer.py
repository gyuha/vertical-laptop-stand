"""Two short end hinges and flat, internally mounted E-shaped snap retainers.

Reuses the v14 body, shaft head and transverse slot without changing legacy
files. Coordinates and the motion convention are defined by build_calibration.
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
N=json.loads((ROOT/'cad/snap-parameters.json').read_text())
P=base.P
V=App.Vector
OUT=ROOT/'exports/snap-retainer'
EVIDENCE=ROOT/'docs/evidence/snap-retainer'


def pin_length_argument():
    # Preserve the old tip and slot offsets while placing the flat clip just
    # 0.25mm beyond the bearing face, instead of leaving a long exposed neck.
    return N['module_length']+N['clip_face_clearance']-(2.05-N['clip_thickness']/2)


def make_half(left):
    shape=base.make_half(left)
    radius=P['barrel_radius']+0.35
    return shape.cut(base.cylinder(radius,N['module_length'],
                       P['depth']-2*N['module_length'])).removeSplitter()


def make_pin():
    return base.make_pin(pin_length_argument())


def make_clip():
    t=N['clip_thickness']
    ring=base.cylinder(N['clip_outer_radius'],0,t).cut(
         base.cylinder(N['clip_inner_radius'],-0.1,t+0.2))
    opening=Part.makeBox(10,t+0.2,N['clip_mouth_width'],
                         V(N['clip_mouth_start_x'],-0.1,-N['clip_mouth_width']/2))
    ring=ring.cut(opening)
    finger=Part.makeBox(N['clip_finger_end_x']-N['clip_finger_start_x'],t,
                        N['clip_finger_height'],
                        V(N['clip_finger_start_x'],0,-N['clip_finger_height']/2))
    shape=base.join(ring,finger)
    # Round in the profile plane only. Every slice through the thickness stays
    # identical, so no underside bridge or trapped support is introduced.
    edges=[e for e in shape.Edges if e.BoundBox.YLength>t-1e-6
           and e.BoundBox.XLength<1e-6 and e.BoundBox.ZLength<1e-6]
    return shape.makeFillet(N['clip_corner_radius'],edges).removeSplitter()


def end_pose(shape,rear=False):
    result=shape.copy()
    if rear:
        result.rotate(V(0,0,0),V(1,0,0),180)
        result.translate(V(0,P['depth'],0))
    # Clock the unchanged slot vertically. Both clips then approach from below
    # through the open channel instead of colliding with the side of the body.
    result.rotate(V(0,0,0),V(0,1,0),N['slot_clock_angle_deg'])
    return result


def clip_in_assembly(rear=False):
    shape=make_clip()
    shape.translate(V(0,pin_length_argument()+2.05-N['clip_thickness']/2,0))
    return end_pose(shape,rear)


def components(angle=0):
    h=P['foot_drop']*math.cos(math.radians(angle))-(P['foot_x']-12)*math.sin(math.radians(angle))
    result={'body-left':base.assembly_pose(make_half(True),angle,True),
            'body-right':base.assembly_pose(make_half(False),angle,False)}
    for rear in [False,True]:
        suffix='rear' if rear else 'front'
        for name,shape in [('pin',end_pose(make_pin(),rear)),('clip',clip_in_assembly(rear))]:
            shape.translate(V(0,0,h))
            result[f'{name}-{suffix}']=shape
    return result


def trial_half(left):
    # Retain the actual bearing AND its connecting neck. A radial crop alone
    # cuts the neck into disconnected islands and is not a useful fit sample.
    crop=Part.makeBox(29,N['module_length'],22,V(-22 if left else -7,0,-8))
    return make_half(left).common(crop).removeSplitter()


def write_plate(shapes,placements,path,doc_path=None):
    placed=[]
    doc=App.newDocument('SnapPrint') if doc_path else None
    for (name,shape),(x,y) in zip(shapes,placements):
        shape=shape.copy()
        shape.translate(V(x,y,0))
        placed.append(shape)
        if doc:
            obj=doc.addObject('PartDesign::Feature',name.replace('-','_'))
            obj.Label=name
            obj.Shape=shape
    MeshPart.meshFromShape(Shape=Part.makeCompound(placed),
        LinearDeflection=N['body_mesh_deflection'],AngularDeflection=0.13,
        Relative=False).write(str(path))
    if doc:
        doc.recompute()
        doc.saveAs(str(doc_path))
        Part.export([o for o in doc.Objects if hasattr(o,'Shape')],str(OUT/'assembly-plate.step'))
        App.closeDocument(doc.Name)
    return placed


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    parts={'body-left':make_half(True),'body-right':make_half(False),
           'short-pin':make_pin(),'snap-clip':make_clip(),
           'trial-left':trial_half(True),'trial-right':trial_half(False)}
    records=[]
    printed={}
    for name,shape in parts.items():
        shape.check(True)
        printshape=base.to_print(shape)
        record=base.export_shape(printshape,OUT/f'{name}.stl',
                   linear=N['body_mesh_deflection'] if 'body-' in name else 0.035)
        record['name']=name
        records.append(record)
        printed[name]=printshape
    assembly=[('body-left',printed['body-left']),('body-right',printed['body-right']),
              ('pin-front',printed['short-pin']),('pin-rear',printed['short-pin']),
              ('clip-front',printed['snap-clip']),('clip-rear',printed['snap-clip'])]
    write_plate(assembly,[(24,34),(100,34),(175,34),(192,34),(175,58),(193,58)],
                OUT/'assembly-plate.stl',ROOT/'cad/snap-retainer-print.FCStd')
    trial=[(name,printed[name]) for name in ['trial-left','trial-right','short-pin','snap-clip']]
    write_plate(trial,[(24,34),(62,34),(102,34),(120,34)],OUT/'snap-fit-plate.stl')
    doc=App.newDocument('SnapAssembly')
    for state,angle in [('open',0),('loaded',P['sample_loaded_angle_deg'])]:
        for name,shape in components(angle).items():
            base.export_shape(shape,EVIDENCE/f'{state}-{name}.stl',
                              linear=N['body_mesh_deflection'] if 'body-' in name else 0.035)
            if state=='open':
                obj=doc.addObject('PartDesign::Feature',name.replace('-','_'))
                obj.Label=name
                obj.Shape=shape
    doc.recompute()
    doc.saveAs(str(ROOT/'cad/snap-retainer-assembly.FCStd'))
    App.closeDocument(doc.Name)
    clear_start=make_pin().BoundBox.YMax
    manifest={'units':'mm','base_parameters_sha256':hashlib.sha256((ROOT/'cad/parameters.json').read_bytes()).hexdigest(),
              'module_length_mm':N['module_length'],
              'barrel_free_interval_mm':[N['module_length'],P['depth']-N['module_length']],
              'actual_central_clear_interval_mm':[clear_start,P['depth']-clear_start],
              'actual_central_clear_length_mm':P['depth']-2*clear_start,
              'pin_length_argument_mm':pin_length_argument(),
              'pin_total_length_mm':make_pin().BoundBox.YLength,
              'clip_bearing_face_gap_mm':N['clip_face_clearance'],
              'assembly_quantities':{'body-left':1,'body-right':1,'short-pin':2,'snap-clip':2},
              'parts':records}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
