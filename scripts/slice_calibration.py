"""Resolve Bambu's shipped profile inheritance and slice locally, without printing."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
APP=Path('/Applications/BambuStudio.app/Contents')
PROFILES=APP/'Resources/profiles/BBL'
OUT=ROOT/'exports/calibration'


def clip_support_moves(gcode,kit):
    """Count actual support extrusion endpoints in isolated clip footprints."""
    origins=[(175,58),(193,58)] if kit=='snap-retainer' else [(120,34)]
    feature='';relative=True;last_e=0.0;x=y=0.0;count=0
    for raw in gcode.splitlines():
        if raw.startswith('; FEATURE: '):
            feature=raw[11:].strip()
        code=raw.split(';',1)[0].strip()
        if code=='M83': relative=True
        if code=='M82': relative=False
        values={k:float(value) for k,value in re.findall(r'([XYE])(-?\d+(?:\.\d+)?)',code)}
        if code.startswith('G92') and 'E' in values:
            last_e=values['E'];continue
        if not re.match(r'^G[01](?:\s|$)',code):
            continue
        x=values.get('X',x);y=values.get('Y',y)
        delta=values.get('E',0) if relative else values.get('E',last_e)-last_e
        if 'E' in values: last_e=values['E']
        if delta>1e-8 and feature.startswith('Support'):
            if any(px<=x<=px+9.13 and py<=y<=py+10.01 for px,py in origins):
                count+=1
    return count


def support_moves(gcode):
    """Count support extrusion moves anywhere on the plate."""
    feature='';count=0
    for raw in gcode.splitlines():
        if raw.startswith('; FEATURE: '):
            feature=raw[11:].strip()
        code=raw.split(';',1)[0].strip()
        if feature.startswith('Support') and re.match(r'^G[01]\s.*E\d*\.?\d+',code):
            count+=1
    return count


def profile(name,kind,stack=()):
    assert name not in stack, f'Profile cycle: {name}'
    path=PROFILES/kind/(name+'.json')
    raw=json.loads(path.read_text())
    data={}
    if raw.get('inherits'):
        data.update(profile(raw['inherits'],kind,(*stack,name)))
    for include in raw.get('include',[]):
        data.update(profile(include,kind,(*stack,name)))
    data.update(raw)
    data.pop('inherits',None)
    data.pop('include',None)
    return data


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kit',choices=['fit','mechanism','snap-retainer','snap-fit','print-in-place','print-in-place-trial'],required=True)
    args=parser.parse_args()
    snap=args.kit.startswith('snap-')
    in_place=args.kit.startswith('print-in-place')
    model_root=ROOT/'exports/snap-retainer' if snap else OUT
    if in_place:
        model_root=ROOT/'exports/print-in-place'
        model='assembly-plate.stl' if args.kit=='print-in-place' else 'hinge-trial.stl'
        output=model_root/('sliced-assembly' if args.kit=='print-in-place' else 'sliced-trial')
    elif snap:
        model='assembly-plate.stl' if args.kit=='snap-retainer' else 'snap-fit-plate.stl'
        output=model_root/('sliced-assembly' if args.kit=='snap-retainer' else 'sliced-fit')
    else:
        model='fit-plate.stl' if args.kit=='fit' else 'calibration-plate.stl'
        output=OUT/f'sliced-{args.kit}'
    output.mkdir(exist_ok=True,parents=True)
    machine=profile('Bambu Lab X1 Carbon 0.4 nozzle','machine')
    process=profile('0.20mm Strength @BBL X1C','process')
    filament=profile('Generic PLA','filament')
    process.update({'enable_support':'1',
                    'support_type':'normal(auto)','support_on_build_plate_only':'0',
                    'brim_type':'outer_only','brim_width':'3','brim_object_gap':'0.15',
                    'skirt_loops':'0'})
    if in_place:
        # Support inside an assembled hinge could never be removed.
        process['enable_support']='0'
    machine['curr_bed_type']='Textured PEI Plate'
    for name,data in [('machine',machine),('process',process),('filament',filament)]:
        (output/f'{name}.json').write_text(json.dumps(data,indent=2)+'\n')
    assert float(filament['filament_density'][0])>1
    assert machine.get('machine_start_gcode'), 'Unresolved start gcode template'
    command=[str(APP/'MacOS/BambuStudio'),'--debug','2',
             '--load-settings',str(output/'machine.json')+';'+str(output/'process.json'),
             '--load-filaments',str(output/'filament.json'),
             '--arrange','0','--orient','0','--slice','0',
             '--export-3mf',f'{args.kit}-x1c-pla.3mf',
             '--outputdir',str(output),str(model_root/model)]
    proc=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    (output/'slicer.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode:
        raise SystemExit(proc.stdout+proc.stderr)
    result=json.loads((output/'result.json').read_text())
    assert result['return_code']==0,result
    gcode=(output/'plate_1.gcode').read_text()
    assert '; filament_density: 0' not in gcode
    assert '; machine_start_gcode = \n' not in gcode
    if in_place:
        result['enable_support']=process['enable_support']
        result['support_extrusions']=support_moves(gcode)
        assert result['support_extrusions']==0,'Support was generated on a print-in-place plate'
    if snap:
        result['clip_region_support_extrusions']=clip_support_moves(gcode,args.kit)
        assert result['clip_region_support_extrusions']==0,'Support was generated under a flat clip'
    if snap or in_place:
        result['input_stl_sha256']=hashlib.sha256((model_root/model).read_bytes()).hexdigest()
        result['profile_sha256']={name:hashlib.sha256((output/f'{name}.json').read_bytes()).hexdigest()
                                  for name in ['machine','process','filament']}
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
