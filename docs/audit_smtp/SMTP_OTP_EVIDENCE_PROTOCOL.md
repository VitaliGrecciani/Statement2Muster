# Statement2Muster — SMTP-OTP Delivery Evidence Protocol

**Datum:** 2026-09-14  
**Referenz:** [24_SMTP_STATUS_AND_FULL_GO_PLAN_2026-09-14.md](../../24_SMTP_STATUS_AND_FULL_GO_PLAN_2026-09-14.md)  
**Umgebung:** Hetzner Cloud (Ubuntu Linux 6.8.0-137-generic)  
**Container:** `s2m-backend-api`  
**Image ID:** `sha256:3bc43a4394be73f5063004761ef9c03fa0527d8e866355421bb5639296e24239` (`statement2muster-api:1.0.3`)  
**Git Commit:** `559dac06918cacd5440df9d1c6fe85c72512a7a5`  

---

## 1. Konfiguration des Mail-Dienstes

- **Provider:** Resend (Region: Europe / Ireland `eu-west-1`)
- **Protokoll:** SMTP über Port 587 (STARTTLS)
- **Authentifizierung:** Resend API-Credential
- **Absenderadresse:** `Statement2Muster <no-reply@statement2muster.com>`
- **Domain-Verifikation:**
  - DKIM: `resend._domainkey.statement2muster.com` (TXT) — **Verified**
  - SPF / Return-Path: `send.statement2muster.com` (MX / TXT) — **Verified**
  - Inbound Mail: Verbleibt unverändert beim Weiterleitungsdienst ImprovMX (`statement2muster.com` MX)

---

## 2. Ablauf der End-to-End-Verifikation

| Schritt | API-Aufruf | HTTP-Status | Ergebnis & Bestätigung |
|---|---|---|---|
| **1. Code anfordern** | `POST /api/v1/auth/request-code` | **200 OK** | 6-stelliger Einmalcode generiert (TTL 10 Min). E-Mail über Resend SMTP erfolgreich an Empfänger zugestellt. Bestätigt im Uvicorn-Log (`Verification email successfully delivered via SMTP`). |
| **2. Code empfangen** | Posteingang des Empfängers | — | E-Mail mit Betreff *"Your Statement2Muster Verification Code"* und Absender `no-reply@statement2muster.com` physisch im Postfach eingegangen. Empfang durch Product Owner (PO) verifiziert. |
| **3. Code einlösen** | `POST /api/v1/auth/token` | **200 OK** | Einmalcode erfolgreich verifiziert und invalidiert (`used = 1`). Asymmetrischer RS256 Bearer JWT ausgestellt (`expires_in = 600`). Tenant mit Initialguthaben registriert. |
| **4. Autorisierte Konvertierung** | `POST /api/v1/convert` | **200 OK** | Anfrage mit `Authorization: Bearer <JWT>` erfolgreich durch den isolierten Prozess-Supervisor verarbeitet. 1 Buchung im kanonischen Format zurückgegeben. |

---

## 3. Status nach Entscheidung 24

Gemäß Entscheidung 24 des Chef-Architekten ist die **funktionale SMTP-OTP-Zustellkette offiziell angenommen und geschlossen**.
