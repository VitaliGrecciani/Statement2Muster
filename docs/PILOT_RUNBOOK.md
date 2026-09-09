# Pilot-Leitfaden & Kanzlei-Handbuch (Statement2Muster DACH)

**Version:** 1.0.2  
**Gültig für:** Deutschland & Österreich (DATEV / BMD)  
**Herausgeber:** Vitali Grecciani (Grecciani Labs)  
**Kontakt:** support@statement2muster.com  

---

## 1. Zielsetzung des Pilotbetriebs

Dieser Leitfaden richtet sich an Steuerberatungskanzleien, Wirtschaftsprüfer und Finanzbuchhaltungen im DACH-Raum, die am kontrollierten Pilotbetrieb von **Statement2Muster** teilnehmen.

Das System wandelt digitale Bank- und Kreditkartenauszüge (PDF/CSV) vollautomatisch und **100% In-Memory (Zero Retention)** in standardisierte Buchungsstapel für **DATEV Kanzlei-Rechnungswesen** und **BMD NTCS** um.

---

## 2. Unterstützte Banken & Kompatibilitätsmatrix (Freigegebene Profile)

Im Rahmen des Piloten werden ausschließlich zertifizierte Bankprofile unterstützt:

| Institut / Kartenaussteller | Dateityp | Unterstützte Währungen | Besonderheiten |
|---|---|---|---|
| **American Express** | PDF & CSV | EUR, USD, GBP, CHF | Automatische Erkennung von Abrechnungszeitraum und Kartennummer |
| **Sparkassen / VR Banken** | CSV / CAMT | EUR | Standardisiertes deutsches Banken-CSV mit Valuta/Buchungstext |
| **Wise Business** | CSV | EUR, USD, GBP, CHF | Multi-Währungs-Auszüge, Spaltenprüfung Gebühren/Nettobetrag |
| **Strukturierte Bank-CSVs** | CSV | Alle ISO 4217 | Mindestanforderung: Datum, Buchungstext, Betrag |

> [!IMPORTANT]
> **Strikte Formatvalidierung (Default-Deny)**:  
> Unvollständige, verschlüsselte oder unbekannte Dateiformate werden vom System mit dem Statuscode **HTTP 422 (UnsupportedFormatError)** abgelehnt. Es werden niemals unvollständige oder fehlerhafte Pseudo-Buchungen erzeugt.

---

## 3. Saldenabstimmung (Solldoppik Reconciliation Engine)

Statement2Muster erzwingt eine mathematische Saldenprüfung nach den Grundsätzen ordnungsmäßiger Buchführung (GoBD / BAO):

$$\text{Startsaldo} + \sum \text{Umsätze} = \text{Endsaldo}$$

### Bedeutung der Prüfstatus im Browser-Interface:

1. **`BALANCED` (Grüner Haken — Salden ausgeglichen)**:
   - Die Summe aller Einzelbuchungen stimmt centgenau mit der Differenz aus Start- und Endsaldo überein.
   - Der Buchungsstapel ist rechnerisch vollständig und kann bedenkenlos importiert werden.
2. **`DISCREPANCY` (Rotes Warnsignal — Saldenabweichung)**:
   - Es besteht eine Differenz ($\Delta \neq 0$). Typische Ursache: fehlende Seiten im Auszug oder unleserliche Scan-Zeilen.
   - **Kanzlei-Handlung**: Vor dem Import prüfen, ob alle Seiten der Monatsauszugs vorliegen.
3. **`UNVERIFIED` (Grauer Hinweis — Einzelbeleg ohne Saldo)**:
   - Bei Einzeltransaktionslisten (z.B. Kreditkarten-Umsatzübersicht ohne ausgewiesene Kontensalden) wird die rechnerische Summe gebildet, ein Saldovortrag liegt nicht vor.

---

## 4. Import-Anleitung für DATEV Kanzlei-Rechnungswesen

### Exportformat: `DATEV (EXTF 700)`

1. **Auszug konvertieren**:
   - Im Browser-Addon oder Portal die Auszüge hochladen.
   - Zielformat **DATEV (EXTF)** auswählen.
   - Auf *DATEV CSV herunterladen* klicken (erzeugt z.B. `EXTF_Auszug_*.csv`).
2. **DATEV öffnen**:
   - DATEV Kanzlei-Rechnungswesen starten und den gewünschten Mandantenbestand öffnen.
3. **Stapelverarbeitung aufrufen**:
   - Menüleiste: `Bestand` $\rightarrow$ `Importieren` $\rightarrow$ `Stapelverarbeitung`.
4. **Datei importieren**:
   - Als Quellverzeichnis den Download-Ordner angeben.
   - Die Datei `EXTF_*.csv` in der Liste markieren und auf **Einspielen / Verarbeiten** klicken.
5. **Ergebnisprüfung**:
   - Belegdatum (Format TTMM), Buchungstext (maximal 60 Zeichen), Betrag (centgenau formatiert mit Komma) und Soll/Haben-Kennzeichen (`S` für Soll, `H` für Haben) sind unmittelbar im Buchungsstapel verfügbar.

---

## 5. Import-Anleitung für BMD NTCS

### Exportformat: `BMD 5.1 CSV (Bankauszugsverbuchung)`

1. **Auszug konvertieren**:
   - Zielformat **BMD 5.1** wählen und Datei herunterladen (Dateiname: `BMD_*.csv`).
2. **BMD NTCS aufrufen**:
   - Programmteil: `Finanzbuchhaltung` $\rightarrow$ `Zahlungsverkehr` $\rightarrow$ `Bankauszugsverbuchung`.
3. **Import-Assistent ausführen**:
   - Menü: `Importieren` $\rightarrow$ Schnittstelle: *Standard Bankauszug CSV (Semikolon-getrennt)*.
   - Buchungskonto der Bank zuweisen (z.B. `2800` SKR04 bzw. `2800` Kontenrahmen Österreich).
4. **Vorerfassung & Buchung**:
   - Die Buchungszeilen werden mit Belegdatum, Text und Betrag eingelesen. Die automatische OP-Zuordnung von BMD greift auf die bereinigten Buchungstexte zu.

---

## 6. Datenschutz & Mandantenschutz (Zero-Retention-Garantie)

- **Keine Speicherung (Zero Durable Storage)**: Weder Auszugsdateien noch Buchungstexte werden auf Serverfestplatten gespeichert. Die Verarbeitung erfolgt ausschließlich im flüchtigen RAM (tmpfs).
- **Keine Datenvermischung (Anti-Mix)**: Jede Auszugsdatei wird strikt isoliert verarbeitet. Es findet kein automatisches Vermischen über unterschiedliche Mandanten oder Konten hinweg statt.
- **Serverstandort**: Frankfurt am Main, Deutschland (ISO-27001 zertifiziert).

---

## 7. Support, Fehlerbehebung & SLA im Piloten

- **E-Mail Support**: [support@statement2muster.com](mailto:support@statement2muster.com)
- **Reaktionszeit (SLA)**: Werktags innerhalb von **< 24 Stunden**.
- **Fehlermeldung (DSGVO-konform)**:
  - Bei Problemen bitte **nur** die Fehlermeldung (z.B. HTTP 422 oder Statuscode) sowie die Bank und das Auszugsformat (z.B. *Sparkasse Girokonto Monatsauszug 2026*) übermitteln.
  - **Niemals ungeschwärzte Kundendaten, IBANs oder persönliche Belege per E-Mail versenden!**
- **Rückabwicklung / Erstattung**:
  - Sollte ein Auszug eines deklarierten Profils nicht importierbar sein, erfolgt eine umgehende Fehlerbehebung oder vollständige Erstattung über das Stripe-Portal.
