# Repertoire & Registry of Applicable Data Processing Addenda (DPA), Agreements & Provider Chains

**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Verantwortlicher (Controller):** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Datum:** 2026-09-16  
**Status:** Реестр применимых договоров и цепочек обработки данных (актуализировано во исполнение Решения № 43 Главного Архитектора)  

---

## 1. Funktionale Trennung der Verarbeitungsketten (Separation of Pipelines)

Zur Vermeidung von Missverständnissen wird die Datenverarbeitung bei Statement2Muster strikt nach Zweck und Datenfluss in drei getrennte Pipelines unterteilt:

```
[Mandant / Kanzlei]
       │
       ├─► PIPELINE 1: Kernverarbeitung (Auszüge) ────────► [Hetzner Frankfurt (RAM / tmpfs)]
       │   (100% in Deutschland, keine Weiterleitung an Dritte, RAM-Cache TTL 600s)
       │
       ├─► PIPELINE 2: Abrechnung & Lizenzverwaltung ─────► [Stripe Payments Europe (Irland)]
       │   (Keine Auszugsdaten; nur E-Mail, Betrag, Customer ID, Sub ID)
       │
       └─► PIPELINE 3: Authentifizierung & Support ──────► [Resend & ImprovMX (USA/SCCs) -> Zielpostfach]
           (3A: OTP-Codes per Resend: nur E-Mail + 6-stelliger 10-Minuten-Code)
           (3B: Support-Anfragen per ImprovMX -> Ziel-Postfach iCloud Mail)
```

---

## 2. Detaillierter Dienstleister- und DPA-Nachweis

### A. Kernverarbeitung der Kontoauszüge (Auftragsverarbeitung gem. Art. 28 DSGVO)

#### 1. Hetzner Online GmbH
* **Unternehmenssitz:** Industriestr. 25, 91710 Gunzenhausen, Deutschland.
* **Rechenzentrumsstandort:** Frankfurt am Main, Deutschland (ISO/IEC 27001 zertifiziert).
* **Rolle:** Auftragsverarbeiter (Sub-processor) für Cloud-Infrastruktur / Rechenzentrumsbetrieb.
* **Gegenstand der Verarbeitung:** Bereitstellung des Linux-Containers für In-Memory-Parsing, Auszugsstrukturierung und flüchtigen In-Memory-Ergebnis-Cache (TTL: 600 Sekunden / 10 Minuten ab Zwischenspeicherung in `tmpfs`/RAM zur Unterstützung idempotenter Wiederholungsabrufe desselben Zielformats).
* **Verarbeitete Daten:** Hochgeladene PDF- und CSV-Auszugsdaten zur flüchtigen Konvertierung; kryptografisch signierte Sitzungstoken (RS256); Lizenzstatus.
* **Dauer der Speicherung:** 
  - Server-RAM-Cache: Maximal 600 Sekunden ab Zwischenspeicherung; danach automatische Freigabe (Garbage Collection).
  - Keine Speicherung auf Festplatten/SSDs (Zero Durable Storage).
* **Vertragliche Grundlage:** Auftragsverarbeitungsvertrag (AVV) nach Art. 28 DSGVO der Hetzner Online GmbH (Fassung gültig ab 25.05.2018 / DSGVO-konform).
* **Abschlussmethode & Status:** Elektronisch abgeschlossen im Hetzner Kundenkonto (Cloud / Robot Console).
* **Account-Bestätigung:** Account aktiv, Host `46.225.95.36`, zugeordnet dem Verantwortlichen Vitali Grecciani.
* **Drittlandübermittlung:** Keine. Die Verarbeitung erfolgt zu 100% innerhalb der Bundesrepublik Deutschland (EU).
* **Quelle:** [Hetzner Datenschutz & AVV](https://www.hetzner.com/de/legal/privacy-policy)

---

### B. Zahlungsabwicklung und Lizenzverwaltung

#### 2. Stripe Payments Europe, Ltd.
* **Unternehmenssitz:** 1 Grand Canal Street Lower, Grand Canal Dock, Dublin, D02 H210, Irland.
* **Rolle:**
  - *Eigenständiger Verantwortlicher (Independent Controller)* für PCI-DSS-Zahlungsabwicklung und Betrugsprävention.
  - *Auftragsverarbeiter (Data Processor)* für kaufmännische Kundenstammdaten und wiederkehrende Lizenzabonnements im Auftrag des Diensteanbieters.
* **Gegenstand der Verarbeitung:** Autorisierung und Abrechnung von Einmalkäufen (Lifetime) und Monatsabonnements (Starter, PRO).
* **Verarbeitete Datenkategorien:** E-Mail-Adresse des Nutzers, Rechnungsbetrag, Zahlungsmethode (Kreditkartentoken), Stripe Customer ID, Stripe Subscription ID, Transaktionszeitstempel.
* **Strikte Isolation:** Stripe erhält zu keinem Zeitpunkt Zugriff auf Kontoauszüge oder Buchungszeilen.
* **Vertragliche Grundlage:** 
  - Stripe Services Agreement (Europe)
  - Stripe Data Processing Agreement (DPA, Fassung vom 16.02.2024) inkl. Standardvertragsklauseln der EU (SCCs).
* **Abschlussmethode & Status:** Elektronisch akzeptiert bei Einrichtung und Verifizierung des Stripe Merchant Accounts (Live-Account aktiv).
* **Account-Bestätigung:** Bestätigt für Merchant Account Vitali Grecciani (Statement2Muster).
* **Quelle:** [Stripe Legal & DPA](https://stripe.com/en-at/legal/dpa)

---

### C. Authentifizierung und Kanzlei-Support

#### 3. Plus Five Five, Inc. (dba Resend)
* **Unternehmenssitz:** 2261 Market Street #5151, San Francisco, CA 94114, USA (Delaware Corporation).
* **Rolle:** Auftragsverarbeiter (Processor) für den E-Mail-Versand transaktionaler Einmalpasswörter.
* **Gegenstand der Verarbeitung:** Technische Zustellung der 6-stelligen Login-Einmalcodes (OTP) zur passwortlosen Anmeldung im Dienst.
* **Verarbeitete Datenkategorien:** Empfänger-E-Mail-Adresse, temporärer 6-stelliger Bestätigungscode (Gültigkeitsdauer: 10 Minuten), Versandzeitstempel.
* **Strikte Isolation:** Der Konvertierungspfad leitet niemals Auszugs- oder Finanzdaten an Resend weiter.
* **Vertragliche Grundlage & Drittlandübermittlung:**
  - Resend Data Processing Addendum (DPA, Fassung November 2023 / 2024) gemäß Art. 28 DSGVO.
  - Übermittlungsmechanismus: EU-Standardvertragsklauseln (Standard Contractual Clauses – SCCs, Modul 2 Controller-to-Processor bzw. Modul 3 Processor-to-Processor) nach Durchführungsbeschluss (EU) 2021/914 der Kommission gemäß Art. 46 Abs. 2 lit. c DSGVO.
* **Abschlussmethode & Status:** Elektronisch vereinbart im Rahmen der Registrierung und Erzeugung des API-Schlüssels für `statement2muster.com`.
* **Account-Bestätigung:** Resend-Produktionsaccount aktiv, API-Schlüssel konfiguriert für Domain `statement2muster.com`.
* **Quelle:** [Resend DPA](https://resend.com/legal/dpa), [Resend GDPR Info](https://resend.com/security/gdpr)

#### 4. ImprovMX Inc. & E-Mail-Support-Zielpostfach
* **Unternehmenssitz:** 2093 Philadelphia Pike #6858, Claymont, DE 19703, USA (Delaware Corporation).
* **Rolle:** Technischer Dienstleister für MX-Forwarding eingehender Support-E-Mails.
* **Gegenstand der Verarbeitung:** Weiterleitung von eingehenden E-Mails an `support@statement2muster.com` und `kontakt@statement2muster.com` an das Kanzlei-Postfach des Verantwortlichen (`vitali@grecciani.com`).
* **Vollständige Transport- und Speicherkette:**
  1. *Absender* sendet E-Mail an `support@statement2muster.com`.
  2. *ImprovMX MX-Gateway* (`mx1.improvmx.com`, `mx2.improvmx.com`, USA/EU) leitet die E-Mail per TLS-Verschlüsselung an `vitali@grecciani.com` weiter (flüchtiges Routing).
  3. *Ziel-Postfach:* Gehostet bei **Apple Inc. (iCloud Mail for Custom Domains)** mit serverseitiger TLS-Verschlüsselung und biometrisch gesichertem Zugriff (Zwei-Faktor-Authentifizierung).
* **Umgang mit freiwilligen Dateianhängen:** 
  Der reguläre Konvertierungspfad leitet niemals Auszugsdateien über E-Mail oder ImprovMX. Übersendet ein Nutzer dem Support freiwillig Beispieldateien per E-Mail zur Fehleranalyse, werden diese streng vertraulich und zweckgebunden ausschließlich zur Bearbeitung des Tickets verwendet und nach Lösung des Falls aus dem Zielpostfach gelöscht.
* **Vertragliche Grundlage:** ImprovMX Terms of Service & Privacy Policy (Stand: 2024).
* **Abschlussmethode & Status:** Elektronische Account-Einrichtung und DNS-MX-Eintragskonfiguration für die Domain `statement2muster.com`.
* **Quelle:** [ImprovMX Terms](https://improvmx.com/terms/), [ImprovMX Privacy](https://improvmx.com/transparency/privacy-policy/)

---

## 3. Clientseitige Speicherung (Chrome Extension Storage)

| Speicherort | Technologie | Gespeicherte Daten | Verweildauer & Kontrolle |
|---|---|---|---|
| **Web-Client (Landing/App)** | Browser `localStorage` | Asymmetrisch signiertes Sitzungstoken (RS256 JWT, Ablauf 10 Min.) | Wird bei Logout oder Ablauf nach 10 Min. automatisch gelöscht. |
| **Chrome Extension** | `chrome.storage.local` | `statementHistory` (bis zu 15 Einträge): Dateiname, Zeilenzahl, Gesamtsumme (`totalSum`), Zeitstempel und der **vollständige erzeugte CSV-Text** (`csvText`) | **100% lokal auf dem Rechner des Nutzers.** Bleibt über Browser-Sitzungen hinweg erhalten. Keine Übertragung an Backend-Server. Kann vom Nutzer jederzeit über die Schaltfläche „Verlauf leeren“ vollständig gelöscht werden. |

---

## 4. Verfahren zum Abschluss des AVV für Kanzleikunden (Art. 28 Abs. 9 DSGVO)

1. **Öffentliche Bereitstellung:** Der vollständige Vertragstext ist unter `https://statement2muster.com/avv` dauerhaft einsehbar.
2. **Elektronischer Abschluss (Click-Wrap):** Bei der Registrierung und Annahme der AGB wird der AVV als integraler Bestandteil der Nutzungsvereinbarung rechtswirksam elektronisch abgeschlossen.
3. **Individuelles Kanzlei-Exemplar:** Kanzleien können jederzeit ein mit ihren Kanzleidaten individualisiertes und durch Grecciani Labs digital gegengezeichnetes PDF-Exemplar für die eigene DSGVO-Verfahrensdokumentation anfordern (formlose E-Mail an `support@statement2muster.com`).

---

## 5. Erklärung des Verantwortlichen (Owner Acceptance Statement)

```text
================================================================================
BESTÄTIGUNG DES VERANTWORTLICHEN / INHABERS

Hiermit bestätige ich, Vitali Grecciani, als Inhaber von Grecciani Labs und
datenschutzrechtlich Verantwortlicher für das Projekt Statement2Muster:

1. Die in diesem Register aufgeführten Verträge und Datenschutzvereinbarungen 
   (Hetzner Online AVV, Stripe DPA, Resend DPA mit EU-Standardvertragsklauseln 
   und ImprovMX Terms) wurden für die in Produktion eingesetzten Accounts 
   wirksam elektronisch abgeschlossen und sind vollumfänglich in Kraft.

2. Die Systeme sind so konfiguriert, dass Mandanten-Auszugsdaten ausschließlich
   auf den Servern der Hetzner Online GmbH in Frankfurt am Main verarbeitet werden
   und kein Hilfsdienstleister (Stripe, Resend, ImprovMX) im regulären Betrieb
   Zugriff auf Auszugsinhalte erhält.

3. Die veröffentlichten Live-Texte auf https://statement2muster.com (Impressum,
   Datenschutz, AVV, AGB, Widerruf) entsprechen exakt den in diesem Dossier
   dokumentierten Inhalten.

Klosterneuburg, am 16.09.2026

Vitali Grecciani (Inhaber / Product Owner)
================================================================================
```
