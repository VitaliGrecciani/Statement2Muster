"""Record reviewed source hashes; excludes secrets, real DB, PDFs and logs."""
from pathlib import Path
import hashlib, json, re
root=Path(__file__).resolve().parents[2]
paths=[]
for folder,patterns in {'backend/app':['*.py'],'extension':['*.js','*.json','*.html'],'extension_firefox_build':['*.js','*.json','*.html'],'landing':['*.js','*.html'],'docs':['*.md'],'scripts':['*.ps1']}.items():
    for pattern in patterns:
        paths.extend((root/folder).rglob(pattern))
paths += list((root/'backend').glob('test_*.py'))
paths += [root/p for p in ['backend/Dockerfile','backend/requirements.txt','05_AUDIT_2026-09-08.md','06_ADR_001_MANAGED_CONVERSION_AND_ENTITLEMENTS.md','07_REAUDIT_2026-09-09.md']]
manifest={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths)) if p.is_file()}
out=Path(__file__).resolve().parent
(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf8')
report=(root/'07_REAUDIT_2026-09-09.md').read_text(encoding='utf8')
rows=re.findall(r'^\| (A\d{2}) \| (P\d) \| ([^|]+)\|',report,re.M)
assert len(rows)==31 and len({r[0] for r in rows})==31
closed=[r[0] for r in rows if r[2].strip().startswith('Закрыт')]
assert len(closed)==5
missing=[]
for link in re.findall(r'\]\(([^)]+)\)',report):
    if not link.startswith('https:') and not (root/link).exists():missing.append(link)
assert not missing,missing
print(json.dumps({'source_files':len(manifest),'matrix_rows':len(rows),'closed':closed,'missing_local_links':missing},ensure_ascii=False))
