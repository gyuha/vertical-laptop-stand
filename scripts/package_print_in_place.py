"""Package the print-in-place design after validating evidence and file links."""
from pathlib import Path
import hashlib
import json
import posixpath
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'exports/print-in-place-kit.zip'
OUT=ROOT/'exports/print-in-place'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report=json.loads((ROOT/'docs/evidence/print-in-place/geometry-report.json').read_text())
    assert report['result']=='pass'
    for filename,expected in report['source_sha256'].items():
        assert digest(ROOT/filename)==expected,f'Stale source evidence: {filename}'
    for filename,expected in report['artifact_sha256'].items():
        assert digest(OUT/filename)==expected,f'Stale artifact evidence: {filename}'
    for folder,model in [('sliced-assembly','assembly-plate.stl'),('sliced-trial','hinge-trial.stl')]:
        result=json.loads((OUT/folder/'result.json').read_text())
        assert result['return_code']==0 and result['support_extrusions']==0
        assert result['input_stl_sha256']==digest(OUT/model),f'Stale slice: {folder}'
    files=[ROOT/'docs/print-in-place.md',ROOT/'cad/print-in-place.FCStd']
    files += [ROOT/'cad'/name for name in ['parameters.json','print-in-place-parameters.json',
              'band_geometry.py','build_calibration.py','build_print_in_place.py']]
    files += [ROOT/'scripts'/name for name in ['freecad_python.sh','check_geometry.py','check_print_in_place.py',
              'slice_calibration.py','render_models.py','render_print_in_place.py','package_print_in_place.py']]
    files += [p for p in (ROOT/'docs/evidence/print-in-place').glob('*') if p.suffix in {'.png','.json'}]
    files += [p for p in OUT.rglob('*') if p.suffix in {'.stl','.step','.json','.3mf'}]
    payload={p.relative_to(ROOT).as_posix():p for p in files if p.is_file()}
    links=0
    for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',(ROOT/'docs/print-in-place.md').read_text()):
        target=posixpath.normpath(posixpath.join('docs',link.split('#')[0]))
        assert target in payload,f'Broken bundle link: docs/print-in-place.md -> {target}'
        links+=1
    hashes={name:digest(path) for name,path in sorted(payload.items())}
    with zipfile.ZipFile(DEST,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,path in sorted(payload.items()):z.write(path,name)
        z.writestr('bundle-sha256.json',json.dumps(hashes,indent=2)+'\n')
    with zipfile.ZipFile(DEST) as z:
        assert z.testzip() is None
        for name,expected in hashes.items():
            assert hashlib.sha256(z.read(name)).hexdigest()==expected
        print(f'{DEST.name}: {len(z.namelist())} files; {DEST.stat().st_size:,} bytes; {links} local links; CRC and hashes passed')


if __name__=='__main__':
    main()
