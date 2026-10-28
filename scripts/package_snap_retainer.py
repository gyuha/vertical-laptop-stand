"""Package the new dual-end design after validating evidence and file links."""
from pathlib import Path
import hashlib
import json
import posixpath
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'exports/snap-retainer-kit.zip'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report=json.loads((ROOT/'docs/evidence/snap-retainer/geometry-report.json').read_text())
    assert report['result']=='pass'
    for filename,expected in report['source_sha256'].items():
        assert digest(ROOT/filename)==expected,f'Stale source evidence: {filename}'
    for filename,expected in report['artifact_sha256'].items():
        assert digest(ROOT/'exports/snap-retainer'/filename)==expected,f'Stale mesh evidence: {filename}'
    for filename,expected in report['native_artifact_sha256'].items():
        assert digest(ROOT/filename)==expected,f'Stale native evidence: {filename}'
    for folder,model in [('sliced-assembly','assembly-plate.stl'),('sliced-fit','snap-fit-plate.stl')]:
        base=ROOT/'exports/snap-retainer'
        result=json.loads((base/folder/'result.json').read_text())
        assert result['return_code']==0 and result['clip_region_support_extrusions']==0
        assert result['input_stl_sha256']==digest(base/model),f'Stale slice: {folder}'
        for name,expected in result['profile_sha256'].items():
            assert digest(base/folder/f'{name}.json')==expected
    files=[ROOT/'README.md',ROOT/'docs/snap-retainer.md',ROOT/'docs/calibration.md']
    files += [ROOT/'cad'/name for name in ['parameters.json','snap-parameters.json','band_geometry.py',
              'build_calibration.py','build_snap_retainer.py','snap-retainer-print.FCStd','snap-retainer-assembly.FCStd']]
    files += [p for p in (ROOT/'scripts').glob('*') if p.suffix in {'.py','.sh'}]
    files += [p for p in (ROOT/'references').glob('*') if p.suffix in {'.stl','.json'}]
    files += [p for p in (ROOT/'docs/design').glob('*.svg')]
    files += [p for p in (ROOT/'docs/evidence/snap-retainer').glob('*') if p.suffix in {'.png','.json','.stl'}]
    files += [p for p in (ROOT/'exports/snap-retainer').rglob('*') if p.suffix in {'.stl','.step','.json','.3mf'}]
    payload={p.relative_to(ROOT).as_posix():p for p in files if p.is_file()}
    links=0
    for name,path in payload.items():
        if path.suffix!='.md': continue
        for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',path.read_text()):
            if link.startswith(('https://','http://','#')): continue
            target=posixpath.normpath(posixpath.join(posixpath.dirname(name),link.split('#')[0]))
            # The README download link refers to the containing ZIP itself.
            if target=='exports/snap-retainer-kit.zip': continue
            assert target in payload,f'Broken bundle link: {name} -> {target}'
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
