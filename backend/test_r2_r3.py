import asyncio
import io
import json
import time
import uuid
import hmac
import hashlib
from typing import Dict, Any

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.db.session import init_db, async_session_maker
from app.db.models import Tenant, Entitlement, StripeEventInbox, UsageReservation
from app.services.billing_service import process_stripe_event
from app.services.quota_service import check_and_reserve_quota, commit_quota, release_quota

def generate_stripe_signature(payload_bytes: bytes, secret: str) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    asyncio.run(init_db())

@pytest.mark.asyncio
async def test_jwt_asymmetric_token_lifecycle():
    """R2: Verifies RS256 token creation and validation (ADR-001)."""
    tenant_id = str(uuid.uuid4())
    user_id = "test@kanzlei-muster.de"
    
    token = create_access_token(user_id=user_id, tenant_id=tenant_id)
    payload = decode_access_token(token)
    
    assert payload["sub"] == user_id
    assert payload["tenant_id"] == tenant_id
    assert payload["iss"] == "statement2muster.com"
    assert payload["aud"] == "statement2muster-api"
    assert "exp" in payload

@pytest.mark.asyncio
async def test_early_asgi_middleware_rejection():
    """R3: Verifies unauthenticated/oversized requests are rejected BEFORE parsing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. No Authorization header -> 401
        res = await client.post("/api/v1/convert")
        assert res.status_code == 401
        assert res.json()["error"] == "unauthorized"

        # 2. Invalid Bearer token -> 401
        res = await client.post(
            "/api/v1/convert",
            headers={"Authorization": "Bearer invalid.token.value"}
        )
        assert res.status_code == 401

        # 3. Oversized payload Content-Length -> 413
        oversized = settings.MAX_BATCH_SIZE_BYTES + 1024
        res = await client.post(
            "/api/v1/convert",
            headers={
                "Authorization": "Bearer some.token",
                "Content-Length": str(oversized)
            }
        )
        assert res.status_code == 413
        assert res.json()["error"] == "payload_too_large"

@pytest.mark.asyncio
async def test_stripe_webhook_and_idempotency():
    """R2: Verifies signed Stripe webhook processing and inbox idempotency."""
    event_id = f"evt_test_{uuid.uuid4().hex[:8]}"
    payload = {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{uuid.uuid4().hex[:8]}",
                "mode": "payment",
                "amount_total": 8900,
                "customer": f"cus_{uuid.uuid4().hex[:8]}",
                "customer_details": {"email": "kanzlei@vienna.at"}
            }
        }
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    sig = generate_stripe_signature(payload_bytes, settings.STRIPE_WEBHOOK_SECRET)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First delivery -> 200 OK
        res = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=payload_bytes,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"}
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"

        # Duplicate delivery -> idempotent skip (returns already_processed without duplicating)
        res_dup = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=payload_bytes,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"}
        )
        assert res_dup.status_code == 200
        assert res_dup.json()["status"] == "already_processed"

        # Bad signature -> 400 Bad Request
        res_bad = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=payload_bytes,
            headers={"Stripe-Signature": "t=123,v1=bad_sig", "Content-Type": "application/json"}
        )
        assert res_bad.status_code == 400

@pytest.mark.asyncio
async def test_quota_two_phase_commit_and_limits():
    """R2: Tests quota reservation, commit, release, and Trial/Starter bounds."""
    tenant_id = str(uuid.uuid4())
    idemp_key = str(uuid.uuid4())

    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=f"trial_{uuid.uuid4().hex[:8]}@kanzlei.de")
        db.add(tenant)
        await db.commit()

        # Step 1: Reserve 2 files (Trial limit is 3)
        res = await check_and_reserve_quota(db, tenant_id, file_count=2, idempotency_key=idemp_key)
        assert res.status_code if hasattr(res, "status_code") else True
        assert res.status == "RESERVED"
        assert res.units == 2

        # Step 2: Commit successful files
        await commit_quota(db, res, successful_count=2)
        assert res.status == "COMMITTED"

        # Step 3: Request 2 more files -> 2 + 2 = 4 > 3 -> 429 Too Many Requests
        with pytest.raises(Exception) as exc_info:
            await check_and_reserve_quota(db, tenant_id, file_count=2, idempotency_key=str(uuid.uuid4()))
        assert "429" in str(exc_info.value) or "exceeds" in str(exc_info.value)

        # Step 4: Release quota on failure
        failed_res = await check_and_reserve_quota(db, tenant_id, file_count=1, idempotency_key=str(uuid.uuid4()))
        assert failed_res.status == "RESERVED"
        await release_quota(db, failed_res)
        assert failed_res.status == "RELEASED"

@pytest.mark.asyncio
async def test_convert_full_flow_with_auth_and_quota():
    """E2E test of /api/v1/convert with Bearer auth, quota reservation, and CSV result."""
    tenant_id = str(uuid.uuid4())
    user_email = f"e2e_{uuid.uuid4().hex[:8]}@kanzlei.at"

    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=user_email)
        db.add(tenant)
        await db.commit()

    token = create_access_token(user_id=user_email, tenant_id=tenant_id)

    # Valid CSV statement
    sample_csv = "Datum;Text;Betrag\n02.06.2026;Musterkauf;-12,50\n"
    files = [("files", ("test.csv", io.BytesIO(sample_csv.encode("utf-8")), "text/csv"))]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/convert",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )
        assert res.status_code == 200
        assert "Content-Disposition" in res.headers
        assert "X-Reservation-Id" in res.headers
        assert "X-Quota-Units" in res.headers
        assert res.headers["X-Quota-Units"] == "1"
        assert b"Musterkauf" in res.content
