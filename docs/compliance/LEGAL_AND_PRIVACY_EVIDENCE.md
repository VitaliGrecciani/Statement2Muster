# Statement2Muster — Legal, Privacy & Compliance Evidence Dossier

**Status:** Updated per Chief Architect Decision № 43  
**Datum:** 2026-09-16  
**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Inhaber / Diensteanbieter:** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Aufsichtsbehörde:** Österreichische Datenschutzbehörde (DSB), Barichgasse 40-42, 1030 Wien  
**Referenz-Register:** [DPA & Contracts Registry](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md)

---

## 1. Rechtlicher Rahmen und Anwendungsbereich (Governing Law)

Statement2Muster stellt spezialisierte Softwarewerkzeuge zur Strukturierung und Konvertierung digitaler Bank- und Kreditkartenauszüge in normierte Zielformate des Rechnungswesens (**DATEV Format EXTF** und **BMD NTCS**) bereit.

Der Dienst richtet sich primär an Gewerbetreibende, Steuerberater und Wirtschaftsprüfer (B2B) im DACH-Raum und beachtet:
- **Verordnung (EU) 2016/679 (DSGVO):** Transparente Rechenschaftslegung (Art. 5 Abs. 2 DSGVO), Bereitstellung eines standardisierten Auftragsverarbeitungsvertrags (AVV) nach Art. 28 DSGVO und Absicherung grenzüberschreitender Hilfsdienste nach Art. 46 DSGVO.
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

### Pipeline 3: Transaktionale Login-Zustellung (OTP) & Support
* **Dienstleister für OTP-Zustellung:** **Plus Five Five, Inc. (dba Resend)**, San Francisco, CA, USA (Delaware Corp).
  * **Rolle:** Auftragsverarbeiter für E-Mail-Zustellung.
  * **Daten:** E-Mail-Adresse und temporärer 6-stelliger Einmalcode (Gültigkeit: 10 Minuten).
  * **Übermittlungsgrundlage:** Resend Data Processing Addendum (DPA) mit Standardvertragsklauseln der EU (SCCs) gemäß Art. 46 Abs. 2 lit. c DSGVO.
* **Dienstleister für Support-MX-Routing:** **ImprovMX Inc.**, Claymont, DE, USA (Delaware Corp).
  * **Rolle:** E-Mail-Forwarding von `support@statement2muster.com` an das Kanzlei-Postfach des Verantwortlichen (`vitali@grecciani.com`, gehostet bei Apple Inc. / iCloud Mail mit TLS-Verschlüsselung).
  * **Daten:** Freiwillige Support-E-Mails. Sollte ein Nutzer freiwillig Beispieldateien per E-Mail übersenden, werden diese streng vertraulich zur Ticketlösung verarbeitet und danach gelöscht.

---

## 3. Technische Speicher- und Sicherheitsarchitektur

### A. Server-Verarbeitung: Flüchtige In-Memory-Verarbeitung & RAM-Cache
1. **Flüchtige Verarbeitung:**
   - Eingehende PDF- und CSV-Dateien werden direkt im Arbeitsspeicher (RAM) bzw. in temporären RAM-Dateisystemen (Linux `tmpfs`) des Containers verarbeitet.
   - Auf den Servern findet keine persistente Speicherung von Auszugsinhalten auf Festplatten oder SSDs statt (Zero Durable Retention).
2. **Idempotenter RAM-Ergebnis-Cache:**
   - Gemäß Konfiguration `RAM_CACHE_TTL_SECONDS = 600` wird das Konvertierungsergebnis für **maximal 10 Minuten ab Zwischenspeicherung** in einem flüchtigen Arbeitsspeicher-Cache gehalten (`idempotent_result_cache`).
   - Zweck: Ermöglicht dem Benutzer, bei Verbindungsabbrüchen oder wiederholten Abrufen desselben Formats das identische Ergebnis ohne erneutes Parsing und ohne Kontingentverlust abzurufen. Der Cache-Schlüssel ist formatspezifisch.
   - Nach Ablauf von 10 Minuten oder bei einem Server-Neustart wird der Cache automatisch aus dem RAM freigegeben.
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

## 4. Status der öffentlich publizierten Dokumente

| Dokument | URL-Pfad | Wesentliche Inhalte & Anpassungen | Status |
|---|---|---|---|
| **Impressum** | `/impressum` | Anbieterkennzeichnung § 5 ECG / § 25 MedienG (Vitali Grecciani, Klosterneuburg) | **Live & verifiziert** |
| **Datenschutz** | `/datenschutz` | Art. 13/14 DSGVO: RAM/tmpfs, TTL 600s ab Zwischenspeicherung, Hetzner, Stripe, Resend (Plus Five Five Inc., SCCs), ImprovMX -> iCloud Mail, Chrome-Historie (15 Einträge mit csvText und totalSum), DSB Wien | **Aktualisiert (Decision 43)** |
| **AVV** | `/avv` | Art. 28 DSGVO: TOMs § 5 (tmpfs, RAM TTL 600s, lokale 15-Einträge-Historie), § 6 getrennte Subprozessoren (Hetzner Kern-Prozessor; Stripe/Resend/ImprovMX Hilfsdienste) | **Aktualisiert (Decision 43)** |
| **AGB** | `/agb` | B2B/B2C-Bedingungen, Lizenzierung (Starter, PRO, Lifetime), Kündigungsregeln | **Live & verifiziert** |
| **Widerruf** | `/widerruf` | Verbraucher-Widerruf (14 Tage) + 14-Tage Geld-zurück-Garantie | **Live & verifiziert** |

---

## 5. Konformitätsfazit für das Audit

Mit den in коммит 191ebec und nachfolgenden Schritten vorgenommenen Anpassungen:
1. Sind alle Punkte aus **Решение № 43** vollständig adressiert:
   - Der genaue Umfang der clientseitigen Chrome-Historie (bis zu 15 Einträge, `csvText`, `totalSum`) ist in Datenschutz, AVV und Dossier transparent offengelegt.
   - Der Zweck des RAM-Caches ist exakt als formatspezifischer idempotenter Replay-Cache mit 600s TTL ab Zwischenspeicherung beschrieben.
   - Das [DPA & Contracts Registry](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md) enthält die vollständige Support-E-Mail-Kette (inkl. Ziel-Postfach iCloud Mail), die Regelung für freiwillige E-Mail-Anhänge sowie das Bestätigungs-Statement des Account-Inhabers (Vitali Grecciani).
   - Die Kernverarbeitung der Bankdaten verbleibt zu 100% auf Hetzner in Frankfurt am Main.
