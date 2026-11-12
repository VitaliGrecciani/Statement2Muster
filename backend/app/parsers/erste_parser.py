import datetime
import hashlib
import io
import logging
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber
from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger("statement2muster.erste")

_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_EUR_AMOUNT_RE = re.compile(r"^([+-]?)\s*(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*([+-]?)$")
_IBAN_RE = re.compile(r"\b(AT\d{2}\s?(?:\d{4}\s?){4})\b")
_STMT_NUM_RE = re.compile(r"\bNr\.\s*(\d{1,4})/(\d{4})\b", re.IGNORECASE)


def parse_strict_dmy(raw: str) -> Optional[datetime.date]:
    """Parses strict DD.MM.YYYY with real calendar validation (rejects e.g. 29.02.2026)."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not _DATE_RE.match(cleaned):
        return None
    try:
        return datetime.datetime.strptime(cleaned, "%d.%m.%Y").date()
    except ValueError:
        return None


def is_valid_iban(iban: str) -> bool:
    """Validates IBAN format and ISO 7064 mod-97 checksum."""
    cleaned = re.sub(r"\s+", "", (iban or "").upper())
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$", cleaned):
        return False
    if cleaned.startswith("AT") and len(cleaned) != 20:
        return False
    if cleaned.startswith("DE") and len(cleaned) != 22:
        return False
    rearranged = cleaned[4:] + cleaned[:4]
    numeric_str = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    try:
        return int(numeric_str) % 97 == 1
    except ValueError:
        return False


def parse_strict_eur_cents(raw: str) -> Optional[int]:
    """
    Parses strict DACH comma-decimal EUR amount strings such as:
    '72,00-', '4,38 -', '1.000,00', '0,04', '+294,83', '-12,50'.
    Rejects dot-decimal numbers (like FX rate '1.1567' or fee '0.64') and conflicting signs.
    """
    if not raw:
        return None
    cleaned = (
        str(raw)
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2212", "-")
        .replace("EUR", "")
        .replace("€", "")
        .strip()
    )
    m = _EUR_AMOUNT_RE.match(cleaned)
    if not m:
        return None
    lead_sign, int_part, dec_part, trail_sign = m.groups()
    if lead_sign and trail_sign:
        # Conflicting or duplicated signs (e.g. "-12,00-" or "+12,00-")
        return None
    if "." in int_part:
        # Verify strict thousands grouping (e.g. 1.000, not 1.15)
        groups = int_part.split(".")
        if len(groups[0]) < 1 or len(groups[0]) > 3 or any(len(g) != 3 for g in groups[1:]):
            return None
    int_digits = int_part.replace(".", "")
    cents = int(int_digits) * 100 + int(dec_part)
    if lead_sign == "-" or trail_sign == "-":
        return -cents if cents != 0 else 0
    return cents


def _group_words_by_line(words: List[Dict[str, Any]], y_tolerance: float = 3.5) -> List[List[Dict[str, Any]]]:
    """Groups pdfplumber words into visual horizontal lines ordered top-to-bottom, left-to-right."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (round(float(w["top"]), 1), float(w["x0"])))
    lines: List[List[Dict[str, Any]]] = []
    current_line: List[Dict[str, Any]] = []
    current_top: Optional[float] = None

    for w in sorted_words:
        top = float(w["top"])
        if current_top is None or abs(top - current_top) <= y_tolerance:
            current_line.append(w)
            if current_top is None:
                current_top = top
        else:
            current_line.sort(key=lambda item: float(item["x0"]))
            lines.append(current_line)
            current_line = [w]
            current_top = top
    if current_line:
        current_line.sort(key=lambda item: float(item["x0"]))
        lines.append(current_line)
    return lines


def _extract_iban_strict(text: str) -> Tuple[str, bool]:
    """
    Finds IBAN after 'IBAN:' or standalone AT/DE IBAN token.
    Stops cleanly before adjacent metadata labels (e.g. 'BIC:', 'SWIFT:') on the same line.
    Returns (cleaned_iban, is_valid_or_empty). If malformed IBAN exists, returns (raw, False).
    """
    raw_segment = ""
    m = re.search(r"IBAN\s*:\s*([^\r\n]+)", text or "", re.IGNORECASE)
    if m:
        line_tail = re.split(r"(?:^|\s)\b(?:BIC|SWIFT)\b\s*:?", m.group(1), maxsplit=1, flags=re.IGNORECASE)[0].strip()
        tok = re.match(r"^([A-Z]{2}\d{2}(?:[ \t]*[A-Z0-9]{1,4}){2,8})", line_tail, re.IGNORECASE)
        if tok:
            raw_segment = tok.group(1)
        elif line_tail:
            raw_segment = line_tail.split()[0]
    else:
        m2 = re.search(r"\b(AT\d{2}(?:\s?\d{4}){4})\b", text or "")
        if m2:
            raw_segment = m2.group(1)
    if not raw_segment:
        return "", True
    candidate = re.sub(r"\s+", "", raw_segment.strip().upper())
    return candidate, is_valid_iban(candidate)


def _classify_erste_partner(extra_lines: List[str], line1_text: str) -> Tuple[Optional[str], List[str]]:
    """
    Separates counterparty/partner name from continuation purpose lines in Erste Digitales Banking.
    Returns (partner_or_none, remaining_purpose_lines) without duplicating partner in both fields.
    """
    if not extra_lines:
        return None, []

    cand = extra_lines[0].strip()
    if not cand:
        return None, extra_lines[1:]

    cand_lower = cand.lower()
    non_partner_prefixes = (
        "kartenendnummer",
        "s visa card",
        "s mastercard",
        "iban",
        "bic",
        "mandatsreferenz",
        "gläubiger-id",
        "referenz",
        "reklamationen",
        "verwendungszweck",
        "kurs",
        "entgelt",
    )
    if any(cand_lower.startswith(p) for p in non_partner_prefixes):
        return None, extra_lines

    if "iban" in cand_lower or re.search(r"\b(?:AT|DE)\d{2}\s?\d{4}", cand):
        return None, extra_lines

    company_markers = (
        "gmbh",
        "ag",
        "kg",
        "og",
        "ug",
        "e.u.",
        "ltd",
        "limited",
        "inc.",
        "inc",
        "s.à r.l.",
        "sarl",
        "ohg",
        "gbr",
        "mbh",
        "stiftung",
        "verein",
        "versicherung",
        "bank",
        "wien",
        "österreich",
        "austria",
        "finanzamt",
        "gericht",
    )
    has_company_marker = any(
        re.search(rf"(?:^|\b|\s){re.escape(marker)}(?:$|\b|\s|\.)", cand_lower)
        for marker in company_markers
    ) or cand.startswith(("HG ", "BG ", "LG "))

    # Purely clean personal/entity name on continuation line (2-4 capitalized words, no numbers)
    is_clean_name = bool(
        re.match(r"^[A-ZÄÖÜ][A-Za-zÄÖÜäöüß&\.\-]+(?:\s+[A-ZÄÖÜa-zäöüß&\.\-]+){1,4}$", cand)
        and not any(ch.isdigit() for ch in cand)
    )

    # Known fee/product descriptions shouldn't misclassify single-line fees (extra_lines is empty there anyway),
    # and if line1 already IS just a bank card bill summary ("s Kreditkartenrechnung ..."), avoid wrong attribution.
    if "kreditkartenrechnung" in line1_text.lower() and "visa card" in cand_lower:
        return None, extra_lines

    if has_company_marker or is_clean_name:
        return cand, extra_lines[1:]

    return None, extra_lines


class ErsteBankAustriaParser:
    """
    Dedicated parser for Erste Bank / Sparkassen Austria 'Digitales Banking' Kontoauszug PDFs
    (with multi-page segment support, Valuta/Value date tracking, and per-segment balance checks).
    """

    def is_applicable(self, pdf_bytes: bytes) -> bool:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if not pdf.pages:
                    return False
                first_text = (pdf.pages[0].extract_text() or "").upper()
                has_erste = (
                    "ERSTE BANK" in first_text
                    or "OESTERREICHISCHEN SPARKASSEN" in first_text
                    or "GIBAATWW" in first_text
                )
                has_stmt = "KONTOAUSZUG" in first_text or "ACCOUNT STATEMENT" in first_text
                has_cols = "BUCHUNGSTEXT" in first_text and "VALUTA" in first_text
                return has_erste and has_stmt and has_cols
        except Exception as e:
            logger.debug(f"ErsteBankAustriaParser.is_applicable error: {e}")
            return False

    def parse_with_metadata(
        self,
        pdf_bytes: bytes,
        filename: str = "",
        use_valuta_as_booking_date: bool = False,
    ) -> Dict[str, Any]:
        file_tag = hashlib.sha256((filename or "erste").encode("utf-8")).hexdigest()[:8]
        transactions: List[Dict[str, Any]] = []
        warnings: List[str] = []
        unparsed_errors: List[str] = []

        account_holder = "Erste Bank Kunde"
        account_iban = ""
        currency = "EUR"
        statement_year = str(datetime.date.today().year)

        segments: List[Dict[str, Any]] = []

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
                if total_pages > settings.MAX_PAGES_PER_FILE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"PDF exceeds maximum allowed limit of {settings.MAX_PAGES_PER_FILE} pages.",
                    )
                if total_pages == 0:
                    return {
                        "account_holder": account_holder,
                        "account_id": "",
                        "currency": currency,
                        "transactions": [],
                        "warnings": ["Leeres PDF-Dokument."],
                        "errors": ["PDF enthält keine Seiten."],
                    }

                p1_text = pdf.pages[0].extract_text() or ""
                holder_cand = self._extract_account_holder(p1_text)
                if holder_cand:
                    account_holder = holder_cand

                active_seg: Optional[Dict[str, Any]] = None

                for page_idx, page in enumerate(pdf.pages):
                    page_num = page_idx + 1
                    page_text = page.extract_text() or ""
                    if len(page_text.strip()) < 20:
                        unparsed_errors.append(
                            f"Seite {page_num} enthält keine lesbare Textebene (möglicher Scan in Misch-PDF)."
                        )
                        continue

                    page_iban, iban_ok = _extract_iban_strict(page_text)
                    if not iban_ok:
                        unparsed_errors.append(
                            f"Seite {page_num}: Ungültige IBAN-Prüfsumme oder ungültiges IBAN-Format ('{page_iban}')."
                        )
                    elif page_iban:
                        if not account_iban:
                            account_iban = page_iban
                        elif page_iban != account_iban:
                            unparsed_errors.append(
                                f"Seite {page_num}: Abweichende IBAN '{page_iban}' im Dokument erkannt (erwartet '{account_iban}')."
                            )

                    page_curr = self._extract_currency(page_text)
                    if page_curr and page_curr != currency:
                        if page_idx == 0:
                            currency = page_curr
                        else:
                            unparsed_errors.append(
                                f"Seite {page_num}: Gemischte Kontowährung '{page_curr}' erkannt."
                            )

                    stmt_match = _STMT_NUM_RE.search(page_text)
                    seg_num = int(stmt_match.group(1)) if stmt_match else None
                    seg_year = stmt_match.group(2) if stmt_match else None
                    if seg_year and page_idx == 0:
                        statement_year = seg_year

                    open_cents, close_cents = self._extract_page_balances(page_text)

                    starts_new_seg = False
                    if seg_num is not None and seg_year is not None:
                        if (
                            active_seg is None
                            or active_seg["stmt_num"] != seg_num
                            or active_seg["stmt_year"] != seg_year
                        ):
                            starts_new_seg = True
                    elif active_seg is None:
                        starts_new_seg = True

                    if starts_new_seg:
                        active_seg = {
                            "stmt_num": seg_num,
                            "stmt_year": seg_year,
                            "iban": page_iban or account_iban,
                            "currency": currency,
                            "opening_cents": open_cents,
                            "closing_cents": close_cents,
                            "pages": [page_num],
                            "txs": [],
                        }
                        segments.append(active_seg)
                    else:
                        active_seg["pages"].append(page_num)
                        if close_cents is not None:
                            active_seg["closing_cents"] = close_cents

                    page_txs, page_errors = self._extract_page_transactions(
                        page=page,
                        page_text=page_text,
                        page_num=page_num,
                        seg_num=seg_num,
                        account_holder=account_holder,
                        account_iban=account_iban,
                        currency=currency,
                        filename=filename,
                        use_valuta_as_booking_date=use_valuta_as_booking_date,
                    )
                    unparsed_errors.extend(page_errors)
                    active_seg["txs"].extend(page_txs)
                    transactions.extend(page_txs)

                    if len(transactions) > settings.MAX_ROWS_PER_FILE:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File exceeds maximum allowed limit of {settings.MAX_ROWS_PER_FILE} rows.",
                        )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"ErsteBankAustriaParser error ({file_tag}): {e}", exc_info=True)
            unparsed_errors.append(f"Interner Parser-Fehler: {e}")

        # Validate multi-segment consistency & chain balances (Decision 61 §2.3)
        opening_balance_cents, closing_balance_cents, chain_errors = self._reconcile_segments(segments)
        unparsed_errors.extend(chain_errors)

        if use_valuta_as_booking_date and transactions:
            warnings.append(
                "Valutadatum als Buchungsdatum verwendet (Quellspalte 'Valuta/Value' des Erste Bank PDFs)."
            )
        elif transactions:
            warnings.append(
                "Auszug enthält nur Valutadaten ('Valuta/Value'), kein separates Buchungsdatum. Aktivieren Sie explizit 'Valutadatum als Buchungsdatum', falls zulässig."
            )

        if unparsed_errors:
            # Mark discrepancy or propagate explicit parsing errors
            warnings.extend(unparsed_errors)

        if unparsed_errors and not transactions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=" ".join(unparsed_errors),
            )

        if len(transactions) == 0:
            return {
                "account_holder": account_holder,
                "account_id": account_iban,
                "currency": currency,
                "statement_year": statement_year,
                "transactions": [],
                "warnings": warnings,
                "errors": unparsed_errors or ["Keine Buchungen im Erste Bank Auszug gefunden."],
            }

        # Mark ERROR validation_status if segment validation / unparsed lines failed inside this file
        if unparsed_errors:
            transactions[0]["_validation_status"] = "ERROR"
            transactions[0]["_warnings"] = list(unparsed_errors)

        return {
            "account_holder": account_holder,
            "account_id": account_iban,
            "currency": currency,
            "statement_year": statement_year,
            "opening_balance_cents": opening_balance_cents,
            "closing_balance_cents": closing_balance_cents,
            "transactions": transactions,
            "warnings": warnings,
            "errors": unparsed_errors,
            "segments_count": len(segments),
            "statement_numbers": [
                (int(seg["stmt_year"]), int(seg["stmt_num"]))
                for seg in segments
                if seg.get("stmt_year") is not None and seg.get("stmt_num") is not None
            ],
        }

    def _extract_account_holder(self, p1_text: str) -> str:
        lines = [l.strip() for l in p1_text.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            if "zuletzt gültiger kontowortlaut" in line.lower() and i > 0:
                cand = lines[i - 1].strip()
                if cand and not any(sw in cand.lower() for sw in ("erste bank", "sparkasse", "am belvedere")):
                    return cand
        return ""

    def _extract_currency(self, page_text: str) -> str:
        m = re.search(r"Betr[äa]ge/Amounts\s+in\s+([A-Z]{3})", page_text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        return "EUR"

    def _extract_page_balances(self, page_text: str) -> Tuple[Optional[int], Optional[int]]:
        open_cents: Optional[int] = None
        close_cents: Optional[int] = None

        m_open = re.search(
            r"Alter\s+Kontostand(?:\s+Old\s+Balance)?\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)",
            page_text,
            re.IGNORECASE,
        )
        if m_open:
            open_cents = parse_strict_eur_cents(m_open.group(1))

        # Prefer table footer 'Neuer Kontostand/New Balance' or box 'Neuer Kontostand ...'
        m_close_all = re.findall(
            r"Neuer\s+Kontostand(?:/New\s+Balance)?\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)",
            page_text,
            re.IGNORECASE,
        )
        if m_close_all:
            close_cents = parse_strict_eur_cents(m_close_all[-1])

        return open_cents, close_cents

    def _reconcile_segments(
        self, segments: List[Dict[str, Any]]
    ) -> Tuple[Optional[int], Optional[int], List[str]]:
        if not segments:
            return None, None, []
        errors: List[str] = []

        seen_nums: set = set()
        prev_seg: Optional[Dict[str, Any]] = None

        for seg in segments:
            s_num = seg.get("stmt_num")
            s_year = seg.get("stmt_year")
            if s_num is not None and s_year is not None:
                key = (s_year, s_num)
                if key in seen_nums:
                    errors.append(
                        f"Doppelter Auszug Nr. {s_num:03d}/{s_year} im zusammengeführten PDF erkannt."
                    )
                seen_nums.add(key)

                if prev_seg and prev_seg.get("stmt_num") is not None and prev_seg.get("stmt_year") == s_year:
                    expected_next = prev_seg["stmt_num"] + 1
                    if s_num != expected_next:
                        errors.append(
                            f"Fehlender oder vertauschter Auszug: nach Nr. {prev_seg['stmt_num']:03d}/{s_year} folgt Nr. {s_num:03d}/{s_year}."
                        )

            open_c = seg.get("opening_cents")
            close_c = seg.get("closing_cents")
            seg_tx_sum = sum(t["_amount_cents"] for t in seg.get("txs", []))

            if open_c is not None and close_c is not None:
                if open_c + seg_tx_sum != close_c:
                    errors.append(
                        f"Saldendifferenz in Auszug Nr. {s_num or '?'}/{s_year or '?'}: "
                        f"Anfangssaldo + Umsätze ({open_c + seg_tx_sum}) != Endsaldo ({close_c})."
                    )

            if prev_seg is not None:
                prev_close = prev_seg.get("closing_cents")
                if prev_close is not None and open_c is not None and prev_close != open_c:
                    errors.append(
                        f"Saldensprung zwischen Auszug Nr. {prev_seg.get('stmt_num') or '?'} "
                        f"(Endsaldo {prev_close}) und Nr. {s_num or '?'} (Anfangssaldo {open_c})."
                    )

            prev_seg = seg

        first_open = segments[0].get("opening_cents")
        last_close = segments[-1].get("closing_cents")

        # If any segment lacked closing balance, don't falsely claim overall BALANCED
        if any(seg.get("opening_cents") is None or seg.get("closing_cents") is None for seg in segments):
            return None, None, errors

        return first_open, last_close, errors

    def _extract_page_transactions(
        self,
        page: Any,
        page_text: str,
        page_num: int,
        seg_num: Optional[int],
        account_holder: str,
        account_iban: str,
        currency: str,
        filename: str,
        use_valuta_as_booking_date: bool,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        words = page.extract_words() or []
        txs: List[Dict[str, Any]] = []
        errors: List[str] = []

        # Attempt coordinate-based column parsing first
        col_bounds = self._detect_table_columns(words)
        if col_bounds is not None:
            header_bottom, valuta_x_start, amount_x_start = col_bounds
            visual_lines = _group_words_by_line(words, y_tolerance=3.5)
            rows: List[Tuple[str, str, str, float]] = []

            for line_words in visual_lines:
                line_top = float(line_words[0]["top"])
                if line_top <= header_bottom + 1.0:
                    continue
                full_line_text = " ".join(w["text"] for w in line_words).strip()
                low = full_line_text.lower()
                if low.startswith("neuer kontostand") or "neuer kontostand/new balance" in low:
                    break
                if re.match(r"^AT\d{2}[\d\s]{14,}\s+\d{2}\.\d{2}\.\d{4}", full_line_text) or low.startswith("iban datum/date"):
                    break

                text_tokens: List[str] = []
                valuta_tokens: List[str] = []
                amt_tokens: List[str] = []

                for w in line_words:
                    x0 = float(w["x0"])
                    if x0 >= amount_x_start:
                        amt_tokens.append(w["text"])
                    elif x0 >= valuta_x_start:
                        valuta_tokens.append(w["text"])
                    else:
                        text_tokens.append(w["text"])

                rows.append(
                    (
                        " ".join(text_tokens).strip(),
                        " ".join(valuta_tokens).strip(),
                        " ".join(amt_tokens).strip(),
                        line_top,
                    )
                )

            return self._parse_column_rows(
                rows=rows,
                page_num=page_num,
                seg_num=seg_num,
                account_holder=account_holder,
                account_iban=account_iban,
                currency=currency,
                filename=filename,
                use_valuta_as_booking_date=use_valuta_as_booking_date,
            )

        # Fallback: line-by-line text state machine when vector word boxes aren't columnar
        lines = [l.strip() for l in page_text.splitlines() if l.strip()]
        in_table = False
        fallback_rows: List[Tuple[str, str, str, float]] = []
        row_re = re.compile(
            r"^(?P<txt>.+?)\s+(?P<val>\d{2}\.\d{2}\.\d{4}(?:\s*\*)?)\s+(?P<amt>(?:[+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)|.+)$"
        )

        for idx, line in enumerate(lines):
            low = line.lower()
            if "buchungstext" in low and "valuta" in low:
                in_table = True
                continue
            if not in_table:
                continue
            if low.startswith("neuer kontostand"):
                break
            m = row_re.match(line)
            if m:
                amt_cand = m.group("amt").strip()
                looks_like_damaged_amt = (
                    (bool(re.search(r"\d", amt_cand)) or bool(re.fullmatch(r"[A-Za-z*?]{1,4}[,\.][A-Za-z0-9*?]{1,3}[+-]?", amt_cand)))
                    and ("," in amt_cand or "." in amt_cand or amt_cand.endswith(("+", "-")) or amt_cand.startswith(("+", "-")))
                    and len(amt_cand.split()) <= 2
                )
                if parse_strict_eur_cents(amt_cand) is not None or looks_like_damaged_amt:
                    fallback_rows.append((m.group("txt").strip(), m.group("val").strip(), amt_cand, float(idx)))
                else:
                    fallback_rows.append((line, "", "", float(idx)))
            else:
                m_abschluss = re.match(r"^(\*{3}\s*Abschlussbuchung.+?)\s+(\d{2}\.\d{2}\.\d{4})$", line, re.IGNORECASE)
                if m_abschluss:
                    fallback_rows.append((m_abschluss.group(1).strip(), m_abschluss.group(2).strip(), "", float(idx)))
                else:
                    fallback_rows.append((line, "", "", float(idx)))

        return self._parse_column_rows(
            rows=fallback_rows,
            page_num=page_num,
            seg_num=seg_num,
            account_holder=account_holder,
            account_iban=account_iban,
            currency=currency,
            filename=filename,
            use_valuta_as_booking_date=use_valuta_as_booking_date,
        )

    def _detect_table_columns(self, words: List[Dict[str, Any]]) -> Optional[Tuple[float, float, float]]:
        for line_words in _group_words_by_line(words, y_tolerance=4.0):
            line_text = " ".join(w["text"] for w in line_words).lower()
            if "buchungstext" in line_text and "valuta" in line_text and ("beträge" in line_text or "amounts" in line_text):
                valuta_w = next((w for w in line_words if "valuta" in w["text"].lower()), None)
                amt_w = next(
                    (w for w in line_words if "beträge" in w["text"].lower() or "amounts" in w["text"].lower()),
                    None,
                )
                if valuta_w and amt_w:
                    valuta_x_start = float(valuta_w["x0"]) - 18.0
                    amount_x_start = float(amt_w["x0"]) - 25.0
                    header_bottom = max(float(w["bottom"]) for w in line_words)
                    if valuta_x_start < amount_x_start:
                        return header_bottom, valuta_x_start, amount_x_start
        return None

    def _parse_column_rows(
        self,
        rows: List[Tuple[str, str, str, float]],
        page_num: int,
        seg_num: Optional[int],
        account_holder: str,
        account_iban: str,
        currency: str,
        filename: str,
        use_valuta_as_booking_date: bool,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        txs: List[Dict[str, Any]] = []
        errors: List[str] = []
        current: Optional[Dict[str, Any]] = None
        after_abschluss_header = False

        def flush_current():
            nonlocal current
            if not current:
                return
            partner, remaining_lines = _classify_erste_partner(current["extra_lines"], current["line1"])
            desc_parts = [current["line1"]] + remaining_lines
            desc = re.sub(r"\s+", " ", " ".join(p for p in desc_parts if p)).strip()
            valuta_date_str = current["valuta_date"].strftime("%d.%m.%Y")
            beleg_date_str = valuta_date_str if use_valuta_as_booking_date else ""
            cents = current["amount_cents"]
            sign = "-" if cents < 0 else ""
            abs_c = abs(cents)
            amt_str = f"{sign}{abs_c // 100},{abs_c % 100:02d}"
            seg_prefix = f"ERS-{seg_num:03d}" if seg_num is not None else f"ERS-P{page_num}"

            txs.append(
                {
                    "Belegdatum": beleg_date_str,
                    "Valutadatum": valuta_date_str,
                    "Buchungstext": desc[:250],
                    "Partner": partner,
                    "Betrag": amt_str,
                    "_amount_cents": cents,
                    "Währung": currency,
                    "Belegnummer": f"{seg_prefix}-{len(txs) + 1}",
                    "Gegenkonto/Konto": "",
                    "_source_file": filename,
                    "_account_holder": account_holder,
                    "_account_id": account_iban,
                    "_allow_missing_booking_date": True,
                }
            )
            current = None

        for col_text, col_valuta, col_amt, _ in rows:
            if not col_text and not col_valuta and not col_amt:
                continue

            clean_valuta = col_valuta.replace("*", "").strip()
            has_valuta = bool(clean_valuta)
            has_amt = bool(col_amt)

            if has_valuta or has_amt:
                flush_current()
                after_abschluss_header = False

                # Check known non-booking header line: *** Abschlussbuchung per DD.MM.YYYY **** | DD.MM.YYYY | empty
                if "abschlussbuchung" in col_text.lower() and not has_amt:
                    after_abschluss_header = True
                    continue

                if not has_valuta or not has_amt:
                    errors.append(
                        f"Seite {page_num}: Unvollständige Buchungszeile '{col_text}' (Valuta='{col_valuta}', Betrag='{col_amt}')."
                    )
                    continue

                parsed_val = parse_strict_dmy(clean_valuta)
                if not parsed_val:
                    errors.append(f"Seite {page_num}: Ungültiges Valutadatum '{col_valuta}' bei '{col_text}'.")
                    continue

                cents = parse_strict_eur_cents(col_amt)
                if cents is None:
                    errors.append(f"Seite {page_num}: Nicht eindeutiger Betrag '{col_amt}' bei '{col_text}'.")
                    continue

                if not col_text:
                    errors.append(f"Seite {page_num}: Fehlendes Buchungstext-Feld am {col_valuta}.")
                    continue

                current = {
                    "line1": col_text,
                    "extra_lines": [],
                    "valuta_date": parsed_val,
                    "amount_cents": cents,
                }
            else:
                if after_abschluss_header and col_text.lower().startswith("reklamationen"):
                    continue
                m_hidden_row = re.match(
                    r"^(?P<txt>.+?)\s+(?P<val>\d{2}\.\d{2}\.\d{4}(?:\s*\*)?)\s+(?P<amt>\S+(?:\s+[+-])?)$",
                    col_text,
                )
                if m_hidden_row and not col_text.lower().startswith("***"):
                    hid_amt = m_hidden_row.group("amt").strip()
                    if (
                        parse_strict_eur_cents(hid_amt) is not None
                        or (
                            (bool(re.search(r"\d", hid_amt)) or "," in hid_amt)
                            and ("," in hid_amt or "." in hid_amt or hid_amt.endswith(("+", "-")) or hid_amt.startswith(("+", "-")))
                        )
                    ):
                        flush_current()
                        errors.append(
                            f"Seite {page_num}: Nicht eindeutiger Betrag '{hid_amt}' bei '{m_hidden_row.group('txt').strip()}'."
                        )
                        continue
                if current is not None:
                    current["extra_lines"].append(col_text)
                else:
                    errors.append(f"Seite {page_num}: Nicht zugeordnete Zeile im Umsatzbereich: '{col_text}'.")

        flush_current()
        return txs, errors


class ErsteVisaCardParser:
    """
    Dedicated parser for Erste Bank / Sparkasse 's Visa Card Business Gold' MONATSRECHNUNG PDFs.
    Uses 'Buchung' (2nd date) as booking_date, separates merchant/partner from location/FX details,
    terminates cleanly before summary totals, and reconciles against Offener Betrag balances.
    """

    def is_applicable(self, pdf_bytes: bytes) -> bool:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if not pdf.pages:
                    return False
                first_text = (pdf.pages[0].extract_text() or "").upper()
                has_stmt = "MONATSRECHNUNG" in first_text or "MONTHLY STATEMENT" in first_text
                has_cols = "KAUF" in first_text and "BUCHUNG" in first_text and (
                    "VERTRAGSUNTERNEHMEN" in first_text or "CONTRACTING COMPANY" in first_text
                )
                return has_stmt and has_cols
        except Exception as e:
            logger.debug(f"ErsteVisaCardParser.is_applicable error: {e}")
            return False

    def parse_with_metadata(self, pdf_bytes: bytes, filename: str = "") -> Dict[str, Any]:
        file_tag = hashlib.sha256((filename or "visa").encode("utf-8")).hexdigest()[:8]
        transactions: List[Dict[str, Any]] = []
        warnings: List[str] = []
        unparsed_errors: List[str] = []

        account_holder = "s Visa Card Business"
        card_number = ""
        currency = "EUR"
        statement_year = str(datetime.date.today().year)
        opening_balance_cents: Optional[int] = None
        closing_balance_cents: Optional[int] = None

        row_re = re.compile(
            r"^(?P<kauf>\d{2}\.\d{2}\.\d{4})\s+"
            r"(?P<buchung>\d{2}\.\d{2}\.\d{4})\s+"
            r"(?P<body>.+?)\s+"
            r"(?P<eur_amt>(?:[+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?))$"
        )

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
                if total_pages > settings.MAX_PAGES_PER_FILE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"PDF exceeds maximum allowed limit of {settings.MAX_PAGES_PER_FILE} pages.",
                    )
                if total_pages == 0:
                    return {
                        "account_holder": account_holder,
                        "account_id": "",
                        "currency": currency,
                        "transactions": [],
                        "errors": ["PDF enthält keine Seiten."],
                    }

                p1_text = pdf.pages[0].extract_text() or ""
                m_card = re.search(r"Kartennummer\s*/\s*Card\s*Number\s*\n?\s*([0-9Xx\*]{8,20})", p1_text, re.IGNORECASE)
                if not m_card:
                    m_card = re.search(r"Umsatz\s+der\s+Karte\s+([0-9Xx\*]{4,20})", p1_text, re.IGNORECASE)
                if m_card:
                    card_number = m_card.group(1).strip()

                m_yr = re.search(r"\b\d{2}\.\d{2}\.(20\d{2})\b", p1_text)
                if m_yr:
                    statement_year = m_yr.group(1)

                lines = p1_text.splitlines()
                for i, l in enumerate(lines):
                    if "zuletzt gültiger kontowortlaut" in l.lower() and i > 0:
                        cand = lines[i - 1].strip()
                        if cand:
                            account_holder = cand
                            break

                in_tx_table = False

                for page_idx, page in enumerate(pdf.pages):
                    page_num = page_idx + 1
                    page_text = page.extract_text() or ""
                    if len(page_text.strip()) < 20:
                        unparsed_errors.append(
                            f"Seite {page_num} enthält keine lesbare Textebene (möglicher Scan in Misch-PDF)."
                        )
                        continue

                    col_map = self._detect_visa_columns(page.extract_words() or [])

                    # Extract opening & closing balances explicitly
                    m_prev = re.search(
                        r"Offener\s+Betrag\s+Vormonat\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)",
                        page_text,
                        re.IGNORECASE,
                    )
                    if m_prev and opening_balance_cents is None:
                        opening_balance_cents = parse_strict_eur_cents(m_prev.group(1))

                    m_out = re.search(
                        r"Offener\s+Betrag\s*/\s*Outstanding\s+balance\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)",
                        page_text,
                        re.IGNORECASE,
                    )
                    if m_out:
                        closing_balance_cents = parse_strict_eur_cents(m_out.group(1))

                    if col_map is not None:
                        p_txs, p_errs, in_tx_table = self._parse_visa_page_by_columns(
                            page=page,
                            col_map=col_map,
                            page_num=page_num,
                            account_holder=account_holder,
                            card_number=card_number,
                            currency=currency,
                            filename=filename,
                            start_in_table=in_tx_table,
                        )
                        transactions.extend(p_txs)
                        unparsed_errors.extend(p_errs)
                    else:
                        for raw_line in page_text.splitlines():
                            line = raw_line.strip()
                            if not line:
                                continue
                            low = line.lower()

                            if ("betrag eur" in low or low.startswith("purchase booking")) and not in_tx_table:
                                in_tx_table = True
                                continue
                            if low.startswith("offener betrag vormonat") or low.startswith("umsatz der karte"):
                                in_tx_table = True
                                continue
                            if (
                                low.startswith("offener betrag / outstanding")
                                or low.startswith("einzugsbetrag")
                                or low.startswith("der einzugsbetrag wird")
                            ):
                                in_tx_table = False
                                continue
                            if not in_tx_table:
                                continue

                            # Header labels broken across lines before first tx
                            if any(
                                h in low
                                for h in (
                                    "kauf buchung",
                                    "purchase booking",
                                    "contracting company",
                                    "amount foreign currency",
                                )
                            ):
                                continue

                            m = row_re.match(line)
                            if not m:
                                unparsed_errors.append(
                                    f"Seite {page_num}: Unbekannte/unvollständige Kreditkarten-Zeile: '{line}'."
                                )
                                continue

                            kauf_date = parse_strict_dmy(m.group("kauf"))
                            buchung_date = parse_strict_dmy(m.group("buchung"))
                            if not kauf_date or not buchung_date:
                                unparsed_errors.append(
                                    f"Seite {page_num}: Ungültiges Datum in Zeile '{line}'."
                                )
                                continue

                            eur_cents = parse_strict_eur_cents(m.group("eur_amt"))
                            if eur_cents is None:
                                unparsed_errors.append(
                                    f"Seite {page_num}: Ungültiger EUR-Betrag '{m.group('eur_amt')}' in '{line}'."
                                )
                                continue

                            tx = self._build_visa_tx_from_body(
                                body=m.group("body").strip(),
                                kauf_str=m.group("kauf"),
                                buchung_date=buchung_date,
                                eur_cents=eur_cents,
                                tx_idx=len(transactions) + 1,
                                account_holder=account_holder,
                                card_number=card_number,
                                currency=currency,
                                filename=filename,
                            )
                            transactions.append(tx)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"ErsteVisaCardParser error ({file_tag}): {e}", exc_info=True)
            unparsed_errors.append(f"Interner Visa-Parser-Fehler: {e}")

        if unparsed_errors:
            warnings.extend(unparsed_errors)

        if unparsed_errors and not transactions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=" ".join(unparsed_errors),
            )

        if not transactions:
            return {
                "account_holder": account_holder,
                "account_id": card_number,
                "currency": currency,
                "statement_year": statement_year,
                "transactions": [],
                "warnings": warnings,
                "errors": unparsed_errors or ["Keine Kartentransaktionen gefunden."],
            }

        if unparsed_errors:
            transactions[0]["_validation_status"] = "ERROR"
            transactions[0]["_warnings"] = list(unparsed_errors)

        return {
            "account_holder": account_holder,
            "account_id": card_number,
            "currency": currency,
            "statement_year": statement_year,
            "opening_balance_cents": opening_balance_cents,
            "closing_balance_cents": closing_balance_cents,
            "transactions": transactions,
            "warnings": warnings,
            "errors": unparsed_errors,
        }

    def _detect_visa_columns(self, words: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
        grouped = _group_words_by_line(words, y_tolerance=4.0)
        for idx, line_words in enumerate(grouped):
            txt = " ".join(w["text"] for w in line_words).lower()
            if "vertragsunternehmen" in txt or ("kauf" in txt and "buchung" in txt and "ort" in txt):
                header_words = list(line_words)
                header_bottom = max(float(w["bottom"]) for w in line_words)
                if idx + 1 < len(grouped):
                    next_words = grouped[idx + 1]
                    next_txt = " ".join(w["text"] for w in next_words).lower()
                    if "contracting" in next_txt or "purchase" in next_txt or "amount" in next_txt:
                        header_words.extend(next_words)
                        header_bottom = max(header_bottom, max(float(w["bottom"]) for w in next_words))

                kauf_w = next((w for w in header_words if w["text"].lower() == "kauf"), None)
                buch_w = next((w for w in header_words if w["text"].lower() == "buchung"), None)
                merch_w = next((w for w in header_words if "vertragsunternehmen" in w["text"].lower()), None)
                ort_w = next((w for w in header_words if w["text"].lower() == "ort"), None)
                fw_amt_w = next(
                    (w for w in header_words if "fremdw" in w["text"].lower()),
                    None,
                )
                fw_kurs_w = next((w for w in header_words if "fw-kurs" in w["text"].lower()), None)
                fee_w = next((w for w in header_words if "entgelt" in w["text"].lower()), None)
                eur_candidates = [w for w in header_words if w["text"].lower() in ("betrag", "eur", "amount")]
                right_eur_w = max(eur_candidates, key=lambda w: float(w["x0"])) if eur_candidates else None
                right_eur_x = float(right_eur_w["x0"]) if right_eur_w else 0.0

                # Prefer 'Betrag' word belonging to 'Betrag EUR' (rightmost 'Betrag') if present
                betrag_words = sorted([w for w in header_words if w["text"].lower() == "betrag"], key=lambda w: float(w["x0"]))
                eur_col_x = float(betrag_words[-1]["x0"]) if len(betrag_words) >= 2 else (right_eur_x - 20.0)
                if fee_w and eur_col_x <= float(fee_w["x1"]):
                    eur_col_x = float(fee_w["x1"]) + 10.0

                fx_betrag_x = float(betrag_words[0]["x0"]) if len(betrag_words) >= 2 else (
                    float(fw_amt_w["x0"]) - 30.0 if fw_amt_w else eur_col_x - 150.0
                )

                if kauf_w and buch_w and merch_w and right_eur_x > float(merch_w["x0"]):
                    ort_x = (float(ort_w["x0"]) - 8.0) if ort_w else (float(merch_w["x0"]) + 110.0)
                    return {
                        "header_bottom": header_bottom,
                        "buchung_x": float(buch_w["x0"]) - 8.0,
                        "merch_x": float(merch_w["x0"]) - 8.0,
                        "ort_x": ort_x,
                        "fx_amt_x": max(ort_x + 35.0, fx_betrag_x - 18.0),
                        "fx_rate_x": (float(fw_kurs_w["x0"]) - 12.0) if fw_kurs_w else (eur_col_x - 90.0),
                        "fee_x": (float(fee_w["x0"]) - 12.0) if fee_w else (eur_col_x - 45.0),
                        "eur_x": eur_col_x - 15.0,
                    }
        return None

    def _parse_visa_page_by_columns(
        self,
        page: Any,
        col_map: Dict[str, float],
        page_num: int,
        account_holder: str,
        card_number: str,
        currency: str,
        filename: str,
        start_in_table: bool,
    ) -> Tuple[List[Dict[str, Any]], List[str], bool]:
        txs: List[Dict[str, Any]] = []
        errors: List[str] = []
        in_table = start_in_table

        for line_words in _group_words_by_line(page.extract_words() or [], y_tolerance=3.5):
            top = float(line_words[0]["top"])
            if top <= col_map["header_bottom"] + 1.0:
                continue
            full_line = " ".join(w["text"] for w in line_words).strip()
            low = full_line.lower()

            if low.startswith("offener betrag vormonat") or low.startswith("umsatz der karte"):
                in_table = True
                continue
            if (
                low.startswith("offener betrag / outstanding")
                or low.startswith("einzugsbetrag")
                or low.startswith("der einzugsbetrag wird")
            ):
                in_table = False
                continue

            # Skip column headers if encountered
            if "kauf" in low and "buchung" in low:
                in_table = True
                continue

            if not in_table and not re.match(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}\.\d{2}\.\d{4}\b", full_line):
                continue

            in_table = True
            kauf_t, buch_t, merch_t, ort_t, fx_amt_t, fx_rate_t, fee_t, eur_t = (
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
            )
            for w in line_words:
                x0 = float(w["x0"])
                if x0 >= col_map["eur_x"]:
                    eur_t.append(w["text"])
                elif x0 >= col_map["fee_x"]:
                    fee_t.append(w["text"])
                elif x0 >= col_map["fx_rate_x"]:
                    fx_rate_t.append(w["text"])
                elif x0 >= col_map["fx_amt_x"]:
                    fx_amt_t.append(w["text"])
                elif x0 >= col_map["ort_x"]:
                    ort_t.append(w["text"])
                elif x0 >= col_map["merch_x"]:
                    merch_t.append(w["text"])
                elif x0 >= col_map["buchung_x"]:
                    buch_t.append(w["text"])
                else:
                    kauf_t.append(w["text"])

            kauf_str = " ".join(kauf_t).strip()
            buch_str = " ".join(buch_t).strip()
            merch_str = " ".join(merch_t).strip()
            ort_str = " ".join(ort_t).strip()
            fx_amt_str = " ".join(fx_amt_t).strip()
            fx_rate_str = " ".join(fx_rate_t).strip()
            fx_cur_prefix = re.match(r"^([A-Z]{3})\s+(.+)$", fx_rate_str)
            if fx_amt_str and fx_cur_prefix and re.match(r"^\d[\d\.,]*$", fx_amt_str):
                fx_amt_str = f"{fx_amt_str} {fx_cur_prefix.group(1)}"
                fx_rate_str = fx_cur_prefix.group(2).strip()
            fee_str = " ".join(fee_t).strip()
            eur_str = " ".join(eur_t).strip()

            kauf_date = parse_strict_dmy(kauf_str)
            buch_date = parse_strict_dmy(buch_str)
            eur_cents = parse_strict_eur_cents(eur_str)

            if not kauf_date or not buch_date or eur_cents is None:
                errors.append(
                    f"Seite {page_num}: Unvollständige Kreditkarten-Zeile: '{full_line}'."
                )
                continue

            tx = self._make_visa_tx(
                kauf_str=kauf_str,
                buchung_date=buch_date,
                merch_str=merch_str,
                ort_str=ort_str,
                fx_amt_str=fx_amt_str,
                fx_rate_str=fx_rate_str,
                fee_str=fee_str,
                eur_cents=eur_cents,
                tx_idx=len(txs) + 1,
                account_holder=account_holder,
                card_number=card_number,
                currency=currency,
                filename=filename,
            )
            txs.append(tx)

        return txs, errors, in_table

    def _build_visa_tx_from_body(
        self,
        body: str,
        kauf_str: str,
        buchung_date: datetime.date,
        eur_cents: int,
        tx_idx: int,
        account_holder: str,
        card_number: str,
        currency: str,
        filename: str,
    ) -> Dict[str, Any]:
        fx_amt_str = ""
        fx_rate_str = ""
        fee_str = ""
        core_text = body

        fx_tail = re.search(
            r"\s+(\d[\d\.,]*\s+[A-Z]{3})\s+(\d+[\.,]\d+)(?:\s+(\d+[\.,]\d+))?$",
            body,
        )
        if fx_tail:
            fx_amt_str = fx_tail.group(1).strip()
            fx_rate_str = fx_tail.group(2).strip()
            fee_str = (fx_tail.group(3) or "").strip()
            core_text = body[: fx_tail.start()].strip()

        # Split location token at end if distinct (e.g. 'AWS EMEA aws.amazon.co', 'GITHUB, INC. GITHUB.COM')
        merch_str = core_text
        ort_str = ""
        if core_text.lower() != "ihre zahlung vormonat":
            parts = core_text.rsplit(" ", 1)
            if len(parts) == 2 and parts[0]:
                merch_str, ort_str = parts[0].strip(), parts[1].strip()

        return self._make_visa_tx(
            kauf_str=kauf_str,
            buchung_date=buchung_date,
            merch_str=merch_str,
            ort_str=ort_str,
            fx_amt_str=fx_amt_str,
            fx_rate_str=fx_rate_str,
            fee_str=fee_str,
            eur_cents=eur_cents,
            tx_idx=tx_idx,
            account_holder=account_holder,
            card_number=card_number,
            currency=currency,
            filename=filename,
        )

    def _make_visa_tx(
        self,
        kauf_str: str,
        buchung_date: datetime.date,
        merch_str: str,
        ort_str: str,
        fx_amt_str: str,
        fx_rate_str: str,
        fee_str: str,
        eur_cents: int,
        tx_idx: int,
        account_holder: str,
        card_number: str,
        currency: str,
        filename: str,
    ) -> Dict[str, Any]:
        is_payment_notice = "ihre zahlung" in merch_str.lower()
        partner = None if is_payment_notice else (merch_str.strip() or None)

        purpose_parts: List[str] = []
        if is_payment_notice:
            purpose_parts.append(merch_str.strip())
        elif ort_str:
            purpose_parts.append(ort_str.strip())
        else:
            # If no Ort is present, keep partner non-duplicated and add purchase date context
            purpose_parts.append(f"Kartenumsatz (Kauf {kauf_str})")

        foreign_currency: Optional[str] = None
        foreign_amount_cents: Optional[int] = None
        if fx_amt_str:
            fx_m = re.match(r"^(\d[\d\.,]*)\s+([A-Z]{3})$", fx_amt_str.strip())
            if fx_m:
                fx_raw_num, fx_curr = fx_m.groups()
                # Normalize both 49,00 and 49.00 cleanly
                norm_fx = fx_raw_num
                if "," not in norm_fx and "." in norm_fx and len(norm_fx.rsplit(".", 1)[1]) == 2:
                    norm_fx = norm_fx.replace(".", ",")
                parsed_fx_cents = parse_strict_eur_cents(norm_fx)
                if parsed_fx_cents is not None:
                    foreign_currency = fx_curr
                    foreign_amount_cents = -abs(parsed_fx_cents) if eur_cents < 0 else abs(parsed_fx_cents)

            fx_note_bits = [fx_amt_str]
            if fx_rate_str:
                fx_note_bits.append(f"Kurs {fx_rate_str}")
            if fee_str:
                fx_note_bits.append(f"Entgelt {fee_str} EUR")
            purpose_parts.append(f"({', '.join(fx_note_bits)})")

        if not is_payment_notice and ort_str:
            purpose_parts.append(f"Kauf {kauf_str}")

        description = re.sub(r"\s+", " ", " ".join(purpose_parts)).strip()

        sign = "-" if eur_cents < 0 else ""
        abs_c = abs(eur_cents)
        amt_str = f"{sign}{abs_c // 100},{abs_c % 100:02d}"
        buchung_str = buchung_date.strftime("%d.%m.%Y")

        return {
            "Belegdatum": buchung_str,
            "Valutadatum": "",  # Kauf is purchase date, NOT Valuta/booking date
            "Buchungstext": description[:250],
            "Partner": partner,
            "ForeignCurrency": foreign_currency,
            "ForeignAmountCents": foreign_amount_cents,
            "Betrag": amt_str,
            "_amount_cents": eur_cents,
            "Währung": currency,
            "Belegnummer": f"VISA-{buchung_date.strftime('%d%m')}-{tx_idx}",
            "Gegenkonto/Konto": "",
            "_source_file": filename,
            "_account_holder": account_holder,
            "_account_id": card_number,
        }
