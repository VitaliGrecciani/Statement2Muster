# Leitfaden für den Steuerberater: DATEV & BMD Importprüfung

**Projekt:** Statement2Muster DACH  
**Zweck:** Fachliche Abnahme und Importvalidierung von generierten Buchungsstapeln (DATEV EXTF 700 & BMD NTCS)  
**Datum:** 2026-09-16  
**Anforderung:** Gemäß Решение № 42 des Hauptarchitekten  

---

## 🇷🇺 Инструкция для Product Owner (Виталия)

Для получения финального вердикта **Full GO** передайте реальному бухгалтеру или налоговому консультанту (Steuerberater) тестовый комплект из папки `docs/accounting/samples/`:
1. `EXTF_DATEV_Buchungsstapel.csv` (для DATEV Rechnungswesen)
2. `BMD_NTCS_Buchungen.csv` (для BMD NTCS)
3. `sample_bank_statement.csv` (исходная синтетическая выписка банка)

**Что требуется от бухгалтера для закрытия аудита:**
Бухгалтер должен заполнить форму в разделе 4 (Sign-Off):
* Указать программу и версию (например, *DATEV Rechnungswesen V. 14.2*);
* Подтвердить число проводок (**10 из 10**);
* Сверить контрольные суммы: **Haben € 7.850,00**, **Soll € 2.246,30**, **Сальдо € +5.603,70**;
* Подтвердить корректность разноски по счетам (банк `1200`/`2800` против контрагентов);
* Поставить дату, имя и подпись / название канцелярии.

---

## 🇩🇪 Anleitung für die Steuerberatungskanzlei / den Buchhalter

Sehr geehrte Damen und Herren,

im Rahmen der Qualitätssicherung unseres Auszugskonverters **Statement2Muster** möchten wir Sie bitten, die beiliegenden Testdateien in Ihrer Kanzleisoftware (**DATEV** bzw. **BMD NTCS**) zu importieren und die rechnerische und fachliche Richtigkeit der Buchungssätze kurz zu bestätigen.

### 1. Prüfpaket & Soll-Werte zur rechnerischen Abstimmung

Im Ordner `docs/accounting/samples/` finden Sie 10 synthetische Geschäftsvorfälle aus dem Monat Januar 2026. Bitte gleichen Sie die importierten Buchungen mit folgenden Kontrollwerten ab:

| Kennzahl | Erwarteter Soll-Wert | Beschreibung / Konten |
|---|---|---|
| **Anzahl Buchungssätze** | **10** | 3 Haben-Buchungen (Erlöse), 7 Soll-Buchungen (Aufwand) |
| **Summe Haben (Umsatz Plus)** | **€ 7.850,00** | Kundenzahlungen & Erlöse (Gegenkonto 8400) |
| **Summe Soll (Umsatz Minus)** | **€ 2.246,30** | Miete (4210), IT (4930), Büro (4980), Telekom (4920), Marketing (4600), Spesen (4970) |
| **Netto-Veränderung / Saldo** | **€ +5.603,70** | Saldo Bankkonto 1200 (DATEV) bzw. 2800 (BMD) |

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

### 4. Kanzlei-Bestätigung (Sign-Off Vorlage gem. Решение № 42)

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
   [ ] Haben-Umsatzsumme geprüft: € 7.850,00 (stimmt überein)
   [ ] Soll-Umsatzsumme geprüft: € 2.246,30 (stimmt überein)
   [ ] Saldo-Veränderung geprüft: € +5.603,70 (stimmt überein)
   [ ] Konten und Gegenkonten sachgerecht zugeordnet
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
