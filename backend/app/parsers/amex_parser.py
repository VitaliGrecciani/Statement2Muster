import re
from typing import List, Dict, Any, Optional
import io
import os
import asyncio
import concurrent.futures
import tempfile
import logging
import pdfplumber
from datetime import datetime

logger = logging.getLogger("statement2muster.amex")

class AmexStatementParser:
    """
    In-Memory PDF parser for American Express Statements (Austria & Germany).
    Extracts transactions, account holder, card number, and statement period.
    """

    def is_applicable(self, pdf_bytes: bytes) -> bool:
        """Checks if the PDF is an American Express statement."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if len(pdf.pages) == 0:
                    return False
                first_page_text = pdf.pages[0].extract_text() or ""
                return "AMERICAN EXPRESS" in first_page_text.upper() or "AMEX" in first_page_text.upper()
        except Exception as e:
            logger.debug(f"is_applicable check failed: {e}")
            return False

    def parse_with_metadata(self, pdf_bytes: bytes, filename: str = "") -> Dict[str, Any]:
        """
        Parses statement and returns metadata (Kontoinhaber, Kartennummer, Währung) + transactions.
        """
        transactions = []
        statement_year = str(datetime.now().year)
        account_holder = "Unbekannt"
        card_number = ""
        currency = "EUR"

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if len(pdf.pages) > 0:
                    p1_text = pdf.pages[0].extract_text() or ""
                    
                    # 1. Date (e.g. "Datum 07.08.26" or "07.08.2026")
                    date_match = re.search(r"Datum\s+(\d{2})\.(\d{2})\.(\d{2,4})", p1_text, re.IGNORECASE)
                    if date_match:
                        raw_year = date_match.group(3)
                        statement_year = f"20{raw_year}" if len(raw_year) == 2 else raw_year

                    # 2. Card Number (e.g. "xxxx-xxxxxx-22001", "3752-xxxxxx-22001", "22001")
                    card_match = re.search(r"(?:[xX0-9]{4}-[xX0-9]{6}-(\d{5})|Kartennummer\s+([xX0-9\-]+))", p1_text, re.IGNORECASE)
                    if card_match:
                        matched_digits = card_match.group(1) or card_match.group(2)
                        card_number = matched_digits.strip()

                    # 3. Account Holder / Company Name
                    # Pattern A: Direct table line like "MSC POURIA SANGLAJI xxxx-xxxxxx-22001"
                    name_card_line = re.search(r"^([A-Za-zÄÖÜäöüß0-9\.\,\-\s\&]{3,50})\s+[xX0-9]{4}-[xX0-9]{6}", p1_text, re.MULTILINE)
                    if name_card_line:
                        candidate = name_card_line.group(1).strip()
                        if not any(sw in candidate.lower() for sw in ["angefertigt", "ihre", "seite", "datum", "kartenummer"]):
                            account_holder = candidate

                    # Pattern B: "Neue Belastungen für MSC POURIA SANGLAJI"
                    if account_holder == "Unbekannt":
                        belastung_match = re.search(r"(?:Neue\s+)?Belastungen\s+für\s+([A-Za-zÄÖÜäöüß0-9\.\,\-\s\&]{3,50})", p1_text, re.IGNORECASE)
                        if belastung_match:
                            account_holder = belastung_match.group(1).strip()

                    # Pattern C: Multiline "Angefertigt für \n MSC POURIA SANGLAJI"
                    if account_holder == "Unbekannt":
                        lines = [l.strip() for l in p1_text.split('\n') if l.strip()]
                        for i, line in enumerate(lines):
                            if "angefertigt für" in line.lower() and i + 1 < len(lines):
                                next_line = lines[i+1].split('   ')[0].strip()
                                if not any(sw in next_line.lower() for sw in ["ihre", "seite", "datum", "karten"]):
                                    account_holder = next_line
                                    break

                logger.info(f"[{filename}] Clean Metadata -> Holder: '{account_holder}', Card: '{card_number}', Year: '{statement_year}'")

                # Transaction matching
                line_pattern = re.compile(
                    r"^(\d{2}\.\d{2})\s+(\d{2}\.\d{2})\s+(.+?)\s+([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})(?:\s+(CR))?$",
                    re.MULTILINE
                )

                # Process all pages
                for page_idx, page in enumerate(pdf.pages):
                    text = page.extract_text(layout=False) or ""
                    lines = text.split("\n")
                    
                    i = 0
                    while i < len(lines):
                        line = lines[i].strip()
                        match = line_pattern.match(line)
                        
                        if match:
                            trans_date_raw, booking_date_raw, details, amount_raw, is_credit = match.groups()
                            
                            # Date DD.MM.YYYY
                            trans_day, trans_month = trans_date_raw.split(".")
                            full_date = f"{trans_day}.{trans_month}.{statement_year}"
                            
                            # Clean details
                            cleaned_details = re.sub(r"\b\d+[\.,]\d{2}\s+[A-Z\s]+(?:DOLLAR|USD|GBP|CHF|YEN)\b", "", details).strip()
                            
                            # Check for exchange rate / secondary lines
                            extra_info = []
                            if i + 1 < len(lines):
                                next_line = lines[i + 1].strip()
                                if next_line.startswith("Referenzwechselkurs") or next_line.startswith("Entgelt in EUR"):
                                    extra_info.append(next_line)
                                    i += 1
                            
                            if extra_info:
                                full_description = f"{cleaned_details} ({'; '.join(extra_info)})"
                            else:
                                full_description = cleaned_details

                            # Filter summary headers
                            if not any(skip_word in full_description for skip_word in [
                                "Summe Belastungen", "Saldo sonstige", "Summe erworbene Punkte", "Saldo der letzten"
                            ]):
                                clean_amount_str = amount_raw.replace(".", "")
                                
                                if is_credit == "CR":
                                    betrag_formatted = clean_amount_str
                                else:
                                    betrag_formatted = f"-{clean_amount_str}"

                                transactions.append({
                                    "Belegdatum": full_date,
                                    "Buchungstext": full_description,
                                    "Betrag": betrag_formatted,
                                    "Währung": currency,
                                    "Belegnummer": f"AMEX-{trans_day}{trans_month}",
                                    "Gegenkonto/Konto": "",
                                    "_source_file": filename,
                                    "_account_holder": account_holder,
                                    "_account_id": card_number
                                })
                        i += 1
        except Exception as e:
            logger.error(f"Error parsing Amex PDF statement ({filename}): {e}")

        return {
            "account_holder": account_holder,
            "account_id": card_number,
            "currency": currency,
            "statement_year": statement_year,
            "transactions": transactions
        }

    def parse(self, pdf_bytes: bytes) -> List[Dict[str, Any]]:
        res = self.parse_with_metadata(pdf_bytes)
        return res.get("transactions", [])


class UniversalBankStatementParser:
    """
    Universal Parser for German & Austrian Bank Statements (VR Bank, Volksbank,
    Raiffeisenbank, Sparkasse, Deutsche Bank, Commerzbank, DKB, ING, Erste Bank, RLB, etc.).
    Extracts multi-line transactions, IBAN, Kontoinhaber, and statement period.
    """

    def is_applicable(self, text_sample: str) -> bool:
        return True

    def parse_with_metadata(self, pdf_bytes: bytes, filename: str = "") -> Dict[str, Any]:
        transactions = []
        statement_year = str(datetime.now().year)
        account_holder = "Bank Kunde"
        iban = ""
        currency = "EUR"

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"[{filename}] UniversalBankParser opening {total_pages} page(s)")

                if total_pages == 0:
                    return {"account_holder": account_holder, "account_id": iban, "currency": currency, "transactions": []}

                # 1. Metadata from page 1
                p1_text = pdf.pages[0].extract_text() or ""
                logger.info(f"[{filename}] Page 1 preview ({len(p1_text)} chars): {repr(p1_text[:300])}")

                # Year detection
                year_match = re.search(r"(?:per|vom|Zeitraum|Datum|Auszug\s+Nr\.?|Rechnungsabschluss)\s*(?:[0-9\.\-\s/]+)?\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", p1_text, re.IGNORECASE)
                if year_match:
                    raw_year = year_match.group(3)
                    statement_year = f"20{raw_year}" if len(raw_year) == 2 else raw_year
                else:
                    four_digit_year = re.search(r"\b(202[0-9])\b", p1_text)
                    if four_digit_year:
                        statement_year = four_digit_year.group(1)

                # IBAN detection (DE..., AT...)
                iban_match = re.search(r"\b((?:DE|AT)\d{2}\s?(?:\d{4}\s?){3,5}\d{1,4})\b", p1_text)
                if iban_match:
                    iban = iban_match.group(1).replace(" ", "")

                # Kontoinhaber detection
                holder_match = re.search(r"(?:Kontoinhaber(?:in)?|Konto\s+lautend\s+auf|Name\s*:\s*|Empfänger\s*:\s*)\s*:?\s*([A-Za-zÄÖÜäöüß0-9\.\,\-\s\&]{3,60})", p1_text, re.IGNORECASE)
                if holder_match:
                    cand = holder_match.group(1).strip().split("\n")[0]
                    if not any(sw in cand.lower() for sw in ["iban", "bic", "blz", "seite", "datum", "konto-nr", "auszug"]):
                        account_holder = cand
                else:
                    if "VR Bank" in p1_text or "Volksbank" in p1_text or "VR-Bank" in p1_text:
                        account_holder = "VR Bank Konto"
                    elif "Sparkasse" in p1_text:
                        account_holder = "Sparkasse Konto"
                    elif "Deutsche Bank" in p1_text:
                        account_holder = "Deutsche Bank Konto"
                    elif filename:
                        account_holder = filename.rsplit('.', 1)[0]

                logger.info(f"[{filename}] Extracted Metadata -> Holder='{account_holder}', IBAN='{iban}', Year='{statement_year}'")

                # Multi-strategy extraction: Strategy 1 (Stream), Strategy 2 (Layout), Strategy 3 (Tables)
                # Strategy 1: layout=False
                blocks_false = [p.extract_text(layout=False) or "" for p in pdf.pages]
                raw_combined = "\n".join([b for b in blocks_false if b])
                transactions = self._extract_transactions(raw_combined, statement_year, account_holder, iban, filename)

                # Strategy 2: layout=True if Strategy 1 found 0
                if not transactions:
                    logger.info(f"[{filename}] Strategy 1 returned 0 txs, trying Strategy 2 (layout=True)...")
                    blocks_true = [p.extract_text(layout=True) or "" for p in pdf.pages]
                    raw_layout_combined = "\n".join([b for b in blocks_true if b])
                    transactions = self._extract_transactions(raw_layout_combined, statement_year, account_holder, iban, filename)

                # Strategy 3: extract_tables() if Strategy 1 & 2 returned 0
                if not transactions:
                    logger.info(f"[{filename}] Strategy 1 & 2 returned 0 txs, trying Strategy 3 (pdfplumber.extract_tables())...")
                    table_txs = self._extract_from_tables(pdf, statement_year, account_holder, iban, filename)
                    if table_txs:
                        transactions = table_txs
                        logger.info(f"[{filename}] Strategy 3 succeeded: {len(transactions)} txs found in tables")

                # Strategy 4: Automatic Native OCR for Scanned PDFs (when 0 chars or 0 txs found)
                total_chars = len(raw_combined.strip())
                if not transactions and (total_chars < 50 or total_pages > 0):
                    logger.info(f"[{filename}] PDF has no digital text layer ({total_chars} chars). Launching Strategy 4 (High-Res Native OCR Engine)...")
                    ocr_text = self._run_native_ocr(pdf_bytes, filename)
                    if ocr_text:
                        logger.info(f"[{filename}] OCR extracted {len(ocr_text)} chars. Parsing OCR transactions...")
                        ocr_txs = self._extract_transactions(ocr_text, statement_year, account_holder, iban, filename)
                        if ocr_txs:
                            transactions = ocr_txs
                            logger.info(f"[{filename}] Strategy 4 (OCR) succeeded: {len(transactions)} txs recognized!")

        except Exception as e:
            logger.error(f"Error in UniversalBankStatementParser for '{filename}': {e}", exc_info=True)

        return {
            "account_holder": account_holder,
            "account_id": iban,
            "currency": currency,
            "statement_year": statement_year,
            "transactions": transactions
        }

    def _run_native_ocr(self, pdf_bytes: bytes, filename: str) -> str:
        """Renders scanned PDF pages to high-res images and recognizes text with Windows Native OCR."""
        import concurrent.futures

        def _ocr_worker():
            try:
                import pypdfium2 as pdfium
                import winsdk.windows.media.ocr as ocr
                import winsdk.windows.graphics.imaging as imaging
                import winsdk.windows.storage as storage
                import asyncio
                import tempfile

                pdf = pdfium.PdfDocument(pdf_bytes)
                total_pages = len(pdf)
                page_results = []

                async def process_pages_async():
                    import winsdk.windows.globalization as glob
                    # Prioritize German language for German & Austrian bank statements
                    engine = None
                    for lang_tag in ["de-DE", "de-AT", "de-CH", "en-US"]:
                        try:
                            engine = ocr.OcrEngine.try_create_from_language(glob.Language(lang_tag))
                            if engine:
                                break
                        except Exception:
                            pass

                    if not engine:
                        engine = ocr.OcrEngine.try_create_from_user_profile_languages()

                    with tempfile.TemporaryDirectory() as tmpdir:
                        for idx in range(total_pages):
                            page = pdf.get_page(idx)
                            # Render at 3.0 scale for crisp OCR (~216 DPI)
                            pil_img = page.render(scale=3.0).to_pil()
                            img_path = os.path.join(tmpdir, f"scan_page_{idx}.png")
                            pil_img.save(img_path, format="PNG")

                            file = await storage.StorageFile.get_file_from_path_async(os.path.abspath(img_path))
                            stream = await file.open_async(storage.FileAccessMode.READ)
                            decoder = await imaging.BitmapDecoder.create_async(stream)
                            bitmap = await decoder.get_software_bitmap_async()

                            res = await engine.recognize_async(bitmap)
                            lines = [self._normalize_ocr_line(line.text) for line in res.lines]
                            page_results.append("\n".join(lines))
                            logger.info(f"[{filename}] OCR Page {idx+1}/{total_pages}: {len(lines)} lines recognized")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(process_pages_async())
                finally:
                    loop.close()

                return "\n\n".join(page_results)
            except Exception as ocr_err:
                logger.error(f"Native OCR failed on '{filename}': {ocr_err}", exc_info=True)
                return ""

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(_ocr_worker).result()

    def _normalize_ocr_line(self, line: str) -> str:
        """Normalizes Cyrillic/Latin homoglyphs in dates and amounts produced by OCR on localized Windows."""
        if not line:
            return ""

        # Fix homoglyphs in dates (e.g. 02.ов.202В -> 02.06.2026)
        def repl_date(m):
            raw = m.group(0)
            return (raw.replace('о', '0').replace('О', '0')
                       .replace('в', '6').replace('В', '6')
                       .replace('з', '3').replace('З', '3')
                       .replace('б', '6').replace('Б', '6'))

        line = re.sub(r'\b[0-9\w]{1,2}[\.\/\-][0-9\w]{1,2}(?:[\.\/\-][0-9\w]{2,4})?\b', repl_date, line)

        # Fix homoglyphs in currency amounts
        def repl_amount(m):
            raw = m.group(0)
            return (raw.replace('о', '0').replace('О', '0')
                       .replace('з', '3').replace('З', '3')
                       .replace('б', '6').replace('Б', '6'))

        line = re.sub(r'[-+]?\s*[0-9\w]+(?:\.[0-9\w]+)*,[0-9\w]{2}\s*[-+SHsh]?', repl_amount, line)
        return line

    def _extract_transactions(self, text: str, year: str, holder: str, iban: str, filename: str) -> List[Dict[str, Any]]:
        txs = []
        lines = [self._normalize_ocr_line(l.strip()) for l in text.split("\n") if l.strip()]

        skip_phrases = [
            "alter kontostand", "neuer kontostand", "alter saldo", "neuer saldo",
            "übertrag von seite", "übertrag auf seite", "kontostand am", "rechnungsabschluss",
            "kontostand per", "freistellungsauftrag", "einlagensicherung", "ihre ansprechpartner",
            "seite ", "iban:", "bic:", "gläubiger-id", "mandatsreferenz:", "buchungstag wert",
            "buchungstag / wert", "vorgang / verwendungszweck", "soll / haben", "umsatz in eur",
            "wertstellung vorgang", "auszug nr", "iban / bic", "seite:", "datum uhrzeit"
        ]

        current_tx_meta = None
        current_lines = []

        # Supports standard (DD.MM.YYYY, DD.MM.) and OCR variants (DD/MM/YYYY, DD-MM-YYYY, DD MM YYYY)
        date_finder_re = re.compile(r"^([^\d]{0,10})(\d{1,2}[\.\/\-]\s*\d{1,2}(?:[\.\/\-]\s*\d{2,4})?)(?:\s+(\d{1,2}[\.\/\-]\s*\d{1,2}(?:[\.\/\-]\s*\d{2,4})?))?\s*(.*)$")

        for line in lines:
            line_lower = line.lower()

            if any(line_lower.startswith(sp) for sp in skip_phrases):
                if current_tx_meta and current_lines:
                    self._process_tx_block(txs, current_tx_meta, current_lines, year, holder, iban, filename)
                    current_tx_meta = None
                    current_lines = []
                continue

            m = date_finder_re.match(line)
            if m and self._is_valid_date(m.group(2)):
                if current_tx_meta and current_lines:
                    self._process_tx_block(txs, current_tx_meta, current_lines, year, holder, iban, filename)

                b_date = re.sub(r"\s+", "", m.group(2))
                prefix = m.group(1).strip()
                rest = m.group(4).strip()
                full_first_line = f"{prefix} {rest}".strip() if prefix else rest

                current_tx_meta = {"date": b_date}
                current_lines = [full_first_line] if full_first_line else []
            else:
                if current_tx_meta is not None:
                    current_lines.append(line)

        # Process final block
        if current_tx_meta and current_lines:
            self._process_tx_block(txs, current_tx_meta, current_lines, year, holder, iban, filename)

        return txs

    def _extract_from_tables(self, pdf, year: str, holder: str, iban: str, filename: str) -> List[Dict[str, Any]]:
        txs = []
        date_re = re.compile(r"\b(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\b")
        amount_re = re.compile(r"([-+]?\s*(?:[0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),[0-9]{2}\s*[-+SHsh]?)")

        for page in pdf.pages:
            try:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 2:
                            continue
                        row_text = " ".join([str(c or "").strip() for c in row if c])
                        
                        # Find date
                        date_m = date_re.search(row_text)
                        amt_m = amount_re.findall(row_text)

                        if date_m and amt_m:
                            b_date = date_m.group(1)
                            if self._is_valid_date(b_date):
                                self._process_tx_block(txs, {"date": b_date}, [row_text], year, holder, iban, filename)
            except Exception as e:
                logger.debug(f"Table extraction exception: {e}")

        return txs

    def _is_valid_date(self, s: str) -> bool:
        clean = re.sub(r"\s+", "", s)
        parts = clean.split(".")
        if len(parts) >= 2:
            try:
                d = int(parts[0])
                m = int(parts[1])
                return 1 <= d <= 31 and 1 <= m <= 12
            except ValueError:
                return False
        return False

    def _process_tx_block(self, tx_list: List[Dict], meta: Dict, raw_lines: List[str], year: str, holder: str, iban: str, filename: str):
        full_text = " ".join(raw_lines).strip()
        if not full_text:
            return

        # Format full date DD.MM.YYYY
        raw_date = meta["date"]
        d_parts = raw_date.split(".")
        if len(d_parts) == 2 or (len(d_parts) == 3 and not d_parts[2]):
            full_date = f"{d_parts[0].zfill(2)}.{d_parts[1].zfill(2)}.{year}"
        elif len(d_parts) == 3:
            y_str = d_parts[2]
            full_y = f"20{y_str}" if len(y_str) == 2 else y_str
            full_date = f"{d_parts[0].zfill(2)}.{d_parts[1].zfill(2)}.{full_y}"
        else:
            full_date = raw_date

        # Look for German / European currency numbers (supports both comma and dot decimal: -120,50, -120.50, 1.250,00-, +4850.00, 75,30 S)
        amount_re = re.compile(r"([-+]?\s*(?:[0-9]{1,3}(?:[\.,][0-9]{3})*|[0-9]+)[\.,][0-9]{2}\s*[-+SHsh]?)(?:\s*(?:EUR|€))?", re.IGNORECASE)
        matches = amount_re.findall(full_text)
        if not matches:
            return

        raw_amt = matches[-1].strip()
        
        # Clean amount and determine sign
        cleaned = raw_amt.replace(" ", "").replace("EUR", "").replace("€", "").strip()
        is_negative = False

        if cleaned.endswith("-") or cleaned.startswith("-") or cleaned.upper().endswith("S"):
            is_negative = True
            cleaned = cleaned.rstrip("-sS").lstrip("-")
        elif cleaned.endswith("+") or cleaned.startswith("+") or cleaned.upper().endswith("H"):
            is_negative = False
            cleaned = cleaned.rstrip("+hH").lstrip("+")
        else:
            is_negative = False

        # Format to German comma decimal for DATEV / BMD
        if "." in cleaned and "," not in cleaned:
            parts = cleaned.split(".")
            if len(parts[-1]) == 2:
                cleaned = "".join(parts[:-1]) + "," + parts[-1]
        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "")

        final_amount = f"-{cleaned}" if is_negative else cleaned

        # Clean description
        desc = re.sub(re.escape(raw_amt), "", full_text).strip()
        desc = re.sub(r"\s+", " ", desc)
        if not desc:
            desc = f"Bankumsatz vom {full_date}"

        tx_list.append({
            "Belegdatum": full_date,
            "Buchungstext": desc[:250],
            "Betrag": final_amount,
            "Währung": "EUR",
            "Belegnummer": f"BNK-{d_parts[0].zfill(2)}{d_parts[1].zfill(2)}",
            "Gegenkonto/Konto": "",
            "_source_file": filename,
            "_account_holder": holder,
            "_account_id": iban
        })

