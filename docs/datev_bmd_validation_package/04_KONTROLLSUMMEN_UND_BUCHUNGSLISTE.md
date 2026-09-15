# Statement2Muster — Kontrollsummen & Buchungsliste (Abstimmungsblatt)

**Dokument-ID:** S2M-VAL-2026-04  
**Prüfperiode:** 01.01.2026 – 31.01.2026  
**Zielsysteme:** DATEV Kanzlei-Rechnungswesen (EXTF 700) | BMD NTCS 5.1 (Satzart 0)  
**Status:** Prüfbereit zur Übergabe an Steuerberater / Buchhalter  

---

## 1. Übersicht & Zweck

Dieses Dokument dient dem Steuerberater, Wirtschaftsprüfer oder Bilanzbuchhalter als **verbindliche Referenz und Abstimmungsunterlage**. Es enthält die exakten rechnerischen Soll- und Haben-Kontrollsummen sowie die vollständige Einzelaufstellung aller synthetischen Buchungssätze.

Nach dem Import in **DATEV Kanzlei-Rechnungswesen** bzw. **BMD NTCS** müssen die im Buchungsstapel angezeigten Summen exakt mit den untenstehenden Kontrollwerten übereinstimmen.

---

## 2. Konten- und Stammdatenmatrix

| Datenfeld | DATEV SKR03 | DATEV SKR04 | BMD NTCS (Österreich) |
| :--- | :--- | :--- | :--- |
| **Girokonto (Sparkasse)** | `1200` | `1800` | `2800` |
| **Kreditkarte (Amex)** | `1210` | `1810` | `2810` |
| **Beraternummer** | `1001` | `1001` | – |
| **Mandantennummer** | `10001` | `10001` | – |
| **Wirtschaftsjahr** | 2026 (01.01. – 31.12.) | 2026 (01.01. – 31.12.) | 2026 |
| **Sachkontenlänge** | 4-stellig | 4-stellig | 4-stellig |
| **Zeichensatz / Zeilenumbruch** | Windows-1252 / CRLF | Windows-1252 / CRLF | Windows-1252 / CRLF |

---

## 3. Kontrollsummen (Soll- / Haben-Abstimmung)

### A. Sparkasse / Girokonto (Januar 2026)
* **Dateien:**  
  * DATEV SKR03: `02_DATEV_EXTF_EXPORTS/EXTF_Sparkasse_Januar2026_SKR03_1200.csv`
  * DATEV SKR04: `02_DATEV_EXTF_EXPORTS/EXTF_Sparkasse_Januar2026_SKR04_1800.csv`
  * BMD NTCS: `03_BMD_NTCS_EXPORTS/BMD_Sparkasse_Januar2026_Konto2800.csv`
* **Anzahl Buchungssätze:** `10`
* **Summe Soll (Gutschriften / Zugänge):** `4.465,00 EUR`
* **Summe Haben (Lastschriften / Abgänge):** `1.765,00 EUR`
* **Monatssaldo (Netto-Veränderung):** `+2.700,00 EUR`

### B. American Express Business Kreditkarte (Januar 2026)
* **Dateien:**  
  * DATEV SKR03: `02_DATEV_EXTF_EXPORTS/EXTF_Amex_Januar2026_SKR03_1210.csv`
  * DATEV SKR04: `02_DATEV_EXTF_EXPORTS/EXTF_Amex_Januar2026_SKR04_1810.csv`
  * BMD NTCS: `03_BMD_NTCS_EXPORTS/BMD_Amex_Januar2026_Konto2810.csv`
* **Anzahl Buchungssätze:** `7`
* **Summe Soll (Gutschriften / Ausgleichszahlung):** `779,65 EUR`
* **Summe Haben (Aufwendungen / Belastungen):** `779,65 EUR`
* **Monatssaldo (Netto-Veränderung):** `0,00 EUR` (Kreditkartenkonto per 31.01. vollständig ausgeglichen)

---

## 4. Detaillierte Buchungszeilen

### 4.1 Sparkasse / Erste Bank (Konto 1200 / 1800 / 2800)

| Nr. | Datum | S/H | Betrag (EUR) | Belegfeld 1 | Buchungstext | Verwendungszweck / Partner |
| :---: | :---: | :---: | :---: | :--- | :--- | :--- |
| 1 | 05.01.2026 | **S** | 2.450,00 | `Rechnung RE-2026-001` | Meier GmbH - Rechnung RE-2026-001 Software | Software-Verkauf |
| 2 | 08.01.2026 | **H** | 1.250,00 | `CSV-2` | Immobilien Verwaltung KG - Bueromiete Jaenner 2026 | Büromiete |
| 3 | 12.01.2026 | **H** | 180,50 | `CSV-3` | DATEV eG - DATEV Cloud Lizenz monatlich | DATEV Softwarelizenz |
| 4 | 15.01.2026 | **S** | 1.890,00 | `Rechnung RE-2026-002` | Mueller & Soehne OG - Rechnung RE-2026-002 Beratung | Beratungsleistung |
| 5 | 18.01.2026 | **H** | 75,40 | `CSV-5` | Pagro Diskont - Buerobedarf & Papier | Bürobedarf |
| 6 | 22.01.2026 | **H** | 89,90 | `CSV-6` | A1 Telekom Austria - Internet & Telefon Festnetz | Telekommunikation |
| 7 | 25.01.2026 | **S** | 120,00 | `CSV-7` | Lieferant Mayer - Gutschrift Ueberzahlung | Lieferantenüberzahlung |
| 8 | 28.01.2026 | **H** | 145,20 | `CSV-8` | Gasthaus Zum Loeffel - Geschaeftsessen Bewirtung | Bewirtungsaufwand |
| 9 | 30.01.2026 | **H** | 24,00 | `CSV-9` | Erste Bank AG - Kontofuehrung Q1 2026 | Bankspesen |
| 10 | 31.01.2026 | **S** | 5,00 | `CSV-10` | Erste Bank AG - Habenzinsen Festgeldkonto | Zinsertrag |

### 4.2 American Express Business (Konto 1210 / 1810 / 2810)

| Nr. | Datum | S/H | Betrag (EUR) | Belegfeld 1 | Buchungstext | Kategorie / Erläuterung |
| :---: | :---: | :---: | :---: | :--- | :--- | :--- |
| 1 | 04.01.2026 | **H** | 320,45 | `AMX-2026-001` | Vitali Grecciani - AWS Cloud Services Europe | Server-Hosting / Cloud |
| 2 | 10.01.2026 | **H** | 245,00 | `AMX-2026-002` | Vitali Grecciani - Hotel Koenigshof Muenchen Geschaeftsreise | Geschäftsreise Übernachtung |
| 3 | 15.01.2026 | **H** | 112,80 | `AMX-2026-003` | Vitali Grecciani - Deutsche Bahn Ticket ICE 512 | Reisekosten Bahn |
| 4 | 20.01.2026 | **S** | 245,00 | `AMX-2026-004` | Vitali Grecciani - Rueckverguetung Hotel Storno | Stornogutschrift Hotel |
| 5 | 28.01.2026 | **H** | 86,40 | `AMX-2026-005` | Vitali Grecciani - Google Workspace Business | Cloud Software Lizenzen |
| 6 | 30.01.2026 | **H** | 15,00 | `AMX-2026-006` | Vitali Grecciani - Monatliche Kartengebuehr | Kreditkartengebühr |
| 7 | 31.01.2026 | **S** | 534,65 | `AMX-2026-007` | Vitali Grecciani - Ausgleichszahlung Lastschrift | Kartenausgleich über Bankkonto |

---

## 5. Buchungstechnische Hinweise für den Steuerberater

1. **Soll/Haben-Logik bei Aktivkonten:**
   * Geldeingänge erhöhen den Bank- / Kassenbestand: **Soll (S)**.
   * Geldausgänge verringern den Bank- / Kassenbestand: **Haben (H)**.
   * Gemäß DATEV-Konvention wird im Feld `Konto` das jeweilige Finanzkonto (z. B. `1200`) eingetragen. Gegenkonten können in DATEV direkt bei der manuellen/halbautomatischen Nachbearbeitung bzw. Kontierung zugeordnet werden.
2. **OPOS-Zuordnung:**
   * In Zeile 1 und Zeile 4 der Sparkasse wurde die Belegnummer (`Rechnung RE-2026-001` bzw. `Rechnung RE-2026-002`) direkt in `Belegfeld 1` übernommen. Beim Import in DATEV kann das System dadurch offene Posten (OPOS) vollautomatisch vorschlagen und ausgleichen.
3. **Umlaute und Zeichensatz:**
   * Alle Exportdateien sind strikt in **Windows-1252 (ANSI)** codiert. Es treten keine typischen UTF-8-Zeichensatzfehler (`Ã¤`, `Ã¼`, `Ã¶`, `ÃŸ`) auf.
