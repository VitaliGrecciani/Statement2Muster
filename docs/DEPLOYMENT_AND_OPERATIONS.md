# Leitfaden für Bereitstellung & Betrieb (Statement2Muster DACH)

**Version:** 1.0.2  
**Zielumgebung:** Hetzner Cloud (Frankfurt am Main, ISO-27001)  
**Sicherheitsniveau:** Zero-Retention In-Memory Conversion  

---

## 1. Architektur- und Sicherheitskonzept

Das Backend von Statement2Muster ist nach dem Prinzip des **Minimal Privileges** und **Zero Durable Storage** konstruiert:

1. **Keine persistenten Kundendaten**: Hochgeladene PDF- und CSV-Dateien verbleiben ausschließlich im flüchtigen Arbeitsspeicher (RAM).
2. **Read-Only Root Filesystem**: Der Container besitzt schreibgeschützten Zugriff auf das Root-Dateisystem.
3. **Flüchtige Mounts (tmpfs)**: Temporäre Pufferungen erfolgen ausschließlich im `tmpfs` mit strikten Größenbeschränkungen (max. 64 MB) und den Flags `noexec, nosuid, nodev`.
4. **Unprivilegierter Ausführungskontext**: Der Prozess läuft unter einem dedizierten System-Benutzer `appuser` (UID 10001).
5. **Frühes ASGI-Gate**: Nicht autorisierte Anfragen (401) oder Anfragen über 30 MB (413) werden vor dem Multipart-Parsing sofort abgewiesen.

---

## 2. Docker Compose Produktionsmanifest (`docker-compose.prod.yml`)

```yaml
version: '3.8'

services:
  api:
    image: statement2muster-api:1.0.2
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: s2m-backend-api
    restart: always
    read_only: true
    user: "10001:10001"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    tmpfs:
      - /tmp:size=64M,noexec,nosuid,nodev
    environment:
      - ENVIRONMENT=production
      - PROJECT_NAME=Statement2Muster DACH
      - VERSION=1.0.2
      - SQLITE_DB_PATH=/app/data/statement2muster_prod.db
      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
      - STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET}
      - JWT_PRIVATE_KEY_PEM=${JWT_PRIVATE_KEY_PEM}
      - JWT_PUBLIC_KEY_PEM=${JWT_PUBLIC_KEY_PEM}
    volumes:
      - s2m-data:/app/data:rw
    ports:
      - "127.0.0.1:8000:8000"
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 128M
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  s2m-data:
    driver: local
```

---

## 3. Reverse-Proxy-Konfiguration (Nginx)

Für den TLS-Terminierungs-Proxy (z.B. Nginx vor Port 8000) gilt folgende Härtung:

```nginx
server {
    listen 443 ssl http2;
    server_name api.statement2muster.com;

    # SSL / TLS 1.3 Strict
    ssl_certificate /etc/letsencrypt/live/api.statement2muster.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.statement2muster.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # Sicherheits-Header
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;

    # Maximaler Request-Body (Budget: 30 MB)
    client_max_body_size 30M;
    client_body_buffer_size 128k;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts für lange PDF-Parsing-Batches
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

---

## 4. Betriebs- und Healthcheck-Monitoring (Ohne PII)

### 4.1. Liveness & Readiness Endpoint (`GET /healthz`)

Der Endpunkt prüft:
- Erreichbarkeit und Lese-/Schreibfähigkeit der Datenbank (SQLite).
- Status der Zero-Retention-Enforcement.

**Beispiel-Antwort:**
```json
{
  "status": "healthy",
  "service": "statement2muster-api",
  "version": "1.0.2",
  "database": "connected",
  "zero_retention": "enforced"
}
```

### 4.2. Zu überwachende Schlüssel-Metriken (Prometheus / Logs)

| Metrik | Zielwert | Bedeutung |
|---|---|---|
| **P95 Konvertierungszeit** | < 2.500 ms | Schnelle Verarbeitung auch bei mehrseitigen PDFs |
| **Solldoppik Balanced Ratio** | > 95% | Anteil mathematisch perfekt stimmiger Auszüge |
| **HTTP 413 Abweisungsrate** | < 0.5% | Erkennung von Oversized-Requests / DoS-Versuchen |
| **HTTP 422 Rate** | Trendstabil | Unbekannte/korrupte Formate (Schutz vor Falschimport) |
| **Stripe Webhook Latency** | < 500 ms | Schnelle Gutschrift von Quota-Kontingenten |
| **RAM-Auslastung Container** | < 350 MB | Keine Speicherlecks bei Dauerbetrieb |

> [!NOTE]
> **Datenschutz im Monitoring**: Logmeldungen enthalten zu keinem Zeitpunkt IBANs, Kundennamen, Dateinamen oder Betragstexte. Als Trace-Bezeichner dient ausschließlich die ersten 8 Zeichen der anonymisierten `tenant_id` oder eine Zufalls-UUID.
