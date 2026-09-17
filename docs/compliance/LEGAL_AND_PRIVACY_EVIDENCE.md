# Statement2Muster — Legal, Privacy & Compliance Evidence Dossier

**Status:** Updated per Chief Architect Decision № 46 (Closure Stage 2 — Authoritative Mail Routing & ImprovMX DPA)  
**Datum:** 2026-09-17  
**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Inhaber / Diensteanbieter:** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Aufsichtsbehörde:** Österreichische Datenschutzbehörde (DSB), Barichgasse 40-42, 1030 Wien  
**Referenz-Register:** [DPA & Contracts Registry](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md)  
**Pilot-AVV-Vorlage:** [Muster-AVV für Kanzleien](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md)  
**ImprovMX DPA (gezeichnet):** [PDF-Dokument](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/improvmx_dpa_signed.pdf)  

---

## 1. Rechtlicher Rahmen und Anwendungsbereich (Governing Law)

Statement2Muster stellt spezialisierte Softwarewerkzeuge zur Strukturierung und Konvertierung digitaler Bank- und Kreditkartenauszüge in normierte Zielformate des Rechnungswesens (**DATEV Format EXTF** und **BMD NTCS**) bereit.

Der Dienst richtet sich primär an Gewerbetreibende, Steuerberater und Wirtschaftsprüfer (B2B) im DACH-Raum und beachtet:
- **Verordnung (EU) 2016/679 (DSGVO):** Transparente Rechenschaftslegung (Art. 5 Abs. 2 DSGVO), Bereitstellung eines standardisierten Auftragsverarbeitungsvertrags (AVV) nach Art. 28 DSGVO, Bereitstellung bilateraler Kanzlei-AVV-Muster für Pilotbetriebe und Absicherung von Hilfsdiensten nach Art. 45 / Art. 46 DSGVO.
- **E-Commerce-Gesetz (ECG):** Anbieterkennzeichnung gemäß § 5 ECG.
- **Mediengesetz (MedienG):** Offenlegungspflichten gemäß § 25 MedienG.
- **Telekommunikationsgesetz (TKG 2021):** Strikte Einhaltung des § 165 Abs. 3 TKG 2021 (einwilligungsfreier Verzicht auf Tracking- oder Werbe-Cookies).
- **Konsumentenschutzgesetz (KSchG) & FAGG:** 14-tägiges gesetzliches Widerrufsrecht für Verbraucher nebst 14-Tage-Geld-zurück-Garantie.

---

## 2. Dienstleister, Rollen und Verarbeitungs-Pipelines

Zur Vermeidung von Pauschalaussagen wird die Verarbeitung strikt nach Zuständigkeit getrennt:

### Pipeline 1: Kernverarbeitung von Mandanten-Auszügen (Auftragsverarbeitung)
* **Dienstleister:** **Hetzner Online GmbH** (Industriestr. 25, 91710 Gunzenhausen, Deutschland).
* **Standort:** ISO/IEC 27001-zertifiziertes Rechenzentrum in **Frankfurt am Main, Deutschland**.
* **Aufgabe:** Ausführung des Docker-Containers `statement2muster-api`, Parsing und Strukturierung von Auszugsdaten in `tmpfs` / RAM.
* **Garantie:** Die Auszugsverarbeitung verbleibt zu 100% in Deutschland. **Kein externer Hilfsdienstleister (weder Stripe noch Resend noch ImprovMX) erhält im regulären Konvertierungspfad Zugriff auf hochgeladene Auszüge oder Buchungsinhalte.**

### Pipeline 2: Kaufmännische Abrechnung und Zahlungsabwicklung
* **Dienstleister:** **Stripe Payments Europe, Ltd.** (Dublin, Irland).
* **Aufgabe:** Abrechnung von Lizenzen und Abonnements.
* **Rolle:** Eigenständiger Verantwortlicher für Zahlungs- und Kreditkartendaten; Auftragsverarbeiter für kaufmännische Kundenstammdaten.
* **Übertragene Daten:** E-Mail-Adresse, Zahlungsbetrag, Stripe Customer ID, Stripe Subscription ID. Keine Bankauszüge.
* **Vertrag:** Stripe DPA (Stand 16.02.2024).

### Pipeline 3: Transaktionale Login-Zustellung (OTP) & Support-Kommunikation
* **Dienstleister für OTP-Zustellung:** **Plus Five Five, Inc. (dba Resend)**, San Francisco, CA, USA (Delaware Corp).
  * **Rolle:** Auftragsverarbeiter für E-Mail-Zustellung von Einmalpasswörtern.
  * **Daten:** E-Mail-Adresse und temporärer 6-stelliger Einmalcode (Gültigkeit: 10 Minuten).
  * **Exakte Vertragsfassung & Übermittlungsgrundlage:** *Resend Data Processing Addendum (DPA)* — **Last update: August 27th, 2026** mit Standardvertragsklauseln der EU (SCCs) gemäß Art. 46 Abs. 2 lit. c DSGVO (Modul 2 Controller-to-Processor und Modul 3 Processor-to-Processor).
* **Dienstleister für Inbound MX-Routing:** **ImprovMX Inc.**, 2093 Philadelphia Pike #6858, Claymont, DE 19703, USA (Delaware Corp).
  * **Rolle:** Auftragsverarbeiter für E-Mail-Routing / MX-Weiterleitung an das Zielpostfach des Verantwortlichen.
  * **Autoritative DNS-Einträge (Vercel DNS `ns1.vercel-dns.com`):** `10 mx1.improvmx.com`, `20 mx2.improvmx.com`, `v=spf1 include:spf.improvmx.com ~all`.
  * **Vertrag & Übermittlungsgrundlage:** *ImprovMX Data Processing Agreement (DPA)* vom **9. September 2026**, bilateral unterzeichnet von Matthew Tse (CEO ImprovMX Inc.) und Vitali Grecciani (Grecciani Labs), inkl. Standardvertragsklauseln der EU (SCCs) nach Art. 46 Abs. 2 lit. c DSGVO. Hinterlegt unter [`docs/compliance/improvmx_dpa_signed.pdf`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/improvmx_dpa_signed.pdf).
* **Dienstleister für Zielpostfach:** **Google Ireland Limited / Google LLC**, Gordon House, Dublin 4, Irland / Mountain View, CA, USA.
  * **Rolle:** E-Mail-Diensteanbieter / Auftragsverarbeiter für das persönliche Zielpostfach des Verantwortlichen (`vitogr24@gmail.com`).
  * **Rechtsgrundlage:** EU-U.S. Data Privacy Framework (DPF) gem. Art. 45 DSGVO & EU-SCCs gem. Art. 46 DSGVO; TLS 1.3 / 1.2 Transportverschlüsselung und 2FA.
* **Schutz vor Datenabfluss:** Der reguläre Konvertierungspfad leitet niemals Auszugsdateien an E-Mail-Dienste weiter. Sollte ein Nutzer freiwillig Beispieldateien per E-Mail übersenden, werden diese streng vertraulich zur Ticketlösung verarbeitet und danach gelöscht.

---

## 3. Technische Speicher- und Sicherheitsarchitektur

### A. Server-Verarbeitung: Flüchtige In-Memory-Verarbeitung & RAM-Cache
1. **Flüchtige Verarbeitung:**
   - Eingehende PDF- und CSV-Dateien werden direkt im Arbeitsspeicher (RAM) bzw. in temporären RAM-Dateisystemen (Linux `tmpfs`) des Containers verarbeitet.
   - Auf den Servern findet keine persistente Speicherung von Auszugsinhalten auf Festplatten oder SSDs statt (Zero Durable Retention).
2. **Idempotenter RAM-Ergebnis-Cache:**
   - Gemäß Konfiguration `RAM_CACHE_TTL_SECONDS = 600` wird das Konvertierungsergebnis für **maximal 10 Minuten ab Zwischenspeicherung** in einem flüchtigen Arbeitsspeicher-Cache gehalten (`idempotent_result_cache`).
   - Zweck: Ermöglicht dem Benutzer, bei Verbindungsabbrüchen oder wiederholten Abrufen desselben Zielformats das identische Ergebnis ohne erneuten Parsing-Aufwand und ohne Kontingentverlust abzurufen. Der Cache-Schlüssel ist formatspezifisch.
   - Nach Ablauf von 10 Minuten oder bei einem Server-Neustart wird der Cache automatisch aus dem flüchtigen RAM freigegeben (Memory Deallocation / Garbage Collection).
3. **Datenbank-Isolation (Zero Statement Retention):**
   - Die Datenbank speichert ausschließlich administrative Identitäten (`users`, `entitlements`, `revoked_tokens`).
   - Es existieren keine Tabellen für Buchungstexte, IBANs oder Auszugstransaktionen.

### B. Kryptografie und Sitzungsverwaltung
- **Signaturalgorithmus:** Kryptografisch asymmetrisch **signierte** Tokens (**RS256 / RSA-2048**) gemäß Architect ADR-001 (nicht Ed25519 und nicht verschlüsselt).
- **Transportverschlüsselung:** Durchgehend TLS 1.3 / TLS 1.2 mit Perfect Forward Secrecy.
- **Sitzungsdauer:** Access Token läuft nach 10 Minuten ab (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 10`).

### C. Clientseitiges Speicherverhalten (Browser & Chrome Extension)
- **Webbrowser:** Speichert lediglich das signierte RS256-Sitzungstoken im `localStorage` zur Aufrechterhaltung der aktiven Sitzung.
- **Chrome Extension (Lokale Historie bis 15 Einträge):**
  - Zur Arbeitserleichterung speichert die Erweiterung die letzten **bis zu 15 Konvertierungen** im lokalen Speicher des Browsers (`chrome.storage.local`).
  - Gespeicherte Felder: `id`, `filename`, `timestamp`, `count`, `totalSum` und der **vollständige erzeugte CSV-Text (`csvText`)**.
  - **Speicherort:** Ausschließlich lokal auf dem Rechner des Nutzers. Verbleibt sitzungsübergreifend auf dem Gerät.
  - **Kontrolle:** Der Nutzer kann diese Historie jederzeit mit einem Klick auf die Schaltfläche „Verlauf leeren“ vollständig aus seinem Browser löschen.
  - Das Server-Prinzip „Zero Durable Storage“ erstreckt sich per Definition nicht auf diese lokalen Browserdaten oder lokal heruntergeladene Dateien.

---

## 4. Status der öffentlich publizierten Dokumente & AVV-Prozess

| Dokument | URL-Pfad / Ablage | Wesentliche Inhalte & Anpassungen | Status |
|---|---|---|---|
| **Impressum** | `/impressum` | Anbieterkennzeichnung § 5 ECG / § 25 MedienG (Vitali Grecciani, Klosterneuburg) | **Live & verifiziert** |
| **Datenschutz** | `/datenschutz` | Art. 13/14 DSGVO: RAM/tmpfs, TTL 600s ab Zwischenspeicherung, Hetzner (Kernverarbeitung in Frankfurt), Stripe, Resend (DPA Stand 27.08.2026, SCCs), ImprovMX (DPA 09.09.2026, SCCs) & Google DPF Zielpostfach (`vitogr24@gmail.com`), Chrome-Historie (15 Einträge mit csvText und totalSum), DSB Wien | **Aktualisiert (Decision 46)** |
| **AVV (Online)** | `/avv` | Art. 28 DSGVO: TOMs § 5 (tmpfs, RAM TTL 600s idempotenter Replay ohne Kontingentverlust, lokale 15-Einträge-Historie), § 6 getrennte Subprozessoren (Hetzner Kern-Prozessor; Stripe/Resend/ImprovMX/Google Hilfsdienste), § 9 RAM Deallocation | **Aktualisiert (Decision 46)** |
| **Muster-AVV (Bilateral)** | `docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md` | Vollständige druckreife zweisprachig/deutsche AVV-Vereinbarung inkl. Anlagen (TOMs, 5 Subprozessoren: Hetzner, Stripe, Resend, ImprovMX, Google) zur individuellen Gegenzeichnung für Kanzleien und Pilot-Betriebe vor der Verarbeitung von Echtdaten | **Aktualisiert (Decision 46)** |
| **AGB** | `/agb` | B2B/B2C-Bedingungen, Lizenzierung (Starter, PRO, Lifetime), Kündigungsregeln | **Live & verifiziert** |
| **Widerruf** | `/widerruf` | Verbraucher-Widerruf (14 Tage) + 14-Tage Geld-zurück-Garantie | **Live & verifiziert** |

---

## 5. Konformitätsfazit für das Audit (Vollständige Schließung Stage 2)

Mit den in diesem Prüfpaket vorgenommenen Anpassungen:
1. Sind alle Feststellungen aus **Решение № 46** des Hauptarchitekten restlos erfüllt:
   - **DNS- und Routing-Konsistenz:** Das in autoritativen Vercel-DNS-Servern (`ns1.vercel-dns.com`) hinterlegte MX-Routing (`mx1.improvmx.com`, `mx2.improvmx.com`) stimmt exakt mit der vertraglichen Dokumentation und den Datenschutzerklärungen überein.
   - **Gegenzeichnung ImprovMX DPA:** Das offizielle *ImprovMX Data Processing Agreement* (Datum: 9. September 2026) wurde beidseitig rechtswirksam gezeichnet (Matthew Tse, CEO ImprovMX Inc., und Vitali Grecciani, Grecciani Labs) und ist als PDF-Beleg unter [`docs/compliance/improvmx_dpa_signed.pdf`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/improvmx_dpa_signed.pdf) hinterlegt.
   - **Tatsächliches Zielpostfach:** Die Weiterleitung an das tatsächliche Empfängerpostfach des Verantwortlichen (`vitogr24@gmail.com`) ist offengelegt und datenschutzrechtlich über das EU-U.S. Data Privacy Framework (DPF gem. Art. 45 DSGVO) von Google LLC sowie EU-SCCs abgesichert.
   - **Tatsächliche Subprozessoren-Kette:** Alle 5 Subprozessoren (Hetzner, Stripe, Resend, ImprovMX, Google) sind in `landing/avv.html`, `landing/datenschutz.html`, `landing/app.js`, `docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md` und `docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md` vollkommen konsistent und synchronisiert erfasst.
   - **Inhaber-Bestätigung:** Das datierte [Bestätigungs-Statement](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md#5-erklärung-des-verantwortlichen-owner-acceptance-statement) des Inhabers (Vitali Grecciani) vom 17.09.2026 bestätigt diese lückenlose vertragliche und operative Basis.
2. Der organisatorisch-rechtliche Kontur (Stage 2) ist damit vollständig, widerspruchsfrei und auditfähig abgeschlossen.
