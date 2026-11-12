import csv
import io
import re
from typing import List
from app.schemas.canonical import CanonicalTransaction
from app.exporters.bmd_bankauszug import sanitize_csv_text


def export_to_bmd_csv(transactions: List[CanonicalTransaction], default_bank_account: str = "2800") -> bytes:
    """
    Exports CanonicalTransactions to Austrian BMD NTCS 5.1 Bankauszugsverbuchung format (8 columns).
    Encoding: Windows-1252 with CRLF. Uses stdlib csv.writer for RFC-compliant quoting.
    """
    konto = (default_bank_account or "2800").strip()
    if not re.fullmatch(r"[0-9]{3,9}", konto):
        raise ValueError(f"Invalid BMD bank account code: '{konto}'")

    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(["Satzart", "Belegdatum", "Konto", "Gegenkonto", "Betrag", "Währung", "Text", "Belegnummer"])

    for tx in transactions:
        satzart = "0"
        belegdatum = tx.booking_date.strftime("%d.%m.%Y") if tx.booking_date else ""
        gegenkonto = (tx.contra_account or "").strip()
        if gegenkonto and not re.fullmatch(r"[0-9]{3,9}", gegenkonto):
            raise ValueError(f"Invalid BMD contra_account code: '{gegenkonto}'")
        betrag = tx.signed_amount  # Signed with comma e.g. -12,34
        waehrung = (tx.currency or "EUR").strip()
        raw_desc = (tx.description or "").strip()
        raw_partner = (tx.partner or "").strip()
        if raw_partner and raw_desc and raw_partner not in raw_desc:
            combined_desc = f"{raw_partner} - {raw_desc}"
        else:
            combined_desc = raw_desc or raw_partner
        text = sanitize_csv_text(combined_desc)[:120]
        belegnummer = sanitize_csv_text(tx.reference or "")[:30]

        writer.writerow([satzart, belegdatum, konto, gegenkonto, betrag, waehrung, text, belegnummer])

    return out.getvalue().encode("windows-1252", errors="replace")
