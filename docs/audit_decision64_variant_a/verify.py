"""Independent Round-3 verification. Synthetic local ASGI/browser traffic and temporary SQLite."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'backend'))

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

async def stalled_body():
    from playwright.async_api import async_playwright
    import test_browser_smoke as smoke
    httpd, port = smoke._serve_dir(ROOT / 'extension')
    server, stall_port = await smoke._start_hung_body_export_server()
    logs = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            page.on('console', lambda msg: logs.append(msg.text) if msg.type == 'error' else None)
            await page.add_init_script(smoke._extension_chrome_stub_script(f'http://127.0.0.1:{port}', {'authToken': 'synthetic-audit-token'}))
            await page.goto(f'http://127.0.0.1:{port}/sidepanel.html', wait_until='domcontentloaded')
            result = await page.evaluate('''async (url) => {
                const controller = new AbortController();
                let headersSeen = false; const started = performance.now();
                const timer = setTimeout(() => controller.abort('timeout'), 500);
                try {
                    const response = await fetch(url, {headers: {Authorization: 'Bearer synthetic-audit-token'}, signal: controller.signal});
                    headersSeen = true;
                    await response.arrayBuffer();
                    return {headersSeen, completed: true};
                } catch (err) { return {headersSeen, error: String(err), aborted: controller.signal.aborted, elapsedMs: performance.now()-started}; }
                finally { clearTimeout(timer); }
            }''', f'http://127.0.0.1:{stall_port}/api/v1/operations/synthetic/export?format=bmd_bankauszug')
            # Await the real application handler, not an already-visible warning from a preceding request.
            handler = await page.evaluate('''async (origin) => {
                apiBaseUrl = origin;
                currentExportSource = 'backend'; currentOperationId = 'synthetic';
                window.__EXPORT_TIMEOUT_MS = 250;
                const originalFetch = window.fetch; let headersSeen = false;
                window.fetch = async (...args) => { const r = await originalFetch(...args); headersSeen = true; return r; };
                const started = performance.now();
                try { const value = await switchPreviewFormat('bmd_bankauszug');
                    return {value, headersSeen, elapsedMs: performance.now()-started,
                        downloadDisabled: document.getElementById('btn-download-csv').disabled,
                        controllerCleared: activeExportController === null,
                        warning: document.getElementById('preview-warning-card').textContent};
                } finally {window.fetch = originalFetch;}
            }''', f'http://127.0.0.1:{stall_port}')
            await browser.close()
            return {'raw_fetch': result, 'real_application_handler': handler, 'console_errors': logs}
    finally:
        server.close(); await server.wait_closed()
        httpd.shutdown(); httpd.server_close()

async def run():
    old = load('audit63', ROOT / 'docs/audit_decision63_variant_a/probes.py')
    result = {'r63_counterexamples': await old.endpoint_probes()}
    result['submitted_stall_server'] = await stalled_body()
    from app.db.session import engine
    await engine.dispose()
    return result

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='s2m-audit64-', ignore_cleanup_errors=True) as tmp:
        db = Path(tmp)/'audit.db'
        os.environ['SQLITE_DB_PATH']=str(db)
        os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+db.as_posix()
        result=asyncio.run(run())
        p=subprocess.run([sys.executable,'-E',str(ROOT/'docs/audit_decision63_variant_a/probes.py'),'--chain-child'],capture_output=True,text=True,timeout=6)
        result['chain_12_segments']={'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
        checks={}
        for file in ['extension/app.js','extension_firefox_build/app.js','extension_firefox_build/background.js','landing/app.js']:
            p=subprocess.run(['node','--check',file],cwd=ROOT,capture_output=True,text=True)
            checks[file]={'exit':p.returncode,'stderr':p.stderr}
        build=load('ff',ROOT/'scripts/build_firefox_extension.py')
        checks['firefox']=build.build_firefox_extension(check_only=True)
        result['build_checks']=checks
        (OUT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='build_checks'},indent=2,ensure_ascii=True))
