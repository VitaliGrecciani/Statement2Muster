# Statement2Muster — Matrix der Unterstützten Bankprofile (Pilotbetrieb v1.0.2)

**Dokument-Version:** 1.0.2  
**Gültig ab:** 9. September 2026  
**Zielgruppe:** Kanzleien, Steuerberater, Wirtschaftsprüfer und Systemarchitekten  
**Sicherheitsstandard:** Zero Durable Retention (RAM-only Verarbeitung gemäß DSGVO Art. 28)

---

## 1. Übersicht & Zertifizierte Bankprofile

Statement2Muster v1.0.2 unterstützt für den Kanzlei-Pilotbetrieb fünf primäre Bank- und Zahlungsdienstleister-Profile des DACH-Raums. Die Formate werden zur Laufzeit automatisch im Arbeitsspeicher erkannt und in das kanonische Datenmodell (`CanonicalTransaction`) normalisiert.

| Institut / Profil | Unterstützte Formate | Erkennungsmerkmale | Standard-Währung | Konten-Identifikation |
|---|---|---|---|---|
| **Sparkassen-Finanzgruppe** | CSV, PDF, MT940 | Spalten: `Auftragskonto`, `Buchungstag`, `Betrag`, `Verwendungszweck` | EUR | IBAN (`DE..` / `AT..`), Kontonummer |
| **Volksbanken / Raiffeisenbanken** | CSV, PDF, CAMT.053 | Schlüsselwörter: `VR Bank`, `Volksbank`, `Raiffeisen`, `Buchungstag`, `Saldo nach Buchung` | EUR | IBAN, BLZ + Kontonummer |
| **Deutsche Bank / Postbank** | CSV, PDF | Spalten: `Buchungstag`, `Wert`, `Umsatzart`, `Begünstigter / Auftraggeber`, `Verwendungszweck`, `Betrag` | EUR | IBAN, Kontonummer |
| **Wise Europe (ehem. TransferWise)** | CSV | Spalten: `TransferWise ID`, `Date`, `Amount`, `Currency`, `Description`, `Payment Reference`, `Running Balance` | EUR, USD, GBP | Wise Account ID / Currency Partition |
| **American Express (DACH)** | PDF (digital & scan) | Kopf: `AMERICAN EXPRESS`, `Datum DD.MM.YY`, Kartennummer `3752-xxxxxx-22001`, Layout-Spalten | EUR | Kartennummer (letzte 5 Ziffern) |

---

## 2. Detaillierte Profil-Spezifikationen

### 2.1 Sparkassen-Finanzgruppe
- **Encoding:** ISO-8859-1 (Windows-1252) oder UTF-8 mit automatischer Erkennung.
- **Trennzeichen:** Semikolon (`;`) standardmäßig.
- **Datumsformat:** `DD.MM.YY` oder `DD.MM.YYYY`.
- **Betragsformat:** Deutsches Format mit Punkt als Tausendertrennzeichen und Komma als Dezimaltrenner (z.B. `1.234,56` oder `-45,00`).
- **Besonderheiten:**
  - Automatische Bereinigung von CRLF-Zeilenumbrüchen innerhalb von Verwendungszwecken.
  - Erkennung von Saldozeilen (`Kontostand`, `Endsaldo`) zur exakten Saldenverifikation.

### 2.2 Volksbanken & Raiffeisenbanken (VR-Bank)
- **Encoding:** Windows-1252 oder UTF-8.
- **Trennzeichen:** Semikolon (`;`).
- **S/H-Indikator:** Unterstützung von Beträgen mit explizitem S/H-Suffix (z.B. `100,00 S` für Soll / Lastschrift; `100,00 H` für Haben / Gutschrift).
- **Universal PDF Extractor:** Mehrstufige geometrische Textextraktion (`layout=False`, `layout=True`, `extract_tables()`, OCR Fallback).

### 2.3 Deutsche Bank
- **Encoding:** ISO-8859-1.
- **Trennzeichen:** Semikolon (`;`).
- **Struktur:** Kopfzeilen mit Metadaten (Kontonummer, Auszugsnummer) vor der tabellarischen Buchungsmatrix.
- **Betragskonvention:** Positive Werte = Gutschriften, negative Werte mit vorangestelltem Minus = Lastschriften.

### 2.4 Wise Europe
- **Encoding:** UTF-8.
- **Trennzeichen:** Komma (`,`).
- **Multiwährungs-Behandlung:**
  - Jede Transaktion trägt die explizite ISO-Währung (`EUR`, `USD`, `GBP`).
  - **Strikter Export-Safeguard:** Wenn ein Batch Buchungen unterschiedlicher Währungen enthält, verweigert die API den Buchhaltungs-Export (DATEV/BMD) mit `HTTP 422 Unprocessable Content`, um Wechselkurs-Fehlbuchungen im Rechnungswesen absolut auszuschließen. Eine Partitionierung pro Währung ist zwingend.

### 2.5 American Express (Deutschland & Österreich)
- **Format:** PDF (digital generiert oder gescannt).
- **Jahreswechsel-Korrektur (Rollover):**
  - Wenn ein Januar-Auszug Buchungen aus dem November oder Dezember des Vorjahres enthält, rechnet der Parser das Buchungsjahr automatisch zurück (`statement_year - 1`).
- **Fremdwährungen & Gebühren:**
  - Transaktionen mit Umrechnungskursen (z.B. `Referenzwechselkurs`, `Entgelt in EUR`) werden strukturiert im Buchungstext erfasst (`Text (Referenzwechselkurs 1.08; Entgelt in EUR 0.45)`).
- **OCR-Absicherung:**
  - Bei reinen Bild-PDFs greift der integrierte OCR-Dienst mit Homoglyphen-Normalisierung (z.B. Ersetzung von kyrillischem `б`/`Б` durch Ziffer `6`).

---

## 3. Buchhalterische Export-Standards

### 3.1 DATEV Format (EXTF 700 — Buchungsstapel)
- **Kompatibilität:** DATEV Rechnungswesen / Kanzlei-Rechnungswesen (Header-Version 700).
- **Header-Definition:**
  - `DTVF` / `EXTF` Kennzeichnung.
  - Dynamisches Wirtschaftsjahr basierend auf den verarbeiteten Belegdaten.
  - Mandanten- und Beraternummer konfigurierbar (Standard: Berater `10001`, Mandant `1001`).
- **Soll/Haben-Logik:**
  - Bank-Gutschriften (Mittelzufluss) werden mit Kennzeichen `"S"` (Soll auf Bankkonto) exportiert.
  - Bank-Lastschriften (Mittelabfluss) werden mit Kennzeichen `"H"` (Haben auf Bankkonto) exportiert.
- **Spaltenformat (6 Standard-Spalten):**
  1. `Umsatz (ohne Soll/Haben-Kz)` (z.B. `10,00`)
  2. `Soll/Haben-Kennzeichen` (`S` oder `H`)
  3. `Konto` (z.B. `1200` für SKR03 bzw. `1800` für SKR04)
  4. `Gegenkonto` (Gegenkonto oder Sammelkonto)
  5. `Belegdatum` (`TTMM` oder `TTMMJJ`)
  6. `Buchungstext` (Formel-bereinigt, max. 60 Zeichen)

### 3.2 BMD NTCS 5.1 Format
- **Kompatibilität:** BMD NTCS Finanzbuchhaltung (Österreich & Deutschland).
- **Standard-Bankkonto:** `2800` (österreichischer Einheitskontenrahmen) oder mandantenspezifisch.
- **Struktur:**
  - Satzart, Belegnummer, Belegdatum, Konto, Gegenkonto, Betrag (mit Vorzeichen), Buchungstext.

### 3.3 Muster-CSV Format
- Kanzlei-unabhängiges Prüf- und Kontrollformat für Vorab-Reviews und Mandantenabstimmungen.

---

## 4. Validierungs- und Schutzmechanismen

1. **Integer-Cents Arithmetik:**
   Alle Beträge werden intern ausschließlich als ganzzahlige Cents (`int`) gespeichert und verarbeitet. Fließkomma-Rundungsfehler (`float IEEE-754`) sind mathematisch ausgeschlossen.

2. **Saldenprüfung (Reconciliation):**
   - Es gilt: $\text{Anfangssaldo} + \sum \text{Transaktionen} = \text{Endsaldo}$.
   - Weicht die Summe ab, wird der Status auf `DISCREPANCY` gesetzt und der Buchhaltungs-Export blockiert.

3. **CSV- und Formelsanitisierung:**
   - Transaktionstexte, die mit `=`, `+`, `-` oder `@` beginnen, werden mit einem vorangestellten Hochkomma (`'`) maskiert, um Formula Injection in Microsoft Excel und LibreOffice Calc zu verhindern.

4. **Batch- und Ressourcengrenzen:**
   - Maximale Dateigröße: 10 MiB pro Datei.
   - Maximales Batch-Volumen: 50 MiB pro Anfrage.
   - Maximale Seitenzahl: 100 Seiten pro PDF.
   - Maximales Zeilenbudget: 10.000 Zeilen pro Datei (Streaming-geprüft direkt im Parser).

5. **Zero Durable Retention:**
   - Weder Bankauszüge noch Buchungsdaten werden auf Festplatten oder persistente Speichermedien geschrieben.
   - Der RAM-Ergebniscache unterliegt einem strikten TTL von 10 Minuten (600 Sekunden) und einem Budget von 50 MiB mit LRU-Verdrängung.
