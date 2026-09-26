import pytest
import base64
import datetime
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.api.endpoints.gpt_action import gpt_download_cache, gpt_free_tier_tracker

@pytest.mark.asyncio
async def test_gpt_convert_datev_structured():
    """Verifies that ChatGPT Action generates valid DATEV EXTF 700 Windows-1252 export on /v1/gpt/convert and /api/v1/gpt/convert."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": "test-session-datev-01",
            "bank_name": "American Express Business",
            "export_format": "datev",
            "default_bank_account": "1200",
            "transactions": [
                {
                    "booking_date": "2026-03-10",
                    "value_date": "2026-03-11",
                    "amount": -149.90,
                    "currency": "EUR",
                    "description": "Büromaterial & Druckerpatronen GmbH",
                    "reference": "RE-2026-881"
                },
                {
                    "booking_date": "2026-03-12",
                    "amount": 2500.00,
                    "currency": "EUR",
                    "description": "Kundenüberweisung Softwareentwicklung",
                    "reference": "GS-9901"
                }
            ]
        }
        
        # Test /v1/gpt/convert
        resp = await client.post("/v1/gpt/convert", json=payload)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        assert data["status"] == "success"
        assert data["export_format"] == "datev"
        assert "DATEV_EXTF_American_Express_Business_" in data["filename"]
        assert "download_id" in data
        assert "download_url" in data
        assert data["expires_in_minutes"] == 30
        assert data["file_base64"] is not None
        assert len(data["file_base64"]) > 50
        
        # Free tier status verification (first conversion)
        ft_status = data["free_tier_status"]
        assert ft_status["conversions_used"] == 1
        assert ft_status["remaining_free_conversions"] == 2
        assert ft_status["limit_reached"] is False
        
        # Summary verification
        summary = data["summary"]
        assert summary["transaction_count"] == 2
        assert summary["total_debit"] == -149.90
        assert summary["total_credit"] == 2500.00
        assert summary["net_balance"] == 2350.10
        assert summary["date_from"] == "2026-03-10"
        assert summary["date_to"] == "2026-03-12"
        
        # Test RAM-only download via /v1/gpt/download/{download_id}
        download_id = data["download_id"]
        dl_resp = await client.get(f"/v1/gpt/download/{download_id}")
        assert dl_resp.status_code == 200
        assert "text/csv" in dl_resp.headers["content-type"]
        assert "charset=windows-1252" in dl_resp.headers["content-type"]
        assert f'attachment; filename="{data["filename"]}"' in dl_resp.headers["content-disposition"]
        assert dl_resp.headers["X-Zero-Retention"] == "enforced-in-memory-only"
        
        # Must decode cleanly with Windows-1252
        csv_text = dl_resp.content.decode("windows-1252")
        lines = csv_text.splitlines()
        assert len(lines) == 4  # 2 header lines + 2 transactions
        
        # Check DATEV EXTF header
        assert lines[0].startswith('"EXTF";700;21;"Buchungsstapel";12;')
        assert '"Statement2Muster"' in lines[0]
        
        # Check debit line (Haben for active account outgoing money)
        row1 = lines[2].split(";")
        assert row1[0] == '"149,90"'
        assert row1[1] == '"H"'
        assert row1[6] == '"1200"'
        assert "Büromaterial" in row1[13]
        
        # Check credit line (Soll for active account incoming money)
        row2 = lines[3].split(";")
        assert row2[0] == '"2500,00"'
        assert row2[1] == '"S"'
        assert row2[6] == '"1200"'
        assert "Kundenüberweisung" in row2[13]

@pytest.mark.asyncio
async def test_gpt_convert_bmd_structured():
    """Verifies that ChatGPT Action generates valid Austrian BMD NTCS 5.1 export on /api/v1/gpt/convert."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": "test-session-bmd-01",
            "bank_name": "Wise Business",
            "export_format": "bmd",
            "default_bank_account": "2800",
            "transactions": [
                {
                    "booking_date": "2026-02-01",
                    "amount": -85.50,
                    "currency": "EUR",
                    "description": "Hosting Hetzner",
                    "reference": "HETZ-1"
                }
            ]
        }
        
        resp = await client.post("/api/v1/gpt/convert", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_format"] == "bmd"
        assert "BMD_NTCS_Wise_Business_" in data["filename"]
        
        # Verify download via /api/v1/gpt/download/{download_id}
        dl_resp = await client.get(f"/api/v1/gpt/download/{data['download_id']}")
        assert dl_resp.status_code == 200
        csv_text = dl_resp.content.decode("windows-1252")
        lines = csv_text.splitlines()
        assert lines[0].startswith('"Satzart";"Belegdatum";"Konto";')
        assert '"-85,50"' in lines[1]
        assert '"2800"' in lines[1]

@pytest.mark.asyncio
async def test_gpt_download_not_found():
    """Ensures 404 is returned for expired or non-existent download token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/v1/gpt/download/non_existent_token_12345")
        assert resp.status_code == 404
        assert "Zero-Durable-Retention" in resp.json()["detail"] or "Datenschutzrichtlinie" in resp.json()["detail"]

@pytest.mark.asyncio
async def test_gpt_free_tier_limits_and_exhaustion():
    """Verifies that an unlicensed session gets 3 free conversions, and 4th returns limit_reached."""
    transport = ASGITransport(app=app)
    session_key = "test-session-free-quota-cycle"
    # Reset tracker for clean test
    gpt_free_tier_tracker.delete(f"used_sess_{session_key}")

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": session_key,
            "bank_name": "Test Bank",
            "export_format": "datev",
            "transactions": [
                {
                    "booking_date": "2026-03-01",
                    "amount": -10.00,
                    "currency": "EUR",
                    "description": "Coffee"
                }
            ]
        }

        # Conversion 1
        resp1 = await client.post("/v1/gpt/convert", json=payload)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "success"
        assert data1["free_tier_status"]["conversions_used"] == 1
        assert data1["free_tier_status"]["remaining_free_conversions"] == 2

        # Conversion 2
        resp2 = await client.post("/v1/gpt/convert", json=payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "success"
        assert data2["free_tier_status"]["conversions_used"] == 2
        assert data2["free_tier_status"]["remaining_free_conversions"] == 1

        # Conversion 3
        resp3 = await client.post("/v1/gpt/convert", json=payload)
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["status"] == "success"
        assert data3["free_tier_status"]["conversions_used"] == 3
        assert data3["free_tier_status"]["remaining_free_conversions"] == 0

        # Conversion 4 -> Must trigger limit_reached!
        resp4 = await client.post("/v1/gpt/convert", json=payload)
        assert resp4.status_code == 200
        data4 = resp4.json()
        assert data4["status"] == "limit_reached"
        assert data4["free_tier_status"]["limit_reached"] is True
        assert data4["free_tier_status"]["remaining_free_conversions"] == 0
        assert data4["download_url"] == ""
        assert "Kostenloses Kontingent erreicht" in data4["message"]
        assert "starter" in data4["upgrade_info"]
        assert "pro" in data4["upgrade_info"]
        assert "lifetime" in data4["upgrade_info"]

@pytest.mark.asyncio
async def test_gpt_license_key_bypasses_limits():
    """Verifies that providing a valid license key bypasses free tier limits immediately."""
    transport = ASGITransport(app=app)
    session_key = "test-session-pro-unlimited"
    # Pre-exhaust the free tier count to 5
    gpt_free_tier_tracker.set(f"used_sess_{session_key}", 5)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": session_key,
            "license_key": "s2m_test_pro_key",
            "bank_name": "Test Bank",
            "export_format": "datev",
            "transactions": [
                {
                    "booking_date": "2026-03-01",
                    "amount": -500.00,
                    "currency": "EUR",
                    "description": "Server hosting"
                }
            ]
        }
        resp = await client.post("/v1/gpt/convert", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["free_tier_status"]["is_unlimited"] is True
        assert data["free_tier_status"]["plan"] == "pro"
        assert data["free_tier_status"]["limit_reached"] is False
        assert data["download_url"] != ""

@pytest.mark.asyncio
async def test_gpt_check_license_endpoint():
    """Verifies check-license endpoint with valid and invalid keys."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Valid test key
        resp1 = await client.post("/v1/gpt/check-license", json={"license_key": "s2m_test_pro_key"})
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["valid"] is True
        assert data1["plan"] == "pro"

        # Invalid key
        resp2 = await client.post("/v1/gpt/check-license", json={"license_key": "invalid_random_key_123"})
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["valid"] is False
        assert "starter" in data2["upgrade_info"]

@pytest.mark.asyncio
async def test_gpt_convert_file_base64_supervised():
    """Verifies server-side parsing via parser_supervisor for base64-encoded CSV."""
    transport = ASGITransport(app=app)
    csv_sample = (
        "Buchungstag;Wertstellung;Umsatzart;Beguenstigter;Verwendungszweck;Betrag;Waehrung\n"
        "15.03.2026;15.03.2026;Ueberweisung;Telekom Deutschland;Rechnung DSL;-79,90;EUR\n"
        "20.03.2026;20.03.2026;Gutschrift;Kunde GmbH;Projekt 42;1500,00;EUR\n"
    )
    b64_content = base64.b64encode(csv_sample.encode("utf-8")).decode("ascii")

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": "test-session-base64-01",
            "license_key": "PRO-DEMO-2026",
            "file_base64": b64_content,
            "filename": "kontoauszug_sample.csv",
            "export_format": "datev"
        }
        resp = await client.post("/v1/gpt/convert", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["summary"]["transaction_count"] == 2
        assert data["summary"]["total_debit"] == -79.90
        assert data["summary"]["total_credit"] == 1500.00
        assert data["summary"]["net_balance"] == 1420.10

@pytest.mark.asyncio
async def test_gpt_convert_empty_error():
    """Rejects empty request missing transactions, file_base64, and raw_content."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/v1/gpt/convert", json={"bank_name": "Empty"})
        assert resp.status_code == 400
