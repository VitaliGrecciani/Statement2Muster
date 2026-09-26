import pytest
import json
import uuid
import base64
import asyncio
import datetime
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, revoke_token, _revoked_tokens
from app.db.session import async_session_maker, init_db
from sqlalchemy import select
from app.db.models import Tenant, Entitlement, UsageReservation
from app.api.endpoints.gpt_action import gpt_download_cache, gpt_free_tier_tracker


@pytest.fixture(autouse=True, scope="function")
def reset_caches():
    gpt_download_cache.clear()
    gpt_free_tier_tracker.clear()
    _revoked_tokens.clear()
    yield
    gpt_download_cache.clear()
    gpt_free_tier_tracker.clear()
    _revoked_tokens.clear()


@pytest.mark.asyncio
async def test_gpt_convert_datev_structured():
    """Verifies valid DATEV EXTF 700 Windows-1252 export on /v1/gpt/convert and /api/v1/gpt/convert."""
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
        assert data["file_base64"] is not None  # Small batch has base64
        
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
    """Verifies Austrian BMD NTCS 5.1 export on /api/v1/gpt/convert."""
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
        resp = await client.get("/v1/gpt/download/non_existent_token_12345")
        assert resp.status_code == 404
        assert "RAM-Zwischenspeicher" in resp.json()["detail"] or "abgelaufen" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_gpt_free_tier_limits_and_exhaustion():
    """Verifies that an unlicensed demo session gets 3 free conversions, and 4th returns limit_reached."""
    transport = ASGITransport(app=app)
    session_key = "test-session-free-quota-cycle"
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
        assert resp1.json()["status"] == "success"
        assert resp1.json()["free_tier_status"]["conversions_used"] == 1
        assert resp1.json()["free_tier_status"]["remaining_free_conversions"] == 2

        # Conversion 2
        resp2 = await client.post("/v1/gpt/convert", json=payload)
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "success"
        assert resp2.json()["free_tier_status"]["conversions_used"] == 2

        # Conversion 3
        resp3 = await client.post("/v1/gpt/convert", json=payload)
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "success"
        assert resp3.json()["free_tier_status"]["conversions_used"] == 3
        assert resp3.json()["free_tier_status"]["remaining_free_conversions"] == 0

        # Conversion 4 -> Must trigger limit_reached!
        resp4 = await client.post("/v1/gpt/convert", json=payload)
        assert resp4.status_code == 200
        data4 = resp4.json()
        assert data4["status"] == "limit_reached"
        assert data4["free_tier_status"]["limit_reached"] is True
        assert data4["download_url"] is None
        assert "Demo-Kontingent erreicht" in data4["message"]
        assert "starter" in data4["upgrade_info"]
        assert "pro" in data4["upgrade_info"]


@pytest.mark.asyncio
async def test_gpt_concurrent_quota_atomic_guard():
    """Architect G02: Verifies that concurrent requests at limit cannot race past the limit."""
    transport = ASGITransport(app=app)
    session_key = "test-session-concurrent-race"
    # Pre-set used count to 2 (only 1 remaining)
    gpt_free_tier_tracker.set(f"used_sess_{session_key}", 2)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": session_key,
            "transactions": [
                {"booking_date": "2026-03-01", "amount": -10.00, "description": "Item"}
            ]
        }

        # Fire 2 concurrent requests
        responses = await asyncio.gather(
            client.post("/v1/gpt/convert", json=payload),
            client.post("/v1/gpt/convert", json=payload)
        )
        statuses = [r.json().get("status") for r in responses]
        
        # Exactly one must succeed, and the second must be limit_reached!
        assert "success" in statuses
        assert "limit_reached" in statuses
        assert gpt_free_tier_tracker.get(f"used_sess_{session_key}") == 3


@pytest.mark.asyncio
async def test_gpt_invalid_date_rejected_422():
    """Architect G05: Invalid or unparseable dates must be rejected with 422, NEVER defaulting to today()."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": "test-invalid-date-01",
            "transactions": [
                {"booking_date": "not-a-date", "amount": -10.00, "description": "Invalid item"}
            ]
        }
        resp = await client.post("/v1/gpt/convert", json=payload)
        assert resp.status_code == 422
        assert "Ungültiges Datumsformat" in resp.json()["detail"] or "Fehlendes Datum" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_gpt_mixed_years_rejected_422():
    """Architect G05: DATEV export spanning multiple fiscal years must be rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": "test-mixed-years",
            "export_format": "datev",
            "transactions": [
                {"booking_date": "2025-12-31", "amount": -50.00, "description": "Old year"},
                {"booking_date": "2026-01-01", "amount": -60.00, "description": "New year"}
            ]
        }
        resp = await client.post("/v1/gpt/convert", json=payload)
        assert resp.status_code == 422
        assert "mehrere Geschäftsjahre" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_gpt_mixed_currencies_rejected_422():
    """Architect G05: Mixed currencies (e.g. EUR + USD) must be rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "session_id": "test-mixed-curr",
            "transactions": [
                {"booking_date": "2026-03-01", "amount": 10.00, "currency": "EUR", "description": "Euros"},
                {"booking_date": "2026-03-02", "amount": 20.00, "currency": "USD", "description": "Dollars"}
            ]
        }
        resp = await client.post("/v1/gpt/convert", json=payload)
        assert resp.status_code == 422
        assert "Gemischte Währungen" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_gpt_payload_and_row_budget_limits():
    """Architect G04: Input row count and raw content size limits must be enforced."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Test row limit
        old_rows_limit = settings.MAX_ROWS_PER_FILE
        settings.MAX_ROWS_PER_FILE = 2
        try:
            payload = {
                "session_id": "test-row-limit",
                "transactions": [
                    {"booking_date": "2026-03-01", "amount": 1.0, "description": f"Tx {i}"}
                    for i in range(3)
                ]
            }
            resp = await client.post("/v1/gpt/convert", json=payload)
            assert resp.status_code == 413
            assert "exceeds maximum allowed limit" in resp.json()["detail"]
        finally:
            settings.MAX_ROWS_PER_FILE = old_rows_limit

        # 2. Test raw content size limit
        old_file_size = settings.MAX_FILE_SIZE_BYTES
        settings.MAX_FILE_SIZE_BYTES = 40
        try:
            raw_text = "Buchungstag;Betrag;Waehrung;Verwendungszweck\n10.03.2026;-10,00;EUR;Test raw content limit\n"
            resp = await client.post("/v1/gpt/convert", json={
                "session_id": "test-raw-limit",
                "raw_content": raw_text
            })
            assert resp.status_code == 413
            assert "exceeds maximum limit" in resp.json()["detail"]
        finally:
            settings.MAX_FILE_SIZE_BYTES = old_file_size


@pytest.mark.asyncio
async def test_gpt_large_batch_omits_inline_base64():
    """Architect G06: Large batch (1500 rows) must omit inline base64 to keep response compact."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        txs = [
            {"booking_date": "2026-03-01", "amount": 1.0, "description": f"Row #{i}"}
            for i in range(150)  # > 100 rows threshold
        ]
        payload = {
            "session_id": "test-large-batch",
            "transactions": txs
        }
        resp = await client.post("/v1/gpt/convert", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["file_base64"] is None  # Base64 omitted
        assert data["download_url"] is not None
        # Verify JSON length is very compact (< 10k chars)
        assert len(resp.text) < 10000


@pytest.mark.asyncio
async def test_gpt_rejected_fake_and_canceled_licenses():
    """Architect G01: Fake prefixes like cs_live_* or canceled subscriptions must NOT grant Pro."""
    transport = ASGITransport(app=app)
    
    test_uid = uuid.uuid4().hex[:8]
    tenant_id = f"tenant_canceled_{test_uid}"
    email = f"canceled_{test_uid}@test.de"
    sub_id = f"sub_canceled_{test_uid}"
    
    # Create synthetic tenant with canceled subscription
    async with async_session_maker() as db:
        t = Tenant(id=tenant_id, email=email, name="Canceled User")
        db.add(t)
        ent = Entitlement(
            tenant_id=t.id,
            plan_code="pro",
            status="canceled",
            source_type="subscription",
            source_id=sub_id
        )
        db.add(ent)
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Fake cs_live prefix without auth
        resp1 = await client.post("/v1/gpt/convert", json={
            "session_id": "test-fake-key",
            "license_key": "cs_live_arbitrary_fake_12345",
            "transactions": [{"booking_date": "2026-03-01", "amount": -10, "description": "Item"}]
        })
        assert resp1.status_code == 200
        # Must be treated as unlicensed demo, NOT Pro!
        assert resp1.json()["free_tier_status"]["is_unlimited"] is False

        # 2. Canceled subscription sub_id
        resp2 = await client.post("/v1/gpt/convert", json={
            "session_id": "test-canceled-sub",
            "license_key": sub_id,
            "transactions": [{"booking_date": "2026-03-01", "amount": -10, "description": "Item"}]
        })
        assert resp2.status_code == 200
        assert resp2.json()["free_tier_status"]["is_unlimited"] is False


@pytest.mark.asyncio
async def test_gpt_auth_bearer_token_unified_quota():
    """Architect G02: Authenticated tenant uses check_and_reserve_quota with strict Starter limit."""
    transport = ASGITransport(app=app)
    test_uid = uuid.uuid4().hex[:8]
    tenant_id = f"tenant_starter_{test_uid}"
    email = f"starter_{test_uid}@test.de"
    
    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=email, name="Starter User")
        db.add(tenant)
        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code="starter",
            status="active",
            source_type="subscription",
            source_id=f"sub_starter_{test_uid}"
        )
        db.add(ent)
        await db.commit()

    token = create_access_token(user_id=email, tenant_id=tenant_id)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "transactions": [{"booking_date": "2026-03-01", "amount": -50, "description": "Starter Tx"}]
        }
        resp = await client.post("/v1/gpt/convert", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["free_tier_status"]["plan"] == "starter"

        # Verify quota committed in DB
        async with async_session_maker() as db:
            query = select(UsageReservation).where(UsageReservation.tenant_id == tenant_id)
            res = await db.execute(query)
            reservations = res.scalars().all()
            assert len(reservations) >= 1
            assert any(r.status == "COMMITTED" for r in reservations)


@pytest.mark.asyncio
async def test_gpt_revoked_token_in_body_rejected_401():
    """F01: Verify that a revoked token in license_key returns 401, not 200."""
    transport = ASGITransport(app=app)
    test_uid = uuid.uuid4().hex[:8]
    tenant_id = f"tenant_revoked_{test_uid}"
    email = f"revoked_{test_uid}@test.de"
    
    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=email, name="Revoked User")
        db.add(tenant)
        await db.commit()

    token = create_access_token(user_id=email, tenant_id=tenant_id)
    revoke_token(token)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Pass revoked token via header
        resp_hdr = await client.post("/v1/gpt/convert", 
            json={"session_id": "test-revoked-hdr", "transactions": [{"booking_date": "2026-03-01", "amount": -10, "description": "T"}]},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp_hdr.status_code == 401

        # Pass revoked token via license_key body
        resp_body = await client.post("/v1/gpt/convert", 
            json={"session_id": "test-revoked-body", "license_key": token, "transactions": [{"booking_date": "2026-03-01", "amount": -10, "description": "T"}]}
        )
        assert resp_body.status_code == 401


@pytest.mark.asyncio
async def test_gpt_different_inputs_same_session_separate_reservations():
    """F02: Different inputs in the same session create separate committed reservations."""
    transport = ASGITransport(app=app)
    test_uid = uuid.uuid4().hex[:8]
    tenant_id = f"tenant_multi_{test_uid}"
    email = f"multi_{test_uid}@test.de"
    
    now = datetime.datetime.now(datetime.timezone.utc)
    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=email, name="Multi User")
        db.add(tenant)
        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code="starter",
            status="active",
            source_type="subscription",
            source_id=f"sub_multi_{test_uid}",
            valid_until=now + datetime.timedelta(days=30),
            current_period_start=now - datetime.timedelta(days=1)
        )
        db.add(ent)
        await db.commit()

    token = create_access_token(user_id=email, tenant_id=tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = f"shared-sess-{test_uid}"
        for i in [10, 20, 30]:
            resp = await client.post("/v1/gpt/convert", json={
                "session_id": session_id,
                "transactions": [{"booking_date": "2026-03-10", "amount": -i, "description": f"Tx {i}"}]
            }, headers=headers)
            assert resp.status_code == 200

        async with async_session_maker() as db:
            query = select(UsageReservation).where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.status == "COMMITTED"
            )
            res = await db.execute(query)
            rows = res.scalars().all()
            assert len(rows) == 3
            # Each should have a distinct request_hash
            hashes = {r.request_hash for r in rows}
            assert len(hashes) == 3


@pytest.mark.asyncio
async def test_gpt_invalid_retry_does_not_mutate_prior_committed_ledger():
    """F02: An invalid request following successful ones does not release prior reservations."""
    transport = ASGITransport(app=app)
    test_uid = uuid.uuid4().hex[:8]
    tenant_id = f"tenant_retry_{test_uid}"
    email = f"retry_{test_uid}@test.de"
    
    now = datetime.datetime.now(datetime.timezone.utc)
    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=email, name="Retry User")
        db.add(tenant)
        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code="starter",
            status="active",
            source_type="subscription",
            source_id=f"sub_retry_{test_uid}",
            valid_until=now + datetime.timedelta(days=30),
            current_period_start=now - datetime.timedelta(days=1)
        )
        db.add(ent)
        await db.commit()

    token = create_access_token(user_id=email, tenant_id=tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = f"retry-sess-{test_uid}"
        # Successful request
        resp1 = await client.post("/v1/gpt/convert", json={
            "session_id": session_id,
            "transactions": [{"booking_date": "2026-03-10", "amount": -15, "description": "Good"}]
        }, headers=headers)
        assert resp1.status_code == 200

        # Invalid request in same session
        resp2 = await client.post("/v1/gpt/convert", json={
            "session_id": session_id,
            "transactions": [{"booking_date": "bad-date", "amount": -15, "description": "Bad"}]
        }, headers=headers)
        assert resp2.status_code == 422

        # Check ledger: first reservation must remain COMMITTED
        async with async_session_maker() as db:
            query = select(UsageReservation).where(UsageReservation.tenant_id == tenant_id)
            res = await db.execute(query)
            rows = res.scalars().all()
            assert len(rows) == 1
            assert rows[0].status == "COMMITTED"


@pytest.mark.asyncio
async def test_gpt_ambiguous_date_rejected():
    """F04: Ambiguous date format (with slashes) must be rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/v1/gpt/convert", json={
            "session_id": "test-ambiguous-date",
            "transactions": [{"booking_date": "03/04/2026", "amount": -10, "description": "Coffee"}]
        })
        assert resp.status_code == 422
        assert "Mehrdeutiges" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_gpt_oversized_account_rejected():
    """F03: Oversized/invalid default_bank_account is rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/v1/gpt/convert", json={
            "session_id": "test-bad-account",
            "default_bank_account": "1" * 40000,
            "transactions": [{"booking_date": "2026-03-10", "amount": -10, "description": "Coffee"}]
        })
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_gpt_distinct_accounts_same_request_id_conflict():
    """F02 (Decision 51): Distinct accounts under same request_id produce different hashes and 409 Conflict."""
    transport = ASGITransport(app=app)
    test_uid = uuid.uuid4().hex[:8]
    tenant_id = f"tenant_hash_{test_uid}"
    email = f"hash_{test_uid}@test.de"
    now = datetime.datetime.now(datetime.timezone.utc)

    async with async_session_maker() as db:
        db.add(Tenant(id=tenant_id, email=email))
        db.add(Entitlement(
            tenant_id=tenant_id, plan_code="starter", status="active",
            source_type="subscription", source_id=f"sub_hash_{test_uid}",
            current_period_start=now - datetime.timedelta(days=1),
            valid_until=now + datetime.timedelta(days=30)
        ))
        await db.commit()

    token = create_access_token(user_id=email, tenant_id=tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        p1 = {
            "session_id": f"sess_{test_uid}", "request_id": f"req_{test_uid}",
            "default_bank_account": "1200", "bank_name": "a",
            "transactions": [{"booking_date": "2026-03-10", "amount": -10, "description": "Synthetic"}]
        }
        p2 = {
            "session_id": f"sess_{test_uid}", "request_id": f"req_{test_uid}",
            "default_bank_account": "120", "bank_name": "0a",
            "transactions": [{"booking_date": "2026-03-10", "amount": -10, "description": "Synthetic"}]
        }
        r1 = await client.post("/v1/gpt/convert", json=p1, headers=headers)
        assert r1.status_code == 200

        r2 = await client.post("/v1/gpt/convert", json=p2, headers=headers)
        assert r2.status_code == 409
        assert "Idempotency key reused" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_gpt_completed_replay_returns_cached_or_410():
    """F02 (Decision 51): Completed replay returns cached response with same download_id; returns 410 on eviction."""
    transport = ASGITransport(app=app)
    test_uid = uuid.uuid4().hex[:8]
    tenant_id = f"tenant_replay_{test_uid}"
    email = f"replay_{test_uid}@test.de"
    now = datetime.datetime.now(datetime.timezone.utc)

    async with async_session_maker() as db:
        db.add(Tenant(id=tenant_id, email=email))
        db.add(Entitlement(
            tenant_id=tenant_id, plan_code="starter", status="active",
            source_type="subscription", source_id=f"sub_replay_{test_uid}",
            current_period_start=now - datetime.timedelta(days=1),
            valid_until=now + datetime.timedelta(days=30)
        ))
        await db.commit()

    token = create_access_token(user_id=email, tenant_id=tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        req_payload = {
            "session_id": f"sess_{test_uid}", "request_id": f"req_completed_{test_uid}",
            "transactions": [{"booking_date": "2026-03-10", "amount": -10, "description": "Synthetic"}]
        }
        # First call
        r1 = await client.post("/v1/gpt/convert", json=req_payload, headers=headers)
        assert r1.status_code == 200
        dl_id_1 = r1.json()["download_id"]

        # Second call (replay while cache is valid)
        r2 = await client.post("/v1/gpt/convert", json=req_payload, headers=headers)
        assert r2.status_code == 200
        dl_id_2 = r2.json()["download_id"]
        assert dl_id_1 == dl_id_2

        # Simulate cache eviction
        gpt_download_cache.clear()

        # Third call after eviction -> 410 Gone per Zero Durable Retention
        r3 = await client.post("/v1/gpt/convert", json=req_payload, headers=headers)
        assert r3.status_code == 410
        assert "abgelaufen" in r3.json()["detail"]


@pytest.mark.asyncio
async def test_gpt_many_validation_errors_truncated_under_platform_limit():
    """F03 (Decision 51): 600 validation errors are bounded in count and body size under OpenAI platform limit."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        invalid_payload = {
            "session_id": "test-many-errors",
            "transactions": [{"booking_date": "2026-03-10", "amount": "x", "description": "Synthetic"}] * 600
        }
        raw_json = json.dumps(invalid_payload, ensure_ascii=False)
        assert len(raw_json) > 40000

        resp = await client.post(
            "/v1/gpt/convert",
            content=raw_json.encode("utf-8"),
            headers={"content-type": "application/json"}
        )
        assert resp.status_code == 422
        # Response body must be strictly under 8,000 characters (platform limit 100k)
        assert len(resp.text) < 2000
        errors = resp.json()["detail"]
        assert len(errors) <= 6
        assert errors[-1]["type"] == "too_many_errors"

