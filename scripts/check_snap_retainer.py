"""Validate actual dual-end CAD, output meshes, assembly paths and snap geometry."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def kernel_check():
    sys.path.insert(0,str(ROOT/'cad'))
    import FreeCAD as App
    import Mesh
    import Part
    import build_snap_retainer as cad
    from check_geometry import motion_check
    p,n=cad.P,cad.N
    v=App.Vector
    left,right=cad.make_half(True),cad.make_half(False)
    pin,clip=cad.make_pin(),cad.make_clip()
    native_parts={'body-left':left,'body-right':right,'short-pin':pin,'snap-clip':clip,
                  'trial-left':cad.trial_half(True),'trial-right':cad.trial_half(False)}
    for shape in native_parts.values():
        assert shape.isValid() and len(shape.Solids)==1
        shape.check(True)
    # Independent probes measure the preserved shaft diameter, flange and slot.
    section=Part.Face(pin.slice(v(0,1,0),5)[0])
    assert abs(section.Area-math.pi*3**2)<1e-5
    assert abs(section.BoundBox.XLength-6)<1e-5
    flange=Part.Face(pin.slice(v(0,1,0),-1)[0])
    assert abs(flange.Area-math.pi*5**2)<1e-5
    length=cad.pin_length_argument()
    for y,inside in [(length+0.89,True),(length+0.91,False),
                     (length+3.19,False),(length+3.21,True)]:
        assert pin.isInside(v(0,y,0),1e-7,True)==inside,'Original slot axial width changed'
    assert not pin.isInside(v(0,length+2.05,0.99),1e-7,True)
    assert pin.isInside(v(0,length+2.05,1.01),1e-7,True),'Original slot height changed'
    assert abs(pin.BoundBox.YLength-(length+6.5))<1e-6
    # A constant cross-section and matching area*thickness prove a flat prism,
    # not a covered pocket or a floating hidden key.
    areas=[]
    for i in range(9):
        y=n['clip_thickness']*(i+0.5)/9
        wires=clip.slice(v(0,1,0),y)
        assert len(wires)==1,'Clip is not one open profile'
        areas.append(Part.Face(wires[0]).Area)
    assert max(areas)-min(areas)<1e-6
    assert abs(clip.Volume-areas[0]*n['clip_thickness'])<1e-5
    for z in [-2,2]:
        assert not clip.isInside(v(0,n['clip_thickness']/2,z),1e-7,True),'Clip center is filled'
    assert clip.isInside(v(0,n['clip_thickness']/2,0),1e-7,True),'Central locking tongue missing'
    assert not clip.isInside(v(4,n['clip_thickness']/2,0),1e-7,True),'Snap mouth closed'
    mouth_section=clip.common(Part.makeLine(v(3,n['clip_thickness']/2,-6),
                                           v(3,n['clip_thickness']/2,6)))
    arms=sorted(mouth_section.Edges,key=lambda e:e.BoundBox.ZMin)
    assert len(arms)==2,'Cannot measure both snap mouth arms'
    mouth=arms[1].BoundBox.ZMin-arms[0].BoundBox.ZMax
    assert abs(mouth-n['clip_mouth_width'])<1e-6
    assert mouth<section.BoundBox.XLength and 2*n['clip_inner_radius']>6
    # The complete middle circular axis region must actually be empty.
    barrel_probe=cad.base.cylinder(p['barrel_radius']+0.35,
                                   n['module_length']+0.001,
                                   p['depth']-2*n['module_length']-0.002)
    assert sum(body.common(barrel_probe).Volume for body in [left,right])<1e-5
    parts0=cad.components(0)
    clear_start=cad.make_pin().BoundBox.YMax
    central=Part.makeCylinder(p['barrel_radius']+0.3,p['depth']-2*clear_start-0.02,
                             v(0,clear_start+0.01,p['foot_drop']),v(0,1,0))
    assert sum(shape.common(central).Volume for shape in parts0.values())<1e-5
    assert abs(clear_start-23.6)<1e-6
    # Annular mating faces measured at their material point, not just bounds.
    gaps=[]
    for a,b in [(8,8+p['axial_clearance']),
                (p['depth']-8,p['depth']-8-p['axial_clearance'])]:
        faces=[]
        for body,y in [(left,a),(right,b)]:
            found=[f for f in body.Faces if f.BoundBox.YLength<1e-6
                   and f.distToShape(Part.Vertex(v(0,y,5)))[0]<1e-6]
            assert len(found)==1
            faces.append(found[0])
        distance=faces[0].distToShape(faces[1])[0]
        assert abs(distance-0.6)<1e-6
        gaps.append(distance)
    max_overlap=0
    min_floor=float('inf')
    band_clearance=float('inf')
    for i in range(33):
        angle=p['sample_loaded_angle_deg']*i/32
        parts=cad.components(angle)
        a,b=parts['body-left'],parts['body-right']
        overlap=a.common(b).Volume
        assert overlap<1e-5,f'Body collision at {angle}'
        max_overlap=max(max_overlap,overlap)
        for name,s in parts.items():
            min_floor=min(min_floor,s.optimalBoundingBox(False).ZMin)
            if name.startswith(('pin-','clip-')):
                assert s.common(a).Volume+s.common(b).Volume<1e-5,f'{name} collides at {angle}'
        for side in ['front','rear']:
            assert parts[f'pin-{side}'].common(parts[f'clip-{side}']).Volume<1e-5
        t=math.radians(angle)
        h=p['foot_drop']*math.cos(t)-(p['foot_x']-12)*math.sin(t)
        half=p['laptop_thickness']/2
        seat=h+9/math.cos(t)+half*math.tan(t)
        laptop=Part.makeBox(p['laptop_thickness'],p['depth'],100,v(-half,0,seat))
        for body in [a,b]:
            assert body.common(laptop).Volume<1e-5
            assert body.distToShape(laptop)[0]<1e-5
        wire=Part.makePolygon(cad.base.band_path(0,angle))
        band_clearance=min(band_clearance,min(wire.distToShape(s)[0] for s in parts.values())-p['band_wire_radius'])
    assert min_floor>-1e-5
    assert band_clearance>0.05
    for angle in [-0.1,-2]:
        parts=cad.components(angle)
        assert parts['body-left'].common(parts['body-right']).Volume>0.01,'Opening stop missing'
    extra=cad.components(p['sample_loaded_angle_deg']+2)
    assert extra['body-left'].common(extra['body-right']).Volume<1e-5
    # Two actual under-axis faces must retain their full contact patch.
    stop_faces=[]
    for body in [left,right]:
        matching=[f for f in body.Faces if abs(f.BoundBox.XMin)<1e-7
                  and abs(f.BoundBox.XMax)<1e-7 and f.BoundBox.ZMax<0]
        assert len(matching)==1
        stop_faces.append(matching[0])
    contact=stop_faces[0].common(stop_faces[1]).Area
    assert abs(contact-20)<1e-5
    for step in range(81):
        moving=right.copy()
        moving.translate(v(40*(80-step)/80,0,0))
        assert moving.common(left).Volume<1e-5
    insertion=[]
    for rear in [False,True]:
        suffix='rear' if rear else 'front'
        fixed_pin=cad.end_pose(pin,rear)
        fixed_clip=cad.clip_in_assembly(rear)
        for step in range(41):
            moving=fixed_pin.copy()
            moving.translate(v(0,(1 if rear else -1)*30*(40-step)/40,0))
            assert moving.common(left).Volume+moving.common(right).Volume<1e-5
        # The existing slot is clocked vertically; clip approaches from below.
        # Rigid tongue/backbone must stay clear. Fork interference is measured
        # and reported as intentional elastic engagement, never waived as clear.
        protected=fixed_clip.common(Part.makeBox(2,5,20,
                         v(-1,fixed_clip.BoundBox.YMin-1,-10)))
        overlaps=[]
        for step in range(41):
            offset=8*(40-step)/40
            moving=fixed_clip.copy();moving.translate(v(0,0,-offset))
            rigid=protected.copy();rigid.translate(v(0,0,-offset))
            assert moving.common(left).Volume+moving.common(right).Volume<1e-5,'Clip access blocked'
            assert rigid.common(fixed_pin).Volume<1e-5,'Tongue cannot enter original slot'
            assert moving.optimalBoundingBox(False).ZMin+p['foot_drop']>1
            overlaps.append(moving.common(fixed_pin).Volume)
        assert overlaps[-1]<1e-5 and max(overlaps)>0.01,'Snap engagement not represented'
        locked=Part.makeCompound([fixed_pin,fixed_clip])
        locked.translate(v(0,0.8 if rear else -0.8,0))
        catch=sum(locked.common(b).Volume for b in [left,right])
        assert catch>0.01,'Clip does not catch the bearing axially'
        pushed=fixed_pin.copy();pushed.translate(v(0,-0.3 if rear else 0.3,0))
        assert sum(pushed.common(b).Volume for b in [left,right])>0.01,'Round head does not retain the pin'
        for delta in [-0.4,0.4]:
            shifted=fixed_pin.copy();shifted.translate(v(0,delta,0))
            assert shifted.common(fixed_clip).Volume>0.01,'Tongue does not engage axial slot walls'
        insertion.append({'end':suffix,'pin_samples':41,'clip_samples':41,
                          'max_intentional_fork_overlap_mm3':max(overlaps),
                          'bearing_catch_mm3':catch})
    # Native layouts and STEP must contain exactly the six assembly items.
    print_shapes={}
    for name,part_name,pos in [('body-left','body-left',(24,34)),('body-right','body-right',(100,34)),
                               ('pin-front','short-pin',(175,34)),('pin-rear','short-pin',(192,34)),
                               ('clip-front','snap-clip',(175,58)),('clip-rear','snap-clip',(193,58))]:
        shape=cad.base.to_print(native_parts[part_name])
        shape.translate(v(pos[0],pos[1],0));print_shapes[name]=shape
    for file in ['snap-retainer-print.FCStd','snap-retainer-assembly.FCStd']:
        doc=App.openDocument(str(ROOT/'cad'/file))
        objects=[o for o in doc.Objects if hasattr(o,'Shape')]
        labels=[o.Label for o in objects]
        assert len(labels)==6 and set(labels)==set(parts0),f'Unexpected CAD collection: {labels}'
        expected=print_shapes if 'print' in file else parts0
        for obj in objects:
            original=expected[obj.Label]
            difference=obj.Shape.cut(original).Volume+original.cut(obj.Shape).Volume
            assert difference<1e-4,f'Native CAD shape/pose mismatch: {file}/{obj.Label}'
        App.closeDocument(doc.Name)
    step=Part.Shape();step.read(str(cad.OUT/'assembly-plate.step'))
    assert len(step.Solids)==6
    plate_volume=sum(s.Volume for s in print_shapes.values())
    assert abs(step.Volume-plate_volume)<1e-3,'STEP shape volume differs from print CAD'
    for path in sorted(cad.OUT.glob('*.stl')):
        mesh=Mesh.Mesh(str(path))
        assert not mesh.hasSelfIntersections(),f'Self-intersecting output: {path.name}'
    printed_parts={}
    for name,shape in native_parts.items():
        printed=cad.base.to_print(shape);box=printed.optimalBoundingBox(False)
        printed_parts[name+'.stl']={'volume_mm3':shape.Volume,
             'bounds_mm':[[box.XMin,box.YMin,box.ZMin],[box.XMax,box.YMax,box.ZMax]]}
    trial_volume=sum(native_parts[name].Volume for name in ['trial-left','trial-right','short-pin','snap-clip'])
    return {'pose_samples':33,'max_body_overlap_mm3':max_overlap,
            'printed_parts':printed_parts,'assembly_plate_volume_mm3':plate_volume,
            'trial_plate_volume_mm3':trial_volume,
            'minimum_floor_clearance_mm':min_floor,'minimum_band_clearance_mm':band_clearance,
            'hinge_end_face_gaps_mm':gaps,'opening_stop_contact_mm2':contact,
            'barrel_free_interval_mm':[n['module_length'],p['depth']-n['module_length']],
            'central_clear_interval_mm':[clear_start,p['depth']-clear_start],
            'central_clear_length_mm':p['depth']-2*clear_start,
            'pin_total_length_mm':pin.BoundBox.YLength,'pin_diameter_mm':section.BoundBox.XLength,
            'slot_width_mm':2.3,'slot_height_mm':2.0,'flange_diameter_mm':10,
            'clip_flat_prism':True,'clip_profile_area_mm2':areas[0],
            'clip_thickness_mm':n['clip_thickness'],'clip_mouth_width_mm':mouth,
            'clip_finger_height_mm':n['clip_finger_height'],
            'nominal_required_tip_deflection_per_arm_mm':(section.BoundBox.XLength-mouth)/2,
            'elasticity_assessment':'geometric opening requirement only; force and durability untested',
            'insertion_paths':insertion,'motion':motion_check(p)}


def main(kernel=False):
    if kernel:
        print(json.dumps(kernel_check()))
        return
    from check_geometry import inspect_mesh,mesh_vertices
    out=ROOT/'exports/snap-retainer'
    manifest=json.loads((out/'manifest.json').read_text())
    meshes=[inspect_mesh(out/part['file']) for part in manifest['parts']]
    meshes+=[inspect_mesh(out/'assembly-plate.stl',6),inspect_mesh(out/'snap-fit-plate.stl',4)]
    for name in ['assembly-plate.stl','snap-fit-plate.stl']:
        points=[p for tri in mesh_vertices(out/name) for p in tri]
        assert all(5<=p[0]<=251 and 5<=p[1]<=251 for p in points)
        assert not any(p[0]<18 and p[1]<28 for p in points)
    proc=subprocess.run(['bash',str(ROOT/'scripts/freecad_python.sh'),str(Path(__file__).resolve()),'--kernel'],
                        cwd=ROOT,text=True,capture_output=True)
    if proc.returncode:
        raise SystemExit(proc.stdout+proc.stderr)
    solid=json.loads(proc.stdout.strip().splitlines()[-1])
    for mesh in meshes:
        name=mesh['file']
        expected=solid['printed_parts'].get(name)
        if expected:
            volume=expected['volume_mm3']
            assert max(abs(mesh['bounds_mm'][i][j]-expected['bounds_mm'][i][j])
                       for i in range(2) for j in range(3))<0.05,f'STL/CAD bounds mismatch: {name}'
        else:
            volume=solid['assembly_plate_volume_mm3' if name=='assembly-plate.stl' else 'trial_plate_volume_mm3']
        assert abs(mesh['volume_mm3']-volume)<max(0.15,volume*0.001),f'STL/CAD volume mismatch: {name}'
    sources=['cad/parameters.json','cad/snap-parameters.json','cad/build_calibration.py',
             'cad/build_snap_retainer.py','cad/band_geometry.py','scripts/check_snap_retainer.py']
    report={'result':'pass','scope':'digital geometry only; physical snap force and performance unverified',
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources},
            'artifact_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.stl'))},
            'native_artifact_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
               for name in ['cad/snap-retainer-print.FCStd','cad/snap-retainer-assembly.FCStd',
                            'exports/snap-retainer/assembly-plate.step','exports/snap-retainer/manifest.json']},
            'meshes':meshes,'solid_assembly':solid}
    (ROOT/'docs/evidence/snap-retainer/geometry-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'PASS: {len(meshes)} STL files; six assembly components; two inner clips; 33 motion poses.')
    print('Physical snap force, elastic recovery, strength and durability: NOT TESTED.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--kernel',action='store_true')
    main(parser.parse_args().kernel)
