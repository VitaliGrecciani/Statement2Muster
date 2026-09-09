from pathlib import Path
import re, json, hashlib
root=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent
report=root/'08_REAUDIT_ROUND3_2026-09-09.md'
text=report.read_text(encoding='utf8')
rows=re.findall(r'^\| (A\d{2}) \| (P\d) \| ([^|]+)\|',text,re.M)
assert len(rows)==31 and len(set(r[0] for r in rows))==31
closed=[r[0] for r in rows if r[2].strip().startswith('Закрыт')]
assert len(closed)==6,closed
missing=[p for p in re.findall(r'\]\(([^)]+)\)',text) if not p.startswith('https:') and not (root/p).exists()]
assert not missing,missing
files=[report,root/'backend/Dockerfile',root/'backend/requirements.txt']
for folder,patterns in [('backend/app',['*.py']),('backend',['test_*.py']),('extension',['*.js','*.json','*.html']),('extension_firefox_build',['*.js','*.json','*.html']),('landing',['*.js','*.html']),('docs',['*.md'])]:
 for pattern in patterns:
  files.extend((root/folder).rglob(pattern) if folder!='backend' else (root/folder).glob(pattern))
manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}
(out/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'closed':closed,'unclosed':{p:sum(1 for r in rows if r[1]==p and r[0] not in closed) for p in ['P1','P2','P3']},'missing_links':missing,'hashed_files':len(manifest)},ensure_ascii=False))
