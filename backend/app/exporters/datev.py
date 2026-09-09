import io
import datetime
from typing import List
from app.schemas.canonical import CanonicalTransaction

def export_to_datev_csv(transactions: List[CanonicalTransaction], default_bank_account: str = "1200") -> bytes:
    """
    Exports CanonicalTransactions to official DATEV Format (Buchungsstapel EXTF Version 700).
    Encoding: Windows-1252 with CRLF.
    """
    now = datetime.datetime.now()
    timestamp_str = now.strftime("%Y%m%d%H%M%S000")

    # Determine fiscal year from transactions if available
    valid_years = [tx.booking_date.year for tx in transactions if tx.booking_date]
    if valid_years:
        year = str(min(valid_years))
    else:
        year = now.strftime("%Y")

    # Row 1: EXTF Metadata Header
    # Format: "EXTF";Version;Format-Kategorie;Format-Name;Format-Version;Erzeugt-Am;Importiert;Herkunft;Exportiert-Von;Importiert-Von;Berater;Mandant;Wirtschaftsjahr-Beginn;Sachkontenlänge;Datum-Von;Datum-Bis;Bezeichnung;Diktatkürzel;Buchungstyp;Rechnungslegungszweck;Festschreibung;WKZ
    header_1 = (
        f'"EXTF";700;21;"Buchungsstapel";12;{timestamp_str};;"";"";"";'
        f'1001;10001;{year}0101;4;{year}0101;{year}1231;'
        f'"Statement2Muster";"";1;;0;"EUR"\r\n'
    )

    # Row 2: Field Names
    header_2 = (
        '"Umsatz (ohne Soll/Haben-Kz)";"Soll/Haben-Kennzeichen";"WKZ Umsatz";"Kurs";'
        '"Basis-Umsatz";"WKZ Basis-Umsatz";"Konto";"Gegenkonto (ohne BU-Schlüssel)";'
        '"BU-Schlüssel";"Belegdatum";"Belegfeld 1";"Belegfeld 2";"Skonto";"Buchungstext"\r\n'
    )

    lines = [header_1, header_2]

    for tx in transactions:
        # 1. Umsatz: absolute amount with comma (e.g. 12,34)
        umsatz = tx.abs_amount_str

        # 2. Soll/Haben: 'S' for debit (negative), 'H' for credit (positive)
        sh = tx.soll_haben_kennzeichen

        # 3. Currency
        wkz = tx.currency or "EUR"

        # 4-6. Kurs, Basis-Umsatz, WKZ Basis-Umsatz
        kurs = ""
        basis_umsatz = ""
        wkz_basis = ""

        # 7. Konto: default Sachkonto or parsed
        konto = default_bank_account

        # 8. Gegenkonto
        gegenkonto = tx.contra_account or ""

        # 9. BU-Schlüssel
        bu = ""

        # 10. Belegdatum: Format TTMM (DATEV standard 4-digit date)
        belegdatum = tx.booking_date.strftime("%d%m") if tx.booking_date else "0000"

        # 11. Belegfeld 1: Reference (max 36 chars in DATEV)
        belegfeld_1 = (tx.reference or "")[:36].replace('"', '""')

        # 12. Belegfeld 2
        belegfeld_2 = ""

        # 13. Skonto
        skonto = ""

        # 14. Buchungstext: max 60 characters in DATEV
        buchungstext = (tx.description or "")[:60].replace('"', '""').replace('\n', ' ').replace('\r', '')

        row = (
            f'"{umsatz}";"{sh}";"{wkz}";"{kurs}";"{basis_umsatz}";"{wkz_basis}";'
            f'"{konto}";"{gegenkonto}";"{bu}";"{belegdatum}";"{belegfeld_1}";'
            f'"{belegfeld_2}";"{skonto}";"{buchungstext}"\r\n'
        )
        lines.append(row)

    full_csv = "".join(lines)
    return full_csv.encode("windows-1252", errors="replace")
