# Statement2Muster — Prüfung der gelieferten Linux-Evidenz

Datum: 2026-09-14. Referenz: Entscheidung 16. Gegenstand: docs/audit_c07_hetzner/{C07_EVIDENCE_REPORT.md,results.json,probe_c07_hetzner.py} und neues docker-compose.prod.yml.

**Entscheidung: Linux-Konfiguration und begrenzte Smoke-Test-Evidenz angenommen; C07 insgesamt noch nicht geschlossen. Full GO bleibt ausstehend.** Dies ist eine Prüfung der lokal gelieferten Messungen und Testlogik, keine unabhängig wiederholte Messung auf dem Hetzner-Host. Die Probe wurde nicht erneut ausgeführt: Sie verändert die Container-Datenbank, liest den Signierschlüssel und fordert eine OTP-E-Mail an.

## 1. Angenommene Teilevidenz

Die gelieferten Ergebnisse berichten memory.max=536870912, cpu.max='100000 100000', UID 10001, einen erfolglosen Schreibversuch auf dem read-only Root-Dateisystem und /tmp als 64-MiB-tmpfs. Das Skript liest hierfür konkrete Containerwerte aus. Damit liegt erstmals konkrete Linux-Runtime-Evidenz für die vorgesehenen Grenzen vor, nicht nur ein Compose-Beispiel.

Ebenfalls als begrenzte Laufnachweise angenommen: normale Konvertierung 200 mit zwei Transaktionen, Zeilenbudget 413, Konfigurationswerte 2/4, ein Prozessbaum-Snapshot ohne sichtbare Zombies und keine Treffer des angegebenen IBAN-Canarys in den abgefragten /tmp-/Containerlog-Bereichen. SMTP 502 bestätigt den Fehlerpfad, nicht erfolgreiche Mailzustellung.

Die Verdrahtungsprüfung startet einen separaten docker-exec-Python-Prozess und liest dort Settings/Supervisor. Das unterstützt die Containerkonfiguration, ist keine direkte Inspektion des laufenden Uvicorn-Singletons.

## 2. Warum der beantragte Gesamtabschluss nicht folgt

### C07 — laufender Worker-Kill nicht nachgewiesen

Das Ergebnis lautet ausdrücklich **'Parser admission timeout'**. Es gibt keinen protokollierten gestarteten Worker mit Bereitschafts-Handshake und keinen Nachweis seiner Beendigung. Die 1-ms-Deadline kann bereits bei der Aufnahme ablaufen. active_children=[] ist auch dann wahr, wenn überhaupt kein Kind gestartet wurde.

Die Probe läuft zusätzlich in einem separaten docker-exec-Prozess; active_children bezieht sich auf dessen Kinder, nicht die Kinder des Uvicorn-Prozesses. Ein anschließender docker-top-Snapshot mit einem Prozess ersetzt keine Lifecycle-Messung.

**Nachreichen:** tatsächlicher Supervisor-/Route-Lauf mit Worker-PID und Handshake vor Timeout, blockierender Arbeit bzw. CPU-Schleife, bestätigtem Exit/reaping und erneuter erfolgreicher Konvertierung. Die bereits vereinbarten Crash-/Cancellation-/Kill-Fehler- und OOM-/Überlast-Recovery-Prüfungen sind im gelieferten Skript nicht enthalten. Ein RAM-Limit belegt dessen Konfiguration, nicht Recovery beim Erreichen des Limits.

### Neuer Manifestbefund — P1: Geschäfts- und Sicherheitszustand auf tmpfs

docker-compose.prod.yml setzt **SQLITE_DB_PATH=/tmp/statement2muster_prod.db**. /tmp ist tmpfs; ein persistenter Datenbank-Mount fehlt. Die Datenbank enthält nicht nur flüchtige Bankdateien, sondern auch Tenants, Entitlements, Stripe-Event-Inbox, Quoten/Reservierungen, Auth-Budgets und Token-Widerrufe. Bei Container-Stopp/Neustart ist dieser Zustand nicht dauerhaft gesichert.

Das gefährdet bezahlten Zugang, Idempotenz und die Beständigkeit von Quoten/Sperren. Zero Retention der Finanzdateien verlangt nicht, diesen notwendigen Anwendungszustand ebenfalls flüchtig zu halten. Dieser Befund betrifft das gelieferte Manifest; die effektive DB-Datei des laufenden Remote-Containers wurde hier nicht unabhängig geprüft.

**Korrektur:** Anwendungszustand in persistentem, zugriffsbeschränktem Datenbank-Volume bzw. geeignetem Datenbankdienst speichern; Finanzuploads/-resultate weiterhin aus dauerhaftem Storage ausschließen. Restart-/Migrationstest muss Entitlements, Stripe-Inbox und Sicherheitszustand erhalten. Erst dann dieses Manifest als Produktionsmanifest freigeben.

### Retention — begrenzter Canary-Test statt vollständiger Abnahme

Der Canary stammt aus einer erfolgreichen CSV-Konvertierung. Gesucht wird nur nach diesem IBAN-String in /tmp und docker logs. Nicht enthalten: derselbe Nachweis auf Fehler-/Timeout-/Crash-Pfaden, Proxy-Puffer/Logs, weitere persistente Mounts oder RAM-Cache-Ablauf. Der separat erzeugte Name wird nicht gesucht. Leere Suchausgabe allein sollte außerdem durch geprüfte Exit-Codes ergänzt werden, damit Suchfehler nicht als Trefferfreiheit gelten.

**Nachreichen:** gezielte Canary-Matrix auf den bereits vereinbarten Pfaden mit dokumentierten Suchbereichen und erfolgreichen Prüfkommandos. Healthz.zero_retention='enforced' ist eine Anwendungsaussage, keine unabhängige Messung.

### Artefaktbindung — Dockerfile-Hash ist kein Quellcode-Nachweis

Das Skript trägt die Image-ID als feste Zeichenkette ein; es ermittelt sie nicht mit docker inspect. Gleiche Dockerfile-/requirements-Hashes beweisen nicht gleiche app/-Quellen. Anforderungen mit Versionsbereichen ergeben außerdem nicht automatisch dieselben installierten Pakete.

**Nachreichen:** tatsächlich laufende Container-Image-ID aus Inspect, Zuordnung zum Git-Commit bzw. Hashmanifest der app/-Quellen und installierte Paketversionen. Rohbelege ohne Geheimnisse archivieren. Die gemeldete Image-ID wird nicht als falsch bezeichnet; ihre Provenienz ist mit dem vorliegenden Skript allein nicht verifiziert.

## 3. Verbleibender Full-GO-Bereich

Die fachlichen Abnahmen können parallel vorbereitet werden; C07 ist noch nicht vollständig erledigt.

| Bereich | Verbleibender Nachweis |
|---|---|
| C07/Betrieb | Tatsächlicher Worker-Kill, Crash/Cancellation/OOM/Überlast-Recovery, persistente Zustandsdatenbank, vollständige Retention-Matrix, Artefaktbindung |
| SMTP/Managed-Flow | OTP kommt in realer Testmailbox an; installierte Extension → Anmeldung → managed Konvertierung → Logout. Der Bericht erzeugt Token administrativ und setzt PRO direkt in der DB; das ist zulässiges technisches Bootstrapping, aber keine Benutzer- oder Billing-Abnahme |
| Stripe | Sandbox-Lifecycle einschließlich tatsächlichem Plan/Zugang/Zeitraum, asynchroner Zahlung, Kündigung/Erstattung und Wiederholungen |
| Auth/DB | Widerruf bei Worker-/DB-Fehlern, Restart-Persistenz und Migration |
| DATEV/BMD | Tatsächliche Importprotokolle und fachliche Prüfung der vorgesehenen Pilotprofile |
| Datenschutz/AVV | Zur realen Hosting-/Datenfluss-/Aufbewahrungskonfiguration passende Unterlagen und Onboarding |

## 4. Nächster gezielter Schritt

Zuerst die tmpfs-Datenbank im Release-Manifest korrigieren. Danach ein einziges ergänzendes Linux-Abnahmepaket liefern: Image-/Quellbindung, Restart-Persistenz, gestartete Worker mit Handshake und vollständiger Lifecycle-/Recovery-/Canary-Matrix. Bestehende erfolgreiche cgroup-/UID-/Rootfs-/413-Messungen müssen nicht als neue offene Codefehler behandelt werden; nach Manifeständerung genügt ihre Bestätigung für den endgültigen Build.

**Status: C07 teilweise abgenommen; Full GO für reale Kundenauszüge nicht erteilt.** SMTP-, Stripe- und fachliche Tests können mit Testkonten und synthetischen Daten parallel weitergehen.
