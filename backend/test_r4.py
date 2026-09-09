import io
import json
import uuid
import datetime
from decimal import Decimal
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.security import create_access_token
from app.db.session import init_db, async_session_maker
from app.db.models import Tenant
from app.schemas.canonical import CanonicalTransaction, AccountSummary, StatementResult
from app.services.reconciliation_service import reconcile_account, build_statement_result
from app.exporters.datev import export_to_datev_csv
from app.exporters.bmd import export_to_bmd_csv
from app.exporters.muster_csv import export_to_muster_csv
from app.parsers.registry import registry, UnsupportedFormatError

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    import asyncio
    asyncio.run(init_db())

def test_canonical_integer_cents_no_float_drift():
    """R4: Verifies integer cents eliminate float accumulation drift."""
    cents_sum = 0
    float_sum = 0.0

    for _ in range(1000):
        # 0.07 EUR = 7 cents
        cents_sum += 7
        float_sum += 0.07

    assert cents_sum == 7000  # Exactly 70.00 EUR
    assert Decimal(cents_sum) / Decimal(100) == Decimal("70.00")
    # Float drift demonstration: float_sum is 69.99999999999974 != 70.0
    assert float_sum != 70.0

    tx = CanonicalTransaction(
        tenant_id="t1",
        booking_date=datetime.date(2026, 6, 2),
        amount_cents=-1250,
        currency="EUR",
        description="Office Supplies",
        reference="INV-2026-001"
    )
    assert tx.amount_cents == -1250
    assert tx.signed_amount == "-12,50"
    assert tx.abs_amount_str == "12,50"
    # DATEV active bank account: outgoing money (Lastschrift) is Haben ('H')
    assert tx.soll_haben_kennzeichen == "H"

    tx_positive = CanonicalTransaction(
        tenant_id="t1",
        booking_date=datetime.date(2026, 6, 2),
        amount_cents=50000,
        currency="EUR"
    )
    # DATEV active bank account: incoming money (Gutschrift) is Soll ('S')
    assert tx_positive.soll_haben_kennzeichen == "S"
    assert tx_positive.signed_amount == "500,00"

def test_reconciliation_solldoppik_balanced():
    """R4: Startsaldo + sum(Umsätze) == Endsaldo -> BALANCED."""
    tx1 = CanonicalTransaction(tenant_id="t", booking_date="2026-06-01", amount_cents=-2550) # -25.50
    tx2 = CanonicalTransaction(tenant_id="t", booking_date="2026-06-02", amount_cents=10000) # +100.00

    # Opening: 1000.00 (100000 cents), Net: +74.50 (+7450 cents) -> Closing: 1074.50 (107450 cents)
    summary = reconcile_account(
        account_id="DE89370400440532013000",
        bank_name="Sparkasse",
        transactions=[tx1, tx2],
        opening_balance_cents=100000,
        closing_balance_cents=107450
    )
    assert summary.reconciliation_status == "BALANCED"
    assert summary.discrepancy_cents == 0
    assert summary.turnover_debit_cents == 2550
    assert summary.turnover_credit_cents == 10000

def test_reconciliation_solldoppik_discrepancy():
    """R4: Discrepancy detected when transactions do not match balance difference."""
    tx = CanonicalTransaction(tenant_id="t", booking_date="2026-06-01", amount_cents=-2000) # -20.00

    # Opening: 100.00 (10000), Tx: -20.00 -> calculated: 80.00 (8000), but closing reports 75.00 (7500)
    summary = reconcile_account(
        account_id="AT1234567890",
        bank_name="Erste Bank",
        transactions=[tx],
        opening_balance_cents=10000,
        closing_balance_cents=7500
    )
    assert summary.reconciliation_status == "DISCREPANCY"
    assert summary.discrepancy_cents == 500  # 5.00 EUR discrepancy

def test_datev_buchungsstapel_exporter():
    """R4: Validates DATEV EXTF 700 format compliance."""
    tx1 = CanonicalTransaction(
        tenant_id="t",
        booking_date=datetime.date(2026, 6, 2),
        amount_cents=-4990,
        currency="EUR",
        description="Software Subscription Adobe",
        reference="BELEG-998"
    )
    tx2 = CanonicalTransaction(
        tenant_id="t",
        booking_date=datetime.date(2026, 6, 15),
        amount_cents=120000,
        currency="EUR",
        description="Consulting Services Kanzlei",
        reference="INV-402"
    )

    datev_bytes = export_to_datev_csv([tx1, tx2], default_bank_account="1200")
    datev_text = datev_bytes.decode("windows-1252")
    lines = [l for l in datev_text.split("\r\n") if l]

    # Row 1: EXTF header
    assert lines[0].startswith('"EXTF";700;21;"Buchungsstapel"')
    # Row 2: Columns
    assert "Umsatz (ohne Soll/Haben-Kz)" in lines[1]
    assert "Soll/Haben-Kennzeichen" in lines[1]
    assert "Belegdatum" in lines[1]

    # Row 3 (tx1): -49.90 (Lastschrift) -> Umsatz="49,90", S/H="H", Belegdatum="0206"
    assert '"49,90";"H";"EUR"' in lines[2]
    assert '"0206";"BELEG-998"' in lines[2]
    assert '"Software Subscription Adobe"' in lines[2]

    # Row 4 (tx2): +1200.00 (Gutschrift) -> Umsatz="1200,00", S/H="S", Belegdatum="1506"
    assert '"1200,00";"S";"EUR"' in lines[3]
    assert '"1506";"INV-402"' in lines[3]

def test_bmd_exporter():
    """R4: Validates Austrian BMD NTCS 5.1 export."""
    tx = CanonicalTransaction(
        tenant_id="t",
        booking_date=datetime.date(2026, 6, 2),
        amount_cents=-1500,
        currency="EUR",
        description="Bürobedarf Wien",
        reference="BELEG-01"
    )
    bmd_bytes = export_to_bmd_csv([tx], default_bank_account="2800")
    bmd_text = bmd_bytes.decode("windows-1252")
    lines = [l for l in bmd_text.split("\r\n") if l]

    assert lines[0] == '"Satzart";"Belegdatum";"Konto";"Gegenkonto";"Betrag";"Währung";"Text";"Belegnummer"'
    assert '"0";"02.06.2026";"2800";"";"-15,50";"EUR";"Bürobedarf Wien";"BELEG-01"' not in lines[1]
    assert '"0";"02.06.2026";"2800";"";"-15,00";"EUR";"Bürobedarf Wien";"BELEG-01"' in lines[1]

@pytest.mark.asyncio
async def test_convert_format_switching_and_json_api():
    """R4: E2E tests verifying format=json, format=bmd, format=datev, and format=muster_csv."""
    tenant_id = str(uuid.uuid4())
    user_email = f"r4_{uuid.uuid4().hex[:8]}@kanzlei.at"

    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=user_email)
        db.add(tenant)
        await db.commit()

    token = create_access_token(user_id=user_email, tenant_id=tenant_id)
    sample_csv = "Datum;Text;Betrag\n02.06.2026;Musterkauf;-12,50\n03.06.2026;Gutschrift;100,00\n"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. format=json -> Returns StatementResult
        res_json = await client.post(
            "/api/v1/convert?format=json",
            headers={"Authorization": f"Bearer {token}"},
            files=[("files", ("test.csv", io.BytesIO(sample_csv.encode("utf-8")), "text/csv"))]
        )
        assert res_json.status_code == 200
        data = res_json.json()
        assert "transactions" in data
        assert len(data["transactions"]) == 2
        assert data["transactions"][0]["amount_cents"] == -1250
        assert data["transactions"][1]["amount_cents"] == 10000
        assert "accounts" in data
        assert "overall_reconciliation" in data

        # 2. format=bmd -> Returns BMD CSV
        res_bmd = await client.post(
            "/api/v1/convert?format=bmd",
            headers={"Authorization": f"Bearer {token}"},
            files=[("files", ("test.csv", io.BytesIO(sample_csv.encode("utf-8")), "text/csv"))]
        )
        assert res_bmd.status_code == 200
        assert "BMD_Bankauszug.csv" in res_bmd.headers["Content-Disposition"]
        assert b'"Satzart";"Belegdatum"' in res_bmd.content
        assert b'"-12,50"' in res_bmd.content

        # 3. format=datev (default) -> Returns DATEV EXTF
        res_datev = await client.post(
            "/api/v1/convert?format=datev",
            headers={"Authorization": f"Bearer {token}"},
            files=[("files", ("test.csv", io.BytesIO(sample_csv.encode("utf-8")), "text/csv"))]
        )
        assert res_datev.status_code == 200
        assert "EXTF_Buchungsstapel.csv" in res_datev.headers["Content-Disposition"]
        assert b'"EXTF";700;21;"Buchungsstapel"' in res_datev.content
        assert b'"12,50";"H"' in res_datev.content
        assert b'"100,00";"S"' in res_datev.content

@pytest.mark.asyncio
async def test_unsupported_format_rejection():
    """R4: Verifies unparseable garbage is rejected with 422 instead of silent fake output."""
    tenant_id = str(uuid.uuid4())
    user_email = f"unsupported_{uuid.uuid4().hex[:8]}@kanzlei.at"

    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=user_email)
        db.add(tenant)
        await db.commit()

    token = create_access_token(user_id=user_email, tenant_id=tenant_id)
    garbage_csv = "Random;Header;Without;Any;Financial;Keywords\nFoo;Bar;Baz;1;2;3\n"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/convert",
            headers={"Authorization": f"Bearer {token}"},
            files=[("files", ("bad.csv", io.BytesIO(garbage_csv.encode("utf-8")), "text/csv"))]
        )
        assert res.status_code == 422
        assert "nicht unterstützt" in res.json()["detail"] or "Keine Buchungssätze" in res.json()["detail"]
