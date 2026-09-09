import io
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.security import create_access_token
from app.db.session import async_session_maker
from app.db.models import Tenant

@pytest.mark.asyncio
async def test_healthz_liveness_readiness():
    """Verify container liveness and readiness probe /healthz."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert data["zero_retention"] == "enforced"

        # Also test alias /api/v1/healthz
        resp_alias = await client.get("/api/v1/healthz")
        assert resp_alias.status_code == 200

@pytest.mark.asyncio
async def test_cors_exposed_headers_includes_reconciliation():
    """Verify CORS configuration exposes X-Reconciliation-Status to web extensions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/health",
            headers={"Origin": "chrome-extension://dummyid"}
        )
        assert resp.status_code == 200
        exposed = resp.headers.get("access-control-expose-headers", "")
        assert "X-Reconciliation-Status" in exposed or "x-reconciliation-status" in exposed.lower()

@pytest.mark.asyncio
async def test_pilot_e2e_reconciliation_datev_and_bmd():
    """Full pilot workflow: RS256 Bearer Auth -> balanced Solldoppik statement -> DATEV EXTF & BMD NTCS export."""
    tenant_id = str(uuid.uuid4())
    user_email = f"pilot_{uuid.uuid4().hex[:8]}@kanzlei-muenchen.de"

    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=user_email)
        db.add(tenant)
        await db.commit()

    token = create_access_token(user_id=user_email, tenant_id=tenant_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Synthetic balanced VR-Bank CSV
    csv_content = (
        "Bezeichnung Auftragskonto;IBAN Auftragskonto;BIC Auftragskonto;Bankname;Buchungstag;Valutadatum;Name Zahlungsbeteiligter;IBAN Zahlungsbeteiligter;BIC (SWIFT-Code) Zahlungsbeteiligter;Buchungstext;Verwendungszweck;Betrag;Waehrung;Saldo nach Buchung;Bemerkung\n"
        "Girokonto;DE12345678901234567890;GENODED1VRB;VR-Bank;02.05.2026;02.05.2026;Kunde A;DE99887766554433221100;GENODED1VRB;Ueberweisung;Rechnung RE-101;500,00;EUR;1500,00;\n"
        "Girokonto;DE12345678901234567890;GENODED1VRB;VR-Bank;03.05.2026;03.05.2026;Lieferant B;DE11223344556677889900;GENODED1VRB;Lastschrift;Materialkauf;-200,00;EUR;1300,00;\n"
    ).encode("windows-1252")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Convert to DATEV EXTF
        files = [("files", ("vrbank_mai2026.csv", io.BytesIO(csv_content), "text/csv"))]
        resp_datev = await client.post("/api/v1/convert?format=datev", headers=auth_headers, files=files)
        assert resp_datev.status_code == 200
        assert resp_datev.headers.get("X-Reconciliation-Status") == "BALANCED"
        assert resp_datev.headers.get("X-Quota-Units") == "1"
        assert "EXTF" in resp_datev.headers.get("Content-Disposition", "")
        
        # Check DATEV EXTF header
        body_datev = resp_datev.content.decode("windows-1252")
        assert body_datev.startswith('"EXTF"')
        assert "Buchungsstapel" in body_datev
        assert "500,00" in body_datev
        assert "200,00" in body_datev

        # 2. Convert to BMD 5.1
        tenant_id_bmd = str(uuid.uuid4())
        user_email_bmd = f"pilot_bmd_{uuid.uuid4().hex[:8]}@kanzlei-wien.at"
        async with async_session_maker() as db:
            tenant_b = Tenant(id=tenant_id_bmd, email=user_email_bmd)
            db.add(tenant_b)
            await db.commit()
        token_bmd = create_access_token(user_id=user_email_bmd, tenant_id=tenant_id_bmd)

        files_bmd = [("files", ("vrbank_mai2026.csv", io.BytesIO(csv_content), "text/csv"))]
        resp_bmd = await client.post("/api/v1/convert?format=bmd", headers={"Authorization": f"Bearer {token_bmd}"}, files=files_bmd)
        assert resp_bmd.status_code == 200
        assert resp_bmd.headers.get("X-Reconciliation-Status") == "BALANCED"
        assert "BMD" in resp_bmd.headers.get("Content-Disposition", "")

        # Check BMD content
        body_bmd = resp_bmd.content.decode("windows-1252")
        assert "Satzart" in body_bmd
        assert "500,00" in body_bmd
        assert "-200,00" in body_bmd

@pytest.mark.asyncio
async def test_pilot_unsupported_format_safeguard():
    """Ensure invalid/corrupted files are rejected with HTTP 422 to protect accounting data."""
    tenant_id = str(uuid.uuid4())
    user_email = f"pilot_reject_{uuid.uuid4().hex[:8]}@kanzlei.de"
    async with async_session_maker() as db:
        tenant = Tenant(id=tenant_id, email=user_email)
        db.add(tenant)
        await db.commit()

    token = create_access_token(user_id=user_email, tenant_id=tenant_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Corrupted / unstructured text file
    junk_content = b"Random;Unstructured;Data;Without;Accounting;Meaning\nFoo;Bar;Baz;1;2;3\n"
    files = [("files", ("unknown.csv", io.BytesIO(junk_content), "text/csv"))]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/convert?format=datev", headers=auth_headers, files=files)
        assert resp.status_code == 422
        detail = resp.json().get("detail", "")
        assert "nicht unterstützt" in detail or "Keine Buchungssätze" in detail or "Unsupported" in detail
