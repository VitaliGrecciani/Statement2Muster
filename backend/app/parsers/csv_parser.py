import io
import re
import csv
import datetime
import hashlib
from decimal import Decimal
from typing import Tuple, List, Optional, Dict, Any
import pandas as pd
from app.parsers.base import BaseBankParser
from app.schemas.canonical import CanonicalTransaction, AccountSummary

class StructuredCsvParser(BaseBankParser):
    """
    Robust CSV parser with encoding auto-detection,
    exact integer cents parsing, and currency recognition.
    """

    def can_parse(self, content: bytes, filename: str) -> Tuple[bool, float]:
        if not filename.lower().endswith(('.csv', '.txt')):
            return False, 0.0

        # Check if text contains typical CSV headers
        text = self._decode_bytes(content[:2048])
        lower = text.lower()
        has_date = any(k in lower for k in ['datum', 'date', 'tag', 'zeitraum', 'buchung'])
        has_amount = any(k in lower for k in ['betrag', 'amount', 'umsatz', 'summe', 'wert'])

        if has_date and has_amount:
            return True, 0.85
        return True, 0.3  # Generic CSV fallback

    def parse_to_canonical(
        self,
        content: bytes,
        filename: str,
        tenant_id: str,
        client_entity_id: str = "default"
    ) -> Tuple[List[CanonicalTransaction], Optional[AccountSummary]]:
        text = self._decode_bytes(content)
        file_hash = hashlib.sha256(content).hexdigest()[:16]

        # Detect separator
        sep = self._detect_separator(text)
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, engine='python')
        except Exception:
            df = pd.read_csv(io.StringIO(text), sep=None, dtype=str, engine='python')

        date_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['datum', 'date', 'tag', 'zeitraum', 'buchung'])), None)
        text_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['text', 'verwendungszweck', 'empfänger', 'partner', 'beschreibung', 'details', 'name', 'zahlungsgrund'])), None)
        amount_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['betrag', 'amount', 'umsatz', 'summe', 'wert'])), None)
        curr_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['währung', 'waehrung', 'currency', 'wkz', 'curr'])), None)
        ref_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['beleg', 'referenz', 'reference', 'transaktion', 'auftrags'])), None)

        saldo_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['saldo nach buchung', 'kontostand nach', 'endsaldo', 'saldo'])), None)
        iban_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['auftragskonto', 'iban', 'kontonummer'])), None)
        bank_col = next((c for c in df.columns if any(k in str(c).lower() for k in ['bankname', 'institut', 'bank'])), None)

        if not date_col or not amount_col:
            return [], None

        account_id = "Bank_CSV"
        bank_name = "Structured CSV"
        if iban_col and len(df) > 0 and pd.notna(df[iban_col].iloc[0]):
            account_id = str(df[iban_col].iloc[0]).strip().replace(" ", "")
        if bank_col and len(df) > 0 and pd.notna(df[bank_col].iloc[0]):
            bank_name = str(df[bank_col].iloc[0]).strip()

        transactions: List[CanonicalTransaction] = []
        row_saldos: List[Tuple[int, int]] = []

        for idx, row in df.iterrows():
            date_val = str(row[date_col]).strip() if pd.notna(row[date_col]) else ""
            parsed_date = self._parse_date(date_val)

            raw_amount = str(row[amount_col]).strip() if pd.notna(row[amount_col]) else ""
            if not raw_amount:
                amount_cents, detected_curr, is_valid_amount = 0, None, False
            else:
                amount_cents, detected_curr, is_valid_amount = self._parse_amount_to_cents(raw_amount)

            row_validation = "VALID"
            row_warnings = []

            if not parsed_date:
                row_validation = "ERROR"
                row_warnings.append(f"Invalid calendar date: '{date_val}'")

            if not is_valid_amount:
                row_validation = "ERROR"
                row_warnings.append(f"Unparseable numeric amount: '{raw_amount}'")

            # Per-row account ID isolation (prevents account mixing across multiple rows/IBANs)
            row_account_id = account_id
            if iban_col and pd.notna(row[iban_col]):
                row_account_id = str(row[iban_col]).strip().replace(" ", "")

            curr = str(row[curr_col]).strip() if (curr_col and pd.notna(row[curr_col])) else (detected_curr or "EUR")
            desc = str(row[text_col]).strip() if (text_col and pd.notna(row[text_col])) else ""
            ref = str(row[ref_col]).strip() if (ref_col and pd.notna(row[ref_col])) else f"CSV-{idx+1}"

            if saldo_col and pd.notna(row[saldo_col]):
                raw_saldo = str(row[saldo_col]).strip()
                saldo_cents, _, _ = self._parse_amount_to_cents(raw_saldo)
                row_saldos.append((amount_cents, saldo_cents))

            tx = CanonicalTransaction(
                tenant_id=tenant_id,
                client_entity_id=client_entity_id,
                account_id=row_account_id,
                bank_name=bank_name,
                source_file_id=filename,
                source_row_page=f"row_{idx+1}",
                booking_date=parsed_date,
                amount_cents=amount_cents,
                currency=curr,
                description=desc,
                reference=ref,
                validation_status=row_validation,
                warnings=row_warnings
            )
            transactions.append(tx)

        opening_balance_cents = None
        closing_balance_cents = None
        if row_saldos:
            first_amount, first_saldo = row_saldos[0]
            _, last_saldo = row_saldos[-1]
            opening_balance_cents = first_saldo - first_amount
            closing_balance_cents = last_saldo

        account_summary = AccountSummary(
            account_id=account_id,
            bank_name=bank_name,
            client_entity_id=client_entity_id,
            transaction_count=len(transactions),
            files=[filename],
            opening_balance_cents=opening_balance_cents,
            closing_balance_cents=closing_balance_cents
        )

        return transactions, account_summary

    def _decode_bytes(self, content: bytes) -> str:
        for enc in ['utf-8-sig', 'utf-8', 'windows-1252', 'latin-1']:
            try:
                return content.decode(enc)
            except UnicodeDecodeError:
                continue
        return content.decode('utf-8', errors='ignore')

    def _detect_separator(self, text: str) -> str:
        first_line = text.splitlines()[0] if text.splitlines() else ""
        counts = {";": first_line.count(";"), ",": first_line.count(","), "\t": first_line.count("\t")}
        return max(counts, key=counts.get) if any(counts.values()) else ";"

    def _parse_date(self, val: str) -> Optional[datetime.date]:
        val = val.strip()
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d.%m.%y'):
            try:
                return datetime.datetime.strptime(val[:10], fmt).date()
            except ValueError:
                continue
        return None

    def _parse_amount_to_cents(self, val: str) -> Tuple[int, Optional[str], bool]:
        """
        Extracts currency and converts amount string to exact integer cents without float.
        Returns (cents, currency, is_valid).
        """
        currency = None
        val_upper = val.strip().upper()
        if "€" in val or "EUR" in val_upper:
            currency = "EUR"
        elif "$" in val or "USD" in val_upper:
            currency = "USD"
        elif "£" in val or "GBP" in val_upper:
            currency = "GBP"
        elif "CHF" in val_upper:
            currency = "CHF"

        is_negative = False
        # German banking/accounting suffixes: 'S' = Soll (debit / negative), 'H' = Haben (credit / positive)
        if val_upper.endswith(" S") or val_upper.endswith("S") or val_upper.endswith(" SOLL"):
            is_negative = True
        elif val_upper.endswith(" H") or val_upper.endswith("H") or val_upper.endswith(" HABEN"):
            is_negative = False

        cleaned = re.sub(r'[^\d,\.\-\+]', '', val).strip()
        if not cleaned:
            return 0, currency, False

        # Handle negative sign at end (e.g. "12,50-")
        if cleaned.endswith('-'):
            is_negative = True
            cleaned = cleaned[:-1]
        elif cleaned.startswith('-'):
            is_negative = True
            cleaned = cleaned[1:]
        elif cleaned.startswith('+'):
            cleaned = cleaned[1:]

        if not cleaned:
            return 0, currency, False

        # Distinguish European (1.234,56) vs US (1,234.56)
        if ',' in cleaned and '.' in cleaned:
            if cleaned.rfind(',') > cleaned.rfind('.'):
                # 1.234,56 -> replace . with '' and , with .
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                # 1,234.56 -> replace , with ''
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            # 12,50 -> 12.50
            cleaned = cleaned.replace(',', '.')

        try:
            dec = Decimal(cleaned)
            cents = int((dec * Decimal(100)).to_integral_value())
            if is_negative:
                cents = -cents
            return cents, currency, True
        except Exception:
            return 0, currency, False

