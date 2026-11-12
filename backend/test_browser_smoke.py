import asyncio
import functools
import http.server
import socketserver
import threading
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from playwright.async_api import async_playwright
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.db.models import Tenant, UsageReservation
from app.db.session import async_session_maker, engine, init_db
from app.main import app
from app.services.quota_service import get_or_create_trial_entitlement
from test_bmd_bankauszug_erste import (
    build_synthetic_erste_bank_6page_pdf,
    build_synthetic_erste_bank_6seg_12tx_471_934_pdf,
    make_valid_at_iban,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def _serve_dir(directory: Path):
    handler = functools.partial(_QuietHandler, directory=str(directory))

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    httpd = ReusableTCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


async def _start_hung_body_export_server():
    """Starts a raw loopback TCP HTTP server that sends fast 200 headers + partial chunk, then stalls body."""
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                raw_req = await reader.readuntil(b"\r\n\r\n")
                if raw_req.startswith(b"OPTIONS "):
                    writer.write(
                        b"HTTP/1.1 204 No Content\r\n"
                        b"Access-Control-Allow-Origin: *\r\n"
                        b"Access-Control-Allow-Headers: *\r\n"
                        b"Access-Control-Allow-Methods: GET, OPTIONS\r\n"
                        b"Content-Length: 0\r\n\r\n"
                    )
                    await writer.drain()
                    continue
                headers = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Access-Control-Allow-Headers: *\r\n"
                    b"Content-Type: text/csv; charset=windows-1252\r\n"
                    b"Content-Disposition: attachment; filename=\"BMD_Bankauszug.csv\"\r\n"
                    b"Content-Length: 500\r\n"
                    b"\r\n"
                    b'"Satzart";"Belegdatum";"Konto";"Gegenkonto"\r\n'
                )
                writer.write(headers)
                await writer.drain()
                await asyncio.sleep(5.0)
                break
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _attach_asgi_api_bridge(
    page,
    client: AsyncClient,
    api_origin: str,
    delay_export_once=None,
    delay_convert_ms=0,
    delay_export_headers_ms=0,
):
    """Bridges Chromium fetch() calls targeting api_origin directly to the live FastAPI ASGI app."""
    delayed_export_gate = delay_export_once  # {"event": asyncio.Event}

    async def handle_route(route):
        url = route.request.url
        if not url.startswith(api_origin):
            # Block external fonts/analytics cleanly so Playwright tests never depend on external network
            if url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:") or url.startswith("blob:") or url.startswith("data:"):
                await route.continue_()
            else:
                await route.abort()
            return

        if "/api/v1/convert" in url and delay_convert_ms:
            await asyncio.sleep(delay_convert_ms / 1000.0)

        if "/api/v1/operations/" in url and "/export" in url and delay_export_headers_ms:
            await asyncio.sleep(delay_export_headers_ms / 1000.0)

        if delayed_export_gate is not None and "/api/v1/operations/" in url and "format=bmd_bankauszug" in url and not delayed_export_gate["used"]:
            delayed_export_gate["used"] = True
            delayed_export_gate["started"].set()
            await delayed_export_gate["release"].wait()

        rel_url = url[len(api_origin):]
        req_headers = {k: v for k, v in route.request.headers.items() if k.lower() not in ("host", "content-length")}
        body = route.request.post_data_buffer or b""
        try:
            resp = await client.request(
                method=route.request.method,
                url=rel_url,
                headers=req_headers,
                content=body,
            )
            await route.fulfill(
                status=resp.status_code,
                headers={k: v for k, v in resp.headers.items()},
                body=resp.content,
            )
        except Exception:
            try:
                await route.abort()
            except Exception:
                pass

    await page.route("**/*", handle_route)


def _extension_chrome_stub_script(base_url: str, initial_storage: dict):
    import json
    stor_json = json.dumps(initial_storage)
    return f"""
(() => {{
  const storData = {stor_json};
  const noop = () => {{}};
  window.__capturedDownloads = [];
  window.chrome = {{
    storage: {{
      local: {{
        get: (keys, cb) => {{
          const res = {{}};
          if (Array.isArray(keys)) keys.forEach(k => {{ if (k in storData) res[k] = storData[k]; }});
          else if (typeof keys === 'string') {{ if (keys in storData) res[keys] = storData[keys]; }}
          else Object.assign(res, storData);
          if (cb) {{ cb(res); return; }}
          return Promise.resolve(res);
        }},
        set: (obj, cb) => {{ Object.assign(storData, obj); if (cb) cb(); return Promise.resolve(); }},
        remove: (keys, cb) => {{
          (Array.isArray(keys) ? keys : [keys]).forEach(k => delete storData[k]);
          if (cb) cb();
          return Promise.resolve();
        }}
      }},
      session: {{
        get: (keys, cb) => cb ? cb({{}}) : Promise.resolve({{}}),
        remove: () => Promise.resolve()
      }}
    }},
    runtime: {{
      getURL: (p) => `{base_url}/${{p}}`,
      lastError: null
    }},
    downloads: {{
      download: (opts, cb) => {{
        fetch(opts.url)
          .then(r => r.arrayBuffer())
          .then(buf => {{
            window.__capturedDownloads.push({{
              filename: opts.filename,
              bytes: Array.from(new Uint8Array(buf))
            }});
            if (cb) cb(window.__capturedDownloads.length);
          }})
          .catch(() => {{ if (cb) cb(0); }});
      }}
    }},
    tabs: {{ create: noop }},
    sidePanel: {{}},
    windows: {{}}
  }};
}})();
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("ext_dir_name", ["extension", "extension_firefox_build"])
async def test_playwright_extension_real_pdfjs_and_backend_flows(ext_dir_name):
    """
    Decision 62 Section 4 real Chromium smoke test across BOTH Chrome (`extension`)
    and Firefox build (`extension_firefox_build`):
    - Real `pdf.js` + `pdf.worker.min.js` PDF parsing in offline mode
    - Downloaded CSV bytes verified for UTF-8 BOM + 22-col BMD and EXTF DATEV Windows-1252
    - Backend 422 Valuta block with 0 quota deducted + preview shown
    - Backend 200 convert + format switch download
    - R62-6 Race/reset guard after delayed export response
    - Convert timeout recovery
    """
    await init_db()
    tid = str(uuid.uuid4())
    email = f"pw_ext_{uuid.uuid4().hex[:8]}@kanzlei-wien.at"
    async with async_session_maker() as db:
        db.add(Tenant(id=tid, email=email))
        await db.flush()
        await get_or_create_trial_entitlement(db, tid)
        await db.commit()
    token = create_access_token(user_id=email, tenant_id=tid)

    iban = make_valid_at_iban("20111", "00000077777")
    erste_pdf = build_synthetic_erste_bank_6page_pdf(iban=iban)
    api_origin = "https://api.statement2muster.com"

    ext_dir = ROOT_DIR / ext_dir_name
    httpd, port = _serve_dir(ext_dir)
    base_url = f"http://127.0.0.1:{port}"

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=api_origin) as client:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                try:
                    # 1. OFFLINE REAL PDF.JS TEST
                    ctx_off = await browser.new_context()
                    page_off = await ctx_off.new_page()
                    await page_off.add_init_script(_extension_chrome_stub_script(base_url, {}))

                    # Abort backend health checks so extension enters real Offline/In-Memory mode
                    async def offline_route(route):
                        u = route.request.url
                        if u.startswith(base_url) or u.startswith("blob:") or u.startswith("data:"):
                            await route.continue_()
                        else:
                            await route.abort()

                    await page_off.route("**/*", offline_route)
                    await page_off.goto(f"{base_url}/sidepanel.html", wait_until="domcontentloaded")
                    await page_off.wait_for_selector("#drop-zone")

                    # Upload real PDF without checking Valuta -> preview shown, download disabled
                    await page_off.set_input_files(
                        "#file-input",
                        files=[{"name": "erste_offline.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page_off.click("#upload-fmt-bmd-bankauszug")
                    await page_off.click("#convert-btn")
                    await page_off.wait_for_selector("#preview-view:not(.hidden)")
                    assert await page_off.is_disabled("#btn-download-csv")
                    warn_text = await page_off.inner_text("#preview-warning-card")
                    assert "valuta" in warn_text.lower()

                    # Go back, enable Valuta, convert via real pdf.js -> download 22-col BMD BOM CSV + DATEV
                    await page_off.click("#btn-new-convert")
                    await page_off.set_input_files(
                        "#file-input",
                        files=[{"name": "erste_offline.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page_off.click("#upload-fmt-bmd-bankauszug")
                    await page_off.check("#valuta-as-booking")
                    await page_off.click("#convert-btn")
                    await page_off.wait_for_function("!document.getElementById('btn-download-csv').disabled")
                    assert await page_off.inner_text("#preview-count") == "13"

                    await page_off.click("#btn-download-csv")
                    await page_off.wait_for_function("window.__capturedDownloads.length === 1")
                    dl_bmd22 = await page_off.evaluate("window.__capturedDownloads[0]")
                    bmd22_bytes = bytes(dl_bmd22["bytes"])
                    assert dl_bmd22["filename"] == "BMD_Bankauszug_22.csv"
                    assert bmd22_bytes.startswith(b"\xef\xbb\xbf")
                    assert bmd22_bytes.decode("utf-8-sig").startswith("Transaction Booking Date;Transaction Purpose;")
                    assert "Umlautprüfung äöüß" in bmd22_bytes.decode("utf-8-sig")

                    # Switch to DATEV & verify EXTF Row 1 has "EUR" + Windows-1252 umlauts
                    await page_off.click("#fmt-datev")
                    await page_off.click("#btn-download-csv")
                    await page_off.wait_for_function("window.__capturedDownloads.length === 2")
                    dl_datev = await page_off.evaluate("window.__capturedDownloads[1]")
                    datev_bytes = bytes(dl_datev["bytes"])
                    datev_str = datev_bytes.decode("cp1252")
                    assert datev_str.splitlines()[0].endswith(';"EUR"')
                    assert "Umlautprüfung äö".encode("cp1252") in datev_bytes
                    assert "Buchungsgebühr Überweisungen".encode("cp1252") in datev_bytes

                    # Switch to BMD NTCS (8-column profile) & verify real CSV bytes + 8 columns
                    await page_off.click("#fmt-bmd")
                    await page_off.click("#btn-download-csv")
                    await page_off.wait_for_function("window.__capturedDownloads.length === 3")
                    dl_ntcs = await page_off.evaluate("window.__capturedDownloads[2]")
                    ntcs_bytes = bytes(dl_ntcs["bytes"])
                    assert dl_ntcs["filename"] == "BMD_Bankauszug.csv"
                    ntcs_lines = ntcs_bytes.decode("cp1252").splitlines()
                    assert ntcs_lines[0] == '"Satzart";"Belegdatum";"Konto";"Gegenkonto";"Betrag";"Währung";"Text";"Belegnummer"'
                    assert len(ntcs_lines) == 14

                    # Verify R63-3 6-segment 12-tx baseline PDF (471,66 + 462,76 = 934,42) in real pdf.js
                    await page_off.click("#btn-new-convert")
                    pdf_12tx_baseline = build_synthetic_erste_bank_6seg_12tx_471_934_pdf(iban=iban)
                    await page_off.set_input_files(
                        "#file-input",
                        files=[{"name": "erste_12tx_baseline.pdf", "mimeType": "application/pdf", "buffer": pdf_12tx_baseline}],
                    )
                    await page_off.click("#upload-fmt-bmd-bankauszug")
                    await page_off.check("#valuta-as-booking")
                    await page_off.click("#convert-btn")
                    await page_off.wait_for_function("!document.getElementById('btn-download-csv').disabled")
                    assert await page_off.inner_text("#preview-count") == "12"
                    assert "ausgeglichen" in (await page_off.inner_text("#reconciliation-badge")).lower()
                    await ctx_off.close()

                    # 2. BACKEND CONNECTED FLOW + R62-1 + R62-6 RACE & RESET + TIMEOUT
                    ctx_on = await browser.new_context()
                    page_on = await ctx_on.new_page()
                    gate = {"used": False, "started": asyncio.Event(), "release": asyncio.Event()}
                    await page_on.add_init_script(
                        _extension_chrome_stub_script(
                            base_url,
                            {"authToken": token, "userSession": {"isLoggedIn": True, "email": email, "plan": "kanzlei_trial"}},
                        )
                    )
                    await _attach_asgi_api_bridge(page_on, client, api_origin, delay_export_once=gate)
                    await page_on.goto(f"{base_url}/sidepanel.html", wait_until="domcontentloaded")
                    await page_on.wait_for_function("document.getElementById('server-status-text').textContent.includes('Server Engine aktiv')")

                    # Upload without Valuta -> 422 renders preview + disables download + 0 quota committed!
                    await page_on.set_input_files(
                        "#file-input",
                        files=[{"name": "erste_backend.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page_on.click("#upload-fmt-bmd-bankauszug")
                    await page_on.click("#convert-btn")
                    await page_on.wait_for_selector("#preview-view:not(.hidden)")
                    assert await page_on.is_disabled("#btn-download-csv")
                    assert "valuta" in (await page_on.inner_text("#preview-warning-card")).lower()

                    async with async_session_maker() as db:
                        q_after_block = (await db.execute(
                            select(func.coalesce(func.sum(UsageReservation.units), 0))
                            .where(UsageReservation.tenant_id == tid, UsageReservation.status == "COMMITTED")
                        )).scalar()
                        assert q_after_block == 0

                    # Now check Valuta & convert as DATEV -> 200 OK + download unlocked
                    await page_on.click("#btn-new-convert")
                    await page_on.set_input_files(
                        "#file-input",
                        files=[{"name": "erste_backend.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page_on.click("#upload-fmt-datev")
                    await page_on.check("#valuta-as-booking")
                    await page_on.click("#convert-btn")
                    await page_on.wait_for_function("!document.getElementById('btn-download-csv').disabled")
                    assert await page_on.inner_text("#preview-count") == "13"

                    # Trigger delayed switchPreviewFormat('bmd_bankauszug'), IMMEDIATELY reset via #btn-new-convert & switch to datev
                    await page_on.click("#fmt-bmd-bankauszug")
                    await asyncio.wait_for(gate["started"].wait(), timeout=5.0)
                    await page_on.click("#btn-new-convert")
                    await page_on.click("#upload-fmt-datev")
                    gate["release"].set()
                    await page_on.wait_for_timeout(150)

                    # Stale delayed BMD response MUST NOT overwrite reset state or enable download!
                    assert await page_on.is_disabled("#btn-download-csv")
                    assert await page_on.is_hidden("#preview-view")
                    assert await page_on.evaluate("currentCsvFilename === '' && currentSelectedFormat === 'datev'")

                    # 3. TIMEOUT RECOVERY TEST (convert timeout + GET export header timeout + hung body after 200 headers)
                    ctx_to = await browser.new_context()
                    page_to = await ctx_to.new_page()
                    await page_to.add_init_script(
                        _extension_chrome_stub_script(
                            base_url,
                            {"authToken": token, "userSession": {"isLoggedIn": True, "email": email, "plan": "kanzlei_trial"}},
                        )
                    )
                    await _attach_asgi_api_bridge(page_to, client, api_origin, delay_convert_ms=600)
                    await page_to.goto(f"{base_url}/sidepanel.html", wait_until="domcontentloaded")
                    await page_to.wait_for_function("document.getElementById('server-status-text').textContent.includes('Server Engine aktiv')")
                    await page_to.evaluate("window.__CONVERT_TIMEOUT_MS = 120;")
                    await page_to.set_input_files(
                        "#file-input",
                        files=[{"name": "erste_timeout.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page_to.click("#convert-btn")
                    await page_to.wait_for_function("document.getElementById('status-text').textContent.includes('Zeitüberschreitung')")
                    assert not await page_to.is_disabled("#convert-btn")
                    await asyncio.sleep(0.75)  # allow delayed ASGI route to finish before tearing down ctx_to
                    await ctx_to.close()

                    # 4. GET export timeout (before headers AND stalled body read after fast 200 headers) + clean recovery
                    tid_ex = str(uuid.uuid4())
                    email_ex = f"pw_ex_{uuid.uuid4().hex[:8]}@kanzlei-wien.at"
                    async with async_session_maker() as db:
                        db.add(Tenant(id=tid_ex, email=email_ex))
                        await db.flush()
                        await get_or_create_trial_entitlement(db, tid_ex)
                        await db.commit()
                    token_ex = create_access_token(user_id=email_ex, tenant_id=tid_ex)

                    ctx_ex = await browser.new_context()
                    page_ex = await ctx_ex.new_page()
                    await page_ex.add_init_script(
                        _extension_chrome_stub_script(
                            base_url,
                            {"authToken": token_ex, "userSession": {"isLoggedIn": True, "email": email_ex, "plan": "kanzlei_trial"}},
                        )
                    )
                    await _attach_asgi_api_bridge(page_ex, client, api_origin, delay_export_headers_ms=450)
                    await page_ex.goto(f"{base_url}/sidepanel.html", wait_until="domcontentloaded")
                    await page_ex.wait_for_function("document.getElementById('server-status-text').textContent.includes('Server Engine aktiv')")
                    await page_ex.set_input_files(
                        "#file-input",
                        files=[{"name": "erste_exp_to.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page_ex.click("#upload-fmt-datev")
                    await page_ex.check("#valuta-as-booking")
                    await page_ex.click("#convert-btn")
                    await page_ex.wait_for_function("!document.getElementById('btn-download-csv').disabled")

                    # 4a: Header timeout on GET export
                    await page_ex.evaluate("window.__EXPORT_TIMEOUT_MS = 120;")
                    await page_ex.click("#fmt-bmd")
                    await page_ex.wait_for_function(
                        "document.getElementById('preview-warning-card').textContent.includes('Zeitüberschreitung beim Export')"
                    )
                    assert await page_ex.is_disabled("#btn-download-csv")

                    # 4b: Fast 200 OK headers followed by hung body stream -> aborted cleanly via AbortController!
                    stall_server, stall_port = await _start_hung_body_export_server()
                    try:
                        await page_ex.evaluate(f"window.__origApiBase = apiBaseUrl; apiBaseUrl = 'http://127.0.0.1:{stall_port}';")
                        await page_ex.click("#fmt-bmd-bankauszug")
                        await page_ex.wait_for_function(
                            "document.getElementById('preview-warning-card').textContent.includes('Zeitüberschreitung beim Export')"
                        )
                        assert await page_ex.is_disabled("#btn-download-csv")

                        # 4c: Recovery back to live backend
                        await page_ex.evaluate("apiBaseUrl = window.__origApiBase; window.__EXPORT_TIMEOUT_MS = 5000;")
                        await page_ex.click("#fmt-datev")
                        await page_ex.wait_for_function("!document.getElementById('btn-download-csv').disabled")
                    finally:
                        stall_server.close()
                        await stall_server.wait_closed()
                    await ctx_ex.close()
                    await ctx_on.close()
                finally:
                    await browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_playwright_landing_sample_live_upload_and_download():
    """
    Decision 62 Section 4 real Chromium smoke test on `landing/`:
    - Loads sample data -> switches formats (BMD 22, DATEV EXTF, BMD NTCS) -> verifies real Downloads
    - Authenticates via sessionStorage token -> uploads Erste PDF without Valuta (422 preview + blocked download)
      -> uploads with Valuta opt-in -> verifies BALANCED badge & real downloaded 22-col BMD CSV bytes.
    """
    await init_db()
    tid = str(uuid.uuid4())
    email = f"pw_land_{uuid.uuid4().hex[:8]}@kanzlei-wien.at"
    async with async_session_maker() as db:
        db.add(Tenant(id=tid, email=email))
        await db.flush()
        await get_or_create_trial_entitlement(db, tid)
        await db.commit()
    token = create_access_token(user_id=email, tenant_id=tid)

    iban = make_valid_at_iban("20111", "00000088888")
    erste_pdf = build_synthetic_erste_bank_6page_pdf(iban=iban)
    api_origin = "http://127.0.0.1:8000"

    landing_dir = ROOT_DIR / "landing"
    httpd, port = _serve_dir(landing_dir)
    base_url = f"http://127.0.0.1:{port}"

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=api_origin) as client:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                try:
                    ctx = await browser.new_context(accept_downloads=True)
                    page = await ctx.new_page()
                    await page.add_init_script(f"sessionStorage.setItem('s2m_access_token', '{token}');")
                    await _attach_asgi_api_bridge(page, client, api_origin)
                    await page.goto(f"{base_url}/index.html", wait_until="domcontentloaded")

                    # 1. Sample 1-Click + real file download verification across formats
                    await page.click("#btn-load-sample")
                    await page.wait_for_selector("#demo-result:not(.hidden)")
                    assert await page.inner_text("#demo-count") == "14"

                    # Download DATEV sample -> check EXTF Row 1 has 22 fields & "EUR" in col 22
                    async with page.expect_download() as dl_info:
                        await page.click("#btn-download-demo-csv")
                    dl_d = await dl_info.value
                    d_bytes = Path(await dl_d.path()).read_bytes()
                    d_str = d_bytes.decode("cp1252")
                    assert d_str.splitlines()[0].endswith(';"EUR"')
                    assert len(d_str.splitlines()[0].split(";")) == 22

                    # Switch to BMD Bankauszug 22 cols -> real download UTF-8 BOM + 22 cols
                    await page.select_option("#demo-result-format-select", "bmd_bankauszug")
                    async with page.expect_download() as dl_info2:
                        await page.click("#btn-download-demo-csv")
                    dl_b22 = await dl_info2.value
                    b22_bytes = Path(await dl_b22.path()).read_bytes()
                    assert b22_bytes.startswith(b"\xef\xbb\xbf")
                    assert b22_bytes.decode("utf-8-sig").startswith("Transaction Booking Date;Transaction Purpose;")

                    # Switch to BMD NTCS (8-column profile) -> real download 8 cols Windows-1252
                    await page.select_option("#demo-result-format-select", "bmd_ntcs")
                    async with page.expect_download() as dl_info_ntcs:
                        await page.click("#btn-download-demo-csv")
                    dl_ntcs_l = await dl_info_ntcs.value
                    ntcs_l_bytes = Path(await dl_ntcs_l.path()).read_bytes()
                    ntcs_l_rows = ntcs_l_bytes.decode("cp1252").splitlines()
                    assert ntcs_l_rows[0] == '"Satzart";"Belegdatum";"Konto";"Gegenkonto";"Betrag";"Währung";"Text";"Belegnummer"'
                    assert len(ntcs_l_rows) == 15

                    # 2. Live Upload without Valuta -> 422 renders blocked preview + red alert + disabled download
                    await page.click('input[name="landing-export-format"][value="bmd_bankauszug"]')
                    await page.set_input_files(
                        "#landing-file-input",
                        files=[{"name": "erste_land.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page.wait_for_selector("#demo-result:not(.hidden)")
                    assert await page.is_disabled("#btn-download-demo-csv")
                    assert "valuta" in (await page.inner_text("#demo-warnings")).lower()

                    # 3. Check Valuta & re-upload -> BALANCED + real downloaded 22-col CSV
                    await page.check("#landing-valuta-as-booking")
                    await page.set_input_files(
                        "#landing-file-input",
                        files=[{"name": "erste_land.pdf", "mimeType": "application/pdf", "buffer": erste_pdf}],
                    )
                    await page.wait_for_function("!document.getElementById('btn-download-demo-csv').disabled")
                    assert "ausgeglichen" in (await page.inner_text("#demo-recon-text")).lower()

                    async with page.expect_download() as dl_info3:
                        await page.click("#btn-download-demo-csv")
                    dl_live = await dl_info3.value
                    live_bytes = Path(await dl_live.path()).read_bytes()
                    assert live_bytes.startswith(b"\xef\xbb\xbf")
                    assert "Partner Alpha GmbH" in live_bytes.decode("utf-8-sig")
                    await ctx.close()
                finally:
                    await browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        await engine.dispose()
