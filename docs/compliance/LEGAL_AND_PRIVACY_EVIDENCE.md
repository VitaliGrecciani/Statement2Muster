# Statement2Muster — Legal, Privacy & Compliance Dossier (Stage 2)

**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Verantwortlicher (Controller):** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Stand:** 2026-09-22  
**Status:** Aktualisiert zur finalen Schließung von Stage 2 nach Решение № 47 des Hauptarchitekten (Konsolidierung des Support-Postfachs auf Hetzner Online GmbH unter Art. 28 DSGVO AVV, vollständiger Ausschluss externer Relay- und US-Postfachdienste wie ImprovMX und Google LLC).

---

## 1. Referenzen und Kern-Dokumente

* **Vollständiges Vertrags- und DPA-Register:** [`docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md)  
* **Bilateraler Muster-AVV für Pilot-Kanzleien:** [`docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md)  
* **Hetzner Support Mail Verification Evidence:** [`docs/compliance/HETZNER_MAIL_RECEIPT_EVIDENCE.md`](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/HETZNER_MAIL_RECEIPT_EVIDENCE.md)  
* **Resend DPA (Stand 27. August 2026):** [Offizielle Version](https://resend.com/legal/dpa)  
* **Stripe DPA (Stand 16. Februar 2024):** [Offizielle Version](https://stripe.com/en-at/legal/dpa)  

---

## 2. Dienstleisterketten und Datenflüsse

### A. Kernverarbeitung der Kontoauszüge (Pipeline 1)
* **Dienstleister:** **Hetzner Online GmbH**, Industriestr. 25, 91710 Gunzenhausen, Deutschland.
* **Standort der Verarbeitung:** Rechenzentrum Frankfurt am Main, Deutschland (ISO/IEC 27001 zertifiziert).
* **Vertragliche Grundlage:** Auftragsverarbeitungsvertrag (AVV gem. Art. 28 DSGVO) im Kundenkonto aktiv.
* **Garantie:** Die Auszugsverarbeitung verbleibt zu 100% in Deutschland. **Kein externer Hilfsdienstleister (weder Stripe noch Resend) erhält im regulären Konvertierungspfad Zugriff auf hochgeladene Auszüge oder Buchungsinhalte.**

### B. Zahlungsabwicklung und Lizenzverwaltung (Pipeline 2)
* **Dienstleister:** **Stripe Payments Europe, Ltd.**, 1 Grand Canal Street Lower, Dublin, D02 H210, Irland.
* **Rolle:** Eigenständiger Verantwortlicher für Zahlungsabwicklung; Auftragsverarbeiter für Kundenstammdaten.
* **Daten:** Ausschließlich kaufmännische Metadaten (E-Mail, Rechnungsbetrag, Customer ID, Subscription ID). Keine Finanz- oder Auszugsdaten.
* **Vertragliche Grundlage:** Stripe DPA (Fassung vom 16.02.2024) mit Standardvertragsklauseln der EU (SCCs).

### C. Authentifizierung und Support-Postfach (Pipeline 3)
* **Dienstleister für OTP-Zustellung (3A):** **Plus Five Five, Inc. (dba Resend)**, San Francisco, CA, USA (Delaware Corp).
  * **Rolle:** Auftragsverarbeiter für E-Mail-Zustellung von Einmalpasswörtern.
  * **Daten:** E-Mail-Adresse und temporärer 6-stelliger Einmalcode (Gültigkeit: 10 Minuten).
  * **Exakte Vertragsfassung & Übermittlungsgrundlage:** *Resend Data Processing Addendum (DPA)* — **Last update: August 27th, 2026** mit Standardvertragsklauseln der EU (SCCs) gemäß Art. 46 Abs. 2 lit. c DSGVO (Modul 2 Controller-to-Processor und Modul 3 Processor-to-Processor).
* **Dienstleister für Support-Postfach & Inbound Mail (3B):** **Hetzner Online GmbH**, Industriestr. 25, 91710 Gunzenhausen, Deutschland.
  * **Rolle:** Auftragsverarbeiter für Hosting des Mailservers (`s2m-mailserver` / Postfix / Dovecot / Roundcube) auf Host `46.225.95.36` im Rechenzentrum Frankfurt am Main.
  * **Rechtsgrundlage:** Hetzner Auftragsverarbeitungsvertrag (Art. 28 DSGVO).
  * **Verschlüsselung:** Transportverschlüsselung (TLS 1.3 / STARTTLS / IMAPS) bei SMTP-Empfang und Postfachabruf (keine Ende-zu-Ende-Inhaltsverschlüsselung).
  * **Aufbewahrung & Löschung:** Politik begrenzter Aufbewahrung (Limited Support Retention / Ticket Closure Policy). Support-E-Mails und freiwillig übermittelte Beispieldateien werden streng zweckgebunden genutzt und nach Ticketbeendigung manuell gelöscht.
  * **Ausschluss Dritter:** ImprovMX und Google LLC / Gmail sind vollständig aus der Support-Kette ausgeschlossen und decommissioned.

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
- **Chrome Extension (`chrome.storage.local`):**
  - Speichert die letzten bis zu 15 Konvertierungen lokal: Dateiname, Zeilenzahl, Gesamtsumme (`totalSum`), Zeitstempel sowie den **vollständigen generierten CSV-Text** (`csvText`).
  - **Reine Client-Speicherung:** Diese Daten verbleiben zu 100% auf dem Endgerät des Nutzers und werden niemals an unsere Server übertragen.
  - **Kontrolle:** Der Nutzer kann diese Historie jederzeit mit einem Klick auf die Schaltfläche „Verlauf leeren“ vollständig aus seinem Browser löschen.
  - Das Server-Prinzip „Zero Durable Storage“ erstreckt sich per Definition nicht auf diese lokalen Browserdaten oder lokal heruntergeladene Dateien.

---

## 4. Status der öffentlich publizierten Dokumente & AVV-Prozess

| Dokument | URL-Pfad / Ablage | Wesentliche Inhalte & Anpassungen | Status |
|---|---|---|---|
| **Impressum** | `/impressum` | Anbieterkennzeichnung § 5 ECG / § 25 MedienG (Vitali Grecciani, Klosterneuburg) | **Live & verifiziert** |
| **Datenschutz** | `/datenschutz` | Art. 13/14 DSGVO: RAM/tmpfs, TTL 600s, Hetzner (Kernverarbeitung + Support-Mail in Frankfurt), Stripe, Resend (DPA Stand 27.08.2026, SCCs), Chrome-Historie (15 Einträge mit csvText und totalSum), DSB Wien | **Aktualisiert (22.09.2026)** |
| **AVV (Online)** | `/avv` | Art. 28 DSGVO: TOMs § 5 (tmpfs, RAM TTL 600s idempotenter Replay ohne Kontingentverlust, lokale 15-Einträge-Historie), § 6 getrennte Subprozessoren (Hetzner Kern- & Mail-Prozessor; Stripe/Resend Hilfsdienste), § 9 RAM Deallocation | **Aktualisiert (22.09.2026)** |
| **Muster-AVV (Bilateral)** | `docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md` | Vollständige druckreife zweisprachig/deutsche AVV-Vereinbarung inkl. Anlagen (TOMs, 3 Subprozessoren: Hetzner, Stripe, Resend) zur individuellen Gegenzeichnung für Kanzleien und Pilot-Betriebe vor der Verarbeitung von Echtdaten | **Aktualisiert (22.09.2026)** |
| **AGB** | `/agb` | B2B/B2C-Bedingungen, Lizenzierung (Starter, PRO, Lifetime), Kündigungsregeln | **Live & verifiziert** |
| **Widerruf** | `/widerruf` | Verbraucher-Widerruf (14 Tage) + 14-Tage Geld-zurück-Garantie | **Live & verifiziert** |

---

## 5. Konformitätsfazit für das Audit (Vollständige Schließung Stage 2)

Mit den in diesem Prüfpaket vorgenommenen Anpassungen:
1. Sind alle Feststellungen aus **Решение № 47** des Hauptarchitekten restlos erfüllt:
   - **Beseitigung der Google/Gmail-Lücke:** Der persönliche Gmail-Account und das ImprovMX-Relay wurden vollständig aus der Kette entfernt.
   - **Konsolidierung unter Art. 28 DSGVO AVV:** Die gesamte Support-Mail-Infrastruktur (`support@statement2muster.com`) wird direkt auf dem Server bei der Hetzner Online GmbH in Frankfurt am Main betrieben und ist zu 100% durch den bestehenden Hetzner AVV gedeckt.
   - **Präzise Terminologie (Entscheidung 47):** E-Mail-Verschlüsselung wird korrekt als Transportverschlüsselung (TLS 1.3 / STARTTLS / IMAPS) deklariert. Für Support-Mails gilt die Richtlinie begrenzter Aufbewahrung mit manueller Löschung nach Ticketbeendigung; das Zero-Durable-Storage-Versprechen ist strikt auf den Kern-Konvertierungspfad begrenzt.
   - **Synchronisierte Dokumentation:** Alle Dokumente (`landing/avv.html`, `landing/datenschutz.html`, `docs/compliance/AVV_PILOT_MUSTER_VORLAGE.md` und `docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md`) sind vollständig synchronisiert.
   - **Inhaber-Bestätigung:** Das datierte [Bestätigungs-Statement](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/compliance/DPA_AND_CONTRACTS_REGISTRY.md#5-erklärung-des-verantwortlichen-owner-acceptance-statement) des Inhabers (Vitali Grecciani) vom 22.09.2026 bestätigt diese lückenlose vertragliche und operative Basis.
2. Der organisatorisch-rechtliche Kontur (Stage 2) ist damit vollständig, widerspruchsfrei und bereit für den finalen **FULL GO**-Verdikt.
