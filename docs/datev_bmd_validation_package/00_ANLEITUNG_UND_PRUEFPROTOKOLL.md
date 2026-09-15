# Statement2Muster — Prüfanleitung & Abnahmeprotokoll für Steuerberater / Buchhalter

**Dokument-ID:** S2M-VAL-2026-00  
**Gegenstand:** Externe Validierung des DATEV EXTF 700 & BMD NTCS 5.1 Exports  
**Software-Release:** Statement2Muster Beta v1.0.3  
**Zielgruppe:** Steuerberater, Wirtschaftsprüfer, Bilanzbuchhalter, Kanzleimitarbeiter  
**Datum:** September 2026  

---

## 1. Überblick & Zielsetzung

Dieses Prüfpaket wurde erstellt, um die von **Statement2Muster** generierten Buchungsstapel auf hundertprozentige Kompatibilität mit den in Deutschland und Österreich führenden Kanzleisystemen (**DATEV Kanzlei-Rechnungswesen** und **BMD NTCS 5.1**) zu überprüfen.

### Inhalt dieses Prüfpakets:
1. `01_SYNTHETIC_INPUTS/`: Die synthetischen Quelldateien (Bankkonto Sparkasse & Amex Kreditkarte) als Nachweis der Rohdaten.
2. `02_DATEV_EXTF_EXPORTS/`: Vier DATEV-konforme Buchungsstapel im Format **EXTF 700 (Kategorie 21, Version 12)** für SKR03 und SKR04 (Windows-1252 ANSI, CRLF).
3. `03_BMD_NTCS_EXPORTS/`: Zwei BMD NTCS-konforme Buchungsstapel im Format **Satzart 0 Bankauszugsverbuchung** (Windows-1252 ANSI, CRLF).
4. `04_KONTROLLSUMMEN_UND_BUCHUNGSLISTE.md`: Das vollständige Abstimmungsblatt mit allen Soll-/Haben-Kontrollsummen und Einzelbuchungszeilen.

---

## 2. Import-Anleitung: DATEV Kanzlei-Rechnungswesen

### Voraussetzungen:
* DATEV Kanzlei-Rechnungswesen ab Version 10.x / 11.x / 12.x / 13.x.
* Ein Testmandant (oder bestehender Mandant) mit Kontenrahmen **SKR03** oder **SKR04**.
* Das Wirtschaftsjahr **2026** muss im Mandanten angelegt sein (oder die Buchungsperiode Januar 2026).

### Schritt-für-Schritt Ablauf:
1. **Datei auswählen:**
   * Für SKR03: Wählen Sie `02_DATEV_EXTF_EXPORTS/EXTF_Sparkasse_Januar2026_SKR03_1200.csv` (bzw. Amex `...SKR03_1210.csv`).
   * Für SKR04: Wählen Sie `02_DATEV_EXTF_EXPORTS/EXTF_Sparkasse_Januar2026_SKR04_1800.csv` (bzw. Amex `...SKR04_1810.csv`).
2. **DATEV Stapelverarbeitung öffnen:**
   * Klicken Sie im DATEV-Menü auf:  
     `Bestand -> Importieren -> Stapelverarbeitung`  
     *(Alternativ: `Erfassen -> Belege buchen -> Buchungsstapel importieren`)*.
3. **Quellverzeichnis & Format einstellen:**
   * Wählen Sie als Datenformat: **DATEV-Format**.
   * Wählen Sie den Ordner mit den obigen `.csv`-Dateien aus.
4. **Prüflauf durchführen (Formatprüfer):**
   * Markieren Sie den Buchungsstapel in der Liste und klicken Sie auf **Prüfen** (bzw. Vorschau).
   * **Erwartetes Ergebnis:** 0 Fehler. Der DATEV-Formatprüfer muss die Datei ohne Syntax- oder Strukturfehler akzeptieren.
5. **Stapel importieren:**
   * Klicken Sie auf **Importieren**. Der Stapel wird in die Buchungserfassung übernommen.
6. **Kontrollsummen abgleichen:**
   * Öffnen Sie den importierten Stapel unter `Belege buchen`.
   * Vergleichen Sie die im Stapel angezeigten Summen für **Soll** und **Haben** mit den Werten aus Dokument `04_KONTROLLSUMMEN_UND_BUCHUNGSLISTE.md`.

---

## 3. Import-Anleitung: BMD NTCS 5.1

### Voraussetzungen:
* BMD NTCS ab Version 5.1 (Österreichischer Standard-Kontenrahmen).
* Mandant mit Wirtschaftsjahr **2026**.

### Schritt-für-Schritt Ablauf:
1. **Datei auswählen:**
   * Wählen Sie `03_BMD_NTCS_EXPORTS/BMD_Sparkasse_Januar2026_Konto2800.csv` (bzw. `BMD_Amex_Januar2026_Konto2810.csv`).
2. **Importmaske öffnen:**
   * Navigieren Sie zu:  
     `Finanzbuchung -> Bankauszugsverbuchung -> Import (Satzart 0)`  
     *(bzw. `Fibu-Import / Externe Buchungsdaten`)*.
3. **Parameter prüfen:**
   * Feldtrennzeichen: Semikolon (`;`)
   * Textbegrenzungszeichen: Doppelte Anführungszeichen (`"`)
   * Zeichensatz: Windows-ANSI (Windows-1252)
4. **Import ausführen:**
   * Starten Sie den Einlesevorgang.
   * Überprüfen Sie, ob alle Zeilen fehlerfrei eingelesen wurden.
5. **Kontrollsummen abgleichen:**
   * Kontrollieren Sie Saldo und Einzelzeilen gegen Dokument `04_KONTROLLSUMMEN_UND_BUCHUNGSLISTE.md`.

---

## 4. Die 6 Kern-Prüfpunkte (Audit-Checkliste)

| Nr. | Prüfkriterium | Erwartung / Soll-Zustand | Ergebnis (OK / Fehler) |
| :---: | :--- | :--- | :---: |
| **1** | **Importfähigkeit & Syntax** | Fehlerfreier Import ohne Syntaxabbruch im Kanzleisystem. | [  ] OK  /  [  ] Fehler |
| **2** | **Zeichensatz & Umlaute** | Deutsche Umlaute (ä, ö, ü, ß) und Sonderzeichen werden einwandfrei dargestellt (keine `Ã¤` oder Fragezeichen). | [  ] OK  /  [  ] Fehler |
| **3** | **Datum & Periodenzuordnung** | Belegdaten liegen im Januar 2026 (DATEV: `0501`, `0801` etc.; BMD: `05.01.2026`). Keine Verschiebung von Monat/Tag. | [  ] OK  /  [  ] Fehler |
| **4** | **Vorzeichen & Soll/Haben-Logik** | Gutschriften auf Bankkonto im **Soll (S)**, Lastschriften im **Haben (H)**. BMD-Vorzeichen (+/-) rechnerisch korrekt. | [  ] OK  /  [  ] Fehler |
| **5** | **Kontrollsummen-Abstimmung** | Rechnerische Soll-/Haben-Summen stimmen auf den Cent genau mit dem Abstimmungsblatt (Dokument 04) überein. | [  ] OK  /  [  ] Fehler |
| **6** | **Feldzuordnung (Beleg / Text)** | Rechnungsnummern in `Belegfeld 1` / `Belegnummer`. Partner & Zweck sauber in `Buchungstext` / `Text`. | [  ] OK  /  [  ] Fehler |

---

## 5. Offizielles Freigabe- und Abnahmeprotokoll (Sign-off)

*Bitte nach Durchführung des Imports vom prüfenden Steuerberater / Buchhalter ausfüllen lassen:*

| Feld | Angabe durch Prüfer |
| :--- | :--- |
| **Prüfende Person (Name, Vorname):** | __________________________________________________ |
| **Kanzlei / Unternehmen:** | __________________________________________________ |
| **Berufsbezeichnung:** | [  ] Steuerberater(in)  [  ] Wirtschaftsprüfer(in)  [  ] Bilanzbuchhalter(in) |
| **Eingesetzte Software & Version:** | DATEV Kanzlei-ReWe Version: _________ / BMD NTCS Version: _________ |
| **Datum der Prüfung:** | ____.____.2026 |

### Gesamturteil der Validierung:
[  ] **FREIGEGEBEN (GO):** Die Exportdateien entsprechen vollständig den Formatanforderungen der Kanzleisoftware und können für den produktiven Produktiveinsatz freigegeben werden.  
[  ] **NACHBESSERUNG ERFORDERLICH (NO-GO):** Es traten Abweichungen oder Importfehler auf (Details siehe Bemerkungen unten).

### Bemerkungen / Verbesserungsvorschläge des Prüfers:
__________________________________________________________________________________________  
__________________________________________________________________________________________  
__________________________________________________________________________________________  

<br><br>
___________________________________________ &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ___________________________________________  
**Ort, Datum** &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; **Unterschrift / Kanzleistempel**
