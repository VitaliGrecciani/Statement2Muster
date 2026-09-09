import io
import json
import uuid
import hashlib
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import async_session_maker, init_db
from app.db.models import Tenant, Entitlement, AuthChallenge
from app.services.quota_service import check_and_reserve_quota, get_or_create_trial_entitlement
from app.services.billing_service import process_stripe_event
from app.parsers.csv_parser import StructuredCsvParser
from app.parsers.amex_parser import AmexStatementParser
from app.exporters.muster_csv import export_to_muster_csv
from app.exporters.datev import export_to_datev_csv
from app.schemas.canonical import CanonicalTransaction
import csv

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    import asyncio
    asyncio.run(init_db())

@pytest.mark.asyncio
async def test_regression_1_auth_challenge_and_jwks():
    """
    Regression 1 (A01):
    - Email alone without proof-of-identity must be rejected (401).
    - Wrong code must be rejected (401).
    - Valid code generated via /request-code yields short-lived RS256 token.
    - Code cannot be reused (replay protection).
    - RFC 7517 JWKS available at /api/v1/auth/jwks.json and /auth/jwks.json.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        test_email = f"audit_{uuid.uuid4().hex[:8]}@kanzlei-muenchen.de"

        # 1. Without code -> 401 Unauthorized
        r1 = await c.post("/api/v1/auth/token", json={"email": test_email})
        assert r1.status_code == 401
        assert "code required" in r1.json()["detail"].lower()

        # 2. With invalid code -> 401 Unauthorized
        r2 = await c.post("/api/v1/auth/token", json={"email": test_email, "code": "000000"})
        assert r2.status_code == 401
        assert "invalid or expired" in r2.json()["detail"].lower()

        # 3. Request genuine code
        req_resp = await c.post("/api/v1/auth/request-code", json={"email": test_email})
        assert req_resp.status_code == 200
        assert req_resp.json()["status"] == "pending"

        # Retrieve challenge from DB
        async with async_session_maker() as db:
            ch = (await db.execute(
                select(AuthChallenge)
                .where(AuthChallenge.email == test_email, AuthChallenge.used == 0)
            )).scalars().first()
            assert ch is not None
            valid_code = ch.code

        # 4. Exchange valid code -> 200 OK with RS256 token
        r3 = await c.post("/api/v1/auth/token", json={"email": test_email, "code": valid_code})
        assert r3.status_code == 200
        token_data = r3.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "bearer"
        assert token_data["expires_in"] == 600

        # 5. Replay same code -> 401 Unauthorized (code used)
        r4 = await c.post("/api/v1/auth/token", json={"email": test_email, "code": valid_code})
        assert r4.status_code == 401

        # 6. Check JWKS endpoints
        jwks1 = await c.get("/api/v1/auth/jwks.json")
        assert jwks1.status_code == 200
        assert "keys" in jwks1.json()
        assert jwks1.json()["keys"][0]["kty"] == "RSA"
        assert jwks1.json()["keys"][0]["alg"] == "RS256"

        jwks2 = await c.get("/auth/jwks.json")
        assert jwks2.status_code == 200
        assert jwks2.json() == jwks1.json()

@pytest.mark.asyncio
async def test_regression_2_idempotency_payload_hash_and_parallel_quota():
    """
    Regression 2 (A02, A18):
    - Reusing same X-Idempotency-Key with different payload body returns 409 Conflict.
    - Concurrent / pending quota reservations count active RESERVED units to prevent race bypass.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        tid = str(uuid.uuid4())
        email = f"idemp_{uuid.uuid4().hex[:8]}@example.com"
        async with async_session_maker() as db:
            db.add(Tenant(id=tid, email=email))
            await db.commit()

        token = create_access_token(user_id=email, tenant_id=tid)
        headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": "idemp-test-key-1"}

        csv_body_1 = b"Datum;Text;Betrag\n01.01.2025;PayloadOne;10,00\n"
        csv_body_2 = b"Datum;Text;Betrag\n01.01.2025;PayloadTwo;20,00\n"

        # 1. First request with body 1 -> 200 OK
        r1 = await c.post(
            "/api/v1/convert?format=json",
            headers=headers,
            files={"files": ("test.csv", csv_body_1, "text/csv")}
        )
        assert r1.status_code == 200

        # 2. Replay with same key but CHANGED body -> 409 Conflict
        r2 = await c.post(
            "/api/v1/convert?format=json",
            headers=headers,
            files={"files": ("test.csv", csv_body_2, "text/csv")}
        )
        assert r2.status_code == 409
        assert "different request payload" in r2.json()["detail"].lower()

        # 3. Replay with same key and SAME body -> 200 OK (idempotent)
        r3 = await c.post(
            "/api/v1/convert?format=json",
            headers=headers,
            files={"files": ("test.csv", csv_body_1, "text/csv")}
        )
        assert r3.status_code == 200

    # 4. Parallel quota reservation check
    async with async_session_maker() as db:
        t2 = Tenant(email=f"parallel_{uuid.uuid4().hex[:8]}@example.com")
        db.add(t2)
        await db.flush()

        # First reservation of 3 units (trial allowance is 3) -> succeeds
        res1 = await check_and_reserve_quota(db, t2.id, 3, "res-key-1")
        assert res1.status == "RESERVED"

        # Second reservation of 3 units before commit -> must be rejected (403 or 429)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await check_and_reserve_quota(db, t2.id, 3, "res-key-2")
        assert exc_info.value.status_code in (403, 429)

@pytest.mark.asyncio
async def test_regression_3_stripe_lifecycle_fulfillment_and_refund():
    """
    Regression 3 (A03):
    - Unpaid checkout session (payment_status='unpaid') does NOT activate entitlement.
    - Duplicate webhook event does not duplicate entitlement.
    - Refund event cancels lifetime entitlement matching payment_intent.
    - Active paid entitlement prioritizes over trial.
    """
    async with async_session_maker() as db:
        test_email = f"billing_{uuid.uuid4().hex[:8]}@example.com"
        session_id = f"cs_{uuid.uuid4().hex}"
        pi_id = f"pi_{uuid.uuid4().hex}"

        # 1. Unpaid purchase -> rejected
        unpaid_obj = {
            "id": session_id,
            "mode": "payment",
            "amount_total": 8900,
            "currency": "eur",
            "payment_status": "unpaid",
            "payment_intent": pi_id,
            "customer_details": {"email": test_email}
        }
        await process_stripe_event(db, {
            "id": f"evt_unpaid_{uuid.uuid4().hex}",
            "type": "checkout.session.completed",
            "data": {"object": unpaid_obj}
        })
        ents = (await db.execute(select(Entitlement).where(Entitlement.source_id == session_id))).scalars().all()
        assert len(ents) == 0

        # 2. Paid purchase with unknown price (amount_total=1, currency='usd') -> rejected
        fake_obj = {
            "id": session_id,
            "mode": "payment",
            "amount_total": 1,
            "currency": "usd",
            "payment_status": "paid",
            "payment_intent": pi_id,
            "customer_details": {"email": test_email}
        }
        await process_stripe_event(db, {
            "id": f"evt_fake_{uuid.uuid4().hex}",
            "type": "checkout.session.completed",
            "data": {"object": fake_obj}
        })
        ents = (await db.execute(select(Entitlement).where(Entitlement.source_id == session_id))).scalars().all()
        assert len(ents) == 0

        # 3. Valid paid purchase (EUR 89.00 lifetime) -> activates
        valid_obj = {
            "id": session_id,
            "mode": "payment",
            "amount_total": 8900,
            "currency": "eur",
            "payment_status": "paid",
            "payment_intent": pi_id,
            "customer_details": {"email": test_email},
            "line_items": {"data": [{"price": {"id": "price_lifetime_8900"}}]}
        }
        # Process twice with different event IDs (duplicate webhook delivery)
        for i in range(2):
            await process_stripe_event(db, {
                "id": f"evt_valid_{i}_{uuid.uuid4().hex}",
                "type": "checkout.session.completed",
                "data": {"object": valid_obj}
            })

        ents = (await db.execute(select(Entitlement).where(Entitlement.source_id == session_id))).scalars().all()
        assert len(ents) == 1
        assert ents[0].plan_code == "lifetime"
        assert ents[0].status == "active"
        assert ents[0].payment_intent == pi_id

        # 4. Charge refund with payment_intent -> cancels entitlement
        await process_stripe_event(db, {
            "id": f"evt_refund_{uuid.uuid4().hex}",
            "type": "charge.refunded",
            "data": {"object": {"payment_intent": pi_id}}
        })
        refunded_ent = (await db.execute(select(Entitlement).where(Entitlement.source_id == session_id))).scalars().first()
        assert refunded_ent.status == "canceled"

        # 5. Plan priority: tenant with trial and active PRO gets PRO
        t_user = (await db.execute(select(Tenant).where(Tenant.email == test_email))).scalars().first()
        # Add trial
        db.add(Entitlement(tenant_id=t_user.id, plan_code="trial", status="active", source_type="trial"))
        # Add pro
        db.add(Entitlement(tenant_id=t_user.id, plan_code="pro", status="active", source_type="subscription", source_id="sub_pro_1"))
        await db.flush()

        effective_ent = await get_or_create_trial_entitlement(db, t_user.id)
        assert effective_ent.plan_code == "pro"

@pytest.mark.asyncio
async def test_regression_4_byte_budgets_chunked_and_per_file():
    """
    Regression 4 (A18):
    - Chunked stream exceeding MAX_BATCH_SIZE_BYTES returns 413.
    - File exceeding MAX_FILE_SIZE_BYTES returns 413.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        tid = str(uuid.uuid4())
        email = f"budget_{uuid.uuid4().hex[:8]}@kanzlei.at"
        token = create_access_token(user_id=email, tenant_id=tid)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Chunked stream test with reduced budget
        old_batch = settings.MAX_BATCH_SIZE_BYTES
        settings.MAX_BATCH_SIZE_BYTES = 100
        boundary = "TestBoundary123"
        csv_data = b"Datum;Text;Betrag\n01.01.2025;OversizedChunkedPayloadDataExceedingLimit;500,00\n"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"test.csv\"\r\nContent-Type: text/csv\r\n\r\n".encode()
            + csv_data + f"\r\n--{boundary}--\r\n".encode()
        )
        async def stream_chunks():
            yield body[:60]
            yield body[60:]

        res_chunked = await c.post(
            "/api/v1/convert?format=json",
            headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
            content=stream_chunks()
        )
        settings.MAX_BATCH_SIZE_BYTES = old_batch
        assert res_chunked.status_code == 413

        # 2. Per-file limit check
        old_file_limit = settings.MAX_FILE_SIZE_BYTES
        settings.MAX_FILE_SIZE_BYTES = 20
        res_file = await c.post(
            "/api/v1/convert?format=json",
            headers=headers,
            files={"files": ("oversized.csv", b"Datum;Text;Betrag\n01.01.2025;TooLongToBeAllowedUnderTwentyBytes;10,00\n", "text/csv")}
        )
        settings.MAX_FILE_SIZE_BYTES = old_file_limit
        assert res_file.status_code == 413

def test_regression_5_parsing_robustness_rollover_errors_and_currencies():
    """
    Regression 5 (A10, A11, A12):
    - Invalid calendar dates (31.02) must produce explicit row ERROR (not silently dropped).
    - Invalid amounts (garbage) must produce explicit row ERROR (not 0 VALID).
    - German 'S' suffix (debit) must produce negative amount_cents and balanced reconciliation.
    - 'Waehrung' column alias must be detected as USD (not EUR).
    - Multi-account statements must isolate each transaction's IBAN (no account mixing).
    """
    p = StructuredCsvParser()

    # 1. Invalid date (31.02)
    csv_date = b"Datum;Text;Betrag\n31.02.2025;Lost;10\n01.03.2025;Kept;20\n"
    txs, summary = p.parse_to_canonical(csv_date, "date_test.csv", "tenant_1")
    assert len(txs) == 2
    assert txs[0].validation_status == "ERROR"
    assert "Invalid calendar date" in txs[0].warnings[0]
    assert txs[1].validation_status == "VALID"
    assert txs[1].amount_cents == 2000

    # 2. Invalid amount (garbage)
    csv_amt = b"Datum;Text;Betrag\n01.01.2025;Synthetic;garbage\n"
    txs, _ = p.parse_to_canonical(csv_amt, "amt_test.csv", "tenant_1")
    assert len(txs) == 1
    assert txs[0].validation_status == "ERROR"
    assert "Unparseable numeric amount" in txs[0].warnings[0]

    # 3. S suffix (Soll / debit)
    csv_debit = b"Datum;Text;Betrag;Saldo\n01.01.2025;Synthetic;10,00 S;100,00\n"
    txs, summary = p.parse_to_canonical(csv_debit, "debit_test.csv", "tenant_1")
    assert len(txs) == 1
    assert txs[0].amount_cents == -1000  # Negative!
    from app.services.reconciliation_service import reconcile_account
    rec = reconcile_account(
        summary.account_id,
        summary.bank_name,
        txs,
        summary.opening_balance_cents,
        summary.closing_balance_cents
    )
    assert rec.reconciliation_status == "BALANCED"

    # 4. Currency alias (Waehrung = USD)
    csv_curr = b"Datum;Text;Betrag;Waehrung\n01.01.2025;Synthetic;10;USD\n"
    txs, _ = p.parse_to_canonical(csv_curr, "curr_test.csv", "tenant_1")
    assert txs[0].currency == "USD"

    # 5. Account mixing
    csv_acc = b"Datum;Text;Betrag;IBAN\n01.01.2025;One;10;SYNTHETIC_A\n02.01.2025;Two;20;SYNTHETIC_B\n"
    txs, _ = p.parse_to_canonical(csv_acc, "acc_test.csv", "tenant_1")
    assert txs[0].account_id == "SYNTHETIC_A"
    assert txs[1].account_id == "SYNTHETIC_B"

@pytest.mark.asyncio
async def test_regression_6_reconciliation_discrepancy_blocks_export():
    """
    Regression 6 (A15):
    - Discrepancy statements or batches with unparsed files are permitted in format=json for inspection,
      but MUST be blocked with HTTP 422 on formal accounting exports (datev, bmd, muster_csv).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        tid = str(uuid.uuid4())
        email = f"discrepancy_{uuid.uuid4().hex[:8]}@kanzlei.at"
        token = create_access_token(user_id=email, tenant_id=tid)
        headers = {"Authorization": f"Bearer {token}"}

        # CSV with discrepancy: Opening + Net != Closing
        # 100.00 - 20.00 = 80.00, but Saldo claims 70.00
        discrepancy_csv = (
            "Bezeichnung Auftragskonto;IBAN Auftragskonto;Bankname;Buchungstag;Buchungstext;Betrag;Waehrung;Saldo nach Buchung\n"
            "Konto;DE12345;Sparkasse;01.06.2026;Miete;-20,00;EUR;70,00\n"
            "Konto;DE12345;Sparkasse;02.06.2026;Gehalt;100,00;EUR;190,00\n"
        ).encode("windows-1252")

        # 1. format=json -> Allowed, returns DISCREPANCY status
        r_json = await c.post(
            "/api/v1/convert?format=json",
            headers=headers,
            files={"files": ("discrepancy.csv", discrepancy_csv, "text/csv")}
        )
        assert r_json.status_code == 200
        assert r_json.json()["overall_reconciliation"] == "DISCREPANCY"

        # 2. format=datev -> BLOCKED with 422
        r_datev = await c.post(
            "/api/v1/convert?format=datev",
            headers=headers,
            files={"files": ("discrepancy.csv", discrepancy_csv, "text/csv")}
        )
        assert r_datev.status_code == 422
        assert "export blocked" in r_datev.json()["detail"].lower()

        # 3. format=bmd -> BLOCKED with 422
        r_bmd = await c.post(
            "/api/v1/convert?format=bmd",
            headers=headers,
            files={"files": ("discrepancy.csv", discrepancy_csv, "text/csv")}
        )
        assert r_bmd.status_code == 422

def test_regression_7_csv_quoting_sanitization_and_datev_header():
    """
    Regression 7 (A13, A14, A24):
    - Muster CSV with semicolons in references maintains exactly 6 columns.
    - Formulas starting with '=' are sanitized against CWE-1236 injection.
    - DATEV export sets Wirtschaftsjahr from transaction dates (e.g. 2025).
    - DATEV S/H indicators: positive = 'S' (Soll), negative = 'H' (Haben) on bank account 1200.
    """
    tx1 = CanonicalTransaction(
        tenant_id="t1",
        booking_date=datetime.date(2025, 1, 1),
        amount_cents=1000,
        currency="EUR",
        description="=1+1",
        reference="REF;BROKEN"
    )
    tx2 = CanonicalTransaction(
        tenant_id="t1",
        booking_date=datetime.date(2025, 1, 2),
        amount_cents=-2500,
        currency="EUR",
        description="Office Expense",
        reference="NORMAL-REF"
    )

    # 1. Muster CSV Export
    muster_bytes = export_to_muster_csv([tx1, tx2])
    muster_text = muster_bytes.decode("windows-1252")

    # Verify column count in all rows
    reader = csv.reader(io.StringIO(muster_text), delimiter=";")
    for row in reader:
        assert len(row) == 6, f"Row has wrong column count: {row}"

    # Verify formula injection sanitization
    assert ";=1+1;" not in muster_text
    assert ";'=1+1;" in muster_text

    # 2. DATEV EXTF Export
    datev_bytes = export_to_datev_csv([tx1, tx2])
    datev_text = datev_bytes.decode("windows-1252")
    lines = datev_text.splitlines()

    # Verify header fiscal year is 2025
    assert "20250101" in lines[0]

    # Verify S/H indicators for active bank account (1200)
    # tx1 (+10.00 EUR Gutschrift) -> Soll ('S')
    assert '"10,00";"S";"EUR"' in lines[2]
    # tx2 (-25.00 EUR Lastschrift) -> Haben ('H')
    assert '"25,00";"H";"EUR"' in lines[3]
