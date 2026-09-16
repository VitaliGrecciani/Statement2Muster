# Repertoire & Registry of Applicable Data Processing Addenda (DPA), Agreements & Provider Chains

**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Verantwortlicher (Controller):** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Datum:** 2026-09-16  
**Status:** Реестр применимых договоров и цепочек обработки данных (актуализировано во исполнение Решения № 44 Главного Архитектора)  

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
       └─► PIPELINE 3: Authentifizierung & Support ──────► [Resend & ImprovMX (USA/SCCs) -> Zielpostfach Apple Mail]
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
* **Gegenstand der Verarbeitung:** Bereitstellung des Linux-Containers für In-Memory-Parsing, Auszugsstrukturierung und flüchtigen In-Memory-Ergebnis-Cache (TTL: 600 Sekunden / 10 Minuten ab Zwischenspeicherung in `tmpfs`/RAM zur Unterstützung idempotenter Wiederholungsabrufe desselben Zielformats ohne erneuten Parsing-Aufwand und ohne Kontingentverlust).
* **Verarbeitete Daten:** Hochgeladene PDF- und CSV-Auszugsdaten zur flüchtigen Konvertierung; kryptografisch signierte Sitzungstoken (RS256); Lizenzstatus.
* **Dauer der Speicherung:** 
  - Server-RAM-Cache: Maximal 600 Sekunden ab Zwischenspeicherung; danach automatische Freigabe durch das System (Memory Deallocation / Garbage Collection).
  - Keine Speicherung auf Festplatten/SSDs (Zero Durable Storage).
* **Vertragliche Grundlage:** Auftragsverarbeitungsvertrag (AVV) nach Art. 28 DSGVO der Hetzner Online GmbH (DSGVO-konforme Fassung).
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
* **Exakte Vertragsfassung & Übermittlungsmechanismus:**
  - **Offizielle Fassung:** *Resend Data Processing Addendum (DPA)* — **Last update: August 27th, 2026** (verfügbar unter: `https://resend.com/legal/dpa`).
  - **Rechtsgrundlage:** Art. 28 DSGVO (Auftragsverarbeitung).
  - **Übermittlungsmechanismus:** Standard Contractual Clauses (SCCs) gemäß Durchführungsbeschluss (EU) 2021/914 der Kommission (Modul 2 Controller-to-Processor und Modul 3 Processor-to-Processor) nach Art. 46 Abs. 2 lit. c DSGVO.
* **Abschlussmethode & Status:** Elektronisch vereinbart im Rahmen der Registrierung des Produktionskontos und Erzeugung des API-Schlüssels für die Domain `statement2muster.com`.
* **Account-Bestätigung:** Resend-Produktionsaccount aktiv, API-Schlüssel konfiguriert für Domain `statement2muster.com`.
* **Quelle:** [Resend DPA (August 27th, 2026)](https://resend.com/legal/dpa), [Resend GDPR Info](https://resend.com/security/gdpr)

#### 4. ImprovMX Inc. (Inbound Support MX-Relay)
* **Unternehmenssitz:** 2093 Philadelphia Pike #6858, Claymont, DE 19703, USA (Delaware Corporation).
* **Rolle:** Auftragsverarbeiter (Processor) für technisches MX-Routing und Weiterleitung geschäftlicher Support-E-Mails.
* **Gegenstand der Verarbeitung:** Flüchtige Weiterleitung (Relay) von eingehenden E-Mails an `support@statement2muster.com` und `kontakt@statement2muster.com` an das Kanzlei-Zielpostfach des Verantwortlichen (`vitali@grecciani.com`).
* **Transport- und Verarbeitungskette:**
  1. *Absender* sendet geschäftliche Anfrage an `support@statement2muster.com`.
  2. *ImprovMX MX-Gateway* (`mx1.improvmx.com`, `mx2.improvmx.com`) nimmt die E-Mail entgegen und leitet sie unmittelbar per TLS-Transportverschlüsselung an das Zielpostfach `vitali@grecciani.com` weiter (reines Durchleitungs-Routing, keine permanente Speicherung auf ImprovMX-Servern).
* **Vertragliche Grundlage & Übermittlungsmechanismus:**
  - ImprovMX Terms of Service und Privacy Policy (incorporating GDPR data processing principles and EU Standard Contractual Clauses for transborder email forwarding).
* **Strikte Trennung vom Konvertierungsdienst:** Der reguläre Konvertierungspfad der Plattform leitet niemals Auszugs- oder Buchungsdaten an ImprovMX. Freiwillig per E-Mail übersandte Testdateien werden ausschließlich zur Ticketbeantwortung genutzt und nach Abschluss gelöscht.
* **Abschlussmethode & Status:** Elektronisch akzeptiert bei Account-Erstellung und DNS-MX-Konfiguration für `statement2muster.com`.
* **Quelle:** [ImprovMX Terms](https://improvmx.com/terms/), [ImprovMX Privacy](https://improvmx.com/transparency/privacy-policy/)

#### 5. Apple Distribution International Ltd. / Apple Inc. (Support-Zielpostfach)
* **Unternehmenssitz:** 
  - Für EU/EWR: **Apple Distribution International Ltd.**, Hollyhill Industrial Estate, Cork, Irland.
  - Konzernmutter: **Apple Inc.**, One Apple Park Way, Cupertino, CA 95014, USA.
* **Rolle:** Auftragsverarbeiter (Processor) / E-Mail-Hosting-Provider für das unternehmenseigene Ziel-Postfach `vitali@grecciani.com`.
* **Gegenstand der Verarbeitung:** Sicheres Hosting, Entgegennahme und Bereithaltung der an `vitali@grecciani.com` weitergeleiteten Support- und Geschäftsnachrichten über den Dienst **Apple iCloud Mail (Custom Domain Support)**.
* **Vertragliche Grundlage & Übermittlungsmechanismus:**
  - Apple iCloud Nutzungsbedingungen (iCloud Terms and Conditions, Fassung EU/EWR).
  - Apple Datenschutzrichtlinie (Apple Privacy Policy).
  - Apple Data Privacy Framework (DPF) Zertifizierung für Apple Inc. (Übermittlung gem. Art. 45 DSGVO) bzw. Standardvertragsklauseln der EU (SCCs) gem. Art. 46 DSGVO.
* **Sicherheits- & Zugriffskontrolle:**
  - Transportverschlüsselung (TLS) bei Empfang und Abruf.
  - Serverseitige AES-Verschlüsselung der E-Mail-Inhalte im Ruhezustand (At Rest).
  - Zugriff ausschließlich durch den Verantwortlichen persönlich, abgesichert durch obligatorische hardware- und biometriegestützte Zwei-Faktor-Authentifizierung (Apple 2FA / FaceID / TouchID).
* **Quelle:** [Apple Legal iCloud (EU)](https://www.apple.com/legal/internet-services/icloud/de/terms.html), [Apple Privacy](https://www.apple.com/legal/privacy/de-ww/)

---

## 3. Clientseitige Speicherung (Chrome Extension Storage)

| Speicherort | Technologie | Gespeicherte Daten | Verweildauer & Kontrolle |
|---|---|---|---|
| **Web-Client (Landing/App)** | Browser `localStorage` | Asymmetrisch signiertes Sitzungstoken (RS256 JWT, Ablauf 10 Min.) | Wird bei Logout oder Ablauf nach 10 Min. automatisch gelöscht. |
| **Chrome Extension** | `chrome.storage.local` | `statementHistory` (bis zu 15 Einträge): Dateiname, Zeilenzahl, Gesamtsumme (`totalSum`), Zeitstempel und der **vollständige erzeugte CSV-Text** (`csvText`) | **100% lokal auf dem Rechner des Nutzers.** Bleibt über Browser-Sitzungen hinweg erhalten. Keine Übertragung an Backend-Server. Kann vom Nutzer jederzeit über die Schaltfläche „Verlauf leeren“ vollständig gelöscht werden. |

---

## 4. Verfahren zum Abschluss des AVV für Kanzleikunden (Art. 28 Abs. 9 DSGVO)

Zur Gewährleistung einer rechtsverbindlichen Vereinbarung über die Auftragsverarbeitung gemäß Art. 28 DSGVO stehen zwei klar definierte Verfahrensweisen bereit:

### A. Primärer Weg für Pilot-Kanzleien & B2B-Kunden (Bilateraler Individual-AVV)
1. **Muster-Vorlage:** Grecciani Labs stellt eine vollständige, druck- und zeichnungsreife Vertragsvorlage bereit: [`docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md).
2. **Individualisierung & Gegenzeichnung:** Vor Beginn der Pilotierung oder vor Übergabe erster Mandantenauszüge wird das Dokument mit den Kanzleidaten (Name, Anschrift, Ansprechpartner) ausgefüllt und von beiden Parteien (Verantwortlicher und Auftragsverarbeiter Vitali Grecciani) bilateral rechtswirksam unterzeichnet (digital per qualifizierter elektronischer Signatur bzw. handschriftlich auf Papier).
3. **Archivierung:** Die gegengezeichnete Vereinbarung wird in die Datenschutz-Verfahrensdokumentation der Kanzlei sowie in das Register von Grecciani Labs aufgenommen.

### B. Ergänzender Weg für Self-Service-Kunden (Online-SaaS)
1. **Öffentliche Bereitstellung:** Der vollständige Vertragstext ist unter `https://statement2muster.com/avv` dauerhaft und öffentlich einsehbar.
2. **Einbindung in Nutzungsbedingungen:** Die AGB und der Registrierungsprozess verweisen ausdrücklich auf die Geltung des AVV für gewerbliche Kunden.

---

## 5. Erklärung des Verantwortlichen (Owner Acceptance Statement)

```text
================================================================================
BESTÄTIGUNG DES VERANTWORTLICHEN / INHABERS (AKTUALISIERT NACH ENTSCHEIDUNG 44)

Hiermit bestätige ich, Vitali Grecciani, als Inhaber von Grecciani Labs und
datenschutzrechtlich Verantwortlicher für das Projekt Statement2Muster:

1. Die in diesem Register aufgeführten Verträge und Datenschutzvereinbarungen:
   - Hetzner Online GmbH: Auftragsverarbeitungsvertrag (AVV gem. Art. 28 DSGVO)
   - Stripe Payments Europe, Ltd.: Stripe DPA (Fassung vom 16.02.2024)
   - Plus Five Five, Inc. (Resend): Resend DPA (Fassung vom 27. August 2026,
     inkl. EU-Standardvertragsklauseln / SCCs)
   - ImprovMX Inc.: Terms of Service & Privacy Policy (flüchtiges Inbound-Routing
     inkl. EU-SCCs)
   - Apple Distribution International Ltd. / Apple Inc.: iCloud Nutzungsbedingungen,
     Apple Privacy Policy und DPF/SCC-Übermittlungsgrundlage für das Kanzlei-
     Zielpostfach vitali@grecciani.com
   wurden für die in Produktion eingesetzten Konten und Systeme wirksam abgeschlossen
   und sind vollumfänglich in Kraft.

2. Die Systeme sind so konfiguriert, dass Mandanten-Auszugsdaten ausschließlich
   auf den Servern der Hetzner Online GmbH in Frankfurt am Main verarbeitet werden
   und kein Hilfsdienstleister (Stripe, Resend, ImprovMX, Apple) im regulären Betrieb
   Zugriff auf Auszugsinhalte erhält.

3. Für Pilot-Kanzleien und B2B-Kunden wird vor der Verarbeitung realer Mandantendaten
   das bilaterale Gegenzeichnungsverfahren auf Basis der Muster-Vorlage
   (docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md) verbindlich umgesetzt.

4. Die veröffentlichten Texte auf https://statement2muster.com (Impressum,
   Datenschutz, AVV, AGB, Widerruf) entsprechen exakt den in diesem Dossier
   dokumentierten Inhalten.

Klosterneuburg, am 16.09.2026

Vitali Grecciani (Inhaber / Product Owner)
================================================================================
```
