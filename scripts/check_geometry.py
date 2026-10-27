"""Inspect exported meshes and the actual solid assembly, not just filenames.

The normal Python entry point invokes the FreeCAD kernel using the local launcher.
No printer, cloud account or network connection is used.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def mesh_vertices(path):
    data=path.read_bytes()
    if len(data)>=84 and 84+50*struct.unpack_from('<I',data,80)[0]==len(data):
        return [[struct.unpack_from('<3f',data,84+i*50+12+j*12) for j in range(3)]
                for i in range(struct.unpack_from('<I',data,80)[0])]
    pts=[tuple(map(float,line.split()[1:4])) for line in data.decode().splitlines()
         if line.strip().startswith('vertex ')]
    assert len(pts)%3==0, f'Broken STL: {path}'
    return [pts[i:i+3] for i in range(0,len(pts),3)]


def inspect_mesh(path, expected_components=1):
    tris=mesh_vertices(path)
    assert tris, f'Empty mesh: {path}'
    edges=Counter()
    directed=Counter()
    area_min=float('inf')
    volume=0
    verts=set()
    parent={}
    def find(v):
        parent.setdefault(v,v)
        while parent[v]!=v:
            parent[v]=parent[parent[v]]
            v=parent[v]
        return v
    for tri in tris:
        assert all(math.isfinite(c) for v in tri for c in v), f'Nonfinite: {path}'
        a,b,c=tri
        ab=[b[i]-a[i] for i in range(3)]
        ac=[c[i]-a[i] for i in range(3)]
        cross=[ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]]
        area=math.sqrt(sum(x*x for x in cross))/2
        area_min=min(area_min,area)
        assert area>1e-9, f'Degenerate triangle: {path}'
        volume+=sum(a[i]*[b[1]*c[2]-b[2]*c[1],b[2]*c[0]-b[0]*c[2],b[0]*c[1]-b[1]*c[0]][i] for i in range(3))/6
        q=[tuple(round(v,5) for v in p) for p in tri]
        verts.update(q)
        for i in range(3):
            x,y=q[i],q[(i+1)%3]
            edges[tuple(sorted((x,y)))]+=1
            directed[(x,y)]+=1
            px,py=find(x),find(y)
            parent[px]=py
    assert all(n==2 for n in edges.values()), f'Open/nonmanifold mesh: {path}'
    assert all(directed[(a,b)]==directed[(b,a)] for a,b in edges), f'Inconsistent winding: {path}'
    components=len({find(v) for v in verts})
    assert components==expected_components, f'{path}: {components} components, expected {expected_components}'
    assert volume>0, f'Nonpositive volume: {path}'
    lo=[min(p[i] for p in verts) for i in range(3)]
    hi=[max(p[i] for p in verts) for i in range(3)]
    assert abs(lo[2])<1e-4, f'Mesh does not sit on build plate: {path}, z={lo[2]}'
    assert all(hi[i]-lo[i]<246 for i in range(3)), f'No printer margin: {path}'
    return {'file':path.name,'triangles':len(tris),'components':components,
            'volume_mm3':round(volume,3),'bounds_mm':[lo,hi],
            'min_triangle_area_mm2':area_min}


def kernel_check():
    # Import the same editable geometry, but independently measure intersections,
    # surface positions, rotation limits, and floor clearance of the resulting BReps.
    sys.path.insert(0,str(ROOT/'cad'))
    import FreeCAD as App
    import Part
    import Mesh
    import build_calibration as cad
    p=cad.P
    left,right=cad.make_half(True),cad.make_half(False)
    for s in [left,right]:
        assert s.isValid() and len(s.Solids)==1
        s.check(True)
    # Measure the actual mating annular faces, including their material overlap
    # in X/Z, rather than trusting the clearance parameter or overall bounds.
    hinge_end_gaps=[]
    for end, left_y, right_y in [('front',8,8+p['axial_clearance']),
                                 ('rear',p['depth']-8,p['depth']-8-p['axial_clearance'])]:
        mating=[]
        for body,y in [(left,left_y),(right,right_y)]:
            point=Part.Vertex(App.Vector(0,y,5))
            faces=[face for face in body.Faces if face.BoundBox.YLength<1e-6
                   and face.distToShape(point)[0]<1e-6]
            assert len(faces)==1,f'Missing {end} hinge mating face'
            mating.append(faces[0])
        measured=mating[0].distToShape(mating[1])[0]
        assert abs(measured-p['axial_clearance'])<1e-6,f'{end} hinge end gap is {measured}'
        hinge_end_gaps.append({'end':end,'measured_gap_mm':measured})
    long_edge_fillets=[face for face in left.Faces
                       if isinstance(face.Surface,Part.Cylinder)
                       and abs(face.Surface.Radius-p['outer_edge_fillet'])<1e-5
                       and face.BoundBox.YLength>p['depth']-3]
    assert len(long_edge_fillets)>=3,'Requested perimeter fillets are missing'
    capsule_hooks=[]
    for x in p['hook_x']:
        mid_y=(p['hook_mount_y']+p['hook_neck_end_y'])/2
        assert left.isInside(App.Vector(-x,mid_y,p['hook_z']),1e-6,True), 'Reversed shaft missing'
        assert not left.isInside(App.Vector(-x,-1,p['hook_z']),1e-6,True), 'Hook points out of front'
        tip=Part.Vertex(App.Vector(-x,p['hook_head_end_y'],p['hook_z']))
        assert left.distToShape(tip)[0]<1e-6,'Hook tip not at the back face'
        hook=cad.make_hook(-x)
        assert hook.isValid() and len(hook.Solids)==1,'Disconnected capsule hook'
        bounds=hook.optimalBoundingBox(False)
        span,radius=p['hook_capsule_half_span'],p['hook_neck_radius']
        section=Part.Face(hook.slice(App.Vector(0,1,0),mid_y)[0])
        expected_area=4*span*radius+math.pi*radius**2
        assert abs(section.Area-expected_area)<1e-5,'Capsule neck section is incomplete'
        assert abs(section.BoundBox.XLength-2*(span+radius))<1e-5
        assert abs(section.BoundBox.ZLength-2*radius)<1e-5
        assert abs(bounds.XLength-2*(span+p['hook_head_radius']))<1e-5
        assert abs(bounds.ZLength-2*p['hook_head_radius'])<1e-5
        # Every part of the neck AND the head's projected outline must have
        # backing behind it. The previous half-supported capsule fails here.
        probe=cad.capsule(radius,span,p['hook_mount_y']-0.01,0.01,-x,p['hook_z'])
        root_area=probe.common(left).Volume/0.01
        assert probe.cut(left).Volume<1e-7,'Capsule neck overhangs the crossbar'
        assert abs(root_area-expected_area)<1e-5,'Neck is not fully backed'
        head_projection=cad.capsule(p['hook_head_radius'],span,
                                    p['hook_mount_y']-0.01,0.01,-x,p['hook_z'])
        assert head_projection.cut(left).Volume<1e-7,'Backing does not cover the capsule head outline'
        capsule_hooks.append({'neck_width_mm':section.BoundBox.XLength,
                              'neck_height_mm':section.BoundBox.ZLength,
                              'neck_section_mm2':section.Area,
                              'head_width_mm':bounds.XLength,'head_height_mm':bounds.ZLength,
                              'head_thickness_mm':p['hook_head_end_y']-p['hook_neck_end_y'],
                              'bonded_root_area_mm2':root_area,
                              'neck_fully_backed':True,
                              'head_projection_fully_backed':True,
                              'capsule_coverage_width_mm':2*(span+p['hook_head_radius']+p['hook_backing_margin']),
                              'capsule_coverage_height_mm':2*(p['hook_head_radius']+p['hook_backing_margin'])})
    for x in [-20,-15,-10,-7]:
        assert not left.isInside(App.Vector(x,16,-14),1e-6,True),'Unwanted lower hook platform remains'
    assert left.isInside(App.Vector(-20,2,-10.8),1e-6,True),'Leg-to-backing notch remains'
    assert not left.isInside(App.Vector(-30,2,-18),1e-6,True),'Backing creates an outboard pointed wing'
    assert left.isInside(App.Vector(-16,2,-6.5),1e-6,True),'Diagonal support root is missing'
    assert left.isInside(App.Vector(-14.7,2,-11),1e-6,True),'Widened backing does not reach capsule outer end'
    assert left.isInside(App.Vector(-17.6,2,-14),1e-6,True),'Continuous lower backing transition is missing'
    backing=cad.make_hook_backing(-p['hook_x'][0])
    curves=[e for e in backing.Edges if isinstance(e.Curve,Part.BSplineCurve)
            and e.BoundBox.YLength<1e-6 and abs(e.BoundBox.YMin)<1e-6]
    assert len(curves)==2,'Continuous backing transition curves are missing'
    leg_curve=min(curves,key=lambda e:e.BoundBox.XMin)
    tangent=leg_curve.tangentAt(leg_curve.FirstParameter)
    slope=(p['foot_drop']-3)/(p['foot_x']-25)
    assert abs(tangent.z/tangent.x-slope)<1e-6,'Backing is not tangent to the leg slope'
    assert abs(leg_curve.tangentAt(leg_curve.LastParameter).z)<1e-6,'Lower backing does not join the flat smoothly'
    common=[]
    floor=[]
    laptop_contacts=[]
    band_clearances=[]
    backing_floor_clearances=[]
    backings=[cad.make_hook_backing(-x) for x in p['hook_x']]
    for side in [left,right]:
        assert side.BoundBox.YMin>=-1e-6 and side.BoundBox.YMax<=p['depth']+1e-6, 'Front hook protrusion remains'
        assert abs(side.BoundBox.YLength-p['depth'])<1e-6, 'Stand width differs from requested depth'
    for i in range(33):
        angle=p['sample_loaded_angle_deg']*i/32
        a=cad.assembly_pose(left,angle,True)
        b=cad.assembly_pose(right,angle,False)
        volume=a.common(b).Volume
        common.append(volume)
        floor.append(min(a.BoundBox.ZMin,b.BoundBox.ZMin))
        for backing in backings:
            clearance=cad.assembly_pose(backing,angle,True).optimalBoundingBox(False).ZMin
            assert clearance>1.0,'Capsule backing is too close to the floor'
            backing_floor_clearances.append(clearance)
        theta=math.radians(angle)
        h=p['foot_drop']*math.cos(theta)-(p['foot_x']-12)*math.sin(theta)
        half=p['laptop_thickness']/2
        seat=h+9/math.cos(theta)+half*math.tan(theta)
        laptop=Part.makeBox(p['laptop_thickness'],p['depth'],100,
                            App.Vector(-half,0,seat))
        for body in [a,b]:
            assert body.common(laptop).Volume<1e-5, f'Laptop collides with stop or body at {angle}'
        distances=[s.distToShape(laptop)[0] for s in [a,b]]
        assert max(distances)<1e-5, f'Laptop not seated on both cradles: {distances}'
        laptop_contacts.append({'angle_deg':angle,'seat_height_mm':seat,'shelf_distances_mm':distances})
        axle=cad.make_pin()
        axle.translate(App.Vector(0,0,h))
        for index in range(len(p['hook_x'])):
            points=cad.band_path(index,angle)
            wire=Part.makePolygon(points)
            distances=[wire.distToShape(body)[0] for body in [a,b,axle]]
            clearance=min(distances)-p['band_wire_radius']
            assert clearance>0.05, f'Internal band collides at {angle} deg / pair {index}: {clearance}'
            assert min(pt.z for pt in points)>p['band_wire_radius']+1, 'Band too near floor'
            assert min(pt.y for pt in points)>p['band_wire_radius'], 'Band protrudes at front'
            assert max(pt.y for pt in points)<p['depth']-p['band_wire_radius'], 'Band protrudes at back'
            band_clearances.append(clearance)
    assert max(common)<1e-5, f'Body interference: {max(common)} mm3'
    assert min(floor)>-1e-5, f'Floor interference: {min(floor)} mm'
    outside=[]
    for angle in [-0.1,-2]:
        a=cad.assembly_pose(left,angle,True)
        b=cad.assembly_pose(right,angle,False)
        overlap=a.common(b).Volume
        assert overlap>0.01, f'No physical rotation stop at {angle} deg'
        outside.append({'angle_deg':angle,'stop_overlap_mm3':overlap})
    # Solid intersections intentionally omit touching boundary faces; intersect
    # the two actual under-axis X=0 boundary faces to measure their contact patch.
    faces=[]
    for body in [left,right]:
        matching=[f for f in body.Faces if abs(f.BoundBox.XMin)<1e-7
                  and abs(f.BoundBox.XMax)<1e-7 and f.BoundBox.ZMax<0]
        assert len(matching)==1,'Missing integral stop face'
        faces.append(matching[0])
    shoulder_contact=faces[0].common(faces[1])
    expected_area=(p['opening_stop_top_z']-p['opening_stop_bottom_z'])*p['opening_stop_depth']
    assert abs(shoulder_contact.Area-expected_area)<1e-5, 'Lower stop faces do not mate fully'
    assert shoulder_contact.BoundBox.ZMax<0, 'Opening stop must be below the joint'
    # There is no separate closing limiter. Past the nominal laptop pose the
    # empty mechanism must remain free; the real device/pads establish contact.
    extra_angle=p['sample_loaded_angle_deg']+2
    extra_a=cad.assembly_pose(left,extra_angle,True)
    extra_b=cad.assembly_pose(right,extra_angle,False)
    assert extra_a.common(extra_b).Volume<1e-5,'Unwanted closing stop remains'
    extra_wire=Part.makePolygon(cad.band_path(0,extra_angle))
    extra_band_clearance=min(extra_wire.distToShape(s)[0] for s in [extra_a,extra_b])-p['band_wire_radius']
    assert extra_band_clearance>0.05,'Capsule band catches the body beyond the sample loaded pose'
    # Verify JSON dimensions correspond to material on the exported bodies.
    for point in [(-p['foot_x']+12,16,-p['foot_drop']),
                  (-p['wall_inner_x']-0.4,16,p['wall_top'])]:
        dist=left.distToShape(Part.Vertex(App.Vector(*point)))[0]
        assert dist<1e-6, f'Parameter/solid mismatch at {point}: {dist}'
    axle=cad.make_pin()
    for angle in [0,p['sample_loaded_angle_deg']]:
        for body,sign in [(left,1),(right,-1)]:
            moving=body.copy()
            moving.rotate(App.Vector(0,0,0),App.Vector(0,1,0),angle*sign)
            assert moving.common(axle).Volume<1e-5, 'Axle blocked by a later solid addition'
    self_intersections=[]
    for path in sorted((ROOT/'exports/calibration').glob('*.stl')):
        m=Mesh.Mesh(str(path))
        if hasattr(m,'hasSelfIntersections'):
            assert not m.hasSelfIntersections(), f'Mesh self intersections: {path}'
            self_intersections.append(path.name)
    layout=App.openDocument(str(ROOT/'cad/calibration.FCStd'))
    layout_labels=[obj.Label for obj in layout.Objects if hasattr(obj,'Shape')]
    assert set(layout_labels)=={'mechanism-left','mechanism-right','axle-6mm','axle-key'}, 'Optional fit rings remain in the assembly CAD collection'
    App.closeDocument(layout.Name)
    step_layout=Part.Shape()
    step_layout.read(str(ROOT/'exports/calibration/calibration.step'))
    assert len(step_layout.Solids)==4,'Optional fit rings remain in the assembly STEP collection'
    # The main axle inserts parallel to Y after the two bodies mate.
    insertion=[]
    for i in range(81):
        moving=right.copy()
        moving.translate(App.Vector(40*(80-i)/80,0,0))
        assert moving.common(left).Volume<1e-5,'Bodies cannot mate with pins removed'
    for name,pin,delta in [('main',cad.make_pin(),-1)]:
        for step in range(41):
            offset=delta*(p['depth']+8)*(40-step)/40
            moving=pin.copy()
            moving.translate(App.Vector(0,offset,0))
            volume=moving.common(left).Volume+moving.common(right).Volume
            assert volume<1e-5,f'{name} pin has blocked insertion at {offset}mm: {volume}'
        insertion.append(name)
    for which in ['main']:
        key=cad.key_in_assembly()
        assert abs(key.optimalBoundingBox(False).XLength-10)<1e-6,'End cap must have 10mm diameter'
        vertices,_=key.tessellate(0.03)
        assert max(math.hypot(v.x,v.z) for v in vertices)<5.0001,'Hidden key protrudes beyond cap outline'
        for i in range(41):
            moving=key.copy()
            moving.translate(App.Vector(-(40-i),0,0))
            bodies=[left,right,cad.make_pin()]
            overlap=sum(moving.common(b).Volume for b in bodies)
            assert overlap<1e-5,f'{which} key has blocked insertion at {40-i}mm: {overlap}'
        insertion.append(which+'-key')
    # With the tongue seated in the axle slot, the hidden shoulders must catch
    # the back bearing when pulled toward the front. Front flange catches reverse motion.
    locked=Part.makeCompound([cad.make_pin(),cad.key_in_assembly()])
    locked.translate(App.Vector(0,-1.2,0))
    rear_catch=sum(locked.common(body).Volume for body in [left,right])
    assert rear_catch>0.01,'Concealed retainer does not prevent axle withdrawal'
    pin=cad.make_pin()
    pin.translate(App.Vector(0,0.3,0))
    assert pin.common(left).Volume>0.01,'Front flange does not retain axle'
    return {'max_body_overlap_mm3':max(common), 'minimum_floor_clearance_mm':min(floor),
            'hinge_end_face_gaps':hinge_end_gaps,
            'pose_samples':len(common),'physical_stop_checks':outside,
            'opening_stop_contact_area_mm2':shoulder_contact.Area,
            'opening_stop_contact_bounds':str(shoulder_contact.BoundBox),
            'no_closing_limiter_check_deg':extra_angle,
            'extra_pose_band_surface_clearance_mm':extra_band_clearance,
            'internal_band_paths_checked':len(band_clearances),
            'minimum_band_surface_clearance_mm':min(band_clearances),
            'hook_direction':[0,1,0],
            'hook_mount_y_mm':p['hook_mount_y'],
            'hook_tip_y_mm':p['hook_head_end_y'],
            'capsule_hooks':capsule_hooks,
            'minimum_backing_floor_clearance_mm':min(backing_floor_clearances),
            'lower_hook_platform_removed':True,
            'pointed_hook_wings_removed':True,
            'hook_support_style':'continuous leg-to-backing outline with tangent Bezier transitions',
            'backing_transition_curve_count':len(curves),
            'outer_edge_fillet_radius_mm':p['outer_edge_fillet'],
            'long_perimeter_fillet_faces':len(long_edge_fillets),
            'stand_front_to_back_width_mm':left.BoundBox.YLength,
            'retainer_style':'concealed tongue inside round end cap',
            'retainer_cap_diameter_mm':key.optimalBoundingBox(False).XLength,
            'retainer_rear_catch_overlap_mm3':rear_catch,
            'laptop_contacts':laptop_contacts,'pin_insertion_paths_checked':insertion,
            'mesh_self_intersections_checked':self_intersections}


def motion_check(p):
    sys.path.insert(0,str(ROOT/'cad'))
    from band_geometry import band_centerline
    rows=[]
    for i in range(33):
        angle=p['sample_loaded_angle_deg']*i/32
        t=math.radians(angle)
        h=p['foot_drop']*math.cos(t)-(p['foot_x']-12)*math.sin(t)
        # Inner face ends, after the 0.4mm-deep felt pocket; pad proud = 0.6mm.
        pad_proud=p['felt_thickness']-0.4
        gap=2*((p['wall_inner_x']-pad_proud)*math.cos(t)-p['wall_top']*math.sin(t))
        hook_clearance=min(h+x*math.sin(t)+p['hook_z']*math.cos(t)-p['hook_head_radius']
                           -p['hook_capsule_half_span']*abs(math.sin(t))
                           for x in p['hook_x'])
        spans=[2*(x*math.cos(t)-p['hook_z']*math.sin(t)) for x in p['hook_x']]
        # A horizontal inward force F at a left anchor gives tau_y=z*F (<0),
        # opposite the left body's positive closing rotation. Unit force is enough
        # to check sign; stiffness/preload and friction remain physically unmeasured.
        torque_per_newton=[x*math.sin(t)+p['hook_z']*math.cos(t) for x in p['hook_x']]
        paths=[band_centerline(p,i,angle) for i in range(len(p['hook_x']))]
        band_lengths=[sum(math.dist(a,b) for a,b in zip(path,path[1:])) for path in paths]
        assert all(x<0 for x in torque_per_newton), 'Band torque reversed'
        assert hook_clearance>1.0, f'Insufficient lower-hook clearance: {hook_clearance}'
        rows.append({'angle_deg':angle,'hinge_height_mm':h,'felt_gap_mm':gap,
                     'hook_clearance_mm':hook_clearance,'band_spans_mm':spans,
                     'band_path_lengths_mm':band_lengths,
                     'opening_torque_mm_per_N':torque_per_newton})
    for a,b in zip(rows,rows[1:]):
        assert b['hinge_height_mm']<a['hinge_height_mm']
        assert b['felt_gap_mm']<a['felt_gap_mm']
        assert all(y>x for x,y in zip(a['band_spans_mm'],b['band_spans_mm']))
        assert all(y>x for x,y in zip(a['band_path_lengths_mm'],b['band_path_lengths_mm'])), 'Capsule band does not restore opening'
    assert rows[0]['felt_gap_mm']>p['laptop_thickness']>rows[-1]['felt_gap_mm']
    # Cradle face x=-10,z=9: downward force causes closing, and the face descends.
    rows0=9+p['foot_drop']
    t=math.radians(p['sample_loaded_angle_deg'])
    rows1=10*math.sin(t)+9*math.cos(t)+rows[-1]['hinge_height_mm']
    assert rows1<rows0
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',choices=['calibration','stand'],required=True)
    parser.add_argument('--kernel',action='store_true')
    args=parser.parse_args()
    if args.target=='stand':
        raise SystemExit('Full stand is waiting for physical calibration feedback; no success result is available.')
    if args.kernel:
        print(json.dumps(kernel_check()))
        return
    out=ROOT/'exports/calibration'
    manifest=json.loads((out/'manifest.json').read_text())
    checks=[inspect_mesh(out/p['file']) for p in manifest['parts']]
    checks += [inspect_mesh(out/'calibration-plate.stl',4),inspect_mesh(out/'fit-plate.stl',5)]
    # Fixed plate placement is measured from the actual STL, including the excluded
    # front-left X1C rectangle (x<18,y<28) and a 5mm edge margin.
    for filename in ['calibration-plate.stl','fit-plate.stl']:
        tris=mesh_vertices(out/filename)
        points=[p for tri in tris for p in tri]
        assert all(5<=p[0]<=251 and 5<=p[1]<=251 for p in points)
        assert not any(p[0]<18 and p[1]<28 for p in points), 'X1C excluded region'
    p=json.loads((ROOT/'cad/parameters.json').read_text())
    motion=motion_check(p)
    proc=subprocess.run(['bash',str(ROOT/'scripts/freecad_python.sh'),str(Path(__file__).resolve()),
                         '--target','calibration','--kernel'],cwd=ROOT,text=True,capture_output=True)
    if proc.returncode:
        raise SystemExit(proc.stdout+proc.stderr)
    solid=json.loads(proc.stdout.strip().splitlines()[-1])
    for name,expected in [('body-original.stl','f7671db9738a397e7554e37b29e71e9952b0535ff57e6514d50c0abb74338316'),
                          ('connector-original.stl','e8e561727ff7b86b839c156620de23dbdaed1f730be9b08e3b653d288fde108c')]:
        assert hashlib.sha256((ROOT/'references'/name).read_bytes()).hexdigest()==expected
    report={'result':'pass','scope':'digital calibration geometry only; physical performance unverified',
            'parameters_sha256':hashlib.sha256((ROOT/'cad/parameters.json').read_bytes()).hexdigest(),
            'generator_sha256':hashlib.sha256((ROOT/'cad/build_calibration.py').read_bytes()).hexdigest(),
            'band_geometry_sha256':hashlib.sha256((ROOT/'cad/band_geometry.py').read_bytes()).hexdigest(),
            'artifact_sha256':{f.name:hashlib.sha256(f.read_bytes()).hexdigest()
                               for f in sorted(out.glob('*.stl'))},
            'meshes':checks,'solid_assembly':solid,'motion':motion}
    (ROOT/'docs/evidence/geometry-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'PASS: {len(checks)} STL files; {len(motion)} motion poses; solid interference and stop checks passed.')
    print('Physical fit, friction, force balance and durability: NOT TESTED.')


if __name__=='__main__':
    main()
