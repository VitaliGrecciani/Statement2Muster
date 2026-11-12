import logging
import datetime
import hashlib
from decimal import Decimal
import re
from typing import Tuple, List, Optional, Dict, Any
from fastapi import HTTPException

from app.schemas.canonical import CanonicalTransaction, AccountSummary
from app.parsers.amex_parser import AmexStatementParser, UniversalBankStatementParser
from app.parsers.erste_parser import ErsteBankAustriaParser, ErsteVisaCardParser
from app.parsers.csv_parser import StructuredCsvParser

logger = logging.getLogger("statement2muster.parsers")

class UnsupportedFormatError(Exception):
    """Raised when a file cannot be parsed by any supported bank profile."""
    pass

class BankParserRegistry:
    """
    Central registry and dispatcher for bank statement parsers.
    Implements profile discovery and normalization to CanonicalTransaction.
    """

    def __init__(self):
        self.erste_visa_parser = ErsteVisaCardParser()
        self.erste_bank_parser = ErsteBankAustriaParser()
        self.amex_parser = AmexStatementParser()
        self.universal_parser = UniversalBankStatementParser()
        self.csv_parser = StructuredCsvParser()

    def parse_file(
        self,
        content: bytes,
        filename: str,
        tenant_id: str,
        client_entity_id: str = "default",
        use_valuta_as_booking_date: bool = False,
    ) -> Tuple[List[CanonicalTransaction], Optional[AccountSummary]]:
        """
        Detects appropriate parser profile, executes parsing,
        and normalizes output into CanonicalTransactions.
        """
        lower_name = filename.lower()

        if lower_name.endswith(('.csv', '.txt')):
            can_csv, conf = self.csv_parser.can_parse(content, filename)
            if can_csv and conf > 0.1:
                txs, acc = self.csv_parser.parse_to_canonical(
                    content, filename, tenant_id=tenant_id, client_entity_id=client_entity_id
                )
                if txs:
                    if acc is not None and not acc.segment_fingerprint:
                        acc.segment_fingerprint = self._compute_segment_fingerprint(
                            acc.opening_balance_cents, acc.closing_balance_cents, acc.statement_numbers, txs
                        )
                    return txs, acc
            raise UnsupportedFormatError(f"CSV-Datei '{filename}' enthält keine erkennbaren Bankbuchungs-Spalten (Datum, Betrag).")

        elif lower_name.endswith('.pdf'):
            # 1. Profile detection (dedicated profiles MUST run before Universal; no silent fallback on specialist profile match)
            is_erste_visa = False
            is_erste_bank = False
            is_amex = False
            try:
                is_erste_visa = self.erste_visa_parser.is_applicable(content)
            except Exception:
                pass
            if not is_erste_visa:
                try:
                    is_erste_bank = self.erste_bank_parser.is_applicable(content)
                except Exception:
                    pass
            if not is_erste_visa and not is_erste_bank:
                try:
                    is_amex = self.amex_parser.is_applicable(content)
                except Exception:
                    pass

            file_res = None
            parser_name = "Universal"
            file_tag = f"file_{hashlib.sha256(filename.encode('utf-8')).hexdigest()[:8]}"

            if is_erste_visa:
                parser_name = "Erste Bank s Visa Card"
                try:
                    file_res = self.erste_visa_parser.parse_with_metadata(content, filename=filename)
                except HTTPException:
                    raise
                except Exception as e:
                    logger.debug(f"ErsteVisaCardParser failed on {file_tag}: {e}")
                    raise UnsupportedFormatError(f"Erste Visa Abrechnung '{filename}' konnte nicht geparst werden: {e}")
                if not file_res or not file_res.get("transactions"):
                    errs = " ".join((file_res or {}).get("errors") or [])
                    raise UnsupportedFormatError(
                        errs or f"Erste Visa Abrechnung '{filename}' enthält keine lesbaren Buchungen."
                    )
            elif is_erste_bank:
                parser_name = "Erste Bank Austria"
                try:
                    file_res = self.erste_bank_parser.parse_with_metadata(
                        content,
                        filename=filename,
                        use_valuta_as_booking_date=use_valuta_as_booking_date,
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.debug(f"ErsteBankAustriaParser failed on {file_tag}: {e}")
                    raise UnsupportedFormatError(f"Erste Bank Auszug '{filename}' konnte nicht geparst werden: {e}")
                if not file_res or not file_res.get("transactions"):
                    errs = " ".join((file_res or {}).get("errors") or [])
                    raise UnsupportedFormatError(
                        errs or f"Erste Bank Auszug '{filename}' enthält keine lesbaren Buchungen."
                    )
            else:
                if is_amex or "amex" in lower_name:
                    try:
                        file_res = self.amex_parser.parse_with_metadata(content, filename=filename)
                        parser_name = "American Express"
                    except HTTPException:
                        raise
                    except Exception as e:
                        logger.debug(f"Amex parser failed on {file_tag}: {e}")
                        if is_amex:
                            raise UnsupportedFormatError(f"American Express Auszug '{filename}' konnte nicht geparst werden: {e}")

                if not file_res or not file_res.get("transactions"):
                    try:
                        file_res = self.universal_parser.parse_with_metadata(content, filename=filename)
                        parser_name = "Universal Bank"
                    except HTTPException:
                        raise
                    except Exception as e:
                        logger.debug(f"Universal parser failed on {file_tag}: {e}")

            if not file_res or not file_res.get("transactions"):
                raise UnsupportedFormatError(
                    f"PDF-Datei '{filename}' konnte keinem unterstützten Bank-Profil (Erste Bank, Amex, VR Bank, Sparkasse) zugeordnet werden oder enthält keine lesbaren Buchungen."
                )

            # 2. Normalize raw transactions to CanonicalTransaction
            raw_txs = file_res.get("transactions", [])
            acc_id = file_res.get("account_id") or ""
            currency = file_res.get("currency") or "EUR"
            file_warnings = list(file_res.get("warnings") or [])

            canonical_txs = []
            for idx, raw in enumerate(raw_txs):
                tx = self._raw_to_canonical(
                    raw=raw,
                    idx=idx,
                    filename=filename,
                    tenant_id=tenant_id,
                    client_entity_id=client_entity_id,
                    default_acc_id=acc_id,
                    bank_name=parser_name,
                    default_currency=currency
                )
                if tx:
                    canonical_txs.append(tx)

            if not canonical_txs:
                raise UnsupportedFormatError(
                    f"PDF-Datei '{filename}' enthält keine gültigen normalisierbaren Buchungen."
                )

            # Try to extract balances & segment identity if present in metadata
            opening_bal = file_res.get("opening_balance_cents")
            closing_bal = file_res.get("closing_balance_cents")
            stmt_nums = [
                (int(y), int(n))
                for y, n in (file_res.get("statement_numbers") or [])
            ]
            seg_fp = self._compute_segment_fingerprint(opening_bal, closing_bal, stmt_nums, canonical_txs)

            account_summary = AccountSummary(
                account_id=acc_id or f"{parser_name}_{filename}",
                bank_name=parser_name,
                client_entity_id=client_entity_id,
                opening_balance_cents=opening_bal,
                closing_balance_cents=closing_bal,
                transaction_count=len(canonical_txs),
                files=[filename],
                warnings=file_warnings,
                statement_numbers=stmt_nums,
                segment_fingerprint=seg_fp,
            )

            return canonical_txs, account_summary

        else:
            raise UnsupportedFormatError(
                f"Dateiformat von '{filename}' wird nicht unterstützt. Bitte laden Sie PDF- oder CSV-Kontoauszüge hoch."
            )

    def _compute_segment_fingerprint(
        self,
        opening_cents: Optional[int],
        closing_cents: Optional[int],
        statement_numbers: List[Tuple[int, int]],
        txs: List[CanonicalTransaction],
    ) -> str:
        sig_items = sorted(
            (
                t.booking_date.isoformat() if t.booking_date else "",
                t.value_date.isoformat() if t.value_date else "",
                int(t.amount_cents),
                (t.currency or "EUR").upper(),
                (t.description or "").strip(),
                (t.partner or "").strip(),
            )
            for t in txs
        )
        raw = repr((opening_cents, closing_cents, sorted(statement_numbers), sig_items))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _raw_to_canonical(
        self,
        raw: Dict[str, Any],
        idx: int,
        filename: str,
        tenant_id: str,
        client_entity_id: str,
        default_acc_id: str,
        bank_name: str,
        default_currency: str
    ) -> Optional[CanonicalTransaction]:
        raw_date = str(raw.get("Belegdatum") or "").strip()
        parsed_date = self._parse_date(raw_date) if raw_date else None

        raw_valuta = str(raw.get("Valutadatum") or "").strip()
        parsed_valuta = self._parse_date(raw_valuta) if raw_valuta else None

        if not parsed_date and not (raw.get("_allow_missing_booking_date") and parsed_valuta):
            return None

        if raw.get("_amount_cents") is not None:
            cents = int(raw["_amount_cents"])
            detected_curr = None
        else:
            raw_amount = str(raw.get("Betrag", "0")).strip()
            cents, detected_curr = self._parse_amount_to_cents(raw_amount)

        curr = raw.get("Währung") or detected_curr or default_currency or "EUR"
        desc = str(raw.get("Buchungstext") or "").strip()
        ref = str(raw.get("Belegnummer") or f"TX-{idx+1}")
        acc_id = str(raw.get("_account_id") or default_acc_id)

        raw_partner = raw.get("Partner")
        partner = str(raw_partner).strip() if raw_partner else None

        raw_partner_iban = raw.get("PartnerIBAN")
        partner_iban = str(raw_partner_iban).strip().replace(" ", "") if raw_partner_iban else None
        if partner_iban and acc_id and partner_iban.upper() == acc_id.replace(" ", "").upper():
            partner_iban = None

        raw_fx_curr = raw.get("ForeignCurrency")
        foreign_currency = str(raw_fx_curr).strip().upper() if raw_fx_curr else None
        raw_fx_cents = raw.get("ForeignAmountCents")
        foreign_amount_cents = int(raw_fx_cents) if raw_fx_cents is not None else None

        val_status = raw.get("_validation_status") or "VALID"
        if val_status not in ("VALID", "AMBIGUOUS", "ERROR"):
            val_status = "VALID"
        tx_warnings = list(raw.get("_warnings") or [])

        return CanonicalTransaction(
            tenant_id=tenant_id,
            client_entity_id=client_entity_id,
            account_id=acc_id,
            bank_name=bank_name,
            source_file_id=filename,
            source_row_page=f"item_{idx+1}",
            booking_date=parsed_date,
            value_date=parsed_valuta,
            amount_cents=cents,
            currency=curr,
            description=desc,
            partner=partner,
            partner_iban=partner_iban,
            foreign_currency=foreign_currency,
            foreign_amount_cents=foreign_amount_cents,
            reference=ref,
            validation_status=val_status,
            warnings=tx_warnings,
        )

    def _parse_date(self, val: str) -> Optional[datetime.date]:
        val = val.strip()
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d.%m.%y'):
            try:
                return datetime.datetime.strptime(val[:10], fmt).date()
            except ValueError:
                continue
        return None

    def _parse_amount_to_cents(self, val: str) -> Tuple[int, Optional[str]]:
        currency = None
        if "€" in val or "EUR" in val:
            currency = "EUR"
        elif "$" in val or "USD" in val:
            currency = "USD"
        elif "£" in val or "GBP" in val:
            currency = "GBP"
        elif "CHF" in val:
            currency = "CHF"

        cleaned = re.sub(r'[^\d,\.\-\+sShH]', '', val).strip()
        if not cleaned:
            return 0, currency

        is_negative = False
        upper = cleaned.upper()
        if upper.endswith('-') or upper.startswith('-') or upper.endswith('S'):
            is_negative = True
            cleaned = re.sub(r'[\-sS]', '', cleaned)
        elif upper.endswith('+') or upper.startswith('+') or upper.endswith('H'):
            is_negative = False
            cleaned = re.sub(r'[\+hH]', '', cleaned)

        # European vs US decimal parsing
        if ',' in cleaned and '.' in cleaned:
            if cleaned.rfind(',') > cleaned.rfind('.'):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            cleaned = cleaned.replace(',', '.')

        try:
            dec = Decimal(cleaned)
            cents = int((dec * Decimal(100)).to_integral_value())
            if is_negative:
                cents = -cents
            return cents, currency
        except Exception:
            return 0, currency

registry = BankParserRegistry()
