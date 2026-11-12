import csv
import io
import re
import datetime
from typing import List, Optional
from app.schemas.canonical import CanonicalTransaction
from app.exporters.bmd_bankauszug import sanitize_csv_text

def export_to_datev_csv(
    transactions: List[CanonicalTransaction],
    default_bank_account: str = "1200",
    export_timestamp: Optional[datetime.datetime] = None,
) -> bytes:
    """
    Exports CanonicalTransactions to official DATEV Format (Buchungsstapel EXTF Version 700).
    Encoding: Windows-1252 with CRLF.
    If `export_timestamp` is supplied (R63-4), uses it verbatim for reproducible replays.
    """
    konto = (default_bank_account or "1200").strip()
    if not re.fullmatch(r"[0-9]{3,9}", konto):
        raise ValueError(f"Invalid DATEV bank account code: '{konto}'")

    now = export_timestamp or datetime.datetime.now()
    timestamp_str = now.strftime("%Y%m%d%H%M%S000")

    # Determine fiscal year from transactions if available
    valid_years = [tx.booking_date.year for tx in transactions if tx.booking_date]
    if valid_years:
        year = str(min(valid_years))
    else:
        year = now.strftime("%Y")

    # Row 1: EXTF Metadata Header (22 fields, WKZ in col 22)
    header_1 = (
        f'"EXTF";700;21;"Buchungsstapel";12;{timestamp_str};;"";"";"";'
        f'1001;10001;{year}0101;4;{year}0101;{year}1231;'
        f'"Statement2Muster";"";1;;0;"EUR"\r\n'
    )

    out = io.StringIO(newline="")
    out.write(header_1)
    writer = csv.writer(out, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL, lineterminator="\r\n")

    # Row 2: Field Names
    writer.writerow([
        "Umsatz (ohne Soll/Haben-Kz)",
        "Soll/Haben-Kennzeichen",
        "WKZ Umsatz",
        "Kurs",
        "Basis-Umsatz",
        "WKZ Basis-Umsatz",
        "Konto",
        "Gegenkonto (ohne BU-Schlüssel)",
        "BU-Schlüssel",
        "Belegdatum",
        "Belegfeld 1",
        "Belegfeld 2",
        "Skonto",
        "Buchungstext",
    ])

    for tx in transactions:
        umsatz = tx.abs_amount_str
        sh = tx.soll_haben_kennzeichen
        wkz = (tx.currency or "EUR").strip()
        kurs = ""
        basis_umsatz = ""
        wkz_basis = ""
        gegenkonto = (tx.contra_account or "").strip()
        if gegenkonto and not re.fullmatch(r"[0-9]{3,9}", gegenkonto):
            raise ValueError(f"Invalid DATEV contra_account code: '{gegenkonto}'")
        bu = ""
        belegdatum = tx.booking_date.strftime("%d%m") if tx.booking_date else "0000"
        belegfeld_1 = sanitize_csv_text(tx.reference or "")[:36]
        belegfeld_2 = ""
        skonto = ""

        raw_desc = (tx.description or "").strip()
        raw_partner = (tx.partner or "").strip()
        if raw_partner and raw_desc and raw_partner not in raw_desc:
            combined_desc = f"{raw_partner} - {raw_desc}"
        else:
            combined_desc = raw_desc or raw_partner
        buchungstext = sanitize_csv_text(combined_desc)[:60]

        writer.writerow([
            umsatz, sh, wkz, kurs, basis_umsatz, wkz_basis,
            konto, gegenkonto, bu, belegdatum, belegfeld_1,
            belegfeld_2, skonto, buchungstext,
        ])

    return out.getvalue().encode("windows-1252", errors="replace")
