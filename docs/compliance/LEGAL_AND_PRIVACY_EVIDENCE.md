# Statement2Muster — Legal, Privacy & Compliance Evidence Dossier

**Status:** Updated per Chief Architect Decision № 42  
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
* **Aufgabe:** Ausführung des Docker-Containers `statement2muster-api`, Parsing und Strukturierung von Auszugsdaten.
* **Garantie:** Die Auszugsverarbeitung verbleibt zu 100% in Deutschland. **Kein externer Hilfsdienstleister (weder Stripe noch Resend noch ImprovMX) erhält Zugriff auf hochgeladene Auszüge oder Buchungsinhalte.**

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
  * **Rolle:** E-Mail-Routing von `support@statement2muster.com` an das Kanzlei-Postfach des Verantwortlichen (`vitali@grecciani.com`).
  * **Daten:** Freiwillige Support-E-Mails.

---

## 3. Technische Speicher- und Sicherheitsarchitektur

### A. Server-Verarbeitung: Flüchtige In-Memory-Verarbeitung & RAM-Cache
1. **Flüchtige Verarbeitung:**
   - Eingehende PDF- und CSV-Dateien werden direkt im Arbeitsspeicher (RAM) bzw. in temporären RAM-Dateisystemen (Linux `tmpfs`) verarbeitet.
   - Es findet keine Speicherung von Auszugsinhalten auf Festplatten oder SSDs statt.
2. **Idempotenter RAM-Ergebnis-Cache:**
   - Gemäß Konfiguration `RAM_CACHE_TTL_SECONDS = 600` wird das Konvertierungsergebnis für **maximal 10 Minuten** in einem flüchtigen Arbeitsspeicher-Cache gehalten (`idempotent_result_cache`).
   - Zweck: Ermöglicht dem Benutzer, das Ergebnis nach der Konvertierung ohne erneuten Upload wiederholt in verschiedenen Formaten (DATEV EXTF, BMD NTCS) herunterzuladen.
   - Nach Ablauf von 10 Minuten oder bei einem Server-Neustart wird der Cache unwiderruflich aus dem RAM verworfen.
3. **Datenbank-Isolation (Zero Statement Retention):**
   - Die Datenbank speichert ausschließlich administrative Datensätze (`users`, `entitlements`, `revoked_tokens`).
   - Es existieren keine Tabellen für Buchungstexte, IBANs oder Auszugstransaktionen.

### B. Kryptografie und Sitzungsverwaltung
- **Signaturalgorithmus:** Kryptografisch asymmetrisch **signierte** Tokens (**RS256 / RSA-2048**) gemäß Architect ADR-001 (nicht Ed25519 und nicht symmetrisch).
- **Transportverschlüsselung:** Durchgehend TLS 1.3 / TLS 1.2 mit Perfect Forward Secrecy.
- **Sitzungsdauer:** Access Token läuft nach 10 Minuten ab (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 10`).

### C. Clientseitiges Speicherverhalten (Browser & Chrome Extension)
- **Webbrowser:** Speichert lediglich das signierte RS256-Sitzungstoken im `localStorage` zur Aufrechterhaltung der aktiven Sitzung.
- **Chrome Extension:** Speichert Metadaten der Historie (`statementHistory`: Dateiname, Zeilenzahl, Zeitstempel) **ausschließlich lokal auf dem Gerät des Benutzers** in `chrome.storage.local`. Diese Daten werden nicht an den Server übertragen und können vom Benutzer jederzeit mit einem Klick auf die Schaltfläche „Verlauf leeren“ vollständig gelöscht werden.

---

## 4. Status der öffentlich publizierten Dokumente

| Dokument | URL-Pfad | Wesentliche Inhalte & Anpassungen | Status |
|---|---|---|---|
| **Impressum** | `/impressum` | Anbieterkennzeichnung § 5 ECG / § 25 MedienG (Vitali Grecciani, Klosterneuburg) | **Live & verifiziert** |
| **Datenschutz** | `/datenschutz` | Art. 13/14 DSGVO: 10-Min-RAM-Cache, tmpfs, Hetzner, Stripe, Resend (Plus Five Five Inc., SCCs), ImprovMX, clientseitige Historie, DSB Wien | **Aktualisiert (Decision 42)** |
| **AVV** | `/avv` | Art. 28 DSGVO: TOMs § 5 (tmpfs, RAM TTL 600s), § 6 getrennte Subprozessoren (Hetzner als Kern-Prozessor; Stripe/Resend/ImprovMX als Hilfsdienste) | **Aktualisiert (Decision 42)** |
| **AGB** | `/agb` | B2B/B2C-Bedingungen, Lizenzierung (Starter, PRO, Lifetime), Kündigungsregeln | **Live & verifiziert** |
| **Widerruf** | `/widerruf` | Verbraucher-Widerruf (14 Tage) + 14-Tage Geld-zurück-Garantie | **Live & verifiziert** |

---

## 5. Konformitätsfazit für das Audit

Mit den vorgenommenen Anpassungen:
1. Sind alle in **Решение № 42** identifizierten Widersprüche behoben (exakte 600s RAM-Cache-TTL, RS256-Signatur, tmpfs-Kennzeichnung, lokale Chrome-Historie).
2. Wurden die tatsächlichen Firmenbezeichnungen und Sitze der US-Dienstleister (Plus Five Five, Inc. und ImprovMX Inc.) mit ihren Rechtsgrundlagen (EU-Standardvertragsklauseln / DPA) nachgewiesen und im separaten Register dokumentiert.
3. Ist die Kernverarbeitung der Bankdaten strikt auf Hetzner (Frankfurt, Deutschland) isoliert.
