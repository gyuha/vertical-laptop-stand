"""Validate the print-in-place hinge from the actual CAD and the exported meshes."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'exports/print-in-place'


def kernel_check():
    sys.path.insert(0,str(ROOT/'cad'))
    import FreeCAD as App
    import Part
    import build_print_in_place as cad
    p,n=cad.P,cad.N
    v=App.Vector
    left,right=cad.make_half(True),cad.make_half(False)
    for body in [left,right]:
        assert body.isValid() and len(body.Solids)==1
        body.check(True)
    # Walk the axis: knuckles alternate with real gaps, and no through-hole or
    # separate axle remains (every sample is left, right or a short gap).
    owners=[]
    for i in range(int(p['depth']/0.05)+1):
        y=i*0.05
        a=left.isInside(v(0,y,0),1e-7,True)
        b=right.isInside(v(0,y,0),1e-7,True)
        assert not (a and b),f'Bodies overlap on the axis at Y={y}'
        owner='L' if a else 'R' if b else '-'
        if not owners or owners[-1][0]!=owner:
            owners.append([owner,y,y])
        owners[-1][2]=y
    assert [o[0] for o in owners]==['L','-','R','-','L'],f'Unexpected axis layout {owners}'
    axis_gaps=[o[2]-o[1]+0.05 for o in owners if o[0]=='-']
    assert all(g<1.0 for g in axis_gaps),'Axis gap too long: pin or socket missing'
    zone_radius=6.9  # inside the opening stops (radius >= 7)
    joints=[]
    for lower,upper in cad.joints():
        zone=Part.makeCylinder(zone_radius,16,v(0,lower-6,0),v(0,1,0))
        a,b=left.common(zone),right.common(zone)
        def faces(shape,kind):
            return [f for f in shape.Faces if isinstance(f.Surface,kind)]
        cones=min(f.distToShape(g)[0] for f in faces(a,Part.Cone) for g in faces(b,Part.Cone))
        cylinders=[(f,round(f.Surface.Radius,3)) for f in faces(a,Part.Cylinder)+faces(b,Part.Cylinder)]
        pins=[f for f,r in cylinders if abs(r-cad.RP)<1e-3]
        sockets=[f for f,r in cylinders if abs(r-cad.RH)<1e-3]
        assert len(pins)==1 and len(sockets)==1,'Pin or socket wall missing'
        radial=pins[0].distToShape(sockets[0])[0]
        minimum=a.distToShape(b)[0]
        assert abs(cones-n['cone_normal_gap'])<1e-6,f'Cone normal gap {cones}'
        assert abs(radial-n['radial_clearance'])<1e-6,f'Radial gap {radial}'
        assert minimum>n['radial_clearance']-1e-6,f'Hinge minimum gap {minimum}'
        # Overhang risk the facet check cannot see: where the upper knuckle's
        # first cone ring has no own material just outside and below it.
        upper_body=right if lower==cad.joints()[0][0] else left
        unsupported=0
        for k in range(180):
            phi=math.radians(2*k)
            point=v(6.2*math.cos(phi),upper-0.1,6.2*math.sin(phi))
            if not upper_body.isInside(point,1e-7,True):
                unsupported+=2
        joints.append({'lower_rim_mm':lower,'upper_rim_mm':upper,
                       'cone_normal_gap_mm':cones,'pin_socket_radial_gap_mm':radial,
                       'minimum_gap_mm':minimum,'upper_rim_unsupported_arc_deg':unsupported})
    # Exact BRep test: in print orientation +Y is up, so no face inside the
    # hinge radius may face down more steeply than 45 degrees (bed face aside).
    zone=Part.makeCylinder(cad.OUTER+0.05,p['depth'],v(0,0,0),v(0,1,0))
    steepest=0.0
    for body in [left,right]:
        for face in body.common(zone).Faces:
            if face.BoundBox.YMax<0.05:
                continue
            u0,u1,w0,w1=face.ParameterRange
            for i in range(7):
                for j in range(7):
                    uv=(u0+(u1-u0)*i/6,w0+(w1-w0)*j/6)
                    if face.isInside(face.valueAt(*uv),1e-6,True):
                        steepest=min(steepest,face.normalAt(*uv).y)
    assert steepest>=-math.sqrt(0.5)-1e-6,f'Hinge face steeper than 45 degrees: normal y {steepest}'
    motion=[]
    angles=[-2,-0.1]+[i*0.5 for i in range(21)]+[10.2]
    for angle in angles:
        a,b=cad.posed([left,right],angle)
        overlap=a.common(b).Volume
        if angle<0:
            assert overlap>1e-3,f'Opening stop does not engage at {angle}'
        else:
            assert overlap<1e-6,f'Interference {overlap} at {angle}'
        motion.append({'angle_deg':angle,'overlap_mm3':overlap})
    a,b=cad.posed([left,right],n['print_angle_deg'])
    print_gap=a.distToShape(b)[0]
    assert print_gap>n['radial_clearance']-1e-6,f'Print pose gap {print_gap}'
    stops=Part.makeBox(3.2,p['opening_stop_depth'],p['opening_stop_top_z']-p['opening_stop_bottom_z'],
                     v(-1.6,0,p['opening_stop_bottom_z']))
    lo,hi=cad.posed([left.common(stops),right.common(stops)],n['print_angle_deg'])
    stop_gap=lo.distToShape(hi)[0]
    assert stop_gap>1.0,f'Opening stops too close in print pose: {stop_gap}'
    # A vertex on the posed hinge axis is carried through the plate transform
    # to locate the axis in print XY for the mesh overhang check.
    t=math.radians(n['print_angle_deg'])
    axis=Part.Vertex(v(0,0,p['foot_drop']*math.cos(t)-(p['foot_x']-12)*math.sin(t)))
    plate=cad.print_transform([a,b,axis],n['plate_origin'])
    trial=cad.print_transform(cad.posed([cad.trial_half(left,True),cad.trial_half(right,False)],
                                        n['print_angle_deg'])+[axis],n['trial_origin'])
    return {'joints':joints,'axis_layout':owners,'motion':motion,
            'hinge_brep_min_upward_normal':steepest,
            'print_pose_minimum_gap_mm':print_gap,'print_pose_stop_gap_mm':stop_gap,
            'plate_volume_mm3':plate[0].Volume+plate[1].Volume,
            'trial_volume_mm3':trial[0].Volume+trial[1].Volume,
            'plate_axis_xy':[plate[2].Point.x,plate[2].Point.y],
            'trial_axis_xy':[trial[2].Point.x,trial[2].Point.y]}


def downward_area(path,axis,radius):
    from check_geometry import mesh_vertices
    hinge=other=0.0
    for a,b,c in mesh_vertices(path):
        ab=[b[i]-a[i] for i in range(3)]
        ac=[c[i]-a[i] for i in range(3)]
        nx,ny,nz=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
        length=math.sqrt(nx*nx+ny*ny+nz*nz)
        centroid=[(a[i]+b[i]+c[i])/3 for i in range(3)]
        # Exact 45 degree cones tessellate into facets up to ~2.1 degrees flatter
        # at the cone/profile seams, so the mesh allows 3 degrees; the BRep check
        # in kernel_check is the exact 45 degree test.
        if nz/length>=-math.cos(math.radians(42)) or centroid[2]<0.05:
            continue
        if math.dist(centroid[:2],axis)<radius+0.05:
            hinge+=length/2
        else:
            other+=length/2
    return hinge,other


def main(kernel=False):
    if kernel:
        print(json.dumps(kernel_check()))
        return
    from check_geometry import inspect_mesh,mesh_vertices
    manifest=json.loads((OUT/'manifest.json').read_text())
    meshes=[inspect_mesh(OUT/'assembly-plate.stl',2),inspect_mesh(OUT/'hinge-trial.stl',2)]
    for name in ['assembly-plate.stl','hinge-trial.stl']:
        points=[q for tri in mesh_vertices(OUT/name) for q in tri]
        assert all(5<=q[0]<=251 and 5<=q[1]<=251 for q in points),f'{name} leaves the X1C bed margin'
        assert not any(q[0]<18 and q[1]<28 for q in points),'X1C excluded region'
    proc=subprocess.run(['bash',str(ROOT/'scripts/freecad_python.sh'),str(Path(__file__).resolve()),'--kernel'],
                        cwd=ROOT,text=True,capture_output=True)
    if proc.returncode:
        raise SystemExit(proc.stdout+proc.stderr)
    solid=json.loads(proc.stdout.strip().splitlines()[-1])
    for mesh,key in zip(meshes,['plate_volume_mm3','trial_volume_mm3']):
        assert abs(mesh['volume_mm3']-solid[key])<solid[key]*0.001,f'STL/CAD volume mismatch: {mesh["file"]}'
    radius=json.loads((ROOT/'cad/print-in-place-parameters.json').read_text())['socket_outer_radius']
    overhang={}
    for name,axis in [('assembly-plate.stl',solid['plate_axis_xy']),('hinge-trial.stl',solid['trial_axis_xy'])]:
        hinge,other=downward_area(OUT/name,axis,radius)
        assert hinge<1e-6,f'{name}: {hinge} mm2 of >45 degree downward faces inside the hinge'
        overhang[name]={'hinge_mm2':hinge,'outside_hinge_mm2':other}
    sources=['cad/parameters.json','cad/print-in-place-parameters.json','cad/build_calibration.py',
             'cad/build_print_in_place.py','cad/band_geometry.py','scripts/check_print_in_place.py']
    report={'result':'pass','scope':'digital geometry only; physical print-in-place release and wear unverified',
            'source_sha256':{s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources},
            'artifact_sha256':{f:hashlib.sha256((OUT/f).read_bytes()).hexdigest() for f in manifest['files']},
            'meshes':meshes,'overhang_over_45deg_mm2':overhang,'solid':solid}
    evidence=ROOT/'docs/evidence/print-in-place'
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'geometry-report.json').write_text(json.dumps(report,indent=2)+'\n')
    gaps=', '.join(f"{j['minimum_gap_mm']:.3f}" for j in solid['joints'])
    arcs=', '.join(str(j['upper_rim_unsupported_arc_deg']) for j in solid['joints'])
    print(f'PASS: 2 plates, 2 bodies each; hinge min gaps {gaps} mm; '
          f'print-pose gap {solid["print_pose_minimum_gap_mm"]:.3f} mm; stop gap {solid["print_pose_stop_gap_mm"]:.2f} mm; '
          f'{len(solid["motion"])} motion poses; hinge downward faces <=45deg (BRep).')
    print(f'Upper rim first-layer ring without own support below: {arcs} deg (print-trial risk).')
    print('Physical release after printing, play and wear: NOT TESTED.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--kernel',action='store_true')
    main(parser.parse_args().kernel)
