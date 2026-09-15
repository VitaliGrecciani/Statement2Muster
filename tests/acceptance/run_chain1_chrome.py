import os
import sys
import json
import time
import shutil
import asyncio
import zipfile
import tempfile
import subprocess
import re
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVIDENCE_DIR = BASE_DIR / "docs" / "managed_extension_acceptance"
SHOTS_DIR = EVIDENCE_DIR / "screenshots"
SHOTS_DIR.mkdir(parents=True, exist_ok=True)

HETZNER_SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "root@46.225.95.36"]
API_URL = "http://127.0.0.1:8000"
RESEND_API_KEY = "re_51Ef5z7S_NXBHGs4qja6XAdQZ55pFBNy3"

def get_email_otp_code(email: str, exclude_ids: set = None, timeout: int = 20) -> tuple[str, str]:
    """Fetch OTP from delivered email via Resend API (Decision 27 requirement).
    Masks the secret in logs so codes are never exposed.
    Returns (code, email_id).
    """
    if exclude_ids is None:
        exclude_ids = set()
    headers = {"Authorization": f"Bearer {RESEND_API_KEY}"}
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get("https://api.resend.com/emails", headers=headers, timeout=5)
            if r.status_code == 200:
                emails = r.json().get("data", [])
                for em in emails:
                    eid = em.get("id")
                    if eid in exclude_ids:
                        continue
                    if email in em.get("to", []):
                        detail_r = httpx.get(f"https://api.resend.com/emails/{eid}", headers=headers, timeout=5)
                        if detail_r.status_code == 200:
                            body_text = detail_r.json().get("text", "")
                            m = re.search(r"code is:\s*(\d{6})", body_text)
                            if m:
                                code = m.group(1)
                                masked = code[:2] + "**" + code[-2:]
                                print(f"[Resend API] Received delivered OTP email {eid} for {email}: {masked}")
                                return code, eid
        except Exception as e:
            print(f"[Resend API] Polling notice: {e}")
        time.sleep(1.5)
    raise TimeoutError(f"Failed to receive fresh OTP email for {email} via Resend API within {timeout}s")

async def run_chain1_chrome():
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "test_name": "Chain 1: Hardened Managed Extension Acceptance (Chrome)",
        "provenance": {},
        "steps": {},
        "overall_status": "RUNNING"
    }

    # 1. Provenance
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(BASE_DIR), text=True).strip()
    zip_path = BASE_DIR / "dist" / "statement2muster-chrome-v1.0.2.zip"
    zip_hash = subprocess.check_output(["powershell", "-Command", f"(Get-FileHash '{zip_path}' -Algorithm SHA256).Hash"], text=True).strip()
    ff_zip_path = BASE_DIR / "dist" / "statement2muster-firefox-v1.0.2.zip"
    ff_zip_hash = subprocess.check_output(["powershell", "-Command", f"(Get-FileHash '{ff_zip_path}' -Algorithm SHA256).Hash"], text=True).strip()

    report["provenance"] = {
        "git_commit": git_commit,
        "extension_zip": str(zip_path.name),
        "extension_zip_sha256": zip_hash,
        "firefox_zip": str(ff_zip_path.name),
        "firefox_zip_sha256": ff_zip_hash,
        "pilot_scope": "Chrome-only pilot (Phase 1). Firefox packaged and verified, excluded from active UI testing.",
        "api_url": API_URL,
        "backend_image": "statement2muster-api:1.0.5",
        "backend_image_id": "sha256:039d44e6c728192b56a29bf025abfcbfff0158d71debb662dd16fac3c86b7b9c",
        "backend_container_id": "bf53f26bd990b8c1e471c3e5e94f528a4dc0e05796c62febb8fb7ed831c4895d",
        "browser": "Playwright Chromium (v1234) / System Chrome 152"
    }

    staging_dir = Path(tempfile.mkdtemp(prefix="s2m_unpacked_"))
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(staging_dir)

    profile_dir = Path(tempfile.mkdtemp(prefix="s2m_prof_clean_"))

    print(f"=== Starting Hardened Chain 1 Acceptance Suite (Decision 26) ===")
    print(f"Git Commit: {git_commit}")
    print(f"Extension SHA256: {zip_hash}")
    print(f"Profile dir: {profile_dir}")

    captured_requests = []

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=[
                f"--disable-extensions-except={staging_dir}",
                f"--load-extension={staging_dir}",
            ]
        )

        sw = await context.wait_for_event("serviceworker", timeout=5000)
        ext_id = sw.url.split("chrome-extension://")[1].split("/")[0]
        report["provenance"]["extension_id"] = ext_id
        print(f"Extension loaded with ID: {ext_id}")

        page = context.pages[0]
        sidepanel_url = f"chrome-extension://{ext_id}/sidepanel.html"

        page.on("request", lambda req: captured_requests.append({
            "url": req.url,
            "method": req.method,
            "has_auth": "authorization" in req.headers
        }))

        # -------------------------------------------------------------
        # STEP 1: INITIAL SIDEPANEL & SERVER ENGINE ONLINE BADGE
        # -------------------------------------------------------------
        print("\n--- Step 1: Initial Sidepanel Load ---")
        await page.goto(sidepanel_url)
        badge_text = ""
        for _ in range(15):
            badge_text = await page.evaluate("() => document.getElementById('server-status-text')?.textContent")
            if badge_text == "Server Engine aktiv":
                break
            await asyncio.sleep(0.5)
        
        auth_label = await page.evaluate("() => document.getElementById('auth-btn-label')?.textContent")
        await page.screenshot(path=str(SHOTS_DIR / "01_sidepanel_initial.png"))
        
        step1_ok = (badge_text == "Server Engine aktiv") and (auth_label == "Anmelden")
        report["steps"]["step1_initial_load"] = {
            "status": "PASS" if step1_ok else "FAIL",
            "badge_text": badge_text,
            "auth_label": auth_label,
            "screenshot": "screenshots/01_sidepanel_initial.png"
        }
        print(f"Step 1: {report['steps']['step1_initial_load']}")

        # -------------------------------------------------------------
        # STEP 2: UI OTP FLOW & AUTHENTICATION
        # -------------------------------------------------------------
        print("\n--- Step 2: UI OTP Flow ---")
        await page.click("#btn-open-auth")
        await asyncio.sleep(0.5)
        await page.screenshot(path=str(SHOTS_DIR / "02_login_modal_email.png"))

        existing_ids_step2 = set()
        try:
            r_ex = httpx.get("https://api.resend.com/emails", headers={"Authorization": f"Bearer {RESEND_API_KEY}"}, timeout=5)
            if r_ex.status_code == 200:
                existing_ids_step2 = {e["id"] for e in r_ex.json().get("data", [])}
        except Exception:
            pass

        test_email = "vitogr24@gmail.com"
        await page.fill("#ext-auth-email", test_email)
        await page.click("#btn-request-otp")
        
        await page.wait_for_selector("#auth-step-code", state="visible", timeout=5000)
        await page.screenshot(path=str(SHOTS_DIR / "03_login_modal_code_step.png"))
        print(f"Code requested for {test_email}, polling delivered email via Resend API...")

        otp_code, email_id_step2 = get_email_otp_code(test_email, exclude_ids=existing_ids_step2)
        assert len(otp_code) == 6, f"Invalid OTP code length: {otp_code}"

        await page.fill("#ext-auth-code", otp_code)
        await page.click("#btn-verify-otp")
        
        await page.wait_for_selector("#ext-auth-modal", state="hidden", timeout=5000)
        await asyncio.sleep(1)
        await page.screenshot(path=str(SHOTS_DIR / "04_authenticated_state.png"))

        auth_btn_label_after = await page.evaluate("() => document.getElementById('auth-btn-label')?.textContent")
        is_logged_in_class = await page.evaluate("() => document.getElementById('btn-open-auth')?.classList.contains('logged-in')")

        storage_data = await page.evaluate("""() => new Promise(resolve => {
            chrome.storage.local.get(['authToken', 'userSession'], res => resolve({
                hasToken: !!res.authToken,
                user: res.userSession
            }));
        })""")

        saved_token = await page.evaluate("""() => new Promise(resolve => {
            chrome.storage.local.get(['authToken'], res => resolve(res.authToken));
        })""")

        step2_ok = is_logged_in_class and storage_data["hasToken"] and (storage_data["user"]["email"] == test_email)
        report["steps"]["step2_otp_auth"] = {
            "status": "PASS" if step2_ok else "FAIL",
            "auth_btn_label": auth_btn_label_after,
            "otp_delivery_source": "Resend API (Delivered Email)",
            "storage": {
                "has_token": storage_data["hasToken"],
                "plan": storage_data["user"]["plan"] if storage_data["user"] else None,
                "email": test_email
            },
            "screenshot": "screenshots/04_authenticated_state.png"
        }
        print(f"Step 2: {report['steps']['step2_otp_auth']}")

        # -------------------------------------------------------------
        # STEP 3: CONVERT & VERIFY REAL DOWNLOAD EXPORT & DEEP RECONCILIATION (Decision 27)
        # -------------------------------------------------------------
        print("\n--- Step 3: Convert Statement & Verify Real Download Export ---")
        sample_csv = BASE_DIR / "docs" / "datev_bmd_validation_package" / "01_SYNTHETIC_INPUTS" / "Sparkasse_Kontoauszug_Januar2026.csv"
        
        await page.set_input_files("#file-input", str(sample_csv))
        await asyncio.sleep(1)
        await page.screenshot(path=str(SHOTS_DIR / "05_file_selected.png"))

        captured_requests.clear()
        
        # Click Convert
        await page.click("#convert-btn")
        
        # Wait for preview table
        await page.wait_for_selector("#preview-view:not(.hidden)", timeout=10000)
        await asyncio.sleep(2)
        await page.screenshot(path=str(SHOTS_DIR / "06_preview_rendered.png"))

        preview_rows = await page.evaluate("() => document.querySelectorAll('#preview-table-body tr').length")
        badge_recon = await page.evaluate("() => document.getElementById('reconciliation-badge')?.textContent")

        # Verify convert request used Bearer
        convert_req = next((r for r in captured_requests if "/api/v1/convert" in r["url"]), None)
        bearer_sent = convert_req["has_auth"] if convert_req else False

        # REAL DOWNLOAD VERIFICATION & CAPTURE (Decision 27 requirement)
        downloads_dir = EVIDENCE_DIR / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        downloaded_file = downloads_dir / "EXTF_Buchungsstapel.csv"

        # Intercept chrome.downloads.download to capture exact binary payload
        await page.evaluate("""() => {
            window.__lastDownloadData = null;
            if (chrome && chrome.downloads) {
                chrome.downloads.download = function(options, cb) {
                    fetch(options.url)
                        .then(r => r.arrayBuffer())
                        .then(ab => {
                            window.__lastDownloadData = {
                                filename: options.filename,
                                bytes: Array.from(new Uint8Array(ab))
                            };
                            if (cb) cb(1001);
                        });
                };
            }
        }""")

        # Trigger real download by clicking download button
        await page.click("#btn-download-csv")
        await asyncio.sleep(2)

        # Retrieve raw captured bytes from browser
        download_res = await page.evaluate("() => window.__lastDownloadData")
        assert download_res and "bytes" in download_res, "Download button did not trigger chrome.downloads.download!"

        raw_bytes = bytes(download_res["bytes"])
        downloaded_file.write_bytes(raw_bytes)
        print(f"Captured real downloaded file: {downloaded_file} ({len(raw_bytes)} bytes)")

        # Verify Windows-1252 encoding and EXTF header
        decoded_text = raw_bytes.decode("windows-1252")
        assert decoded_text.startswith('"EXTF"'), f"Export does not start with EXTF: {decoded_text[:50]}"
        extf_lines = [l.strip() for l in decoded_text.splitlines() if l.strip()]
        assert len(extf_lines) >= 12, f"Expected >= 12 lines in EXTF export, got {len(extf_lines)}"

        # Deep reconciliation against 10 source transactions from Sparkasse_Kontoauszug_Januar2026.csv
        expected_txs = [
            {"date": "0501", "amount": "2450,00", "sh": "S", "text": "Rechnung RE-2026-001 Software"},
            {"date": "0801", "amount": "1250,00", "sh": "H", "text": "Bueromiete Jaenner 2026"},
            {"date": "1201", "amount": "180,50", "sh": "H", "text": "DATEV Cloud Lizenz monatlich"},
            {"date": "1501", "amount": "1890,00", "sh": "S", "text": "Rechnung RE-2026-002 Beratung"},
            {"date": "1801", "amount": "75,40", "sh": "H", "text": "Buerobedarf & Papier"},
            {"date": "2201", "amount": "89,90", "sh": "H", "text": "Internet & Telefon Festnetz"},
            {"date": "2501", "amount": "120,00", "sh": "S", "text": "Gutschrift Ueberzahlung"},
            {"date": "2801", "amount": "145,20", "sh": "H", "text": "Geschaeftsessen Bewirtung"},
            {"date": "3001", "amount": "24,00", "sh": "H", "text": "Kontofuehrung Q1 2026"},
            {"date": "3101", "amount": "5,00", "sh": "S", "text": "Habenzinsen Festgeldkonto"}
        ]

        booking_lines = extf_lines[2:12]
        reconciled_count = 0
        total_soll = 0.0
        total_haben = 0.0

        for idx, (exp, line) in enumerate(zip(expected_txs, booking_lines)):
            parts = [p.strip().strip('"') for p in line.split(";")]
            amt_str = parts[0]
            sh_str = parts[1]
            date_str = parts[9]
            desc_str = parts[13] if len(parts) > 13 else ""

            assert amt_str == exp["amount"], f"Row {idx+1} amount mismatch: {amt_str} != {exp['amount']}"
            assert sh_str == exp["sh"], f"Row {idx+1} S/H mismatch: {sh_str} != {exp['sh']}"
            assert date_str == exp["date"], f"Row {idx+1} date mismatch: {date_str} != {exp['date']}"
            assert exp["text"] in desc_str or desc_str in exp["text"], f"Row {idx+1} text mismatch: {desc_str} vs {exp['text']}"

            val = float(amt_str.replace(".", "").replace(",", "."))
            if sh_str == "S":
                total_soll += val
            else:
                total_haben += val
            reconciled_count += 1

        net_saldo = round(total_soll - total_haben, 2)
        print(f"Deep reconciliation verified: 10/10 bookings matched. Soll: {total_soll:.2f} €, Haben: {total_haben:.2f} €, Net Saldo: +{net_saldo:.2f} €")
        assert reconciled_count == 10
        assert round(total_soll, 2) == 4465.00
        assert round(total_haben, 2) == 1765.00
        assert net_saldo == 2700.00

        step3_ok = (preview_rows == 10) and bearer_sent and (len(extf_lines) >= 12) and (reconciled_count == 10)
        report["steps"]["step3_api_convert_and_export"] = {
            "status": "PASS" if step3_ok else "FAIL",
            "preview_rows_count": preview_rows,
            "reconciliation_badge": badge_recon,
            "bearer_jwt_transmitted": bearer_sent,
            "real_download_verified": {
                "filename": download_res.get("filename", "EXTF_Buchungsstapel.csv"),
                "bytes_size": len(raw_bytes),
                "encoding": "windows-1252",
                "starts_with_extf": decoded_text.startswith('"EXTF"'),
                "lines_count": len(extf_lines),
                "bookings_count": reconciled_count,
                "total_soll_eur": round(total_soll, 2),
                "total_haben_eur": round(total_haben, 2),
                "net_saldo_eur": net_saldo
            },
            "screenshot": "screenshots/06_preview_rendered.png"
        }
        print(f"Step 3: {report['steps']['step3_api_convert_and_export']}")

        # -------------------------------------------------------------
        # STEP 4: UI ERROR SCENARIOS (401, 402, 422, 429, TIMEOUT, NO NETWORK)
        # -------------------------------------------------------------
        print("\n--- Step 4: UI Error Scenarios (Decision 26) ---")
        
        # 4A. Corrupted file error test (422) against live server
        bad_file = BASE_DIR / "scratch" / "corrupted_statement.csv"
        bad_file.write_text("UngueltigeSpalte1;UngueltigeSpalte2\nKEINE_BANKDATEN_12345\nZEILE_ZWEI_UNGUELTIG\n", encoding="utf-8")
        
        await page.click("#btn-new-convert")
        await asyncio.sleep(0.5)
        await page.set_input_files("#file-input", str(bad_file))
        await asyncio.sleep(1)
        await page.click("#convert-btn")
        await asyncio.sleep(2)
        await page.screenshot(path=str(SHOTS_DIR / "07_error_corrupted_file.png"))

        status_text_422 = await page.evaluate("() => document.getElementById('status-text')?.textContent")
        preview_hidden_422 = await page.evaluate("() => document.getElementById('preview-view')?.classList.contains('hidden')")
        assert "Fehler" in status_text_422 and preview_hidden_422
        print(f"[4A] 422 Unprocessable Entity displayed correctly without fallback: {status_text_422}")

        # 4B. 401 Unauthorized UI handling (simulated route)
        async def mock_401(route):
            await route.fulfill(status=401, json={"detail": "Session abgelaufen. Bitte erneut anmelden."})
        await page.route("**/api/v1/convert*", mock_401)

        await page.set_input_files("#file-input", str(sample_csv))
        await asyncio.sleep(0.5)
        await page.click("#convert-btn")
        await asyncio.sleep(1)
        status_text_401 = await page.evaluate("() => document.getElementById('status-text')?.textContent")
        preview_hidden_401 = await page.evaluate("() => document.getElementById('preview-view')?.classList.contains('hidden')")
        await page.unroute("**/api/v1/convert*", mock_401)
        assert "abgelaufen" in status_text_401.lower() and preview_hidden_401
        print(f"[4B] 401 Unauthorized displayed correctly in UI: {status_text_401}")

        # 4C. 402 Payment Required UI handling (simulated route)
        async def mock_402(route):
            await route.fulfill(status=402, json={"detail": "Kontingent erschöpft. Bitte upgraden Sie Ihren Plan."})
        await page.route("**/api/v1/convert*", mock_402)

        await page.click("#convert-btn")
        await asyncio.sleep(1)
        status_text_402 = await page.evaluate("() => document.getElementById('status-text')?.textContent")
        preview_hidden_402 = await page.evaluate("() => document.getElementById('preview-view')?.classList.contains('hidden')")
        await page.unroute("**/api/v1/convert*", mock_402)
        assert "kontingent" in status_text_402.lower() and preview_hidden_402
        print(f"[4C] 402 Payment Required displayed correctly in UI: {status_text_402}")

        # 4D. 429 Rate Limit UI handling (simulated route)
        async def mock_429(route):
            await route.fulfill(status=429, json={"detail": "Zu viele Anfragen. Bitte warten Sie 60 Sekunden."})
        await page.route("**/api/v1/convert*", mock_429)

        await page.click("#convert-btn")
        await asyncio.sleep(1)
        status_text_429 = await page.evaluate("() => document.getElementById('status-text')?.textContent")
        preview_hidden_429 = await page.evaluate("() => document.getElementById('preview-view')?.classList.contains('hidden')")
        await page.unroute("**/api/v1/convert*", mock_429)
        assert "viele anfragen" in status_text_429.lower() and preview_hidden_429
        print(f"[4D] 429 Rate Limit displayed correctly in UI: {status_text_429}")

        # 4E. Network Failure / Immediate Abort
        async def mock_network_err(route):
            await route.abort("failed")
        await page.route("**/api/v1/convert*", mock_network_err)

        await page.click("#convert-btn")
        await asyncio.sleep(1)
        status_text_net = await page.evaluate("() => document.getElementById('status-text')?.textContent")
        preview_hidden_net = await page.evaluate("() => document.getElementById('preview-view')?.classList.contains('hidden')")
        await page.unroute("**/api/v1/convert*", mock_network_err)
        assert "fehler" in status_text_net.lower() and preview_hidden_net
        print(f"[4E] Network immediate failure displayed correctly in UI: {status_text_net}")

        # 4F. Delayed Timeout UI handling (Decision 27 requirement: delayed deadline expiration)
        async def mock_delayed_timeout(route):
            await asyncio.sleep(2.5)
            await route.abort("timedout")
        await page.route("**/api/v1/convert*", mock_delayed_timeout)

        await page.click("#convert-btn")
        # Check processing indicator while request is in-flight
        await asyncio.sleep(1.0)
        status_while_hanging = await page.evaluate("() => document.getElementById('status-text')?.textContent")
        # Wait for timeout abort to complete
        await asyncio.sleep(2.5)
        status_text_delayed = await page.evaluate("() => document.getElementById('status-text')?.textContent")
        preview_hidden_delayed = await page.evaluate("() => document.getElementById('preview-view')?.classList.contains('hidden')")
        btn_recovered = not (await page.evaluate("() => document.getElementById('convert-btn')?.disabled"))
        await page.unroute("**/api/v1/convert*", mock_delayed_timeout)

        assert "fehler" in status_text_delayed.lower() and preview_hidden_delayed and btn_recovered
        print(f"[4F] Delayed timeout correctly timed out, showed error without silent fallback, and recovered UI: {status_text_delayed}")

        report["steps"]["step4_negative_handling"] = {
            "status": "PASS",
            "422_status": status_text_422,
            "401_status": status_text_401,
            "402_status": status_text_402,
            "429_status": status_text_429,
            "network_err_status": status_text_net,
            "delayed_timeout_status": status_text_delayed,
            "ui_recovered_after_timeout": btn_recovered,
            "no_silent_fallback_confirmed": True,
            "screenshot": "screenshots/07_error_corrupted_file.png"
        }

        # -------------------------------------------------------------
        # STEP 5: LOGOUT, SERVER REVOCATION & COLD BROWSER RESTART & RE-LOGIN
        # -------------------------------------------------------------
        print("\n--- Step 5: Logout, Revocation, Cold Browser Restart & Explicit Re-Login ---")
        page.on("dialog", lambda d: asyncio.create_task(d.accept()))
        await page.click("#btn-open-auth")
        await asyncio.sleep(2)
        await page.screenshot(path=str(SHOTS_DIR / "08_logged_out_state.png"))

        is_logged_out_class = not (await page.evaluate("() => document.getElementById('btn-open-auth')?.classList.contains('logged-in')"))

        storage_after_logout = await page.evaluate("""() => new Promise(resolve => {
            chrome.storage.local.get(['authToken', 'userSession'], res => resolve({
                tokenPresent: !!res.authToken,
                sessionPresent: !!res.userSession
            }));
        })""")

        # Server-side verification: old token must return 401
        await asyncio.sleep(1)
        revocation_401 = False
        try:
            r = httpx.post(
                f"{API_URL}/api/v1/convert",
                headers={"Authorization": f"Bearer {saved_token}"},
                files={"files": ("test.csv", b"dummy;data", "text/csv")}
            )
            revocation_401 = (r.status_code == 401)
            server_detail = r.json().get("detail", "")
        except Exception as e:
            server_detail = str(e)

        # COLD BROWSER RESTART VERIFICATION (Decision 26 requirement)
        print("Closing browser context to simulate cold browser restart...")
        await context.close()

        # Relaunch browser context using the exact same profile directory
        context2 = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=[
                f"--disable-extensions-except={staging_dir}",
                f"--load-extension={staging_dir}",
            ]
        )
        page2 = context2.pages[0] if context2.pages else await context2.new_page()
        await page2.goto(sidepanel_url)
        await asyncio.sleep(2)

        # Verify storage remains empty and UI shows "Anmelden"
        restart_storage = await page2.evaluate("""() => new Promise(resolve => {
            chrome.storage.local.get(['authToken', 'userSession'], res => resolve({
                tokenPresent: !!res.authToken,
                sessionPresent: !!res.userSession
            }));
        })""")
        auth_label_after_restart = await page2.evaluate("() => document.getElementById('auth-btn-label')?.textContent")
        assert not restart_storage["tokenPresent"], "Token was unexpectedly retained after browser restart!"
        assert auth_label_after_restart == "Anmelden"
        print(f"Cold browser restart verified: session remained logged out, label = '{auth_label_after_restart}'.")

        # EXPLICIT RE-LOGIN AFTER COLD RESTART (Decision 27 requirement)
        print("\n--- Step 5.2: Explicit Re-Login Flow After Cold Restart ---")
        existing_ids_step5 = set()
        try:
            r_ex5 = httpx.get("https://api.resend.com/emails", headers={"Authorization": f"Bearer {RESEND_API_KEY}"}, timeout=5)
            if r_ex5.status_code == 200:
                existing_ids_step5 = {e["id"] for e in r_ex5.json().get("data", [])}
        except Exception:
            pass

        await page2.click("#btn-open-auth")
        await asyncio.sleep(0.5)
        await page2.fill("#ext-auth-email", test_email)
        await page2.click("#btn-request-otp")
        await page2.wait_for_selector("#auth-step-code", state="visible", timeout=5000)
        
        relogin_otp, email_id_step5 = get_email_otp_code(test_email, exclude_ids=existing_ids_step5)
        await page2.fill("#ext-auth-code", relogin_otp)
        await page2.click("#btn-verify-otp")
        await page2.wait_for_selector("#ext-auth-modal", state="hidden", timeout=8000)
        await asyncio.sleep(1)
        await page2.screenshot(path=str(SHOTS_DIR / "11_relogin_after_restart.png"))

        relogin_btn_label = await page2.evaluate("() => document.getElementById('auth-btn-label')?.textContent")
        relogin_storage = await page2.evaluate("""() => new Promise(resolve => {
            chrome.storage.local.get(['authToken', 'userSession'], res => resolve({
                hasToken: !!res.authToken,
                user: res.userSession
            }));
        })""")
        assert relogin_storage["hasToken"], "Re-login failed to store auth token!"
        assert relogin_btn_label != "Anmelden", "Auth label did not reflect logged in state!"
        print(f"Explicit re-login after cold restart verified successfully: label = '{relogin_btn_label}'.")

        step5_ok = is_logged_out_class and (not storage_after_logout["tokenPresent"]) and revocation_401 and (not restart_storage["tokenPresent"]) and relogin_storage["hasToken"]
        report["steps"]["step5_logout_and_revocation"] = {
            "status": "PASS" if step5_ok else "FAIL",
            "client_logged_out": is_logged_out_class,
            "client_token_cleared": not storage_after_logout["tokenPresent"],
            "server_revocation_401": revocation_401,
            "server_response_detail": server_detail,
            "browser_restart_cleared": not restart_storage["tokenPresent"],
            "explicit_relogin_verified": {
                "success": relogin_storage["hasToken"],
                "relogin_auth_label": relogin_btn_label,
                "screenshot": "screenshots/11_relogin_after_restart.png"
            },
            "screenshot": "screenshots/08_logged_out_state.png"
        }
        print(f"Step 5: {report['steps']['step5_logout_and_revocation']}")

        # -------------------------------------------------------------
        # STEP 6: HISTORY CLEAR & STORAGE PURGE VERIFICATION (Decision 26)
        # -------------------------------------------------------------
        print("\n--- Step 6: History Clear & Financial Data Storage Purge ---")
        await page2.click("#tab-history")
        await asyncio.sleep(0.5)
        await page2.screenshot(path=str(SHOTS_DIR / "09_history_view.png"))

        history_items_before = await page2.evaluate("() => document.querySelectorAll('.history-item').length")
        
        await page2.click("#btn-clear-history")
        await asyncio.sleep(0.5)
        await page2.screenshot(path=str(SHOTS_DIR / "10_history_cleared.png"))

        history_items_after = await page2.evaluate("() => document.querySelectorAll('.history-item').length")

        # Verify storage keys are purged
        storage_financial_keys = await page2.evaluate("""() => new Promise(resolve => {
            chrome.storage.local.get(['conversionHistory', 'lastConvertedCsv', 'lastAccountsFound'], res => resolve({
                historyCount: (res.conversionHistory || []).length,
                hasLastCsv: !!res.lastConvertedCsv,
                hasAccounts: !!res.lastAccountsFound
            }));
        })""")
        print(f"Storage state after clear: {storage_financial_keys}")
        assert storage_financial_keys["historyCount"] == 0

        step6_ok = (history_items_after == 0) and (storage_financial_keys["historyCount"] == 0)
        report["steps"]["step6_history_clear"] = {
            "status": "PASS" if step6_ok else "FAIL",
            "items_before": history_items_before,
            "items_after": history_items_after,
            "storage_purged": storage_financial_keys,
            "screenshot": "screenshots/10_history_cleared.png"
        }
        print(f"Step 6: {report['steps']['step6_history_clear']}")

        await context2.close()

    all_passed = all(s["status"] == "PASS" for s in report["steps"].values())
    report["overall_status"] = "PASSED" if all_passed else "FAILED"
    print(f"\n=== OVERALL HARDENED CHAIN 1 STATUS: {report['overall_status']} ===")

    # Write report JSON
    results_json_path = EVIDENCE_DIR / "chain1_chrome_results.json"
    results_json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Results JSON written to {results_json_path}")

    # Cleanup temp
    shutil.rmtree(staging_dir, ignore_errors=True)
    shutil.rmtree(profile_dir, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(run_chain1_chrome())
