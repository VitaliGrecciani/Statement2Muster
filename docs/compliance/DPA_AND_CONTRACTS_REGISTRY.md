# Repertoire & Registry of Applicable Data Processing Addenda (DPA), Agreements & Provider Chains

**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Verantwortlicher (Controller):** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Datum:** 2026-09-17  
**Status:** Реестр применимых договоров и цепочек обработки данных (актуализировано во исполнение Решения № 46 Главного Архитектора — отражение zweiseitig unterzeichneten ImprovMX DPA и реального целевого ящика Google DPF `vitogr24@gmail.com`)  

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
       └─► PIPELINE 3: Authentifizierung & Support ──────► [Resend, ImprovMX & Google]
           (3A: OTP-Codes per Resend: nur E-Mail + 6-stelliger 10-Minuten-Code, DPA 27.08.2026)
           (3B: Support-Routing & Postfach support@statement2muster.com:
                ImprovMX MX Relay [DPA 09.09.2026, SCCs] ──► Google [vitogr24@gmail.com, DPF / SCCs])
```

---

## 2. Detaillierter Dienstleister- und DPA-Nachweis

### A. Kernverarbeitung der Kontoauszüge (Auftragsverarbeitung gem. Art. 28 DSGVO)

#### 1. Hetzner Online GmbH
* **Unternehmenssitz:** Industriestr. 25, 91710 Gunzenhausen, Deutschland.
* **Rechenzentrumsstandort:** Frankfurt am Main, Deutschland (ISO/IEC 27001 zertifiziert).
* **Rolle:** Auftragsverarbeiter (Sub-processor) für Cloud-Infrastruktur und Rechenzentrumsbetrieb.
* **Gegenstand der Verarbeitung:** Bereitstellung des Linux-Containers für In-Memory-Parsing, Auszugsstrukturierung und flüchtigen In-Memory-Ergebnis-Cache (TTL: 600 Sekunden / 10 Minuten ab Zwischenspeicherung in `tmpfs`/RAM zur Unterstützung idempotenter Wiederholungsabrufe desselben Zielformats ohne erneuten Parsing-Aufwand und ohne Kontingentverlust).
* **Verarbeitete Daten:** Hochgeladene PDF- und CSV-Auszugsdaten zur flüchtigen Konvertierung; kryptografisch signierte Sitzungstoken (RS256); Lizenzstatus.
* **Dauer der Speicherung:** 
  - Server-RAM-Cache: Maximal 600 Sekunden ab Zwischenspeicherung; danach automatische Freigabe durch das System (Memory Deallocation / Garbage Collection).
  - Keine Speicherung von Auszugsinhalten auf Festplatten/SSDs (Zero Durable Storage).
* **Vertragliche Grundlage:** Auftragsverarbeitungsvertrag (AVV) nach Art. 28 DSGVO der Hetzner Online GmbH (DSGVO-konforme Fassung).
* **Abschlussmethode & Status:** Elektronisch abgeschlossen im Hetzner Kundenkonto (Cloud / Robot Console).
* **Account-Bestätigung:** Account aktiv, Host `46.225.95.36`, zugeordnet dem Verantwortlichen Vitali Grecciani.
* **Drittlandübermittlung:** Keine. Die gesamte Verarbeitung und Speicherung erfolgt zu 100% innerhalb der Bundesrepublik Deutschland (EU).
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

### C. Authentifizierung (OTP)

#### 3. Plus Five Five, Inc. (dba Resend)
* **Unternehmenssitz:** 2261 Market Street #5151, San Francisco, CA 94114, USA (Delaware Corporation).
* **Rolle:** Auftragsverarbeiter (Processor) für den E-Mail-Versand transaktionaler Einmalpasswörter.
* **Gegenstand der Verarbeitung:** Technische Zustellung der 6-stelligen Login-Einmalcodes (OTP) zur passwortlosen Anmeldung im Dienst.
* **Verarbeitete Datenkategorien:** Empfänger-E-Mail-Adresse, temporärer 6-stelliger Bestätigungscode (Gültigkeitsdauer: 10 Minuten), Versandzeitstempel.
* **Strikte Isolation:** Der Konvertierungspfad leitet niemals Auszugs- oder Finanzdaten an Resend weiter.
* **Exakte Vertragsfassung & Übermittlungsmechanismus:**
  - **Offizielle Fassung:** *Resend Data Processing Addendum (DPA)* — **Last update: August 27th, 2026** (verfügbar unter: `https://resend.com/legal/dpa`).
  - **Rechtsgrundlage:** Art. 28 DSGVO (Auftragsverarbeitung).
  - **Übermittlungsmechanismus:** Standard Contractual Clauses (SCCs) gemäß Durchführungsbeschluss (EU) 2021/914 der Kommission (Modul 2 Controller-to-Processor und Modul 3 Processor-to-Processor) nach Art. 46 Abs. 2 lit. c DSGVO.
* **Abschlussmethode & Status:** Elektronisch vereinbart im Rahmen der Registrierung des Produktionskontos und Erzeugung des API-Schlüssels für die Domain `statement2muster.com`.
* **Account-Bestätigung:** Resend-Produktionsaccount aktiv, API-Schlüssel konfiguriert für Domain `statement2muster.com`.
* **Quelle:** [Resend DPA (August 27th, 2026)](https://resend.com/legal/dpa), [Resend GDPR Info](https://resend.com/security/gdpr)

---

### D. E-Mail-Routing & Support-Postfach (Inbound MX & Zielpostfach)

#### 4. ImprovMX Inc. (MX-Relay / E-Mail-Weiterleitung)
* **Unternehmenssitz:** 2093 Philadelphia Pike #6858, Claymont, DE 19703, USA (Delaware Corporation).
* **Rolle:** Auftragsverarbeiter (Data Processor) für das Inbound-MX-Routing geschäftlicher E-Mails an `support@statement2muster.com`.
* **Gegenstand der Verarbeitung:** Entgegennahme eingehender SMTP-Nachrichten an die Domain `statement2muster.com` über autoritative MX-Gateways und Weiterleitung an das Zielpostfach des Verantwortlichen.
* **Verarbeitete Datenkategorien:** E-Mail-Metadaten (Absender, Empfänger, Zeitstempel, Betreff), Nachrichteninhalt sowie ggf. freiwillig vom Nutzer beigefügte Support-Anhänge.
* **Strikte Isolation:** Der Konvertierungspfad der Web-Applikation leitet niemals Kontoauszüge an ImprovMX weiter. Freiwillig per E-Mail übersandte Beispieldateien werden streng zweckgebunden zur Ticketbeantwortung genutzt und nach Klärung gelöscht.
* **Vertragliche Grundlage & Übermittlungsmechanismus:**
  - **Offizielle Fassung:** *ImprovMX Data Processing Agreement (DPA)* — **Datum: 9. September 2026** (Standard-DPA von ImprovMX Inc.).
  - **Zweiseitige Unterzeichnung:** Rechtswirksam bilateral gezeichnet durch Matthew Tse (CEO ImprovMX Inc., New York) und Vitali Grecciani (Inhaber Grecciani Labs).
  - **PDF-Dokumentnachweis:** Vollständig gezeichnetes Exemplar hinterlegt im Repository unter [`docs/compliance/improvmx_dpa_signed.pdf`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/improvmx_dpa_signed.pdf) (143.205 Bytes).
  - **Übermittlungsmechanismus:** Standard Contractual Clauses (SCCs) der Europäischen Union gemäß Art. 46 Abs. 2 lit. c DSGVO.
* **Autoritative DNS-Konfiguration (Vercel DNS `ns1.vercel-dns.com`):**
  - `MX 10 mx1.improvmx.com.`
  - `MX 20 mx2.improvmx.com.`
  - `TXT "v=spf1 include:spf.improvmx.com ~all"`
* **Quelle:** [ImprovMX DPA](https://improvmx.com/dpa/)

#### 5. Google Ireland Limited / Google LLC (Zielpostfach des Verantwortlichen)
* **Unternehmenssitz:** Gordon House, Barrow Street, Dublin 4, Irland (Google Ireland Limited) / 1600 Amphitheatre Parkway, Mountain View, CA 94043, USA (Google LLC).
* **Rolle:** Auftragsverarbeiter / E-Mail-Diensteanbieter für das persönliche geschäftliche Zielpostfach des Verantwortlichen (`vitogr24@gmail.com`).
* **Gegenstand der Verarbeitung:** Empfang, dauerhafte Entgegennahme, Anzeige und Bearbeitung weitergeleiteter Support-Anfragen durch den Verantwortlichen.
* **Verarbeitete Datenkategorien:** Support-E-Mails von Nutzern an `support@statement2muster.com` (Absenderadresse, Betreff, Nachrichtentext, freiwillige Anhänge).
* **Rechtsgrundlage & Übermittlungsmechanismus:**
  - Google Nutzungsbedingungen & Google Datenschutzerklärung.
  - Zertifizierung unter dem **EU-U.S. Data Privacy Framework (DPF)** gemäß Angemessenheitsbeschluss der EU-Kommission (Art. 45 DSGVO) für Google LLC sowie EU-Standardvertragsklauseln (SCCs) gem. Art. 46 DSGVO.
  - Sicherheitsniveau: Transportverschlüsselung mit TLS 1.3 / TLS 1.2, Zwei-Faktor-Authentifizierung (2FA / Security Key) und strikter Zugriffsschutz des Inhabers.
* **Quelle:** [Google Privacy & Terms](https://policies.google.com/privacy), [Data Privacy Framework List](https://www.dataprivacyframework.gov/)

---

## 3. Clientseitige Speicherung (Chrome Extension Storage)

| Speicherort | Technologie | Gespeicherte Daten | Verweildauer & Kontrolle |
|---|---|---|---|
| **Web-Client (Landing/App)** | Browser `localStorage` | Asymmetrisch signiertes Sitzungstoken (RS256 JWT, Ablauf 10 Min.) | Wird bei Logout oder Ablauf nach 10 Min. automatisch gelöscht. |
| **Chrome Extension** | `chrome.storage.local` | `statementHistory` (bis zu 15 Einträge): Dateiname, Zeilenzahl, Gesamtsumme (`totalSum`), Zeitstempel und der **vollständige erzeugte CSV-Text** (`csvText`) | **100% lokal auf dem Rechner des Nutzers.** Bleibt über Browser-Sitzungen hinweg erhalten. Keine Übertragung an Backend-Server. Kann vom Nutzer jederzeit über die Schaltfläche „Verlauf leeren“ vollständig gelöscht werden. |

---

## 4. Verfahren zum Abschluss des AVV für Kanzleikunden (Art. 28 Abs. 9 DSGVO)

Zur Gewährleistung einer rechtsverbindlichen Vereinbarung über die Auftragsverarbeitung gemäß Art. 28 DSGVO steht für Kanzleien und Pilot-Kunden ein klar definiertes Verfahren bereit:

### A. Primärer Weg für Pilot-Kanzleien & B2B-Kunden (Bilateraler Individual-AVV)
1. **Muster-Vorlage:** Grecciani Labs stellt eine vollständige, druck- und zeichnungsreife Vertragsvorlage bereit: [`docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md).
2. **Individualisierung & Gegenzeichnung:** Vor Beginn der Pilotierung bzw. vor der erstmaligen Verarbeitung von Mandantenauszügen wird das Dokument mit den individuellen Kanzleidaten ausgefüllt und von beiden Parteien (Verantwortlicher und Auftragsverarbeiter Vitali Grecciani) bilateral rechtswirksam unterzeichnet.
3. **Status:** Der Muster-AVV-Vertragssatz und die Dokumentation sind vollständig vorbereitet; die Zulassung der jeweiligen Pilot-Kanzlei zur Verarbeitung von Mandantendaten erfolgt durch den bilateralen AVV-Abschluss vor der ersten Übermittlung.

### B. Ergänzender Weg für Self-Service-Kunden (Online-SaaS)
1. **Öffentliche Bereitstellung:** Der vollständige Vertragstext ist unter `https://statement2muster.com/avv` dauerhaft und öffentlich einsehbar.
2. **Einbindung in Nutzungsbedingungen:** Die AGB verweisen ausdrücklich auf die Geltung des AVV für gewerbliche Nutzer.

---

## 5. Erklärung des Verantwortlichen (Owner Acceptance Statement)

```text
================================================================================
BESTÄTIGUNG DES VERANTWORTLICHEN / INHABERS (AKTUALISIERT NACH ENTSCHEIDUNG 46)

Hiermit bestätige ich, Vitali Grecciani, als Inhaber von Grecciani Labs und
datenschutzrechtlich Verantwortlicher für das Projekt Statement2Muster:

1. Die in diesem Register aufgeführten Verträge und Datenschutzvereinbarungen:
   - Hetzner Online GmbH: Auftragsverarbeitungsvertrag (AVV gem. Art. 28 DSGVO,
     umfassend die Kernverarbeitung der Kontoauszüge in Frankfurt am Main)
   - Stripe Payments Europe, Ltd.: Stripe DPA (Fassung vom 16.02.2024)
   - Plus Five Five, Inc. (Resend): Resend DPA (Fassung vom 27. August 2026,
     inkl. EU-Standardvertragsklauseln / SCCs)
   - ImprovMX Inc.: ImprovMX DPA (Fassung vom 9. September 2026, bilateral
     unterzeichnet am 17.09.2026 inkl. EU-Standardvertragsklauseln / SCCs,
     hinterlegt als docs/compliance/improvmx_dpa_signed.pdf)
   - Google Ireland Limited / Google LLC: Hosting des Zielpostfachs
     vitogr24@gmail.com unter dem EU-U.S. Data Privacy Framework (DPF)
     und EU-Standardvertragsklauseln mit 2FA- und TLS-Absicherung
   wurden für die in Produktion eingesetzten Konten und Systeme wirksam abgeschlossen,
   entsprechen exakt den tatsächlichen Netzwerk- und DNS-Routings und sind
   vollumfänglich in Kraft.

2. Die Systeme sind so konfiguriert, dass Mandanten-Auszugsdaten ausschließlich
   auf den Servern der Hetzner Online GmbH in Frankfurt am Main in flüchtigem
   Speicher (RAM / tmpfs) verarbeitet werden. Kein Hilfsdienstleister (weder
   Stripe noch Resend noch ImprovMX) erhält im regulären Konvertierungspfad
   Zugriff auf Auszugsinhalte. Freiwillig per E-Mail an den Support gesendete
   Beispieldateien werden streng zweckgebunden bearbeitet und nach Abschluss
   des Support-Tickets gelöscht.

3. Für jede Pilot-Kanzlei und jeden B2B-Kunden wird vor der Verarbeitung realer
   Mandantendaten das bilaterale Gegenzeichnungsverfahren auf Basis der Muster-Vorlage
   (docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md) verbindlich umgesetzt.

4. Die veröffentlichten Texte auf https://statement2muster.com (Impressum,
   Datenschutz, AVV, AGB, Widerruf) entsprechen exakt den in diesem Dossier
   dokumentierten Inhalten und Dienstleisterketten.

Klosterneuburg, am 17.09.2026

Vitali Grecciani (Inhaber / Product Owner)
================================================================================
```
