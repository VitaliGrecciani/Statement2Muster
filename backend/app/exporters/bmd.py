from typing import List
from app.schemas.canonical import CanonicalTransaction

def export_to_bmd_csv(transactions: List[CanonicalTransaction], default_bank_account: str = "2800") -> bytes:
    """
    Exports CanonicalTransactions to Austrian BMD NTCS 5.1 Bankauszugsverbuchung format.
    Encoding: Windows-1252 with CRLF.
    """
    header = '"Satzart";"Belegdatum";"Konto";"Gegenkonto";"Betrag";"Währung";"Text";"Belegnummer"\r\n'
    lines = [header]

    for tx in transactions:
        satzart = "0"
        belegdatum = tx.booking_date.strftime("%d.%m.%Y")
        konto = default_bank_account
        gegenkonto = tx.contra_account or ""
        betrag = tx.signed_amount  # Signed with comma e.g. -12,34
        waehrung = tx.currency or "EUR"
        text = (tx.description or "").replace('"', '""').replace('\n', ' ').replace('\r', '')[:120]
        belegnummer = (tx.reference or "").replace('"', '""')[:30]

        row = f'"{satzart}";"{belegdatum}";"{konto}";"{gegenkonto}";"{betrag}";"{waehrung}";"{text}";"{belegnummer}"\r\n'
        lines.append(row)

    full_csv = "".join(lines)
    return full_csv.encode("windows-1252", errors="replace")
