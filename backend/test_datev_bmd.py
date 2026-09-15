import pytest
from pathlib import Path
from decimal import Decimal
import datetime

from app.schemas.canonical import CanonicalTransaction
from app.exporters.datev import export_to_datev_csv
from app.exporters.bmd import export_to_bmd_csv
from app.parsers.csv_parser import StructuredCsvParser

def test_datev_extf_export_format():
    tx = CanonicalTransaction(
        tenant_id="t_test",
        booking_date=datetime.date(2026, 1, 5),
        amount_cents=245000,
        currency="EUR",
        description="Meier GmbH - Rechnung RE-2026-001 Software",
        reference="RE-2026-001"
    )
    
    csv_bytes = export_to_datev_csv([tx], default_bank_account="1200")
    assert isinstance(csv_bytes, bytes)
    
    # Must be valid Windows-1252
    decoded = csv_bytes.decode("windows-1252")
    lines = decoded.strip().split("\r\n")
    
    # Header check
    assert lines[0].startswith('"EXTF";700;21;"Buchungsstapel";12;')
    assert '"Statement2Muster"' in lines[0]
    assert '"EUR"' in lines[0]
    
    # Data row check
    # Format: "2450,00";"S";"EUR";"";"";"";"1200";"";"";"0501";"RE-2026-001";"";"";"Meier GmbH - Rechnung RE-2026-001 Software"
    row = lines[2]
    parts = [p.strip('"') for p in row.split(";")]
    assert parts[0] == "2450,00"
    assert parts[1] == "S"
    assert parts[2] == "EUR"
    assert parts[6] == "1200"
    assert parts[9] == "0501"
    assert parts[10] == "RE-2026-001"
    assert "Meier GmbH" in parts[13]

def test_bmd_ntcs_export_format():
    tx_pos = CanonicalTransaction(
        tenant_id="t_test",
        booking_date=datetime.date(2026, 1, 5),
        amount_cents=245000,
        currency="EUR",
        description="Meier GmbH - Rechnung RE-2026-001 Software",
        reference="RE-2026-001"
    )
    tx_neg = CanonicalTransaction(
        tenant_id="t_test",
        booking_date=datetime.date(2026, 1, 8),
        amount_cents=-125000,
        currency="EUR",
        description="Immobilien Verwaltung KG - Bueromiete Jaenner 2026",
        reference="CSV-2"
    )
    
    csv_bytes = export_to_bmd_csv([tx_pos, tx_neg], default_bank_account="2800")
    decoded = csv_bytes.decode("windows-1252")
    lines = decoded.strip().split("\r\n")
    
    assert lines[0] == '"Satzart";"Belegdatum";"Konto";"Gegenkonto";"Betrag";"Währung";"Text";"Belegnummer"'
    
    # Positive row
    parts_pos = [p.strip('"') for p in lines[1].split(";")]
    assert parts_pos[0] == "0"
    assert parts_pos[1] == "05.01.2026"
    assert parts_pos[2] == "2800"
    assert parts_pos[4] == "2450,00"
    assert parts_pos[7] == "RE-2026-001"
    
    # Negative row
    parts_neg = [p.strip('"') for p in lines[2].split(";")]
    assert parts_neg[0] == "0"
    assert parts_neg[1] == "08.01.2026"
    assert parts_neg[2] == "2800"
    assert parts_neg[4] == "-1250,00"
    assert parts_neg[7] == "CSV-2"

def test_csv_parser_bank_statement():
    sample_csv = (
        "Auftragskonto;Buchungstag;Valutadatum;Buchungstext;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Kontonummer/IBAN;Betrag;Waehrung;Info\n"
        "AT611980000000001234;05.01.2026;05.01.2026;GUTSCHRIFT;Rechnung RE-2026-001 Software;Meier GmbH;DE89370400440532013000;2450,00;EUR;Umsatz gebucht\n"
        "AT611980000000001234;08.01.2026;08.01.2026;DAUERAUFTRAG;Bueromiete Jaenner 2026;Immobilien Verwaltung KG;AT022011100000009876;-1250,00;EUR;Umsatz gebucht\n"
    )
    parser = StructuredCsvParser()
    txs, summary = parser.parse_to_canonical(sample_csv.encode("utf-8"), "test.csv", "t_unit")
    
    assert len(txs) == 2
    assert txs[0].amount_cents == 245000
    assert txs[0].soll_haben_kennzeichen == "S"
    assert "Meier GmbH" in txs[0].description
    assert txs[0].reference == "Rechnung RE-2026-001"
    
    assert txs[1].amount_cents == -125000
    assert txs[1].soll_haben_kennzeichen == "H"
    assert "Immobilien Verwaltung KG" in txs[1].description
