"""Await the real landing export handler against a stalled loopback HTTP body."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'backend'))

async def run():
    from playwright.async_api import async_playwright
    from test_browser_smoke import _serve_dir, _start_hung_body_export_server
    httpd, port = _serve_dir(ROOT/'landing')
    server, stall_port = await _start_hung_body_export_server()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            async def route(r):
                if r.request.url.startswith('http://127.0.0.1:'):
                    await r.continue_()
                else:
                    await r.abort()
            await page.route('**/*', route)
            await page.goto(f'http://127.0.0.1:{port}/index.html',wait_until='domcontentloaded')
            result=await page.evaluate('''async (origin) => {
                sessionStorage.setItem('s2m_access_token','synthetic-token');
                isSampleMode=false; currentOperationId='synthetic'; window.__LANDING_TIMEOUT_MS=250;
                const orig=window.fetch; let headersSeen=false; const start=performance.now();
                window.fetch=async (url, init) => {
                    const path=new URL(url).pathname+new URL(url).search;
                    const resp=await orig(origin+path,init); headersSeen=true; return resp;
                };
                try {const value=await fetchLandingExportBytes('bmd_bankauszug');
                    return {value,headersSeen,elapsedMs:performance.now()-start,
                        controllerCleared:activeLandingExportCtrl===null,downloadDisabled:btnDownloadDemoCsv.disabled,
                        noDownloadBytes:currentDemoBytes===null};
                } finally {window.fetch=orig;}
            }''',f'http://127.0.0.1:{stall_port}')
            await browser.close()
            assert result['headersSeen'] and result['controllerCleared'] and result['downloadDisabled'] and result['noDownloadBytes'] and result['value'] is False
            assert 200 <= result['elapsedMs'] < 2000
            return result
    finally:
        server.close(); await server.wait_closed()
        httpd.shutdown(); httpd.server_close()

if __name__=='__main__':
    result=asyncio.run(run())
    Path(__file__).with_name('landing_deadline_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
