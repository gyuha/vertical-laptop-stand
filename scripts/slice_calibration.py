"""Resolve Bambu's shipped profile inheritance and slice locally, without printing."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
APP=Path('/Applications/BambuStudio.app/Contents')
PROFILES=APP/'Resources/profiles/BBL'
OUT=ROOT/'exports/calibration'


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
    parser.add_argument('--kit',choices=['fit','mechanism'],required=True)
    args=parser.parse_args()
    output=OUT/f'sliced-{args.kit}'
    output.mkdir(exist_ok=True,parents=True)
    machine=profile('Bambu Lab X1 Carbon 0.4 nozzle','machine')
    process=profile('0.20mm Strength @BBL X1C','process')
    filament=profile('Generic PLA','filament')
    process.update({'enable_support':'1',
                    'support_type':'normal(auto)','support_on_build_plate_only':'0',
                    'brim_type':'outer_only','brim_width':'3','brim_object_gap':'0.15',
                    'skirt_loops':'0'})
    machine['curr_bed_type']='Textured PEI Plate'
    for name,data in [('machine',machine),('process',process),('filament',filament)]:
        (output/f'{name}.json').write_text(json.dumps(data,indent=2)+'\n')
    assert float(filament['filament_density'][0])>1
    assert machine.get('machine_start_gcode'), 'Unresolved start gcode template'
    model='fit-plate.stl' if args.kit=='fit' else 'calibration-plate.stl'
    command=[str(APP/'MacOS/BambuStudio'),'--debug','2',
             '--load-settings',str(output/'machine.json')+';'+str(output/'process.json'),
             '--load-filaments',str(output/'filament.json'),
             '--arrange','0','--orient','0','--slice','0',
             '--export-3mf',f'{args.kit}-x1c-pla.3mf',
             '--outputdir',str(output),str(OUT/model)]
    proc=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    (output/'slicer.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode:
        raise SystemExit(proc.stdout+proc.stderr)
    result=json.loads((output/'result.json').read_text())
    assert result['return_code']==0,result
    gcode=(output/'plate_1.gcode').read_text()
    assert '; filament_density: 0' not in gcode
    assert '; machine_start_gcode = \n' not in gcode
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
