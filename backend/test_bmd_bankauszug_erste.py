import asyncio
import csv
import datetime
import io
import json
import subprocess
import time
import uuid
from typing import Dict, List, Optional, Tuple

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.db.models import Entitlement, Tenant, UsageReservation
from app.db.session import async_session_maker, init_db
from app.exporters.bmd_bankauszug import BMD_BANKAUSZUG_HEADERS, export_to_bmd_bankauszug_csv
from app.exporters.formats import normalize_format_key
from app.main import app, canonical_operation_cache
from app.parsers.amex_parser import AmexStatementParser, UniversalBankStatementParser
from app.parsers.csv_parser import StructuredCsvParser
from app.parsers.erste_parser import (
    ErsteBankAustriaParser,
    ErsteVisaCardParser,
    is_valid_iban,
    parse_strict_dmy,
    parse_strict_eur_cents,
)
from app.parsers.registry import registry
from app.schemas.canonical import AccountSummary, CanonicalTransaction
from app.services.parser_process_supervisor import ParserProcessSupervisor
from app.services.reconciliation_service import build_statement_result


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    asyncio.run(init_db())


def make_valid_at_iban(bank_code: str = "20111", acct_digits: str = "00000012345") -> str:
    """Computes a synthetic 20-char Austrian IBAN passing ISO 7064 mod-97 == 1."""
    bban = f"{bank_code}{acct_digits}"
    assert len(bban) == 16
    rearranged = bban + "AT00"
    num = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    check = 98 - (int(num) % 97)
    iban = f"AT{check:02d}{bban}"
    assert is_valid_iban(iban)
    return iban


def _pdf_escape(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")
    out = bytearray()
    for b in raw:
        if b in (ord("\\"), ord("("), ord(")")):
            out.append(ord("\\"))
        out.append(b)
    return bytes(out)


def build_vector_pdf(pages_spec: List[List[Tuple[float, float, str]]]) -> bytes:
    """
    Minimal pure-Python vector PDF 1.4 generator with Helvetica + WinAnsiEncoding.
    Each page is a list of (x, y_top, text) in A4 points (595x842, origin top-left).
    An empty page [] produces 0 extracted characters (simulating a raster/scanned page).
    """
    objects: List[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add_obj(b"")
    pages_id = add_obj(b"")
    font_id = add_obj(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )

    page_ids: List[int] = []
    for items in pages_spec:
        stream_parts: List[bytes] = []
        for x, y_top, text in items:
            y_pdf = 842.0 - float(y_top)
            esc = _pdf_escape(text)
            stream_parts.append(
                f"BT /F1 9 Tf 1 0 0 1 {x:.2f} {y_pdf:.2f} Tm (".encode("ascii")
                + esc
                + b") Tj ET\n"
            )
        stream_bytes = b"".join(stream_parts)
        content_id = add_obj(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"endstream"
        )
        pid = add_obj(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode("ascii")
        )
        page_ids.append(pid)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: List[int] = [0]
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf.extend(f"{idx} 0 obj\n".encode("ascii"))
        buf.extend(body)
        buf.extend(b"\nendobj\n")

    xref_pos = len(buf)
    buf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(buf)


def _fmt_at_amt(cents: int, trailing_minus: bool = True, explicit_plus: bool = False) -> str:
    sign = "-" if cents < 0 else ("+" if explicit_plus and cents > 0 else "")
    ac = abs(cents)
    euros, rem = divmod(ac, 100)
    euro_s = f"{euros:,}".replace(",", ".")
    if cents < 0 and trailing_minus:
        return f"{euro_s},{rem:02d}-"
    return f"{sign}{euro_s},{rem:02d}"


def build_synthetic_erste_bank_6page_pdf(
    iban: str,
    currency: str = "EUR",
    duplicate_seg_num: bool = False,
    include_scan_page: bool = False,
    invalid_valuta_date: Optional[str] = None,
    ambiguous_amount: Optional[str] = None,
    balance_mismatch: bool = False,
) -> bytes:
    """
    Builds a 6-page vector PDF mimicking Erste Bank Digitales Banking (Kontoauszug)
    with chained segments Nr. 029/2026 .. Nr. 034/2026, Alter/Neuer Kontostand,
    01.09.2026 * valuta dates, trailing minus, Abschlussbuchung header + 6 fee rows.
    """
    pages: List[List[Tuple[float, float, str]]] = []
    # Segment balances starting at 1000.00 EUR (100000 cents)
    cur_bal = 100000
    seg_specs = [
        # (seg_num, [(line1, extra_lines, valuta, cents)])
        (
            29,
            [
                ("SEPA-Überweisung Onlinebanking", ["Partner Alpha GmbH", "RE-2026-101 Software"], "01.09.2026 *", -7200),
                ("Gutschrift Kundenzahlung", ["Musterkunde Beta KG", "Honorar Sept"], "02.09.2026", 50000),
            ],
        ),
        (
            30,
            [
                ("Lastschrift Energieversorger", ["Energie Nord AG", "Referenz 998811"], "08.09.2026", -125000),
                ("Bankomat-Behebung", ["Kartenendnummer 8899"], "09.09.2026", -4000),
            ],
        ),
        (
            29 if duplicate_seg_num else 31,
            [
                ("Überweisung Eingang", ["Delta Consulting GmbH", "Umlautprüfung äöüß"], "15.09.2026", 29483),
            ],
        ),
        (
            32,
            [
                ("Online-Kauf SaaS", ["SaaS Cloud Ltd"], "20.09.2026", -1999),
            ],
        ),
        (
            33,
            [
                ("Lastschrift Versicherung", ["Assekuranz Beispiel AG"], invalid_valuta_date or "24.09.2026", -8500),
            ],
        ),
        (
            34,
            [
                ("Buchungsgebühr Überweisungen", [], "30.09.2026", -450),
                ("Kontoführungsentgelt", [], "30.09.2026", -1200),
                ("Porto und Spesen", [], "30.09.2026", -120),
                ("Kartengebühr Business", [], "30.09.2026", -300),
                ("Telefonbanking Entgelt", [], "30.09.2026", -90),
                ("Sollzinsen Abschluss", [], "30.09.2026", -24),
            ],
        ),
    ]

    for idx, (seg_num, entries) in enumerate(seg_specs, start=1):
        if include_scan_page and idx == 2:
            pages.append([])  # Simulated raster/scanned page (0 chars)
            continue

        open_bal = cur_bal
        seg_sum = sum(e[3] for e in entries)
        close_bal = (open_bal + seg_sum + 999) if (balance_mismatch and idx == 1) else (open_bal + seg_sum)
        cur_bal = open_bal + seg_sum

        items: List[Tuple[float, float, str]] = [
            (45, 45, "Erste Bank der oesterreichischen Sparkassen AG"),
            (400, 45, "GIBAATWW"),
            (45, 65, f"KONTOAUSZUG Nr. {seg_num:03d}/2026"),
            (45, 82, "Musterfirma Holding GmbH"),
            (45, 95, "zuletzt gültiger Kontowortlaut"),
            (45, 112, f"IBAN: {iban}"),
            (45, 130, f"Alter Kontostand {_fmt_at_amt(open_bal, trailing_minus=True)}"),
            (45, 155, "Buchungstext"),
            (365, 155, "Valuta/Value"),
            (465, 155, f"Beträge/Amounts in {currency}"),
        ]

        y = 180.0
        if seg_num == 34:
            # Put non-booking header line right before the 6 fee rows
            items.append((45, y, "*** Abschlussbuchung per 30.09.2026 ****"))
            items.append((365, y, "30.09.2026"))
            y += 14.0
            items.append((45, y, "Reklamationen bezüglich Entgelten innerhalb 6 Monate"))
            y += 16.0

        for tx_idx, (line1, extras, valuta, cents) in enumerate(entries):
            amt_s = ambiguous_amount if (ambiguous_amount and idx == 1 and tx_idx == 0) else _fmt_at_amt(cents, trailing_minus=True)
            items.append((45, y, line1))
            items.append((365, y, valuta))
            items.append((475, y, amt_s))
            y += 13.0
            for ex in extras:
                items.append((55, y, ex))
                y += 12.0
            y += 4.0

        items.append((45, y + 12.0, f"Neuer Kontostand/New Balance {_fmt_at_amt(close_bal, trailing_minus=True)}"))
        pages.append(items)

    return build_vector_pdf(pages)


def build_synthetic_erste_visa_pdf(
    card_num: str = "400000XXXXXX9999",
    include_fx: bool = True,
    balanced: bool = True,
) -> bytes:
    """
    Builds a synthetic s Visa Card Business Gold MONATSRECHNUNG PDF matching real column coordinates.
    """
    # Opening -100,00 EUR; Payment +160,99 EUR; Purchases -18,00 EUR & -42,99 EUR => Closing 0,00 EUR
    opening_s = "100,00-"
    closing_s = "0,00" if balanced else "15,00-"
    items: List[Tuple[float, float, str]] = [
        (30, 45, "Erste Bank s Visa Card Business Gold"),
        (30, 65, "MONATSRECHNUNG"),
        (30, 82, f"Kartennummer / Card Number {card_num}"),
        (30, 98, "Beispiel Holding GmbH"),
        (30, 110, "zuletzt gültiger Kontowortlaut"),
        (30, 126, f"Offener Betrag Vormonat {opening_s}"),
        (30, 145, "Kauf"),
        (85, 145, "Buchung"),
        (145, 145, "Vertragsunternehmen"),
        (260, 145, "Ort"),
        (325, 145, "Betrag Fremdw."),
        (390, 145, "FW-Kurs"),
        (445, 145, "Entgelt"),
        (500, 145, "Betrag EUR"),
        # Row 1: Payment / Einzug
        (30, 170, "02.09.2026"),
        (85, 170, "03.09.2026"),
        (145, 170, "Lastschrift Einzug Bankkonto"),
        (510, 170, "160,99+"),
        # Row 2: Local merchant
        (30, 190, "10.09.2026"),
        (85, 190, "11.09.2026"),
        (145, 190, "Cloud Service GmbH"),
        (260, 190, "Wien"),
        (510, 190, "18,00-"),
    ]
    y = 210.0
    if include_fx:
        items.extend([
            (30, y, "14.09.2026"),
            (85, y, "15.09.2026"),
            (145, y, "US Tool Corp"),
            (260, y, "SanFrancisco"),
            (325, y, "49,00 USD"),
            (390, y, "1.1567"),
            (445, y, "0.64"),
            (510, y, "42,99-"),
        ])
        y += 20.0

    items.extend([
        (30, y + 10.0, f"Offener Betrag / Outstanding balance {closing_s}"),
        (30, y + 28.0, "Einzugsbetrag am 05.10.2026: 0,00"),
    ])
    return build_vector_pdf([items])


# ---------------------------------------------------------------------------
# 1. BMD Bankauszug 22-column CSV specification tests
# ---------------------------------------------------------------------------

def test_bmd_bankauszug_22col_schema_bom_crlf_quoting_and_partner():
    txs = [
        CanonicalTransaction(
            tenant_id="t1",
            booking_date=datetime.date(2026, 9, 1),
            value_date=datetime.date(2026, 9, 2),
            partner="Partner Alpha GmbH",
            partner_iban="AT611904300234573201",
            description="Partner Alpha GmbH - RE-2026-101 Software; Liz",
            amount_cents=-123456,
            currency="EUR",
            reference="ERS-029-1",
            account_id="AT112011100000001234",
            foreign_currency="USD",
            foreign_amount_cents=-140000,
        ),
        CanonicalTransaction(
            tenant_id="t1",
            booking_date=datetime.date(2026, 9, 2),
            partner="Eigenkonto GmbH",
            partner_iban="AT112011100000001234",  # Equal to account_id -> must be stripped!
            description="=1+1; =CMD|test",  # CWE-1236 injection vector
            amount_cents=0,  # Zero guard must emit '0,00' not '-0,00'
            currency="EUR",
            reference="=REF",
            account_id="AT112011100000001234",
        ),
    ]

    raw_bytes = export_to_bmd_bankauszug_csv(txs)
    # Must start with UTF-8 BOM (EF BB BF)
    assert raw_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw_bytes

    decoded = raw_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(decoded), delimiter=";")
    rows = list(reader)
    assert len(rows) == 3
    assert rows[0] == BMD_BANKAUSZUG_HEADERS
    assert len(rows[0]) == 22

    # Verify QUOTE_MINIMAL on plain fields (dates, currency, amounts unquoted)
    first_data_line = decoded.split("\r\n")[1]
    assert first_data_line.startswith("01.09.2026;")

    r1 = rows[1]
    assert len(r1) == 22
    assert r1[0] == "01.09.2026"
    # Partner prefix stripped from purpose to avoid duplication
    assert r1[1] == "RE-2026-101 Software; Liz"
    assert r1[2] == "Partner Alpha GmbH"
    assert r1[3] == "AT611904300234573201"
    assert r1[4] == "USD"
    assert r1[5] == "-1400,00"
    assert r1[6] == "EUR"
    assert r1[7] == "-1234,56"  # No thousands separator, signed comma decimal
    assert r1[8] == "-1234,56"  # Booking Amount (EUR-settled)
    # Cols 10..22 (indices 9..21) empty to avoid field pollution
    assert all(cell == "" for cell in r1[9:22])

    r2 = rows[2]
    assert len(r2) == 22
    assert r2[3] == ""  # Self-IBAN stripped
    assert r2[1].startswith("'=")  # CWE-1236 neutralized
    assert r2[7] == "0,00"  # Zero guard
    assert r2[8] == "0,00"


# ---------------------------------------------------------------------------
# 2. Erste Bank Digitales Banking 6-page vector PDF & Valuta opt-in gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_erste_bank_6p_valuta_opt_in_and_quota_protection():
    iban = make_valid_at_iban()
    pdf_bytes = build_synthetic_erste_bank_6page_pdf(iban=iban)

    # First check direct parser unit behavior: 6 segments, 13 txs (including 6 fees, header skipped)
    parser = ErsteBankAustriaParser()
    res_no_val = parser.parse_with_metadata(pdf_bytes, "erste_6p.pdf", use_valuta_as_booking_date=False)
    assert res_no_val["account_id"] == iban
    assert res_no_val["segments_count"] == 6
    assert len(res_no_val["transactions"]) == 13
    assert res_no_val["transactions"][0]["Belegdatum"] == ""
    assert res_no_val["transactions"][0]["Valutadatum"] == "01.09.2026"
    assert res_no_val["transactions"][0]["Partner"] == "Partner Alpha GmbH"
    # Partner must NOT be duplicated in Buchungstext when classified as Partner
    assert "Partner Alpha" not in res_no_val["transactions"][0]["Buchungstext"]
    # Abschlussbuchung header must be skipped while its 6 fee rows are kept
    texts = [t["Buchungstext"] for t in res_no_val["transactions"]]
    assert not any("Abschlussbuchung" in txt for txt in texts)
    assert any("Buchungsgebühr Überweisungen" in txt for txt in texts)
    assert any("Sollzinsen Abschluss" in txt for txt in texts)

    # Now test via full HTTP API & quota DB tracking
    from app.services.quota_service import get_or_create_trial_entitlement
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        tid = str(uuid.uuid4())
        email = f"erste_test_{uuid.uuid4().hex[:8]}@kanzlei-wien.at"
        async with async_session_maker() as db:
            db.add(Tenant(id=tid, email=email))
            await db.flush()
            await get_or_create_trial_entitlement(db, tid)
            await db.commit()

        token = create_access_token(user_id=email, tenant_id=tid)
        headers = {"Authorization": f"Bearer {token}"}

        # Case A: default use_valuta_as_booking_date=False with bmd_bankauszug -> MUST return 422 and NOT deduct quota!
        r_blocked = await c.post(
            "/api/v1/convert?format=bmd_bankauszug",
            headers=headers,
            files={"files": ("erste_6p.pdf", pdf_bytes, "application/pdf")},
        )
        assert r_blocked.status_code == 422
        assert "valuta" in r_blocked.json()["detail"].lower()

        async with async_session_maker() as db:
            committed_units = (await db.execute(
                select(func.coalesce(func.sum(UsageReservation.units), 0))
                .where(UsageReservation.tenant_id == tid, UsageReservation.status == "COMMITTED")
            )).scalar()
            active_units = (await db.execute(
                select(func.coalesce(func.sum(UsageReservation.units), 0))
                .where(UsageReservation.tenant_id == tid, UsageReservation.status.in_(["COMMITTED", "RESERVED"]))
            )).scalar()
            assert committed_units == 0  # 422 MUST NOT consume quota!
            assert active_units == 0     # Reservation must be cleanly RELEASED!

        # Case B1: format=json WITHOUT target_format -> 200 diagnostic preview, operation_id=None, 0 quota committed!
        r_json_no_val = await c.post(
            "/api/v1/convert?format=json",
            headers=headers,
            files={"files": ("erste_6p.pdf", pdf_bytes, "application/pdf")},
        )
        assert r_json_no_val.status_code == 200
        body_no_val = r_json_no_val.json()
        assert body_no_val["export_eligible"] is False
        assert body_no_val["operation_id"] is None
        assert len(body_no_val["export_blocks"]) >= 1
        assert body_no_val["overall_reconciliation"] == "BALANCED"
        assert len(body_no_val["transactions"]) == 13
        assert body_no_val["transactions"][0]["booking_date"] is None
        assert body_no_val["transactions"][0]["value_date"] == "2026-09-01"

        # Case B2: format=json WITH target_format=bmd_bankauszug without opt-in -> 422 with preview result, 0 quota!
        r_json_target_blocked = await c.post(
            "/api/v1/convert?format=json&target_format=bmd_bankauszug",
            headers=headers,
            files={"files": ("erste_6p.pdf", pdf_bytes, "application/pdf")},
        )
        assert r_json_target_blocked.status_code == 422
        err_body = r_json_target_blocked.json()
        assert len(err_body["export_blocks"]) >= 1
        assert len(err_body["result"]["transactions"]) == 13

        async with async_session_maker() as db:
            used_after_b = (await db.execute(
                select(func.coalesce(func.sum(UsageReservation.units), 0))
                .where(UsageReservation.tenant_id == tid, UsageReservation.status == "COMMITTED")
            )).scalar()
            assert used_after_b == 0

        # Case C: explicit use_valuta_as_booking_date=true with format=json&target_format=bmd_bankauszug, then 3 switches!
        r_json_val = await c.post(
            "/api/v1/convert?format=json&target_format=bmd_bankauszug&use_valuta_as_booking_date=true",
            headers=headers,
            files={"files": ("erste_6p.pdf", pdf_bytes, "application/pdf")},
        )
        assert r_json_val.status_code == 200
        body_val = r_json_val.json()
        assert body_val["export_eligible"] is True
        assert body_val["overall_reconciliation"] == "BALANCED"
        assert body_val["transactions"][0]["booking_date"] == "2026-09-01"
        op_id = body_val["operation_id"]
        assert op_id.startswith("op_")

        # Check quota after format=json convert -> 1 total (blocked attempts deducted 0!)
        async with async_session_maker() as db:
            used_before_switches = (await db.execute(
                select(func.coalesce(func.sum(UsageReservation.units), 0))
                .where(UsageReservation.tenant_id == tid, UsageReservation.status == "COMMITTED")
            )).scalar()
            assert used_before_switches == 1

        # Perform 3 format switches via /operations/{op_id}/export -> quota MUST NOT increase!
        r_sw1 = await c.get(f"/api/v1/operations/{op_id}/export?format=bmd_bankauszug", headers=headers)
        assert r_sw1.status_code == 200
        assert r_sw1.content.startswith(b"\xef\xbb\xbf")
        assert b"Umlautpr" in r_sw1.content
        assert "Partner Alpha GmbH" in r_sw1.content.decode("utf-8-sig")

        r_sw2 = await c.get(f"/api/v1/operations/{op_id}/export?format=datev", headers=headers)
        assert r_sw2.status_code == 200
        assert "EXTF" in r_sw2.content.decode("windows-1252")

        r_sw3 = await c.get(f"/api/v1/operations/{op_id}/export?format=bmd_ntcs", headers=headers)
        assert r_sw3.status_code == 200
        assert '"Satzart";"Belegdatum";"Konto"' in r_sw3.content.decode("windows-1252")

        async with async_session_maker() as db:
            used_after_switches = (await db.execute(
                select(func.coalesce(func.sum(UsageReservation.units), 0))
                .where(UsageReservation.tenant_id == tid, UsageReservation.status == "COMMITTED")
            )).scalar()
            assert used_after_switches == used_before_switches  # Zero additional quota consumed!


# ---------------------------------------------------------------------------
# 3. Erste Visa Card Business Gold (MONATSRECHNUNG) tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_erste_visa_gold_fx_buchung_date_and_reconciliation():
    visa_pdf = build_synthetic_erste_visa_pdf(include_fx=True, balanced=True)
    parser = ErsteVisaCardParser()
    assert parser.is_applicable(visa_pdf)
    res = parser.parse_with_metadata(visa_pdf, "visa_gold.pdf")

    assert len(res["transactions"]) == 3
    tx_pay, tx_local, tx_fx = res["transactions"]

    # Booking date must be the 2nd date column ('Buchung'), NOT 1st column ('Kauf')
    assert tx_pay["Belegdatum"] == "03.09.2026"
    assert tx_pay["_amount_cents"] == 16099
    assert tx_local["Belegdatum"] == "11.09.2026"
    assert tx_local["_amount_cents"] == -1800
    assert tx_fx["Belegdatum"] == "15.09.2026"
    assert tx_fx["_amount_cents"] == -4299
    assert tx_fx["ForeignCurrency"] == "USD"
    assert tx_fx["ForeignAmountCents"] == -4900

    # Verify FX metadata & merchant isolation flow through registry + 22-col export
    txs, acct_summary = registry.parse_file(visa_pdf, "visa_gold.pdf", "t1")
    rec = build_statement_result(
        "req1", "t1", txs,
        {f"{acct_summary.client_entity_id}_{acct_summary.account_id}": (
            acct_summary.opening_balance_cents,
            acct_summary.closing_balance_cents,
            acct_summary.bank_name,
        )},
        1, 1,
    )
    assert rec.overall_reconciliation == "BALANCED"

    bmd22 = export_to_bmd_bankauszug_csv(rec.transactions).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(bmd22), delimiter=";"))
    assert len(rows) == 4
    fx_row = [r for r in rows[1:] if r[4] == "USD"][0]
    assert fx_row[5] == "-49,00"
    assert fx_row[6] == "EUR"
    assert fx_row[7] == "-42,99"
    assert fx_row[8] == "-42,99"


# ---------------------------------------------------------------------------
# 4. Cache TTL expiry (410), Cross-Tenant (403), Unauth (401), Bad Format (400)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_operation_cache_ttl_security_and_format_validation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        t1_id = str(uuid.uuid4())
        t2_id = str(uuid.uuid4())
        e1 = f"t1_{uuid.uuid4().hex[:6]}@example.at"
        e2 = f"t2_{uuid.uuid4().hex[:6]}@example.at"
        async with async_session_maker() as db:
            db.add(Tenant(id=t1_id, email=e1))
            db.add(Tenant(id=t2_id, email=e2))
            await db.commit()

        tok1 = create_access_token(user_id=e1, tenant_id=t1_id)
        tok2 = create_access_token(user_id=e2, tenant_id=t2_id)
        csv_data = b"Datum;Text;Betrag\n05.09.2026;Office;50,00\n"

        # Unknown format -> 400
        r_bad_fmt = await c.post(
            "/api/v1/convert?format=foo_invalid",
            headers={"Authorization": f"Bearer {tok1}"},
            files={"files": ("test.csv", csv_data, "text/csv")},
        )
        assert r_bad_fmt.status_code == 400

        # Valid conversion -> get op_id
        r_ok = await c.post(
            "/api/v1/convert?format=json",
            headers={"Authorization": f"Bearer {tok1}"},
            files={"files": ("test.csv", csv_data, "text/csv")},
        )
        assert r_ok.status_code == 200
        op_id = r_ok.json()["operation_id"]

        # Missing Bearer -> 401
        r_unauth = await c.get(f"/api/v1/operations/{op_id}/export?format=datev")
        assert r_unauth.status_code == 401

        # Cross-tenant -> 403 Forbidden
        r_cross = await c.get(
            f"/api/v1/operations/{op_id}/export?format=datev",
            headers={"Authorization": f"Bearer {tok2}"},
        )
        assert r_cross.status_code == 403

        # Simulate TTL expiration (fixed creation timestamp, NOT sliding!)
        entry = canonical_operation_cache._entries[op_id]
        entry.expires_at = time.time() - 5.0
        r_expired = await c.get(
            f"/api/v1/operations/{op_id}/export?format=datev",
            headers={"Authorization": f"Bearer {tok1}"},
        )
        assert r_expired.status_code == 410


# ---------------------------------------------------------------------------
# 5. Negative Parser, Mixed Scan Page, Worker Timeout, IBAN/Date/Amount Guards
# ---------------------------------------------------------------------------

def test_mixed_scan_page_and_segment_gaps_and_validation():
    iban = make_valid_at_iban()
    parser = ErsteBankAustriaParser()

    # 1. Mixed scan page (<20 chars on page 2) -> explicit error, NO silent partial export!
    pdf_mixed_scan = build_synthetic_erste_bank_6page_pdf(iban=iban, include_scan_page=True)
    res_scan = parser.parse_with_metadata(pdf_mixed_scan, "mixed_scan.pdf", use_valuta_as_booking_date=True)
    assert any("textebene" in err.lower() or "scan" in err.lower() for err in res_scan["errors"])
    txs, _summary = registry.parse_file(
        pdf_mixed_scan, "mixed_scan.pdf", "t1", use_valuta_as_booking_date=True
    )
    assert any(t.validation_status == "ERROR" for t in txs)

    # 2. Duplicate segment Nr. 029/2026 -> explicit error & DISCREPANCY
    pdf_dup_seg = build_synthetic_erste_bank_6page_pdf(iban=iban, duplicate_seg_num=True)
    res_dup = parser.parse_with_metadata(pdf_dup_seg, "dup_seg.pdf", use_valuta_as_booking_date=True)
    assert any("doppelter auszug" in e.lower() for e in res_dup["errors"])

    # 3. Balance mismatch -> internal segment DISCREPANCY error
    pdf_bal_err = build_synthetic_erste_bank_6page_pdf(iban=iban, balance_mismatch=True)
    res_bal = parser.parse_with_metadata(pdf_bal_err, "bal_err.pdf", use_valuta_as_booking_date=True)
    assert any("saldendifferenz" in e.lower() for e in res_bal["errors"])

    # 4. Invalid IBAN checksum rejected
    bad_iban = "AT992011100000001234"
    assert not is_valid_iban(bad_iban)
    pdf_bad_iban = build_synthetic_erste_bank_6page_pdf(iban=bad_iban)
    res_iban = parser.parse_with_metadata(pdf_bad_iban, "bad_iban.pdf", use_valuta_as_booking_date=True)
    assert any("iban" in e.lower() for e in res_iban["errors"])

    # 5. Strict calendar & amount helpers
    assert parse_strict_dmy("29.02.2024") == datetime.date(2024, 2, 29)
    assert parse_strict_dmy("29.02.2026") is None
    assert parse_strict_eur_cents("1.1567") is None  # Reject dot decimal FX rate
    assert parse_strict_eur_cents("-12,00-") is None  # Conflicting signs rejected
    assert parse_strict_eur_cents("72,00-") == -7200
    assert parse_strict_eur_cents("1.234,56") == 123456

    # 6. Leap day inside Erste PDF -> explicit error
    pdf_bad_date = build_synthetic_erste_bank_6page_pdf(iban=iban, invalid_valuta_date="29.02.2026")
    res_date = parser.parse_with_metadata(pdf_bad_date, "bad_date.pdf", use_valuta_as_booking_date=True)
    assert any("ungültiges valutadatum" in e.lower() for e in res_date["errors"])

    # 7. Ambiguous amount inside Erste PDF -> explicit error
    pdf_bad_amt = build_synthetic_erste_bank_6page_pdf(iban=iban, ambiguous_amount="1.1567")
    res_amt = parser.parse_with_metadata(pdf_bad_amt, "bad_amt.pdf", use_valuta_as_booking_date=True)
    assert any("nicht eindeutiger betrag" in e.lower() for e in res_amt["errors"])


def test_amex_low_text_threshold_fixed_for_scanned_pdfs(monkeypatch):
    # Verify UniversalBankStatementParser only invokes native OCR when total_chars < 50
    # and raises/errors cleanly on mixed scanned pages inside digital PDFs.
    scan_pdf = build_vector_pdf([[], []])
    p = UniversalBankStatementParser()
    ocr_calls = []

    def fake_ocr(pdf_bytes, filename=""):
        ocr_calls.append(filename)
        return "05.09.2026 Beispiel Buchung -25,00"

    monkeypatch.setattr(p, "_run_native_ocr", fake_ocr)
    res_scan = p.parse_with_metadata(scan_pdf, "scanned.pdf")
    assert ocr_calls == ["scanned.pdf"]
    assert len(res_scan["transactions"]) == 1

    # Digital PDF (>50 chars) with NO empty page MUST NOT call OCR unnecessarily
    ocr_calls.clear()
    digital_pdf = build_vector_pdf([[(40, 50, "Kontoinhaber: Testfirma GmbH"), (40, 80, "05.09.2026 Einkauf Supermarkt -12,50")]])
    res_dig = p.parse_with_metadata(digital_pdf, "digital.pdf")
    assert ocr_calls == []
    assert len(res_dig["transactions"]) == 1

    # Mixed digital + empty scan page -> explicit mixed-scan 422 HTTPException!
    mixed_pdf = build_vector_pdf([[(40, 50, "Kontoinhaber: Testfirma GmbH"), (40, 80, "05.09.2026 Einkauf Supermarkt -12,50")], []])
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        p.parse_with_metadata(mixed_pdf, "mixed.pdf")
    assert exc_info.value.status_code == 422
    assert "textebene" in str(exc_info.value.detail).lower() or "scan" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_non_eur_currency_blocked_for_bmd_bankauszug_and_multifile_chaining():
    iban = make_valid_at_iban("20111", "00000054321")
    usd_pdf = build_synthetic_erste_bank_6page_pdf(iban=iban, currency="USD")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        tid = str(uuid.uuid4())
        email = f"usd_{uuid.uuid4().hex[:6]}@example.at"
        token = create_access_token(user_id=email, tenant_id=tid)
        headers = {"Authorization": f"Bearer {token}"}

        r_usd_22 = await c.post(
            "/api/v1/convert?format=bmd_bankauszug&use_valuta_as_booking_date=true",
            headers=headers,
            files={"files": ("erste_usd.pdf", usd_pdf, "application/pdf")},
        )
        assert r_usd_22.status_code == 422
        assert "eur" in r_usd_22.json()["detail"].lower()

    # Multi-file balance chaining: continuous closing->opening vs gap
    t_a = CanonicalTransaction(tenant_id="t", booking_date="2026-09-01", amount_cents=-5000, account_id=iban)
    t_b = CanonicalTransaction(tenant_id="t", booking_date="2026-09-02", amount_cents=2000, account_id=iban)
    seg1 = {
        "file": "f1.pdf", "order": 0, "bank_name": "Erste Bank",
        "opening_cents": 100000, "closing_cents": 95000, "txs": [t_a],
    }
    seg2_ok = {
        "file": "f2.pdf", "order": 1, "bank_name": "Erste Bank",
        "opening_cents": 95000, "closing_cents": 97000, "txs": [t_b],
    }
    res_ok = build_statement_result(
        "r1", "t", [t_a, t_b],
        {f"default_{iban}": [seg2_ok, seg1]},
        2, 2,
    )
    assert res_ok.overall_reconciliation == "BALANCED"

    seg2_gap = {
        "file": "f2_gap.pdf", "order": 1, "bank_name": "Erste Bank",
        "opening_cents": 94000, "closing_cents": 96000, "txs": [t_b],
    }
    res_gap = build_statement_result(
        "r2", "t", [t_a, t_b],
        {f"default_{iban}": [seg1, seg2_gap]},
        2, 2,
    )
    assert res_gap.overall_reconciliation == "DISCREPANCY"


def test_real_duplicate_payments_kept_in_conversion():
    csv_dupes = (
        "Datum;Buchungstext;Betrag;Saldo\n"
        "05.09.2026;Parkgebuehr Wien;-4,50;95,50\n"
        "05.09.2026;Parkgebuehr Wien;-4,50;91,00\n"
    ).encode("windows-1252")
    p = StructuredCsvParser()
    txs, summary = p.parse_to_canonical(csv_dupes, "dupes.csv", "t1")
    assert len(txs) == 2  # Real duplicates MUST NOT be dropped silently!
    res = build_statement_result(
        "r_dup", "t1", txs,
        {f"{summary.client_entity_id}_{summary.account_id}": (
            summary.opening_balance_cents,
            summary.closing_balance_cents,
            summary.bank_name,
        )},
        1, 1,
    )
    assert res.overall_reconciliation == "BALANCED"


def test_worker_supervisor_timeout_clean():
    supervisor = ParserProcessSupervisor()
    # Non-existent or corrupt PDF raises 422 cleanly, and worker timeout config is respected
    with pytest.raises(Exception):
        asyncio.run(supervisor.parse_file(b"%PDF-1.4\ncorrupt", "bad.pdf", "t1", timeout_seconds=1.0))


def test_frontend_js_win1252_bom_and_client_parsers():
    """Runs Node against extracted pure functions from extension/app.js to verify browser parity."""
    node_script = r"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('extension/app.js', 'utf8');

// Extract pure encoding + format + Erste parser functions via sandbox with minimal DOM/chrome stubs
function noop() {}
function makeEl() {
  return {
    addEventListener: noop, classList: { add: noop, remove: noop, toggle: noop, contains: () => true },
    style: { setProperty: noop }, value: '', checked: false, disabled: false, textContent: '', innerHTML: '',
    appendChild: noop, querySelector: () => makeEl(), querySelectorAll: () => [],
  };
}
const sandbox = {
  console, Math, Date, Number, String, Array, Set, Object, Uint8Array, TextEncoder, TextDecoder, Blob,
  URL: { createObjectURL: noop },
  URLSearchParams: function() { return { get: () => null }; },
  document: {
    getElementById: () => makeEl(),
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => makeEl(),
    body: makeEl(),
    addEventListener: noop,
  },
  window: { innerWidth: 800, location: { search: '' }, addEventListener: noop, open: noop },
  chrome: {
    storage: { local: { get: noop, set: noop, remove: noop }, session: { get: noop, remove: noop } },
    runtime: { getURL: (s) => s, lastError: null },
    downloads: { download: noop },
    tabs: { create: noop },
    sidePanel: {},
    windows: {},
  },
  fetch: async () => ({ ok: false }),
  AbortController: typeof AbortController !== 'undefined' ? AbortController : function() { this.signal = { aborted: false }; this.abort = noop; },
  sessionStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  setTimeout: () => 0,
  clearTimeout: noop,
  setInterval: () => 0,
  confirm: () => false,
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

// 1. Test encodeWindows1252Strict for äöüß€ + unrepresentable glyph
const enc = sandbox.encodeWindows1252Strict('äöüß€\u2603');
if (enc.bytes[0] !== 0xe4 || enc.bytes[1] !== 0xf6 || enc.bytes[2] !== 0xfc || enc.bytes[3] !== 0xdf || enc.bytes[4] !== 0x80 || enc.bytes[5] !== 0x3f) {
  throw new Error('Wrong Windows-1252 byte mapping: ' + Array.from(enc.bytes));
}
if (enc.unrepresentableCount !== 1) throw new Error('Expected 1 unrepresentable char');

// 2. Test UTF-8 BOM encoder
const bomBytes = sandbox.encodeUtf8WithBom('Transaction Booking Date;Test');
if (bomBytes[0] !== 0xef || bomBytes[1] !== 0xbb || bomBytes[2] !== 0xbf) {
  throw new Error('Missing UTF-8 BOM');
}

// 3. Test Erste Bank client-side parser with Abschlussbuchung & partner isolation
const ersteSample = [
  'Erste Bank der oesterreichischen Sparkassen AG',
  'KONTOAUSZUG Nr. 029/2026',
  'Musterfirma GmbH',
  'zuletzt gültiger Kontowortlaut',
  'IBAN: AT611904300234573201',
  'Alter Kontostand 100,00',
  'Buchungstext Valuta/Value Beträge/Amounts in EUR',
  'SEPA-Überweisung 01.09.2026 * 25,00-',
  'Lieferant Test GmbH',
  '*** Abschlussbuchung per 30.09.2026 **** 30.09.2026',
  'Reklamationen innerhalb 6 Monate',
  'Kontoführungsentgelt 30.09.2026 5,00-',
  'Neuer Kontostand/New Balance 70,00'
].join('\n');

const resNoVal = sandbox.parseErsteBankTextClientSide(ersteSample, 'test.pdf', false);
if (resNoVal.transactions.length !== 2) throw new Error('Expected 2 Erste txs, got ' + resNoVal.transactions.length);
if (resNoVal.transactions[0].booking_date !== null) throw new Error('Expected null booking_date when useValuta=false');
if (resNoVal.reconciliation !== 'BALANCED') throw new Error('Expected BALANCED Erste client recon, got ' + resNoVal.reconciliation);

const resWithVal = sandbox.parseErsteBankTextClientSide(ersteSample, 'test.pdf', true);
if (resWithVal.transactions[0].booking_date !== '2026-09-01') throw new Error('Expected 2026-09-01 when useValuta=true');
if (resWithVal.transactions[0].partner !== 'Lieferant Test GmbH') throw new Error('Expected partner extraction');

// 4. Test 22-col client exporter & matching exact Python header spec
const exp22 = sandbox.buildCanonicalResultExport({ transactions: resWithVal.transactions }, 'bmd_bankauszug');
const csvLines = exp22.csvText.split('\r\n').filter(Boolean);
const hdrs = csvLines[0].split(';');
if (hdrs.length !== 22) throw new Error('Expected 22 headers in client exporter');
if (hdrs[3] !== 'Transaction Partner IBAN' || hdrs[6] !== 'Transaction Currency' || hdrs[7] !== 'Transaction Amount' || hdrs[8] !== 'Booking Amount') {
  throw new Error('Header mismatch: ' + hdrs.join(';'));
}
if (!csvLines[1].startsWith('01.09.2026;SEPA-Überweisung;Lieferant Test GmbH;;;;EUR;-25,00;-25,00')) throw new Error('Unexpected row 1: ' + csvLines[1]);

// 5. Test Erste Visa Gold client-side parser (Booking date = 2nd column, FX preservation)
const visaSample = [
  's Visa Card Business Gold MONATSRECHNUNG September 2026',
  'Kartennummer 0000 XXXX XXXX 9999',
  'Kauf Buchung Vertragsunternehmen Betrag Fremdw. FW-Kurs Betrag EUR',
  '02.09.2026 03.09.2026 Zahlung per Einzug 160,99+',
  '14.09.2026 15.09.2026 CLOUD HOSTING VIENNA 49,00 USD 1,1398 42,99-',
  'Kontosaldo neu per 30.09.2026 42,99-',
].join('\n');
const visaRes = sandbox.parseErsteVisaTextClientSide(visaSample, 'visa.pdf');
if (visaRes.transactions.length !== 2) throw new Error('Expected 2 Visa txs, got ' + visaRes.transactions.length);
if (visaRes.transactions[0].booking_date !== '2026-09-03') throw new Error('Visa booking_date wrong: ' + visaRes.transactions[0].booking_date);
if (visaRes.transactions[1].foreign_currency !== 'USD' || visaRes.transactions[1].foreign_amount_cents !== -4900) {
  throw new Error('Visa FX missing: ' + JSON.stringify(visaRes.transactions[1]));
}

// 6. Decision 62 (R62-3): Exact DATEV (22-field col 22 EUR + contra_account) and BMD NTCS (8-col QUOTE_ALL) parity
const parityTx = {
  booking_date: '2026-09-01', amount_cents: -100, currency: 'EUR',
  description: 'Office "Quote"', reference: 'R1', contra_account: '4930', account_id: 'A', validation_status: 'VALID'
};
const datevRes = sandbox.buildCanonicalResultExport({ transactions: [parityTx] }, 'datev');
const datevLines = datevRes.csvText.split('\r\n').filter(Boolean);
const row1Cols = datevLines[0].split(';');
if (row1Cols.length !== 22 || row1Cols[21] !== '"EUR"') {
  throw new Error('DATEV EXTF Row 1 parity failed: len=' + row1Cols.length + ' col22=' + row1Cols[21]);
}
if (!datevLines[2].includes('"1200";"4930"') || !datevLines[2].includes('Office ""Quote""')) {
  throw new Error('DATEV EXTF data row parity failed: ' + datevLines[2]);
}
const bmd8Res = sandbox.buildCanonicalResultExport({ transactions: [parityTx] }, 'bmd');
const bmd8Lines = bmd8Res.csvText.split('\r\n').filter(Boolean);
if (bmd8Lines[0] !== '"Satzart";"Belegdatum";"Konto";"Gegenkonto";"Betrag";"Währung";"Text";"Belegnummer"') {
  throw new Error('BMD 8 header parity failed: ' + bmd8Lines[0]);
}
if (!bmd8Lines[1].startsWith('"0";"01.09.2026";"2800";"4930";"-1,00";"EUR"')) {
  throw new Error('BMD 8 row parity failed: ' + bmd8Lines[1]);
}

// 7. Decision 62 (R62-4): Malformed amount in Erste Bank client parser MUST NOT merge into prior tx
const badAmtText = [
  'Erste Bank Kontoauszug',
  'KONTOAUSZUG Nr. 029/2026',
  'IBAN: AT611904300234573201',
  'Alter Kontostand 100,00',
  'Buchungstext Valuta/Value Beträge/Amounts in EUR',
  'Good 01.09.2026 10,00-',
  'Bad 02.09.2026 12,3X-',
  'Neuer Kontostand/New Balance 90,00'
].join('\n');
const badAmtRes = sandbox.parseErsteBankTextClientSide(badAmtText, 'bad.pdf', true);
if (badAmtRes.transactions.length !== 1 || badAmtRes.transactions[0].description !== 'Good' || badAmtRes.reconciliation !== 'DISCREPANCY') {
  throw new Error('R62-4 malformed amount check failed: ' + JSON.stringify(badAmtRes));
}

// 8. Decision 62 (R62-3) landing/app.js buildLandingCanonicalExport parity
const landingCode = fs.readFileSync('landing/app.js', 'utf8');
const landingSandbox = {
  ...sandbox,
  document: {
    getElementById: () => makeEl(),
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => makeEl(),
    body: makeEl(),
    addEventListener: noop,
  },
  window: { innerWidth: 1200, matchMedia: () => ({ matches: true }), location: { hostname: 'localhost' }, addEventListener: noop },
  location: { hostname: 'localhost' },
};
vm.createContext(landingSandbox);
vm.runInContext(landingCode, landingSandbox);
const lDatev = landingSandbox.buildLandingCanonicalExport([parityTx], 'datev');
const lRow1 = lDatev.csvText.split('\r\n')[0].split(';');
if (lRow1.length !== 22 || lRow1[21] !== '"EUR"') {
  throw new Error('Landing DATEV Row 1 parity failed');
}
const lBmd = landingSandbox.buildLandingCanonicalExport([parityTx], 'bmd_ntcs');
if (!lBmd.csvText.split('\r\n')[1].startsWith('"0";"01.09.2026";"2800";"4930";"-1,00";"EUR"')) {
  throw new Error('Landing BMD 8 row parity failed');
}

// 9. Decision 62 (R62-5 & R62-6): Async offline discontinuous chain & late export abort race after reset
(async () => {
  const mkPage = (num, o, c, d, a) => [
    'Erste Bank Kontoauszug', `KONTOAUSZUG Nr. ${num}/2026`, 'IBAN: AT611904300234573201',
    `Alter Kontostand ${o}`, 'Buchungstext Valuta/Value Beträge/Amounts in EUR',
    `Test ${d} ${a}`, `Neuer Kontostand/New Balance ${c}`
  ].join('\n');
  const pMap = [mkPage('029', '100,00', '90,00', '01.09.2026', '10,00-'), mkPage('030', '200,00', '180,00', '02.09.2026', '20,00-')];
  sandbox.extractTextFromPdf = async idx => ({ text: pMap[idx], pageTexts: [pMap[idx]], lowTextPages: [] });
  sandbox.displayCanonicalPreview = noop;
  sandbox.updateReconciliationBadge = noop;
  sandbox.renderSafeguards = noop;
  let offlineObs = null;
  sandbox.applyClientSideExportToPreview = (res, fmt) => {
    offlineObs = { recon: res.overall_reconciliation, blocks: sandbox.computeClientExportBlocks(res, fmt) };
  };
  vm.runInContext('valutaAsBookingCheckbox.checked = true; currentSelectedFormat = "bmd_bankauszug";', sandbox);
  await sandbox.processClientSideFiles([{ name: 'a.pdf', arrayBuffer: async () => 0 }, { name: 'b.pdf', arrayBuffer: async () => 1 }]);
  if (!offlineObs || offlineObs.recon !== 'DISCREPANCY' || !offlineObs.blocks.length) {
    throw new Error('R62-5 offline discontinuous chain check failed: ' + JSON.stringify(offlineObs));
  }

  let completeBody;
  const deferredBody = new Promise(resolve => { completeBody = resolve; });
  sandbox.chrome.storage.local.get = async () => ({ authToken: 'tok' });
  sandbox.fetch = async () => ({ ok: true, headers: { get: () => null }, arrayBuffer: () => deferredBody });
  vm.runInContext('currentExportSource="backend"; currentOperationId="old-op";', sandbox);
  const pending = sandbox.switchPreviewFormat('bmd_bankauszug');
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  sandbox.clearFile();
  sandbox.syncFormatSelection('datev');
  completeBody(new TextEncoder().encode('Transaction Booking Date;old-stale').buffer);
  await pending;
  const race = vm.runInContext('({sel:currentSelectedFormat,fn:currentCsvFilename,txt:currentCsvText,dl:!btnDownloadCsv.disabled})', sandbox);
  if (race.sel !== 'datev' || race.fn !== '' || race.txt !== '' || race.dl !== false) {
    throw new Error('R62-6 late export leaked after reset: ' + JSON.stringify(race));
  }
  console.log('JS_PARITY_OK');
})().catch(e => { console.error(e); process.exitCode = 1; });
"""
    proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Node failed: {proc.stderr}\n{proc.stdout}"
    assert "JS_PARITY_OK" in proc.stdout


# ---------------------------------------------------------------------------
# 6. Section 4 Baseline Fixtures (12-tx Erste Bank & 5-tx Visa) + Decision 62 Regressions
# ---------------------------------------------------------------------------

def test_section4_12tx_erste_bank_and_5tx_visa_baseline_fixtures():
    """
    Reproducible synthetic Section 4 regression baselines:
    - 12-tx Erste Bank digital statement with positive subtotal 471,66 + 462,76 = 934,42 (93442 cents)
    - 5-tx Erste s Visa Card Business statement with -294,83 opening, +294,83 Einzug,
      and 4 card charges (-4,38, -48,58, -43,00, -17,73) closing at -113,69 (-11369 cents)
    """
    iban = make_valid_at_iban("20111", "00000098765")
    eb_lines = [
        (40, 40, "Erste Bank der oesterreichischen Sparkassen AG"),
        (40, 55, "KONTOAUSZUG"),
        (420, 55, "Nr. 029/2026"),
        (40, 72, "Muster Kanzlei GmbH"),
        (40, 84, "zuletzt gültiger Kontowortlaut"),
        (40, 96, f"IBAN: {iban}"),
        (320, 96, "BIC: GIBAATWWXXX"),
        (40, 114, "Alter Kontostand 1.000,00"),
        (40, 130, "Buchungstext"),
        (360, 130, "Valuta/Value"),
        (465, 130, "Beträge/Amounts in EUR"),
        (40, 150, "Gutschrift Kunde A"), (360, 150, "01.09.2026"), (475, 150, "471,66"),
        (40, 165, "Kunde Alpha GmbH"),
        (40, 180, "Gutschrift Kunde B"), (360, 180, "02.09.2026"), (475, 180, "462,76"),
        (40, 195, "Kunde Beta AG"),
        (40, 210, "Ausgang 03"), (360, 210, "03.09.2026"), (475, 210, "10,00-"),
        (40, 225, "Ausgang 04"), (360, 225, "04.09.2026"), (475, 225, "20,00-"),
        (40, 240, "Ausgang 05"), (360, 240, "05.09.2026"), (475, 240, "30,00-"),
        (40, 255, "Ausgang 06"), (360, 255, "06.09.2026"), (475, 255, "40,00-"),
        (40, 270, "Ausgang 07"), (360, 270, "07.09.2026"), (475, 270, "50,00-"),
        (40, 285, "Ausgang 08"), (360, 285, "08.09.2026"), (475, 285, "60,00-"),
        (40, 300, "Ausgang 09"), (360, 300, "09.09.2026"), (475, 300, "70,00-"),
        (40, 315, "Ausgang 10"), (360, 315, "10.09.2026"), (475, 315, "80,00-"),
        (40, 330, "Ausgang 11"), (360, 330, "11.09.2026"), (475, 330, "90,00-"),
        (40, 345, "Entgelt 12"), (360, 345, "30.09.2026"), (475, 345, "10,00-"),
        # 1000.00 + 471.66 + 462.76 - 460.00 = 1474.42
        (40, 370, "Neuer Kontostand/New Balance 1.474,42"),
    ]
    eb_pdf = build_vector_pdf([eb_lines])
    eb_txs, eb_sum = registry.parse_file(eb_pdf, "erste_12tx.pdf", "t_base", use_valuta_as_booking_date=True)
    assert len(eb_txs) == 12
    assert sum(t.amount_cents for t in eb_txs if t.amount_cents > 0) == 93442
    eb_res = build_statement_result(
        "r_eb12", "t_base", eb_txs,
        {f"{eb_sum.client_entity_id}_{eb_sum.account_id}": (
            eb_sum.opening_balance_cents, eb_sum.closing_balance_cents, eb_sum.bank_name
        )}, 1, 1,
    )
    assert eb_res.overall_reconciliation == "BALANCED"
    assert eb_sum.account_id == iban

    # Same-line IBAN + BIC extraction check (both backend & extension parity)
    from app.parsers.erste_parser import _extract_iban_strict
    extracted, ext_ok = _extract_iban_strict(f"IBAN: {iban} BIC: GIBAATWWXXX\nWeitere Zeile")
    assert ext_ok is True
    assert extracted == iban

    # 5-tx Visa Card baseline: Opening -294,83, +294,83 - 4,38 - 48,58 - 43,00 - 17,73 -> Closing -113,69 (-11369 cents)
    visa_5_lines = [
        (30, 40, "Erste Bank - s Visa Card Business MONATSRECHNUNG September 2026"),
        (30, 56, "Kartennummer / Card Number 4000XXXXXXXX0001"),
        (30, 74, "Offener Betrag Vormonat 294,83-"),
        (30, 92, "Kauf"), (85, 92, "Buchung"), (145, 92, "Vertragsunternehmen"),
        (260, 92, "Ort"), (325, 92, "Betrag Fremdw."), (390, 92, "FW-Kurs"), (500, 92, "Betrag EUR"),
        (30, 110, "01.09.2026"), (85, 110, "02.09.2026"), (145, 110, "Ihre Zahlung Einzug"), (510, 110, "294,83+"),
        (30, 128, "05.09.2026"), (85, 128, "06.09.2026"), (145, 128, "KAFFEEHAUS"), (260, 128, "WIEN"), (510, 128, "4,38-"),
        (30, 146, "10.09.2026"), (85, 146, "11.09.2026"), (145, 146, "BUCHHANDEL"), (260, 146, "LINZ"), (510, 146, "48,58-"),
        (30, 164, "15.09.2026"), (85, 164, "16.09.2026"), (145, 164, "CLOUD SERVICE"), (260, 164, "US"),
        (325, 164, "50,00 USD"), (390, 164, "1,1628"), (510, 164, "43,00-"),
        (30, 182, "20.09.2026"), (85, 182, "21.09.2026"), (145, 182, "TANKSTELLE"), (260, 182, "GRAZ"), (510, 182, "17,73-"),
        (30, 204, "Offener Betrag / Outstanding balance 113,69-"),
    ]
    visa_5_pdf = build_vector_pdf([visa_5_lines])
    v_txs, v_sum = registry.parse_file(visa_5_pdf, "visa_5tx.pdf", "t_base")
    assert len(v_txs) == 5
    assert sum(t.amount_cents for t in v_txs) == 18114
    assert v_sum.opening_balance_cents == -29483
    assert v_sum.closing_balance_cents == -11369
    v_res = build_statement_result(
        "r_v5", "t_base", v_txs,
        {f"{v_sum.client_entity_id}_{v_sum.account_id}": (
            v_sum.opening_balance_cents, v_sum.closing_balance_cents, v_sum.bank_name
        )}, 1, 1,
    )
    assert v_res.overall_reconciliation == "BALANCED"


@pytest.mark.asyncio
async def test_decision62_r62_2_cache_eviction_admission_and_r62_8_headers():
    """Verifies R62-2 (410 on canonical eviction, replay never re-parses, >max_bytes 413) & R62-8 (no-store, SharedMemoryBudget)."""
    from app.main import canonical_operation_cache, _idempotent_result_cache, parser_supervisor, shared_ram_budget
    from app.core.cache import BoundedMemoryCache, SharedMemoryBudget

    # Unit check on SharedMemoryBudget (R62-8): single combined ceiling evicts across sibling caches
    budget = SharedMemoryBudget(max_bytes=200)
    c1 = BoundedMemoryCache(ttl_seconds=60, shared_budget=budget)
    c2 = BoundedMemoryCache(ttl_seconds=60, shared_budget=budget)
    try:
        assert c1.set("k1", b"x" * 120) is True
        assert c2.set("k2", b"y" * 120) is True  # Evicts k1 from sibling cache to respect 200-byte total ceiling!
        assert budget.current_bytes() <= 200
        assert c1.get("k1") is None
        assert c2.set("too_big", b"z" * 300) is False
    finally:
        c1._stopped = True
        c2._stopped = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        tid = str(uuid.uuid4())
        email = f"r62_{uuid.uuid4().hex[:6]}@example.at"
        token = create_access_token(user_id=email, tenant_id=tid)
        headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": f"idem-{tid[:8]}"}
        csv_data = b"Datum;Text;Betrag\n05.09.2026;Office;50,00\n"

        parse_calls = 0
        orig_parse = parser_supervisor.parse_file

        async def counted_parse(*args, **kwargs):
            nonlocal parse_calls
            parse_calls += 1
            return await orig_parse(*args, **kwargs)

        parser_supervisor.parse_file = counted_parse
        try:
            r1 = await c.post("/api/v1/convert?format=json&target_format=datev", headers=headers,
                              files={"files": ("r62.csv", csv_data, "text/csv")})
            assert r1.status_code == 200
            assert "no-store" in (r1.headers.get("cache-control") or "").lower()
            op1 = r1.json()["operation_id"]
            assert parse_calls == 1

            # Evict ONLY canonical cache -> replay MUST return 410 Gone and MUST NOT call parser again!
            canonical_operation_cache.delete(op1)
            r_replay_evicted = await c.post("/api/v1/convert?format=json&target_format=datev", headers=headers,
                                            files={"files": ("r62.csv", csv_data, "text/csv")})
            assert r_replay_evicted.status_code == 410
            assert parse_calls == 1

            # Export on evicted op -> 410 + no-store
            r_exp_gone = await c.get(f"/api/v1/operations/{op1}/export?format=bmd", headers={"Authorization": f"Bearer {token}"})
            assert r_exp_gone.status_code == 410
            assert "no-store" in (r_exp_gone.headers.get("cache-control") or "").lower()

            # Unsafe account code injection blocked with 422 (R62-7)
            r_bad_acc_conv = await c.post(
                '/api/v1/convert?format=bmd&default_bank_account=1200";"EXTRA',
                headers={"Authorization": f"Bearer {token}"},
                files={"files": ("r62.csv", csv_data, "text/csv")},
            )
            assert r_bad_acc_conv.status_code == 422

            r2 = await c.post("/api/v1/convert?format=json", headers={"Authorization": f"Bearer {token}"},
                              files={"files": ("r62_2.csv", csv_data, "text/csv")})
            op2 = r2.json()["operation_id"]
            r_bad_acc_exp = await c.get(
                f"/api/v1/operations/{op2}/export",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "bmd", "default_bank_account": '1200";"EXTRA'},
            )
            assert r_bad_acc_exp.status_code == 422

            # Exceed RAM cache ceiling -> 413 cleanly before committing quota (R62-2)
            orig_max = shared_ram_budget.max_bytes
            try:
                shared_ram_budget.max_bytes = 50
                r_big = await c.post("/api/v1/convert?format=json&target_format=datev",
                                     headers={"Authorization": f"Bearer {token}"},
                                     files={"files": ("r62_big.csv", csv_data, "text/csv")})
                assert r_big.status_code == 413
            finally:
                shared_ram_budget.max_bytes = orig_max

            # Rollout hash compatibility (R62-2): pre-61 & Decision-61 ledger hashes must NOT fail with 409!
            import hashlib
            from app.db.session import async_session_maker
            from app.db.models import UsageReservation
            base_h = hashlib.sha256()
            base_h.update(b"r62.csv\x00" + csv_data + b"\x00")
            leg_v1_h = base_h.copy()
            leg_v1_h.update(b"json:1200:default")
            leg_d61_h = base_h.copy()
            leg_d61_h.update(b"json:1200:default:False")
            async with async_session_maker() as db:
                db.add(UsageReservation(
                    reservation_id=str(uuid.uuid4()),
                    tenant_id=tid,
                    idempotency_key="legacy-v1-key",
                    request_hash=leg_v1_h.hexdigest(),
                    units=1,
                    status="COMMITTED",
                ))
                db.add(UsageReservation(
                    reservation_id=str(uuid.uuid4()),
                    tenant_id=tid,
                    idempotency_key="legacy-d61-key",
                    request_hash=leg_d61_h.hexdigest(),
                    units=1,
                    status="COMMITTED",
                ))
                await db.commit()
            r_leg_v1 = await c.post(
                "/api/v1/convert?format=json",
                headers={"Authorization": f"Bearer {token}", "X-Idempotency-Key": "legacy-v1-key"},
                files={"files": ("r62.csv", csv_data, "text/csv")},
            )
            assert r_leg_v1.status_code == 410  # Clean 410 Gone instead of 409 Conflict!
            r_leg_d61 = await c.post(
                "/api/v1/convert?format=json",
                headers={"Authorization": f"Bearer {token}", "X-Idempotency-Key": "legacy-d61-key"},
                files={"files": ("r62.csv", csv_data, "text/csv")},
            )
            assert r_leg_d61.status_code == 410  # Clean 410 Gone instead of 409 Conflict!
            r_diff_payload = await c.post(
                "/api/v1/convert?format=json",
                headers={"Authorization": f"Bearer {token}", "X-Idempotency-Key": "legacy-v1-key"},
                files={"files": ("other.csv", csv_data, "text/csv")},
            )
            assert r_diff_payload.status_code == 409  # Mismatched file/payload STILL blocked with 409!
        finally:
            parser_supervisor.parse_file = orig_parse


def test_decision62_r62_4_and_r62_5_counterexamples():
    """Verifies R62-4 text fallback damaged amount & R62-5 order-independent + duplicate zero-net statement."""
    class NoColPage:
        def extract_words(self):
            return []

    p = ErsteBankAustriaParser()
    raw, errs = p._extract_page_transactions(
        page=NoColPage(),
        page_text=(
            "Buchungstext Valuta/Value Beträge/Amounts in EUR\n"
            "Good 01.09.2026 10,00-\n"
            "Bad 02.09.2026 12,3X-\n"
        ),
        page_num=1,
        seg_num=29,
        account_holder="Test",
        account_iban="",
        currency="EUR",
        filename="bad.pdf",
        use_valuta_as_booking_date=True,
    )
    assert len(raw) == 1
    assert raw[0]["Buchungstext"] == "Good"
    assert len(errs) == 1

    # Same-day [A, B] vs [B, A] both resolve identically to BALANCED
    ta = CanonicalTransaction(tenant_id="t", account_id="acct", booking_date=datetime.date(2026, 9, 1), amount_cents=100)
    tb = CanonicalTransaction(tenant_id="t", account_id="acct", booking_date=datetime.date(2026, 9, 1), amount_cents=200)
    sa = dict(opening_cents=0, closing_cents=100, txs=[ta], file="a.pdf", order=0)
    sb = dict(opening_cents=100, closing_cents=300, txs=[tb], file="b.pdf", order=1)
    r_fwd = build_statement_result("rf", "t", [ta, tb], {"default_acct": [sa, sb]}, 2, 2)
    r_rev = build_statement_result("rr", "t", [tb, ta], {"default_acct": [dict(sb, order=0), dict(sa, order=1)]}, 2, 2)
    assert r_fwd.overall_reconciliation == "BALANCED"
    assert r_rev.overall_reconciliation == "BALANCED"

    # Duplicated zero-net statement [+100, -100] must be rejected as DISCREPANCY
    z1 = CanonicalTransaction(tenant_id="t", account_id="acct", booking_date=datetime.date(2026, 9, 1), amount_cents=100)
    z2 = CanonicalTransaction(tenant_id="t", account_id="acct", booking_date=datetime.date(2026, 9, 2), amount_cents=-100)
    sz = dict(opening_cents=0, closing_cents=0, txs=[z1, z2], file="dup.pdf", order=0)
    r_dup = build_statement_result("rd", "t", [z1, z2, z1, z2], {"default_acct": [sz, dict(sz, file="dup2.pdf", order=1)]}, 2, 2)
    assert r_dup.overall_reconciliation == "DISCREPANCY"


# ---------------------------------------------------------------------------
# 7. Decision 63 Hardening Regressions (R63-1 – R63-4)
# ---------------------------------------------------------------------------

def build_synthetic_erste_bank_6seg_12tx_471_934_pdf(iban: Optional[str] = None) -> bytes:
    """
    Synthetic 6-segment (Nr. 029..034) Erste Bank PDF with exactly 12 transactions matching
    Decision 63 R63-3 control balances: Opening 471,66 + Net Turnover +462,76 = Closing 934,42.
    """
    if iban is None:
        iban = make_valid_at_iban("20111", "00000471934")
    # Sum of ALL 12 transactions = +50000 - 2000 - 1500 + 20000 - 12000 + 15000 - 10000 - 6000 - 5000 - 1000 - 750 - 474 = +46276 (+462,76)
    seg_specs = [
        (29, [("Honorar Kunde Alpha", ["Alpha GmbH"], "01.09.2026", 50000),
              ("Büromaterial", ["Papierhandel Wien"], "02.09.2026", -2000),
              ("Telefonrechnung", ["Telekom AG"], "03.09.2026", -1500)]),
        (30, [("Gutschrift Kunde Beta", ["Beta KG"], "08.09.2026", 20000),
              ("Software Abo", ["Cloud EU"], "09.09.2026", -12000)]),
        (31, [("Zahlungseingang Gamma", ["Gamma GmbH"], "14.09.2026", 15000),
              ("Versicherung", ["Assekuranz AT"], "15.09.2026", -10000)]),
        (32, [("Steuerberatung", ["Kanzlei Nord"], "20.09.2026", -6000)]),
        (33, [("Treibstoff", ["Tankstelle Süd"], "25.09.2026", -5000)]),
        (34, [("Buchungsgebühr Überweisungen", [], "30.09.2026", -1000),
              ("Kontoführungsentgelt", [], "30.09.2026", -750),
              ("Porto und Spesen", [], "30.09.2026", -474)]),
    ]
    cur_bal = 47166  # 471,66
    pages: List[List[Tuple[float, float, str]]] = []
    for seg_num, entries in seg_specs:
        open_bal = cur_bal
        seg_sum = sum(e[3] for e in entries)
        close_bal = open_bal + seg_sum
        cur_bal = close_bal
        items: List[Tuple[float, float, str]] = [
            (45, 45, "Erste Bank der oesterreichischen Sparkassen AG"),
            (400, 45, "GIBAATWW"),
            (45, 65, f"KONTOAUSZUG Nr. {seg_num:03d}/2026"),
            (45, 82, "Muster Kanzlei Baseline GmbH"),
            (45, 95, "zuletzt gültiger Kontowortlaut"),
            (45, 112, f"IBAN: {iban}"),
            (320, 112, "BIC: GIBAATWWXXX"),
            (45, 130, f"Alter Kontostand {_fmt_at_amt(open_bal, trailing_minus=True)}"),
            (45, 155, "Buchungstext"),
            (365, 155, "Valuta/Value"),
            (465, 155, "Beträge/Amounts in EUR"),
        ]
        y = 180.0
        if seg_num == 34:
            items.append((45, y, "*** Abschlussbuchung per 30.09.2026 ****"))
            items.append((365, y, "30.09.2026"))
            y += 16.0
        for line1, extras, valuta, cents in entries:
            items.append((45, y, line1))
            items.append((365, y, valuta))
            items.append((475, y, _fmt_at_amt(cents, trailing_minus=True)))
            y += 13.0
            for ex in extras:
                items.append((55, y, ex))
                y += 12.0
            y += 4.0
        items.append((45, y + 12.0, f"Neuer Kontostand/New Balance {_fmt_at_amt(close_bal, trailing_minus=True)}"))
        pages.append(items)
    assert cur_bal == 93442
    return build_vector_pdf(pages)


def test_decision63_r63_3_6seg_12tx_471_66_plus_462_76_934_42_baseline():
    """R63-3: 6-segment 12-tx Erste Bank baseline: 471,66 opening + 462,76 net ALL tx = 934,42 closing."""
    iban = make_valid_at_iban("20111", "00000471934")
    pdf_bytes = build_synthetic_erste_bank_6seg_12tx_471_934_pdf(iban)
    txs, acc_sum = registry.parse_file(pdf_bytes, "erste_6seg_12tx.pdf", "t63", use_valuta_as_booking_date=True)
    assert len(txs) == 12
    assert acc_sum.opening_balance_cents == 47166
    assert sum(t.amount_cents for t in txs) == 46276
    assert acc_sum.closing_balance_cents == 93442
    res = build_statement_result(
        "r63_12", "t63", txs,
        {f"{acc_sum.client_entity_id}_{acc_sum.account_id}": (
            acc_sum.opening_balance_cents, acc_sum.closing_balance_cents, acc_sum.bank_name
        )}, 1, 1,
    )
    assert res.overall_reconciliation == "BALANCED"


@pytest.mark.asyncio
async def test_decision63_r63_1_and_r63_4_cache_atomicity_and_replay_bytes():
    """
    R63-1: SharedMemoryBudget pair admission must NEVER leave orphaned refs or charge quota when pair exceeds budget
           (even if canonical fits alone, old entries apply pressure, or budget tightens mid-insert).
    R63-4: Direct CSV POST replay returns byte-for-byte identical SHA-256 across wall-clock second boundary.
    """
    import hashlib
    from sqlalchemy import select, func
    from app.db.session import init_db, async_session_maker
    from app.db.models import Tenant, UsageReservation
    from app.core.cache import estimate_size
    from app.main import shared_ram_budget, canonical_operation_cache, _idempotent_result_cache

    await init_db()
    tid = f"r63_{uuid.uuid4().hex[:8]}"
    email = f"{tid}@kanzlei-wien.at"
    async with async_session_maker() as db:
        db.add(Tenant(id=tid, email=email))
        await db.commit()
    token = create_access_token(user_id=email, tenant_id=tid)
    headers = {"Authorization": f"Bearer {token}"}
    csv_data = b"Datum;Text;Betrag\n05.09.2026;Synthetic office;50,00\n"

    async def committed_units() -> int:
        async with async_session_maker() as db:
            return (await db.execute(
                select(func.coalesce(func.sum(UsageReservation.units), 0))
                .where(UsageReservation.tenant_id == tid, UsageReservation.status == "COMMITTED")
            )).scalar()

    canonical_operation_cache.clear()
    _idempotent_result_cache.clear()
    orig_budget = shared_ram_budget.max_bytes
    orig_set = canonical_operation_cache.set
    orig_idem_set = _idempotent_result_cache.set

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        try:
            # 1. Fault-injection: canonical fits alone, budget tightens to canonical+1 before second insert -> MUST 413 + 0 delta + 0 orphan!
            def tighten_mid_flight(key, value, *args, **kwargs):
                shared_ram_budget.max_bytes = estimate_size(value) + 1
                return orig_set(key, value, *args, **kwargs)

            canonical_operation_cache.set = tighten_mid_flight
            before = await committed_units()
            r_pair = await c.post(
                "/api/v1/convert?format=json&target_format=bmd_bankauszug",
                headers={**headers, "X-Idempotency-Key": "r63-pair-1"},
                files={"files": ("r63.csv", csv_data, "text/csv")},
            )
            assert r_pair.status_code == 413
            assert await committed_units() == before
            assert len(canonical_operation_cache.keys()) == 0
            assert len(_idempotent_result_cache.keys()) == 0

            # 2. Failure on second cache insert -> MUST rollback canonical entry + 413 + 0 committed!
            canonical_operation_cache.set = orig_set
            shared_ram_budget.max_bytes = orig_budget
            _idempotent_result_cache.set = lambda *a, **kw: False
            r_sec_fail = await c.post(
                "/api/v1/convert?format=json&target_format=bmd_bankauszug",
                headers={**headers, "X-Idempotency-Key": "r63-pair-2"},
                files={"files": ("r63.csv", csv_data, "text/csv")},
            )
            assert r_sec_fail.status_code == 413
            assert await committed_units() == before
            assert len(canonical_operation_cache.keys()) == 0

            # 3. Pressure of existing entries: pre-fill stale items, set budget large enough for new pair ONLY if old evicted -> new pair succeeds atomically!
            _idempotent_result_cache.set = orig_idem_set
            canonical_operation_cache.set("stale_1", b"x" * 3000)
            canonical_operation_cache.set("stale_2", b"y" * 3000)
            shared_ram_budget.max_bytes = 5000
            r_evict_ok = await c.post(
                "/api/v1/convert?format=json&target_format=bmd_bankauszug",
                headers={**headers, "X-Idempotency-Key": "r63-pair-3"},
                files={"files": ("r63.csv", csv_data, "text/csv")},
            )
            assert r_evict_ok.status_code == 200
            op_id = r_evict_ok.json()["operation_id"]
            assert canonical_operation_cache.get(op_id) is not None
            assert await committed_units() == before + 1

            # 4. R63-4: Direct DATEV CSV replay across 1.1s boundary must produce identical SHA-256 bytes!
            shared_ram_budget.max_bytes = orig_budget
            h_rep = {**headers, "X-Idempotency-Key": "r63-datev-bytes"}
            r_d1 = await c.post("/api/v1/convert?format=datev", headers=h_rep, files={"files": ("r63.csv", csv_data, "text/csv")})
            await asyncio.sleep(1.1)
            r_d2 = await c.post("/api/v1/convert?format=datev", headers=h_rep, files={"files": ("r63.csv", csv_data, "text/csv")})
            assert r_d1.status_code == 200 and r_d2.status_code == 200
            assert hashlib.sha256(r_d1.content).hexdigest() == hashlib.sha256(r_d2.content).hexdigest()
            assert r_d1.content == r_d2.content
        finally:
            canonical_operation_cache.set = orig_set
            _idempotent_result_cache.set = orig_idem_set
            shared_ram_budget.max_bytes = orig_budget
            canonical_operation_cache.clear()
            _idempotent_result_cache.clear()


@pytest.mark.asyncio
async def test_decision63_r63_2_bounded_chain_12_segments_and_client_parity():
    """
    R63-2: 12 disconnected, 12 ambiguous, and 12 valid scrambled segments must resolve deterministically
    in < 0.5s (no factorial O(N!) hang) on BOTH backend and offline JS, keeping event loop responsive.
    """
    import time
    from pathlib import Path
    from app.services.reconciliation_service import _chain_file_segments

    def make_tx(desc, cents, day=1):
        return CanonicalTransaction(
            tenant_id="t63", account_id="acct63",
            booking_date=datetime.date(2026, 9, day),
            amount_cents=cents, description=desc,
        )

    # 1. Exact Codex 12-segment disconnected counterexample (11 unique 0->0 + 1 disjoint 1000->1100)
    disc_segs = []
    for i in range(11):
        disc_segs.append(dict(
            file=f"disc-{i}.pdf", opening_cents=0, closing_cents=0,
            txs=[make_tx(f"d-{i}-a", 100), make_tx(f"d-{i}-b", -100)],
        ))
    disc_segs.append(dict(file="disc-11.pdf", opening_cents=1000, closing_cents=1100, txs=[make_tx("d-11", 100)]))
    t0 = time.perf_counter()
    _, _, _, has_disc, _ = _chain_file_segments(disc_segs)
    assert time.perf_counter() - t0 < 0.5
    assert has_disc is True

    # 2. 12 connected ambiguous segments (11 unique 0->0 + 1 exiting 0->100)
    amb_segs = [dict(s) for s in disc_segs[:-1]] + [
        dict(file="amb-11.pdf", opening_cents=0, closing_cents=100, txs=[make_tx("amb-11", 100)])
    ]
    t1 = time.perf_counter()
    _, _, _, has_amb, _ = _chain_file_segments(amb_segs)
    assert time.perf_counter() - t1 < 0.5
    assert has_amb is True

    # 3. 12 connected unique sequential segments scrambled in upload order -> BALANCED < 0.5s
    seq_segs = [
        dict(file=f"seq-{i}.pdf", opening_cents=i * 100, closing_cents=(i + 1) * 100, txs=[make_tx(f"s-{i}", 100, day=i + 1)])
        for i in range(12)
    ]
    scrambled = list(reversed(seq_segs))
    t2 = time.perf_counter()
    op, cl, _, has_err, _ = _chain_file_segments(scrambled)
    assert time.perf_counter() - t2 < 0.5
    assert has_err is False and op == 0 and cl == 1200

    # 4. Async API responsiveness check (/healthz works swiftly)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        rh = await c.get("/healthz")
        assert rh.status_code == 200

    # 5. Client-side JS `chainClientFileSegments` parity on 12-segment disconnected + ambiguous + scrambled
    js_probe = r"""
const fs = require('fs');
const vm = require('vm');
const noop = () => {};
const el = () => ({ classList: { add: noop, remove: noop, contains: () => false }, addEventListener: noop, querySelectorAll: () => [], style: { setProperty: noop }, checked: true, disabled: false, textContent: '', value: '' });
const ctx = vm.createContext({
  document: { getElementById: el, querySelector: el, querySelectorAll: () => [], addEventListener: noop, createElement: el },
  window: { innerWidth: 400, location: { search: '' } },
  localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  alert: noop, confirm: () => true,
  chrome: { storage: { local: { get: async () => ({}), set: noop, remove: noop }, session: { get: async () => ({}), remove: noop } }, runtime: { getURL: p => p }, downloads: { download: noop }, tabs: { create: noop } },
  navigator: {}, fetch: noop, Blob, TextEncoder, TextDecoder, URLSearchParams,
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL: noop },
  AbortController, console, setTimeout, clearTimeout, setInterval: noop, clearInterval: noop
});
vm.runInContext(fs.readFileSync('extension/app.js', 'utf8'), ctx);
const t0 = Date.now();
const disc = Array.from({length: 11}, (_, i) => ({
  file: `d${i}.pdf`, openingCents: 0, closingCents: 0, stmtNum: null, stmtYear: null,
  txs: [{ booking_date: '2026-09-01', value_date: '2026-09-01', amount_cents: 100, currency: 'EUR', description: `d${i}-1` },
        { booking_date: '2026-09-01', value_date: '2026-09-01', amount_cents: -100, currency: 'EUR', description: `d${i}-2` }]
})).concat([{ file: 'd11.pdf', openingCents: 1000, closingCents: 1100, stmtNum: null, stmtYear: null,
  txs: [{ booking_date: '2026-09-01', value_date: '2026-09-01', amount_cents: 100, currency: 'EUR', description: 'd11' }] }]);
const rDisc = ctx.chainClientFileSegments(disc);
const amb = disc.slice(0, 11).concat([{ file: 'a11.pdf', openingCents: 0, closingCents: 100, stmtNum: null, stmtYear: null,
  txs: [{ booking_date: '2026-09-01', value_date: '2026-09-01', amount_cents: 100, currency: 'EUR', description: 'a11' }] }]);
const rAmb = ctx.chainClientFileSegments(amb);
const okSeq = Array.from({length: 12}, (_, i) => ({
  file: `s${i}.pdf`, openingCents: i * 100, closingCents: (i + 1) * 100, stmtNum: null, stmtYear: null,
  txs: [{ booking_date: `2026-09-${String(i + 1).padStart(2, '0')}`, value_date: '2026-09-01', amount_cents: 100, currency: 'EUR', description: `s${i}` }]
})).reverse();
const rOk = ctx.chainClientFileSegments(okSeq);
const dt = Date.now() - t0;
if (dt > 500 || !rDisc.hasDiscrepancy || !rAmb.hasDiscrepancy || rOk.hasDiscrepancy) {
  throw new Error('JS R63-2 failed: ' + JSON.stringify({ dt, rDisc, rAmb, rOk }));
}
console.log('JS_R63_2_OK:' + dt + 'ms');
"""
    root_dir = Path(__file__).resolve().parent.parent
    proc = subprocess.run(["node", "-e", js_probe], cwd=root_dir, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"JS R63-2 probe failed: {proc.stderr}\n{proc.stdout}"
    assert "JS_R63_2_OK" in proc.stdout
