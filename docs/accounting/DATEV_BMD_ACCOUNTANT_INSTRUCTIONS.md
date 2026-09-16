# Leitfaden für den Steuerberater: DATEV & BMD Importprüfung

**Projekt:** Statement2Muster DACH  
**Zweck:** Fachliche Abnahme und Importvalidierung von generierten Buchungsstapeln (DATEV EXTF 700 & BMD NTCS)  
**Datum:** 2026-09-16  

---

## 🇷🇺 Краткая инструкция для Product Owner (Виталия)

Для получения финального вердикта **Full GO** от Главного Архитектора необходимо передать реальному бухгалтеру или налоговому консультанту (Steuerberater) подготовленный тестовый комплект из папки:
`docs/accounting/samples/`:
1. `EXTF_DATEV_Buchungsstapel.csv` — файл для импорта в **DATEV Rechnungswesen** (Германия / Австрия).
2. `BMD_NTCS_Buchungen.csv` — файл для импорта в **BMD NTCS** (Австрия).
3. `sample_bank_statement.csv` — исходная синтетическая выписка банка (10 транзакций) для сверки.

**Что требуется от бухгалтера:**
1. Загрузить файл в свою программу через стандартное меню импорта (см. немецкую инструкцию ниже).
2. Убедиться, что программа принимает файл без синтаксических ошибок и блокировок.
3. Подтвердить одной строкой (sign-off): *«Импорт файла EXTF_DATEV_Buchungsstapel.csv в DATEV прошел успешно, 10 проводок созданы корректно»* (или аналогично для BMD).

---

## 🇩🇪 Anleitung für die Steuerberatungskanzlei / den Buchhalter

Sehr geehrte Damen und Herren,

im Rahmen der Qualitätssicherung unseres Auszugskonverters **Statement2Muster** möchten wir Sie bitten, die beiliegenden Testdateien in Ihrer Kanzleisoftware (**DATEV** bzw. **BMD NTCS**) zu importieren und die Fehlerfreiheit des Imports kurz zu bestätigen.

### 1. Prüfpaket (Beispieldaten)
Im Ordner `docs/accounting/samples/` finden Sie 10 synthetische Geschäftsvorfälle aus dem Monat Januar 2026:
- 3 Erlöse / Kundenzahlungen (€ 4.250,00, € 2.100,00, € 1.500,00)
- 7 betriebliche Aufwendungen (Büromiete, Hetzner-Server, Softwarelizenz, Bürobedarf, Telekommunikation, Marketing, Kontoführung)
- **Gesamtsaldo:** Bankkonto 1200 / 2800 schließt exakt ab.

---

### 2. Import in DATEV Rechnungswesen (Deutschland / Österreich)

* **Datei:** `EXTF_DATEV_Buchungsstapel.csv`
* **Format:** Offizielles DATEV-Format **EXTF Version 700** (Format-Kategorie 21, Buchungsstapel).
* **Zeichensatz:** ANSI / Windows-1252 (mit Semikolon als Trennzeichen).
* **Voreingestellte Konten:**
  - Bankkonto: `1200` (SKR03) bzw. anpassbar im Kanzleikontenrahmen.
  - Gegenkonten: `8400` (Erlöse), `4210` (Miete), `4930` (IT/Software), `4980` (Bürobedarf), `4920` (Telefon), `4600` (Werbung), `4970` (Bankspesen).
  - Beraternummer: `1001`, Mandantennummer: `10001` (kann im DATEV-Importdialog Ihrem Testmandanten zugewiesen werden).

**Schritte in DATEV Rechnungswesen:**
1. Mandantenbestand öffnen.
2. Menü: **Bestand ➔ Importieren ➔ Stapelverarbeitung** (oder *Stapelverarbeitung ➔ Importieren*).
3. Quellverzeichnis auswählen und Datei `EXTF_DATEV_Buchungsstapel.csv` markieren.
4. Auf **Importieren** klicken.
5. In der Stapelübersicht den neu importierten Stapel auswählen und auf **Einspielen / Öffnen** klicken.
6. **Erwartetes Ergebnis:** 10 Buchungssätze werden fehlerfrei eingelesen.

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
3. Datei `BMD_NTCS_Buchungen.csv` auswählen.
4. **Erwartetes Ergebnis:** Die 10 Zeilen werden übernommen, Beträge und Belegtexte sind den Buchungszeilen korrekt zugeordnet.

---

### 4. Kanzlei-Bestätigung (Sign-Off Vorlage)

Nach erfolgtem Probeimport genügt eine kurze Rückmeldung per E-Mail an `support@statement2muster.com` oder direkt an Herrn Vitali Grecciani nach folgendem Muster:

```text
===================================================================
BESTÄTIGUNG DER IMPORTFÄHIGKEIT (STATEMENT2MUSTER)

Hiermit bestätige ich, dass die Testdatei:
[X] EXTF_DATEV_Buchungsstapel.csv in DATEV Rechnungswesen
[ ] BMD_NTCS_Buchungen.csv in BMD NTCS

in der Version: _______________________________ (z. B. DATEV 14.x / BMD NTCS)
erfolgreich und ohne Fehlermeldungen importiert werden konnte.

Die Buchungssätze (Belegdatum, Umsatz, Soll/Haben-Zuordnung, 
Konto/Gegenkonto und Buchungstext) wurden ordnungsgemäß übernommen.

Datum: ________________________
Kanzlei / Name: _____________________________________________
Unterschrift / Kurzzeichen: _________________________________
===================================================================
```
