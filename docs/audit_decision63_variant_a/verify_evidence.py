"""Rerun submitted probes without overwriting their evidence; record independent build checks."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

if __name__ == '__main__':
    checks = {}
    for file in ('extension/app.js', 'extension_firefox_build/app.js', 'extension_firefox_build/background.js', 'landing/app.js'):
        p = subprocess.run(['node', '--check', file], cwd=ROOT, capture_output=True, text=True)
        checks[file] = {'exit': p.returncode, 'stderr': p.stderr}
    build = load('ff_build', ROOT / 'scripts/build_firefox_extension.py')
    checked = build.build_firefox_extension(check_only=True)
    expected_manifest = (json.dumps(build.transform_manifest(json.loads((ROOT / 'extension/manifest.json').read_text(encoding='utf-8'))), indent=2, ensure_ascii=False)+'\n').encode('utf-8')
    checks['firefox'] = {'shared_files': len(checked['shared_files']), 'mismatches': checked['mismatches'],
        'manifest_matches_transform': expected_manifest == (ROOT / 'extension_firefox_build/manifest.json').read_bytes(),
        'background_matches_transform': build.FIREFOX_BACKGROUND_JS.encode('utf-8') == (ROOT / 'extension_firefox_build/background.js').read_bytes()}
    (OUT / 'build_checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='s2m-audit63-baseline-', ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / 'audit.db'
        os.environ['SQLITE_DB_PATH'] = str(db)
        os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + db.as_posix()
        module = load('submitted_r2', ROOT / 'docs/audit_decision62_variant_a/probes_round2.py')
        results = asyncio.run(module.run())
        (OUT / 'submitted_probes_rerun.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    paths = []
    for folder, pattern in [('backend/app','*.py'),('extension','*.js'),('landing','*.js')]:
        paths.extend((ROOT / folder).rglob(pattern))
    paths.extend(ROOT / f for f in ['backend/test_bmd_bankauszug_erste.py','backend/test_browser_smoke.py','scripts/build_firefox_extension.py','extension/sidepanel.html','landing/index.html'])
    manifest = {'head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'scope': 'Working tree, not a committed release',
        'sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}}
    (OUT / 'source_manifest.json').write_text(json.dumps(manifest, indent=2),encoding='utf-8')
    print(json.dumps(checks, indent=2))
    print('Submitted probes independently rerun; outputs saved in audit63 directory.')
