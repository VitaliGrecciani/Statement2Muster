# Statement2Muster — Hetzner Support Mail Verification Evidence

**Stand:** 2026-09-22  
**Infrastruktur:** Hetzner Cloud GmbH, Rechenzentrum Frankfurt am Main (ISO/IEC 27001)  
**Host IP:** `46.225.95.36`  
**Hostname:** `mail.statement2muster.com`  
**Support-Postfach:** `support@statement2muster.com`  
**Rechtsgrundlage:** Hetzner Auftragsverarbeitungsvertrag (AVV gem. Art. 28 DSGVO, abgeschlossen mit Vitali Grecciani)  

---

## 1. Technischer Aufbau auf dem Hetzner-Host (Frankfurt am Main)

1. **E-Mail-Server-Container (`s2m-mailserver`):**
   - Software: `docker-mailserver` (Postfix 3.10.13 + Dovecot 2.4.1 + OpenDKIM + OpenDMARC)
   - Konfigurationspfad: `/opt/statement2muster/mail/`
   - Maildir-Speicherpfad: `/var/mail/statement2muster.com/support/` (lokaler Host-Storage in Frankfurt am Main)
   - Aktive und öffentlich erreichbare Ports:
     * Port 25 (SMTP): Direkte Inbound-Zustellung aus dem Internet (verifiziert per Test-NetConnection)
     * Port 993 (IMAPS): Sicherer TLS-Postfachzugriff für Mail-Clients (verifiziert per Test-NetConnection)
     * Port 587 (Submission): Authentifizierter Postausgang
     * Port 465 (SMTPS): Verschlüsselter Postausgang
2. **Webmail-Interface (`s2m-roundcube`):**
   - Software: Roundcube Webmail
   - Interner Port: `127.0.0.1:8150`
   - Reverse-Proxy: Nginx auf Host `46.225.95.36` (`/etc/nginx/sites-enabled/mail.statement2muster.com`), HTTP 200 OK verifiziert.
3. **DKIM & Authentifizierung:**
   - DKIM-Schlüsselpaar generiert: `/tmp/docker-mailserver/opendkim/keys/statement2muster.com/mail.private`
   - Selektor: `mail._domainkey.statement2muster.com`
   - DMARC-Policy: `v=DMARC1; p=quarantine; rua=mailto:support@statement2muster.com; pct=100; sp=quarantine`

---

## 2. Nachweis der direkten E-Mail-Zustellung & Header-Audit (22. September 2026)

Synthetische Test-E-Mail übergeben direkt an den Postfix-Daemon auf Host `46.225.95.36:25` und ausgelesen aus dem Maildir (`/opt/statement2muster/mail/mail-data/statement2muster.com/support/new/`):

```text
Return-Path: <vitogr24@gmail.com>
Delivered-To: support@statement2muster.com
Received: from mail.statement2muster.com
	by mail.statement2muster.com with LMTP
	id 73nDL0dWsmrFAwAAQ22iMQ
	(envelope-from <vitogr24@gmail.com>)
	for <support@statement2muster.com>; Tue, 22 Sep 2026 10:19:51 +0000
Received: from localhost (localhost [127.0.0.1])
	by mail.statement2muster.com (Postfix) with ESMTP id BD09549858
	for <support@statement2muster.com>; Tue, 22 Sep 2026 10:19:51 +0000 (UTC)
Received: from gmail.com (046125146183.public.t-mobile.at [46.125.146.183])
	by mail.statement2muster.com (Postfix) with ESMTPS id 7CF4E4984F
	for <support@statement2muster.com>; Tue, 22 Sep 2026 10:19:51 +0000 (UTC)
Content-Type: multipart/mixed; boundary="===============2066216685574353389=="
MIME-Version: 1.0
From: vitogr24@gmail.com
To: support@statement2muster.com
Subject: Public DNS Inbound Test - Hetzner - 2026-09-22 10:19:51 UTC
Date: Tue, 22 Sep 2026 10:19:51 +0000
Message-ID: <public-dns-audit-1790072391@gmail.com>
```

### Feststellungen & Audit-Konformität:
- **Kein externer Relay:** E-Mail wird direkt von Postfix auf `mail.statement2muster.com` entgegengenommen und per LMTP im Dovecot-Maildir auf Hetzner abgelegt.
- **Speicherort:** Ausschließlich auf Hetzner-Server im ISO/IEC 27001-zertifizierten Rechenzentrum Frankfurt am Main.
- **Keine Weiterleitung an Dritte:** ImprovMX und Google/Gmail sind aus dem Support-Empfangspfad vollständig eliminiert.
- **Verschlüsselung:** Transportverschlüsselung (TLS 1.3 / STARTTLS) beim SMTP-Inbound und IMAPS-Abruf.
- **Aufbewahrung:** Support-E-Mails und freiwillig beigefügte Anhänge unterliegen einer Politik begrenzter Aufbewahrung (Ticket Closure Policy) und werden nach Abschluss des Support-Vorgangs manuell gelöscht (keine dauerhafte Archivierung).
