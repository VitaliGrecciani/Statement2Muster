# Leitfaden für den Steuerberater: DATEV & BMD Importprüfung

**Projekt:** Statement2Muster DACH  
**Zweck:** Fachliche Abnahme und Importvalidierung von generierten Buchungsstapeln (DATEV EXTF 700 & BMD NTCS)  
**Datum:** 2026-09-16  
**Anforderung:** Gemäß Решение № 42 und № 43 des Hauptarchitekten  

---

## 🇷🇺 Инструкция для Product Owner (Виталия)

Для получения финального вердикта **Full GO** передайте реальному бухгалтеру или налоговому консультанту (Steuerberater) тестовый комплект из папки `docs/accounting/samples/`:
1. `EXTF_DATEV_Buchungsstapel.csv` (для DATEV Rechnungswesen)
2. `BMD_NTCS_Buchungen.csv` (для BMD NTCS)
3. `sample_bank_statement.csv` (исходная синтетическая выписка банка)

**Что требуется от бухгалтера для закрытия аудита:**
Бухгалтер должен заполнить форму в разделе 4 (Sign-Off):
* Указать программу и точную версию (например, *DATEV Rechnungswesen V. 14.2*);
* Подтвердить число проводок (**10 из 10**);
* Сверить контрольные суммы по банковскому счёту:
  * В DATEV (счет 1200): **Soll (поступления) € 7.850,00**, **Haben (списания) € 2.246,30**, **Сальдо € +5.603,70**;
  * В BMD (счет 2800): **Положительные суммы € 7.850,00**, **Отрицательные суммы € -2.246,30**, **Сальдо € +5.603,70**;
* Подтвердить корректность разноски по счетам (банк `1200`/`2800` против контрагентов);
* Поставить дату, имя и подпись / название канцелярии.

---

## 🇩🇪 Anleitung für die Steuerberatungskanzlei / den Buchhalter

Sehr geehrte Damen und Herren,

im Rahmen der Qualitätssicherung unseres Auszugskonverters **Statement2Muster** möchten wir Sie bitten, die beiliegenden Testdateien in Ihrer Kanzleisoftware (**DATEV** bzw. **BMD NTCS**) zu importieren und die rechnerische und fachliche Richtigkeit der Buchungssätze kurz zu bestätigen.

### 1. Prüfpaket & Soll-Werte zur rechnerischen Abstimmung

Im Ordner `docs/accounting/samples/` finden Sie 10 synthetische Geschäftsvorfälle aus dem Monat Januar 2026. Bitte gleichen Sie die importierten Buchungen mit folgenden Kontrollwerten ab:

#### A. Sicht des aktiven Bankkontos (Konto 1200 in DATEV / Konto 2800 in BMD)

| Kennzahl | DATEV (Konto 1200) | BMD NTCS (Konto 2800) | Erläuterung |
|---|---|---|---|
| **Anzahl Buchungssätze** | **10** | **10** | 3 Einnahmen / 7 Ausgaben |
| **Gutschriften / Zuflüsse** | **Soll (S): € 7.850,00** | **Betrag positiv: € 7.850,00** | Kundenzahlungen (RE-014, RE-015, RE-016) |
| **Lastschriften / Abflüsse** | **Haben (H): € 2.246,30** | **Betrag negativ: € -2.246,30** | Miete, IT, Software, Büro, Tel, Ads, Spesen |
| **Saldo-Veränderung Bank** | **+ € 5.603,70 (Soll-Überhang)** | **+ € 5.603,70 (Netto-Saldo)** | Endsaldo Bankkonto erhöht sich um € 5.603,70 |

#### B. Sicht der Gegenkonten (Aufwands- und Erlöskonten)

| Gegenkonto | Kontobezeichnung | Buchungsseite (Gegenkonto) | Betrag |
|---|---|---|---|
| **8400** | Erlöse 19% USt / Honorare | **Haben (H)** | **€ 7.850,00** (Summe 3 Einnahmen) |
| **4210** | Miete unbewegliche Wirtschaftsgüter | **Soll (S)** | € 1.450,00 |
| **4930** | Software- und Cloud-Kosten (Hetzner, S2M) | **Soll (S)** | € 274,50 (€ 185,50 + € 89,00) |
| **4980** | Betriebsbedarf / Bürobedarf | **Soll (S)** | € 64,30 |
| **4920** | Telefon- und Internetgebühren | **Soll (S)** | € 95,00 |
| **4600** | Werbe- und Marketingkosten | **Soll (S)** | € 350,00 |
| **4970** | Nebenkosten des Geldverkehrs (Bankspesen) | **Soll (S)** | € 12,50 |
| **Summe Aufwand** | Alle Aufwandskonten kumuliert | **Soll (S)** | **€ 2.246,30** |

---

### 2. Import in DATEV Rechnungswesen (Deutschland / Österreich)

* **Datei:** `EXTF_DATEV_Buchungsstapel.csv`
* **Format:** Offizielles DATEV-Format **EXTF Version 700** (Format-Kategorie 21, Buchungsstapel).
* **Zeichensatz:** ANSI / Windows-1252 (Semikolon als Trennzeichen).
* **Voreingestellte Konten:**
  - Bankkonto: `1200` (SKR03 Standard)
  - Gegenkonten: `8400` (Erlöse), `4210` (Miete), `4930` (IT/Software), `4980` (Bürobedarf), `4920` (Telefon), `4600` (Werbung), `4970` (Bankspesen).
  - Beraternummer: `1001`, Mandantennummer: `10001` (kann im DATEV-Importdialog Ihrem Testmandanten zugewiesen werden).

**Schritte in DATEV Rechnungswesen:**
1. Mandantenbestand öffnen.
2. Menü: **Bestand ➔ Importieren ➔ Stapelverarbeitung** (oder *Stapelverarbeitung ➔ Importieren*).
3. Quellverzeichnis auswählen und Datei `EXTF_DATEV_Buchungsstapel.csv` markieren.
4. Auf **Importieren** klicken.
5. In der Stapelübersicht den neu importierten Stapel auswählen und auf **Einspielen / Öffnen** klicken.
6. **Kontrolle:** Summen und 10 Sätze prüfen.

---

### 3. Import in BMD NTCS (Österreich)

* **Datei:** `BMD_NTCS_Buchungen.csv`
* **Format:** Standardisierter BMD NTCS Buchungszeilen-Import.
* **Zeichensatz:** Windows-1252.
* **Voreingestellte Konten:**
  - Bankkonto: `2800` (ÖKR Standard-Bankkonto).
  - Gegenkonten nach österreichischem Einheitskontenrahmen (ÖKR).

**Schritte in BMD NTCS:**
1. BMD NTCS Finanzbuchhaltung öffnen.
2. Menü: **Buchungserfassung ➔ Werkzeuge / Import ➔ CSV-/Stapelimport**.
3. Datei `BMD_NTCS_Buchungen.csv` auswählen und einlesen.
4. **Kontrolle:** Summen und 10 Zeilen prüfen.

---

### 4. Kanzlei-Bestätigung (Sign-Off Vorlage gem. Решения № 42/43)

Nach erfolgtem Probeimport und Abgleich füllen Sie bitte folgende Bestätigung aus und senden diese per E-Mail an `support@statement2muster.com` oder direkt an Herrn Vitali Grecciani:

```text
================================================================================
FACHLICHE IMPORT- UND SALDENBESTÄTIGUNG (STATEMENT2MUSTER)

1. Softwareumgebung:
   [ ] DATEV Rechnungswesen, Programmversion: _______________________________
   [ ] BMD NTCS, Programmversion: __________________________________________
   [ ] Andere Kanzleisoftware: ______________________________________________

2. Geprüfte Importdatei:
   [ ] EXTF_DATEV_Buchungsstapel.csv
   [ ] BMD_NTCS_Buchungen.csv

3. Abstimmungsergebnis:
   [ ] Import fehlerfrei ohne Warnungen / Abbrüche durchgeführt
   [ ] Anzahl der Buchungssätze: genau 10 Sätze übernommen

   Für DATEV (Bankkonto 1200):
   [ ] Bank-Umsatz Soll (Zuflüsse / Einnahmen): € 7.850,00 geprüft
   [ ] Bank-Umsatz Haben (Abflüsse / Ausgaben): € 2.246,30 geprüft
   [ ] Saldo-Veränderung Bankkonto: + € 5.603,70 geprüft

   Für BMD NTCS (Bankkonto 2800):
   [ ] Summe positiver Beträge (Zuflüsse): € 7.850,00 geprüft
   [ ] Summe negativer Beträge (Abflüsse): € -2.246,30 geprüft
   [ ] Netto-Saldo Bankkonto: + € 5.603,70 geprüft

   Für Gegenkonten:
   [ ] Erlöse (Konto 8400) im Haben mit € 7.850,00 erfasst
   [ ] Aufwandskonten (4210, 4930 etc.) im Soll mit € 2.246,30 erfasst
   [ ] Belegdaten, Belegnummern und Buchungstexte vollständig übernommen

4. Festgestellte Abweichungen / Anmerkungen:
   _____________________________________________________________________________
   _____________________________________________________________________________

Datum: ________________________
Kanzlei / Steuerberatung: _____________________________________________________
Prüfer (Name in Druckbuchstaben): _____________________________________________
Unterschrift / Kanzleistempel: _________________________________________________
================================================================================
```
