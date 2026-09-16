# Statement2Muster — Legal, Privacy & Compliance Evidence Dossier

**Status:** Completed (Stage 2 / Organisatorisch-rechtlicher Kontur)  
**Datum:** 2026-09-16  
**Projekt:** Statement2Muster DACH (Grecciani Labs)  
**Inhaber / Diensteanbieter:** Vitali Grecciani (Einzelunternehmer, Roseggergasse 37, 3400 Klosterneuburg, Österreich)  
**Aufsichtsbehörde:** Österreichische Datenschutzbehörde (DSB), Barichgasse 40-42, 1030 Wien  

---

## 1. Übersicht und rechtlicher Rahmen (Governing Law)

Statement2Muster ist ein spezialisierter B2B-Cloud-Dienst zur Konvertierung und Strukturierung digitaler Kontoauszüge (American Express, Wise, PayPal, Bank-PDFs/CSVs) in die standardisierten Formate des deutschen und österreichischen Rechnungswesens (**DATEV Format EXTF** und **BMD NTCS**).

Der Dienst unterliegt streng den europäischen und österreichischen Rechtsvorschriften:
- **Verordnung (EU) 2016/679 (DSGVO):** Vollständige Erfüllung der Rechenschaftspflicht (Art. 5 Abs. 2 DSGVO) und Bereitstellung eines standardisierten Auftragsverarbeitungsvertrags (AVV) nach Art. 28 DSGVO für Kanzleien und Unternehmen.
- **E-Commerce-Gesetz (ECG):** Impressum und Anbieterkennzeichnung gemäß § 5 ECG.
- **Mediengesetz (MedienG):** Offenlegungspflichten gemäß § 25 MedienG.
- **Telekommunikationsgesetz (TKG 2021):** Strikte Einhaltung des § 165 Abs. 3 TKG 2021 (vollständiger Verzicht auf zustimmungspflichtige Marketing- oder Tracking-Cookies).
- **Konsumentenschutzgesetz (KSchG) & Fern- und Auswärtsgeschäfte-Gesetz (FAGG):** Verbraucherschutz- und Widerrufsbelehrung inklusive 14-Tage-Geld-zurück-Garantie.

---

## 2. Vollständige Kette der Unterauftragsverarbeiter (Sub-processor Chain)

Gemäß Art. 28 Abs. 2 und Abs. 4 DSGVO sowie den Anforderungen des Hauptarchitekten (Решение № 24) ist die Kette der technischen Subunternehmer lückenlos auditiert, dokumentiert und in den vertraglichen AVV eingebunden:

| Subprozessor | Sitz / Land | Funktion im Dienst | Übertragene Daten | Rechtsgrundlage & Garantien |
|---|---|---|---|---|
| **Hetzner Online GmbH** | Industriestr. 25, 91710 Gunzenhausen, **Deutschland** | ISO/IEC 27001-zertifizierte Cloud-Infrastruktur / Rechenzentrumsbetrieb in **Frankfurt am Main** | Temporäre In-Memory-Verarbeitung der Auszüge, verschlüsselte Session-Token, Lizenz-Quota | Art. 28 DSGVO (AVV mit Hetzner), Serverstandort ausschließlich Bundesrepublik Deutschland |
| **Stripe Payments Europe, Ltd.** | 1 Grand Canal Street Lower, Dublin 2, **Irland (EU)** | Autorisierte Zahlungsabwicklung, Checkout-Sessions, wiederkehrende Abonnements | Kaufmännische Metadaten (E-Mail, Rechnungsbetrag, Zahlungsstatus, Stripe Customer- & Sub-IDs) | Art. 6 Abs. 1 lit. b DSGVO, PCI-DSS Level 1 Service Provider; keine Weiterleitung von Bankauszugsdaten an Stripe |
| **Resend, Inc.** | San Francisco, CA, **USA / EU-Routing** | Transaktionale E-Mail-Infrastruktur zur Zustellung von Einmalpasswörtern (OTP / Login-Codes) | Nutzer-E-Mail-Adresse und temporärer 6-stelliger Einmalcode (Gültigkeit: 10 Minuten) | Art. 46 DSGVO (EU-Standardvertragsklauseln / Data Processing Addendum mit Resend); Daten minimiert auf E-Mail + OTP |
| **ImprovMX (Kekanto SAS)** | 60 rue François 1er, 75008 Paris, **Frankreich (EU)** | MX-Routing und Weiterleitung von geschäftlichen Support- und Kontakt-E-Mails (`support@statement2muster.com`) | E-Mails an Kanzlei-Support und Kontaktadressen | Art. 28 DSGVO; Verarbeitung und Routing ausschließlich innerhalb der Europäischen Union |

---

## 3. Technische Datenschutzgarantien: Zero-Durable-Storage & In-Memory-Verarbeitung

Für Steuerberatungskanzleien und Wirtschaftsprüfer (B2B) ist das Berufsgeheimnis (§ 80 StBerG in Deutschland, § 87 WTBG in Österreich) und der Schutz von Mandantendaten essenziell. Statement2Muster implementiert eine architektonische Datenschutzgarantie nach dem Prinzip **Privacy by Design & by Default (Art. 25 DSGVO)**:

1. **Flüchtige Verarbeitung (In-Memory Only):**
   - Hochgeladene PDF- und CSV-Dateien werden direkt im flüchtigen Arbeitsspeicher (RAM) der Engine (`backend/app/parsers/`) geparst.
   - Zu keinem Zeitpunkt werden Auszugsdateien oder darin enthaltene Buchungsinhalte auf Server-Festplatten, SSDs oder temporären Dateisystemen (`/tmp`) gespeichert.
   - Nach erfolgreicher Konvertierung oder Verbindungsabbruch werden die Datenstrukturen unverzüglich im RAM freigegeben.

2. **Datenbank-Isolation (Zero Statement Retention):**
   - Die relationale Datenbank (`sqlite:///` bzw. PostgreSQL) speichert ausschließlich administrative Identitäten:
     - `User`: `id`, `email`, `created_at`
     - `Entitlement`: `plan_name`, `quota_limit`, `quota_used`, `paid_through`, `stripe_subscription_id`, `stripe_customer_id`
     - `RevokedToken`: `jti`, `revoked_at`, `expires_at` (Sicherheits-Blockliste für JWTs)
   - **Es existiert keine Tabelle und kein Feld für Buchungstexte, IBANs, Beträge oder Kontoauszugsinhalte.**

3. **Transport- und Sitzungssicherheit:**
   - Durchgehende TLS 1.3 / TLS 1.2 Transportverschlüsselung mit Perfect Forward Secrecy.
   - Authentifizierung über kryptografisch signierte JWT (EdDSA / Ed25519) mit strengem Invalidation- & Revocation-Mechanismus (geprüft und abgenommen in Managed Extension Review).

4. **Zero-Tracking-Grundsatz (Cookie-free Architecture):**
   - Keine zustimmungspflichtigen Werbe- oder Marketing-Cookies.
   - Kein Google Analytics, kein Meta-Pixel, keine externen CDN-Skripte im Produktionspfad.
   - Lediglich technisch notwendiger `LocalStorage` im Browser für das aktive Sitzungs-Token (gemäß § 165 Abs. 3 TKG 2021 einwilligungsfrei).

---

## 4. Übersicht der veröffentlichten Rechtsdokumente

Alle Dokumente sind über die Hauptnavigation und den Footer der Landingpage sowie im Chrome/Firefox Extension Sidepanel direkt erreichbar:

| Dokument | URL-Pfad | Rechtsgrundlage & Inhalt | Status |
|---|---|---|---|
| **Impressum & Offenlegung** | `https://statement2muster.com/impressum` | § 5 ECG & § 25 MedienG (Österreich); vollständige Kontaktdaten, Vertretungsberechtigung, Gewerbegegenstand | **Verifiziert & Live** |
| **Datenschutzerklärung** | `https://statement2muster.com/datenschutz` | Art. 13 & 14 DSGVO; vollständige Aufklärung über In-Memory-Verarbeitung, Hetzner, Stripe, Resend, ImprovMX, Betroffenenrechte und DSB Wien | **Verifiziert & Live** |
| **Auftragsverarbeitungsvertrag (AVV)** | `https://statement2muster.com/avv` | Art. 28 DSGVO; standardisierter Vertrag für Kanzleien mit granularen Datenkategorien, TOMs (§ 5) und Subprozessoren (§ 6) | **Verifiziert & Live** |
| **Allgemeine Geschäftsbedingungen (AGB)** | `https://statement2muster.com/agb` | B2B- & B2C-Vertragsbedingungen, Lizenzmodelle (Starter, PRO, Lifetime), Kündigungsfristen | **Verifiziert & Live** |
| **Widerrufsbelehrung & Refund Policy** | `https://statement2muster.com/widerruf` | KSchG / FAGG / § 355 BGB; 14-Tage gesetzliches Widerrufsrecht + 14-Tage unbürokratische Geld-zurück-Garantie | **Verifiziert & Live** |

---

## 5. Konformitätsbestätigung für den Hauptarchitekten

Mit den durchgeführten Aktualisierungen sind:
1. Die in **Решение № 24 (раздел 2)** зафиксированные требования к актуализации Hosting-, Privacy- и AVV-материалов под фактическую цепочку **Hetzner, Resend и ImprovMX** полностью исполнены.
2. Категории обрабатываемых данных четко разграничены на временные (flüchtige In-Memory-Verarbeitung) и административные (E-Mail, Stripe-IDs).
3. Права пользователей и контакты надзорного органа (Österreichische Datenschutzbehörde) зафиксированы.
4. Сквозная связность ссылок в веб-интерфейсе и расширении Chrome обеспечена.
