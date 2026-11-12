import csv
import io
import re
from typing import List, Optional
from app.schemas.canonical import CanonicalTransaction

BMD_BANKAUSZUG_HEADERS: List[str] = [
    "Transaction Booking Date",
    "Transaction Purpose",
    "Transaction Partner",
    "Transaction Partner IBAN",
    "Transaction Foreign Currency",
    "Transaction Foreign Amount",
    "Transaction Currency",
    "Transaction Amount",
    "Booking Amount",
    "Invoice Type",
    "Invoice Currency",
    "Invoice Total",
    "Invoice Number",
    "Invoice Internal No",
    "Invoice Date",
    "Invoice Partner Company",
    "Invoice Partner Number",
    "Invoice Document ID",
    "Invoice File",
    "Invoice Tags",
    "Transaction ID",
    "Payment Category",
]

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def sanitize_csv_text(val: Optional[str]) -> str:
    """
    Normalizes internal line breaks/control characters and neutralizes formula
    injection prefixes (CWE-1236) for untrusted text fields only.
    Never pass typed numeric amount fields through this function.
    """
    if not val:
        return ""
    text = str(val).replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _CTRL_RE.sub("", text).strip()
    if not text:
        return ""
    if text[0] in _FORMULA_PREFIXES:
        text = "'" + text
    return text


def format_signed_cents_comma(cents: int) -> str:
    """Formats integer cents with decimal comma and no thousands separator. Never returns '-0,00'."""
    if cents == 0:
        return "0,00"
    sign = "-" if cents < 0 else ""
    abs_cents = abs(cents)
    return f"{sign}{abs_cents // 100},{abs_cents % 100:02d}"


def export_to_bmd_bankauszug_csv(transactions: List[CanonicalTransaction]) -> bytes:
    """
    Exports CanonicalTransactions to the 22-column BMD Bankauszugsverbuchung CSV profile.
    Encoding: UTF-8 with BOM (utf-8-sig), semicolon delimiter, CRLF line endings.
    """
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(BMD_BANKAUSZUG_HEADERS)

    for tx in transactions:
        date_str = tx.booking_date.strftime("%d.%m.%Y") if tx.booking_date else ""
        raw_partner = (tx.partner or "").strip()
        raw_desc = (tx.description or "").strip()

        # Avoid duplicating partner in both Purpose (col 2) and Partner (col 3)
        if raw_partner and raw_desc.startswith(f"{raw_partner} - "):
            raw_desc = raw_desc[len(raw_partner) + 3 :].strip()
        elif raw_partner and raw_desc == raw_partner:
            raw_desc = ""

        purpose = sanitize_csv_text(raw_desc)
        partner = sanitize_csv_text(raw_partner)

        partner_iban = sanitize_csv_text((tx.partner_iban or "").replace(" ", ""))
        # Never leak account holder IBAN into Transaction Partner IBAN
        if partner_iban and tx.account_id and partner_iban == tx.account_id.replace(" ", ""):
            partner_iban = ""

        foreign_currency = sanitize_csv_text(tx.foreign_currency)
        foreign_amount = (
            format_signed_cents_comma(tx.foreign_amount_cents)
            if (foreign_currency and tx.foreign_amount_cents is not None)
            else ""
        )

        currency = sanitize_csv_text((tx.currency or "EUR").upper()) or "EUR"
        amount_str = format_signed_cents_comma(tx.amount_cents)

        row = [
            date_str,          # 1. Transaction Booking Date
            purpose,           # 2. Transaction Purpose
            partner,           # 3. Transaction Partner
            partner_iban,      # 4. Transaction Partner IBAN
            foreign_currency,  # 5. Transaction Foreign Currency
            foreign_amount,    # 6. Transaction Foreign Amount
            currency,          # 7. Transaction Currency
            amount_str,        # 8. Transaction Amount
            amount_str,        # 9. Booking Amount (EUR-settled semantics)
            "",                # 10. Invoice Type
            "",                # 11. Invoice Currency
            "",                # 12. Invoice Total
            "",                # 13. Invoice Number
            "",                # 14. Invoice Internal No
            "",                # 15. Invoice Date
            "",                # 16. Invoice Partner Company
            "",                # 17. Invoice Partner Number
            "",                # 18. Invoice Document ID
            "",                # 19. Invoice File
            "",                # 20. Invoice Tags
            "",                # 21. Transaction ID
            "",                # 22. Payment Category
        ]
        writer.writerow(row)

    return out.getvalue().encode("utf-8-sig")
