"""Create the portable calibration bundle, excluding G-code and runtime state."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'exports/calibration-kit.zip'


def main():
    paths=[ROOT/'README.md']
    for folder,extensions in [
        ('cad',{'.py','.json','.FCStd'}),
        ('scripts',{'.py','.sh'}),
        ('references',{'.stl','.json'}),
        ('docs',{'.md','.png','.json'}),
        ('exports/calibration',{'.stl','.step','.json','.3mf'})]:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in extensions)
    report=json.loads((ROOT/'docs/evidence/geometry-report.json').read_text())
    assert report['result']=='pass'
    for filename,digest in report['artifact_sha256'].items():
        assert hashlib.sha256((ROOT/'exports/calibration'/filename).read_bytes()).hexdigest()==digest
    for kit in ['fit','mechanism']:
        result=json.loads((ROOT/f'exports/calibration/sliced-{kit}/result.json').read_text())
        assert result['return_code']==0
    with zipfile.ZipFile(DEST,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path,str(path.relative_to(ROOT)))
    with zipfile.ZipFile(DEST) as bundle:
        assert bundle.testzip() is None
        assert 'exports/calibration/fit-plate.stl' in bundle.namelist()
        print(f'{DEST.name}: {len(bundle.namelist())} files, {DEST.stat().st_size:,} bytes; CRC passed')


if __name__=='__main__':
    main()
