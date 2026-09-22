# Repertoire & Registry of Applicable Data Processing Addenda (DPA), Agreements & Provider Chains

**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Verantwortlicher (Controller):** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Datum:** 2026-09-22  
**Status:** Реестр применимых договоров и цепочек обработки данных (актуализировано во исполнение Решений № 46 и № 47 Главного Архитектора — консолидация почтового ящика саппорта на суверенной инфраструктуре Hetzner Online GmbH во Франкфурте-на-Майне в рамках действующего AVV ст. 28 DSGVO, полное исключение ImprovMX и Google из цепочки обработки).

---

## 1. Funktionale Trennung der Verarbeitungsketten (Separation of Pipelines)

Zur Gewährleistung technischer und vertraglicher Klarheit wird die Datenverarbeitung bei Statement2Muster strikt nach Verarbeitungszweck und Datenfluss in drei getrennte Pipelines unterteilt:

```
[Mandant / Kanzlei]
       │
       ├─► PIPELINE 1: Kernverarbeitung (Auszüge) ────────► [Hetzner Frankfurt (RAM / tmpfs)]
       │   (100% in Deutschland, keine Weiterleitung an Dritte, Zero Durable Storage, RAM-Cache TTL 600s)
       │
       ├─► PIPELINE 2: Abrechnung & Lizenzverwaltung ─────► [Stripe Payments Europe (Irland)]
       │   (Keine Auszugsdaten; nur E-Mail, Rechnungsbetrag, Customer ID, Sub ID)
       │
       └─► PIPELINE 3: Authentifizierung & Support ──────► [Resend & Hetzner Frankfurt]
           (3A: OTP-Codes per Resend: nur E-Mail + 6-stelliger 10-Minuten-Code, DPA 27.08.2026, SCCs)
           (3B: Support-Routing & Postfach support@statement2muster.com:
                100% Hetzner Mailserver [Frankfurt am Main, Hetzner AVV Art. 28 DSGVO])
```

---

## 2. Detaillierter Dienstleister- und DPA-Nachweis

### A. Kernverarbeitung der Kontoauszüge & Support-Postfach (Auftragsverarbeitung gem. Art. 28 DSGVO)

#### 1. Hetzner Online GmbH
* **Unternehmenssitz:** Industriestr. 25, 91710 Gunzenhausen, Deutschland.
* **Rechenzentrumsstandort:** Frankfurt am Main, Deutschland (ISO/IEC 27001 zertifiziert).
* **Rolle:** Auftragsverarbeiter (Sub-processor) für Cloud-Infrastruktur, Rechenzentrumsbetrieb und Mailhosting.
* **Gegenstand der Verarbeitung:**
  1. *Auszugskonvertierung (Pipeline 1):* Bereitstellung des gehärteten Linux-Containers für In-Memory-Parsing, Auszugsstrukturierung und flüchtigen In-Memory-Ergebnis-Cache (TTL: 600 Sekunden / 10 Minuten ab Zwischenspeicherung in `tmpfs`/RAM zur Unterstützung idempotenter Wiederholungsabrufe desselben Zielformats ohne erneuten Parsing-Aufwand und ohne Kontingentverlust).
  2. *Support-Postfach (Pipeline 3B):* Bereitstellung und Hosting des dedizierten Mailservers (`docker-mailserver` + Roundcube Webmail auf Host `46.225.95.36`), Entgegennahme von geschäftlichen E-Mails an `support@statement2muster.com` über Port 25 (SMTP) und Bereitstellung des verschlüsselten Abrufs über Port 993 (IMAPS).
* **Verarbeitete Datenkategorien:**
  - Pipeline 1: Hochgeladene PDF- und CSV-Auszugsdaten zur flüchtigen Konvertierung; kryptografisch signierte Sitzungstoken (RS256); Lizenzstatus.
  - Pipeline 3B: Support-Anfragen (Absender, Datum, Betreff, Nachrichteninhalt, eventuell vom Nutzer freiwillig zur Fehlerdiagnose übermittelte Beispieldateien).
* **Aufbewahrungsfristen & Löschkonzepte (Klarstellung gem. Entscheidung 47):**
  - *Pipeline 1 (Auszüge):* Strikte **Zero Durable Retention**. Auszugsdaten werden niemals auf persistenten Festplatten/SSDs gespeichert, sondern verbleiben ausschließlich im flüchtigen RAM (`tmpfs`). Nach Ablauf von 600 Sekunden erfolgt die vollständige Freigabe.
  - *Pipeline 3B (Support-E-Mail):* **Politik begrenzter Aufbewahrung (Limited Support Retention / Ticket Closure Policy)**. E-Mails und freiwillig übermittelte Anhänge im Postfach `support@statement2muster.com` werden auf dem Hetzner-Server gespeichert, solange das Ticket in Bearbeitung ist. Nach Klärung und Abschluss der Support-Anfrage werden der Vorgang und eventuelle Beispieldateien manuell gelöscht. Eine dauerhafte Archivierung findet nicht statt.
* **Sicherheitsniveau & Verschlüsselung (Klarstellung gem. Entscheidung 47):**
  - E-Mail-Verschlüsselung: **Transportverschlüsselung (TLS 1.3 / STARTTLS)** beim Empfang über SMTP und beim Abruf über IMAPS. Es handelt sich um Transportverschlüsselung zwischen Übertragungsknoten, nicht um eine proprietäre Ende-zu-Ende-Inhaltsverschlüsselung.
* **Vertragliche Grundlage:** Auftragsverarbeitungsvertrag (AVV) nach Art. 28 DSGVO der Hetzner Online GmbH (DSGVO-konforme Fassung).
* **Abschlussmethode & Status:** Rechtswirksam elektronisch abgeschlossen im Hetzner Kundenkonto (Cloud Console).
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

### D. Decommissioned & Ausgeschlossene Drittanbieter

#### 4. ImprovMX Inc. & Google LLC / Google Ireland Limited (VOLLSTÄNDIG ENTFERNT)
* **Historischer Status:** ImprovMX diente in der frühen Entwicklungsphase als temporäres Weiterleitungs-Relay an eine Google-Mailadresse.
* **Aktueller Status (ab 22.09.2026):** **Vollständig außer Betrieb genommen (Decommissioned)**.
* **Begründung:** Gemäß Entscheidung 47 des leitenden Architekten wurde festgestellt, dass für Standard-Gmail-Konten kein Art.-28-DSGVO-Vertrag vorliegt. Zur Schaffung eines lückenlosen, 100% DSGVO-konformen Rechtsrahmens wurde der gesamte E-Mail-Empfang auf die eigene Hetzner-Serverinfrastruktur in Frankfurt am Main migriert. Weder ImprovMX noch Google sind Bestandteil des aktuellen Datenverarbeitungs- oder Support-Routings.

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
BESTÄTIGUNG DES VERANTWORTLICHEN / INHABERS (AKTUALISIERT NACH ENTSCHEIDUNG 47)

Hiermit bestätige ich, Vitali Grecciani, als Inhaber von Grecciani Labs und
datenschutzrechtlich Verantwortlicher für das Projekt Statement2Muster:

1. Die in diesem Register aufgeführten Verträge und Datenschutzvereinbarungen:
   - Hetzner Online GmbH: Auftragsverarbeitungsvertrag (AVV gem. Art. 28 DSGVO,
     umfassend die Kernverarbeitung der Kontoauszüge sowie das E-Mail-Hosting
     des Support-Postfachs in Frankfurt am Main)
   - Stripe Payments Europe, Ltd.: Stripe DPA (Fassung vom 16.02.2024)
   - Plus Five Five, Inc. (Resend): Resend DPA (Fassung vom 27. August 2026,
     inkl. EU-Standardvertragsklauseln / SCCs für OTP-Zustellung)
   wurden für die in Produktion eingesetzten Konten und Systeme wirksam abgeschlossen,
   entsprechen exakt den tatsächlichen Netzwerk- und Serverkonfigurationen und sind
   vollumfänglich in Kraft.

2. Der Support-E-Mail-Verkehr (support@statement2muster.com) wird zu 100% direkt
   auf der Hetzner-Serverinfrastruktur in Frankfurt am Main entgegengenommen und
   verarbeitet. Weder ImprovMX noch Google LLC / Gmail fungieren als Auftragsverarbeiter
   oder Weiterleitungsglieder.

3. Die Systeme sind so konfiguriert, dass Mandanten-Auszugsdaten (Pipeline 1) ausschließlich
   auf den Servern der Hetzner Online GmbH in flüchtigem Speicher (RAM / tmpfs) mit
   einer maximalen TTL von 600 Sekunden verarbeitet werden (Zero Durable Storage).
   Freiwillig per E-Mail an den Support gesendete Beispieldateien (Pipeline 3B)
   unterliegen der Richtlinie begrenzter Aufbewahrung (Limited Support Retention) und
   werden nach Abschluss des Tickets manuell gelöscht.

4. Für jede Pilot-Kanzlei und jeden B2B-Kunden wird vor der Verarbeitung realer
   Mandantendaten das bilaterale Gegenzeichnungsverfahren auf Basis der Muster-Vorlage
   (docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md) verbindlich umgesetzt.

5. Die veröffentlichten Texte auf https://statement2muster.com (Impressum,
   Datenschutz, AVV, AGB, Widerruf) entsprechen exakt den in diesem Dossier
   dokumentierten Inhalten und Dienstleisterketten.

Klosterneuburg, am 22.09.2026

Vitali Grecciani (Inhaber / Product Owner)
================================================================================
```
