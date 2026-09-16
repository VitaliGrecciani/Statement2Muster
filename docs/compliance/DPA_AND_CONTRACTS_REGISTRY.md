# Repertoire & Registry of Applicable Data Processing Addenda (DPA) & Legal Frameworks

**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Verantwortlicher (Controller):** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Datum:** 2026-09-16  
**Status:** Реестр применимых договоров и цепочек обработки данных (во исполнение Решения № 42 Главного Архитектора)  

---

## 1. Funktionale Trennung der Verarbeitungsketten (Separation of Processing Pipelines)

Zur Vermeidung irreführender Pauschalaussagen wird die Datenverarbeitung bei Statement2Muster streng nach fachlichen Vorgängen und Datenflüssen in drei voneinander getrennte Pipelines unterteilt:

```
[Mandant / Nutzer]
       │
       ├─► PIPELINE A: Kernverarbeitung (Auszüge) ────────► [Hetzner Frankfurt (RAM / tmpfs)]
       │   (Keine Weiterleitung an Dritte, TTL 600s)
       │
       ├─► PIPELINE B: Lizenzierung & Zahlungen  ────────► [Stripe Ireland (Kaufmännisch)]
       │   (Keine Auszugsdaten, nur E-Mail/Betrag/Sub-ID)
       │
       └─► PIPELINE C: Authentifizierung & Support ──────► [Resend & ImprovMX (USA/SCCs)]
           (Nur E-Mail & 6-stelliger 10-Min-OTP-Code)
```

---

## 2. Detaillierter Dienstleister- und DPA-Nachweis

### A. Kernverarbeitung der Kontoauszüge (Auftragsverarbeitung gem. Art. 28 DSGVO)

#### 1. Hetzner Online GmbH
* **Unternehmenssitz:** Industriestr. 25, 91710 Gunzenhausen, Deutschland.
* **Rechenzentrumsstandort:** Frankfurt am Main, Deutschland (ISO/IEC 27001 zertifiziert).
* **Rolle im Sinne der DSGVO:** Auftragsverarbeiter (Sub-processor) für die Bereitstellung der Cloud-Infrastruktur.
* **Gegenstand der Verarbeitung:** Bereitstellung des Linux-Containers für In-Memory-Parsing, Auszugsstrukturierung und flüchtigen In-Memory-Ergebnis-Cache (TTL: 600 Sekunden / 10 Minuten in `tmpfs`/RAM).
* **Verarbeitete Datenkategorien:** Hochgeladene PDF- und CSV-Auszugsdaten zur flüchtigen Konvertierung; kryptografisch signierte Sitzungstoken (RS256); Lizenzstatus.
* **Dauer der Speicherung:** 
  - Auszugsinhalte: Maximal 600 Sekunden im flüchtigen RAM-Cache (zur Ermöglichung des Mehrfach-Downloads ohne erneuten Upload); danach automatische und rückstandslose Löschung.
  - Keine Speicherung auf Festplatten/SSDs (Zero Durable Storage).
* **Vertragliche Grundlage:** Auftragsverarbeitungsvertrag (AVV) nach Art. 28 DSGVO der Hetzner Online GmbH.
* **Abschlussmethode:** Elektronischer Abschluss im Rahmen der Account-Verwaltung in der Hetzner Konsole (Robot / Cloud).
* **Drittlandübermittlung:** Keine. Die Verarbeitung erfolgt zu 100% innerhalb der Bundesrepublik Deutschland (EU).
* **Nachweis & Quelle:** [Hetzner Datenschutz & AVV](https://www.hetzner.com/de/legal/privacy-policy)

---

### B. Zahlungsabwicklung und Lizenzverwaltung

#### 2. Stripe Payments Europe, Ltd.
* **Unternehmenssitz:** 1 Grand Canal Street Lower, Grand Canal Dock, Dublin, D02 H210, Irland.
* **Rolle im Sinne der DSGVO:**
  - *Eigenständiger Verantwortlicher (Independent Controller)* für die Verarbeitung sensibler Kreditkarten- und PCI-DSS-Zahlungsdaten sowie die Geldwäsche- und Betrugsprävention.
  - *Auftragsverarbeiter (Data Processor)* für die Verwaltung kaufmännischer Kundenstammdaten und wiederkehrender Lizenzabonnements im Auftrag des Diensteanbieters.
* **Gegenstand der Verarbeitung:** Autorisierung und Abrechnung von Einmalkäufen (Lifetime) und Monatsabonnements (Starter, PRO).
* **Verarbeitete Datenkategorien:** E-Mail-Adresse des Nutzers, Name, Zahlungsmethode (Kreditkartentoken), Zahlungsbetrag, Stripe Customer ID, Stripe Subscription ID, Transaktionszeitstempel.
* **Strikte Trennung:** Stripe erhält zu keinem Zeitpunkt Zugriff auf Kontoauszüge, Transaktionszeilen oder Buchungsdaten der Kunden.
* **Vertragliche Grundlage:** 
  - Stripe Services Agreement (Europe)
  - Stripe Data Processing Agreement (DPA) inkl. Standardvertragsklauseln der EU (SCCs).
* **Abschlussmethode:** Elektronischer Klick-Vertrag bei Einrichtung und Verifizierung des Stripe Merchant Accounts.
* **Nachweis & Quelle:** [Stripe Legal & DPA](https://stripe.com/en-at/legal/dpa)

---

### C. Authentifizierung und Kanzlei-Support

#### 3. Plus Five Five, Inc. (dba Resend)
* **Unternehmenssitz:** 2261 Market Street #5151, San Francisco, CA 94114, USA (Delaware Corporation).
* **Rolle im Sinne der DSGVO:** Auftragsverarbeiter (Processor) für den E-Mail-Versand transaktionaler Einmalpasswörter.
* **Gegenstand der Verarbeitung:** Technische Zustellung der 6-stelligen Login-Einmalcodes (OTP) zur passwortlosen Anmeldung im Dienst.
* **Verarbeitete Datenkategorien:** Empfänger-E-Mail-Adresse, temporärer 6-stelliger Bestätigungscode (automatische Gültigkeitsdauer: 10 Minuten), Versandzeitstempel.
* **Strikte Trennung:** Resend verarbeitet keinerlei Bankdaten, Auszüge oder Buchungsinhalte.
* **Vertragliche Grundlage & Drittlandübermittlung:**
  - Resend Data Processing Addendum (DPA) gemäß Art. 28 DSGVO.
  - Übermittlungsmechanismus: EU-Standardvertragsklauseln (Standard Contractual Clauses – SCCs, Modul 2 Controller-to-Processor bzw. Modul 3 Processor-to-Processor) nach Durchführungsbeschluss (EU) 2021/914 der Kommission gemäß Art. 46 Abs. 2 lit. c DSGVO.
* **Abschlussmethode:** Elektronische Einbeziehung im Rahmen der Registrierung und API-Nutzung (Terms of Service & DPA).
* **Nachweis & Quelle:** [Resend DPA](https://resend.com/legal/dpa), [Resend GDPR Information](https://resend.com/security/gdpr)

#### 4. ImprovMX Inc.
* **Unternehmenssitz:** 2093 Philadelphia Pike #6858, Claymont, DE 19703, USA (Delaware Corporation).
* **Rolle im Sinne der DSGVO:** Technischer Dienstleister für das MX-Forwarding geschäftlicher Kontaktanfragen.
* **Gegenstand der Verarbeitung:** Weiterleitung von eingehenden E-Mails an `support@statement2muster.com` und `kontakt@statement2muster.com` an das Kanzlei-Postfach des Verantwortlichen (`vitali@grecciani.com`).
* **Verarbeitete Datenkategorien:** Absender-E-Mail, Betreff und Inhalt von freiwillig durch Nutzer übersandten Support-Anfragen.
* **Strikte Trennung:** ImprovMX ist rein für E-Mail-Kommunikation konfiguriert; Auszugsdateien für die Konvertierung laufen niemals über E-Mail oder ImprovMX.
* **Vertragliche Grundlage:** ImprovMX Terms of Service & Privacy Policy.
* **Abschlussmethode:** Elektronische Account-Erstellung und DNS-MX-Eintragskonfiguration für die Domain `statement2muster.com`.
* **Nachweis & Quelle:** [ImprovMX Privacy Policy](https://improvmx.com/transparency/privacy-policy/), [ImprovMX Terms](https://improvmx.com/terms/)

---

## 3. Clientseitige Speicherung (Chrome Extension Storage)

Zur vollständigen Transparenz gegenüber Nutzern und Datenschutzbehörden wird das clientseitige Speicherverhalten der Browser-Erweiterung gesondert ausgewiesen:

| Speicherort | Technologie | Gespeicherte Daten | Zweck | Speicherort & Kontrolle |
|---|---|---|---|---|
| **Web-Client (Landing/App)** | Browser `localStorage` | Asymmetrisch signiertes Sitzungstoken (RS256 JWT, Ablauf 10 Min.) | Authentifizierung aktiver API-Anfragen | Verbleibt im lokalen Browser des Nutzers; wird bei Logout oder Token-Ablauf gelöscht |
| **Chrome Extension** | `chrome.storage.local` | `statementHistory`: Dateiname, Zeilenzahl, Zeitstempel, lokales Vorschau-Objekt | Bedienkomfort: Anzeige der zuletzt konvertierten Auszüge im Sidepanel | **100% lokal auf dem Gerät des Nutzers.** Keine Übertragung an Backend-Server. Kann vom Nutzer jederzeit über die Schaltfläche „Verlauf leeren“ vollständig gelöscht werden. |

---

## 4. Verfahren zum Abschluss des AVV für Kanzleikunden

Für Kanzleien und Unternehmen (B2B), die Statement2Muster für Mandantenauszüge einsetzen, gilt folgender standardisierter Ablauf gemäß Art. 28 Abs. 9 DSGVO:
1. **Veröffentlichung:** Der vollständige AVV-Text ist unter `https://statement2muster.com/avv` dauerhaft und öffentlich abrufbar.
2. **Vertragsschluss:** Mit Registrierung und Zustimmung zu den AGB / Nutzungsbedingungen wird der AVV als verbindlicher Bestandteil des Hauptvertrages elektronisch geschlossen.
3. **Kanzlei-Exemplar:** Auf Wunsch stellt der Auftragnehmer ein mit den Kanzleidaten individualisiertes und digital signiertes PDF-Exemplar für die DSGVO-Verfahrensdokumentation der Kanzlei bereit (Anforderung per formloser E-Mail an `support@statement2muster.com`).
