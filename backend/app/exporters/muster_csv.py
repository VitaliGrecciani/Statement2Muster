import io
import csv
from typing import List
from app.schemas.canonical import CanonicalTransaction

def sanitize_csv_field(val: str) -> str:
    """Sanitizes text against formula injection (CWE-1236) and removes bare line breaks."""
    if not val:
        return ""
    val_str = str(val).replace('\r', '').replace('\n', ' ')
    if val_str and val_str[0] in ('=', '+', '-', '@', '\t', '\r'):
        val_str = "'" + val_str
    return val_str

def export_to_muster_csv(transactions: List[CanonicalTransaction]) -> bytes:
    """
    Exports CanonicalTransactions to clean 6-column Muster CSV format.
    Encoding: Windows-1252 with CRLF.
    Uses standard csv.writer with delimiter=';' and QUOTE_MINIMAL so values containing
    semicolons or quotes are properly escaped without splitting columns.
    """
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=';', quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")

    # Standard 6-column header
    writer.writerow(["Belegdatum", "Buchungstext", "Betrag", "Währung", "Belegnummer", "Gegenkonto/Konto"])

    for tx in transactions:
        date_str = tx.booking_date.strftime("%d.%m.%Y") if tx.booking_date else ""
        raw_desc = (tx.description or "").strip()
        raw_partner = (tx.partner or "").strip()
        if raw_partner and raw_desc and raw_partner not in raw_desc:
            combined_desc = f"{raw_partner} - {raw_desc}"
        else:
            combined_desc = raw_desc or raw_partner
        text = sanitize_csv_field(combined_desc)
        amount = tx.signed_amount
        currency = tx.currency or "EUR"
        ref = sanitize_csv_field(tx.reference or "")
        konto = sanitize_csv_field(tx.contra_account or "")

        writer.writerow([date_str, text, amount, currency, ref, konto])

    return out.getvalue().encode("windows-1252", errors="replace")
