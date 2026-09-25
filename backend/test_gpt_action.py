import pytest
import datetime
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.api.endpoints.gpt import gpt_download_cache

@pytest.mark.asyncio
async def test_gpt_convert_datev_structured():
    """Verifies that ChatGPT Action generates valid DATEV EXTF 700 Windows-1252 export."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
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
        
        resp = await client.post("/api/v1/gpt/convert", json=payload)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        assert data["status"] == "success"
        assert data["export_format"] == "datev"
        assert "DATEV_EXTF_American_Express_Business_" in data["filename"]
        assert "download_id" in data
        assert "download_url" in data
        assert data["expires_in_minutes"] == 30
        
        # Summary verification
        summary = data["summary"]
        assert summary["transaction_count"] == 2
        assert summary["total_debit"] == -149.90
        assert summary["total_credit"] == 2500.00
        assert summary["net_balance"] == 2350.10
        assert summary["date_from"] == "2026-03-10"
        assert summary["date_to"] == "2026-03-12"
        
        # Test RAM-only download
        download_id = data["download_id"]
        dl_resp = await client.get(f"/api/v1/gpt/download/{download_id}")
        assert dl_resp.status_code == 200
        assert "text/csv" in dl_resp.headers["content-type"]
        assert "charset=windows-1252" in dl_resp.headers["content-type"]
        assert f'attachment; filename="{data["filename"]}"' in dl_resp.headers["content-disposition"]
        assert dl_resp.headers["X-Zero-Retention"] == "enforced-in-memory-only"
        
        # Must decode cleanly with Windows-1252
        csv_text = dl_resp.content.decode("windows-1252")
        lines = csv_text.splitlines()
        assert len(lines) == 4 # 2 header lines + 2 transactions
        
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
    """Verifies that ChatGPT Action generates valid Austrian BMD NTCS 5.1 export."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
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
        
        # Verify download
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
        resp = await client.get("/api/v1/gpt/download/non_existent_token_12345")
        assert resp.status_code == 404
        assert "Zero Durable Retention" in resp.json()["detail"]

@pytest.mark.asyncio
async def test_gpt_convert_free_tier_limit():
    """Verifies that unlicensed conversion is capped at 50 transactions with warning."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Generate 65 transactions
        txs = [
            {
                "booking_date": "2026-03-01",
                "amount": -10.00,
                "currency": "EUR",
                "description": f"Tx #{i}"
            }
            for i in range(65)
        ]
        payload = {
            "bank_name": "Test Bank",
            "export_format": "datev",
            "transactions": txs
        }
        resp = await client.post("/api/v1/gpt/convert", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "warning"
        assert data["summary"]["transaction_count"] == 50
        assert any("Free Tier Limit" in note for note in data["notes"])
        assert "pro" in data["upgrade_info"]
        assert "lifetime" in data["upgrade_info"]

@pytest.mark.asyncio
async def test_gpt_convert_empty_error():
    """Rejects empty request missing transactions and raw_content."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/v1/gpt/convert", json={"bank_name": "Empty"})
        assert resp.status_code == 400
