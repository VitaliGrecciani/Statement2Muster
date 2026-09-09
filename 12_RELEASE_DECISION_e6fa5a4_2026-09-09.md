# Statement2Muster v1.0.2 — Entscheidung zu e6fa5a4

Datum: 2026-09-09. HEAD: `e6fa5a42a882262a8844d8f255ede38dce9aa5ca`.

**NO-GO für reale Kundenauszüge.** Zwei verbleibende P1-Bedingungen wurden erneut unabhängig widerlegt: tatsächlicher Parser-Abbruch (C07) und atomare Zulassung von OTP-Anforderungen (C04). Die vereinbarte Betriebs- und fachliche Abnahme bleibt außerdem ausstehend. Die korrigierte Idle-Bereinigung wird angenommen und nicht erneut als fehlend bewertet.

## 1. Unabhängig bestätigte Änderungen

- **25 passed, 3 warnings in 2.63s.** Windows Python 3.12 mit FastAPI 0.141.1, Starlette 1.6.0, multipart 0.0.32 und SQLAlchemy 2.0.52. Kein Nachweis für das unveränderte Linux-Image Python 3.11/FastAPI 0.110.0.
- C06: Nach echter kurzer TTL und Wartezeit zeigt die Basisklassen-Inspektion ohne Purge-Hook **0 Einträge, 0 Payload-Bytes**. Aktiver Sweeper ist vorhanden. Dies bestätigt dieses Idle-Beispiel, keine physische Speicherüberschreibung und keine absolute 10-ms-Frist unter beliebiger Last.
- C04: Die sechs Fehlversuche bleiben nun als sechs gespeichert; lockout_set=true. Verlorene Inkremente dieses Beispiels sind behoben. Alle sechs Antworten bleiben 401, der sequentielle Folge-Lockout funktioniert.
- C01: API-Host-Berechtigung ist in beiden Manifesten vorhanden; Token-Header-Probe bleibt positiv.
- C03: Der neue Validator lehnt production+memory ab. Er ersetzt keinen SMTP-Betriebsnachweis und verbietet production+file nicht.
- A16: Der geprüfte Timeout-Pfad enthält keinen ursprünglichen Dateinamen mehr. Ein deterministischer Hash eines Dateinamens ist eine Pseudonymisierung, keine Garantie von Anonymität; den clientseitig wählbaren Idempotency-Key nicht als vertrauenswürdige anonyme Request-ID behandeln.
- probe_final.py bestätigt weiterhin Logout=401 nach Widerruf, memory ohne Disk-Write, truthful file failure und invoice-Quarantäne.
- Round-3/4-Probes und UI-Auth-Probe erneut ausgeführt; alle angegebenen Artefakthashes stimmen, ZIP-Abweichungen jeweils 0. Alte Stripe-Lookups wurden mit run_offline.py gemockt, damit synthetische Keys keine externen Aufrufe auslösen. Kein realer Stripe-Sandbox-Fulfillment-Lauf.

Evidenz und Skripte: [docs/audit_e6fa5a4](docs/audit_e6fa5a4/). Nur separate synthetische SQLite-Basen und Testdaten; keine produktiven Daten, E-Mails oder Zahlungen. Produktcode unverändert.

## 2. C07 / A17–A20 — P1: Async Exception ist kein harter Worker-Abbruch

main.py startet weiterhin einen Thread im API-Prozess. PyThreadState_SetAsyncExc injiziert SystemExit, danach wartet join nur 50 ms. Es gibt keine Prüfung, dass der Thread tatsächlich beendet ist, und keine Prozess-/Speicherisolation.

Die alte Probe setzt stopped erst nach sleep. SystemExit verhindert diese Zeile, sobald sleep zurückkehrt. Daher bedeutet `worker_completed_after_response=false` lediglich, dass diese Zeile nicht ausgeführt wurde. Bereits das gemeldete `worker_still_running_when_response_received=true` widerspricht dem behaupteten Ende bei 408; die alte Variable war aber ebenfalls nur ein Marker.

Die neue **probe_worker_lifetime.py** hält die tatsächliche Thread-Referenz, prüft is_alive und liest ausschließlich das Vorhandensein synthetischer Eingabebytes im noch lebenden Worker-Frame. Keine Dateninhalte werden ausgegeben:

```json
{
  "http": 408,
  "thread_is_alive_at_408": true,
  "synthetic_input_retained_in_live_frame": true,
  "thread_is_alive_100ms_after_408": true,
  "thread_is_alive_after_sleep_returns": false,
  "worker_completed_after_response": false
}
```

Das reale sleep wird nicht unverzüglich unterbrochen. Bis zu seiner Rückkehr lebt der Thread mit den Eingabedaten weiter. Dass dieses kurze Beispiel später endet, ist kein Hard-Deadline-Nachweis für native PDF-/OCR-Arbeit. Eine asynchrone Ausnahme an beliebiger Python-Ausführungsstelle ist zudem kein zuverlässiges Protokoll zur Freigabe gemeinsam genutzter Ressourcen. Ein eigener nativer Parser-Crash wurde nicht provoziert.

**Remediation:** ctypes-Thread-Abbruch durch einen überwachten, beendbaren Prozess/Worker mit begrenzter Queue, RAM-/CPU-Budget und Eskalation terminate→kill→join ersetzen. Nicht lediglich Future.cancel auf einem Pool verwenden. Nach Timeout muss die Prozessbeendigung vor der behaupteten Ressourcenfreigabe bestätigt werden. Fehler-/Crash-Pfade und Recovery im freizugebenden Linux-Image prüfen. Der Test muss tatsächliche Worker-Lebensdauer prüfen, nicht das Ausbleiben einer normalen Folgezeile.

## 3. C04 / A01–A02 — P1: Anfragen werden gezählt, aber nicht wirksam begrenzt

request_code prüft den zuvor gelesenen request_count, erhöht ihn anschließend und liest ein ORM-Objekt erneut. Es fehlt eine bedingte atomare Zulassung. Die Session verwendet expire_on_commit=False. Ein erneutes SELECT desselben ORM-Objekts garantiert keine Aktualisierung seiner geladenen Attribute; siehe [SQLAlchemy Expiring / Refreshing](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#expiring-refreshing).

**probe_request_race.py** synchronisiert sechs unabhängige Sessions unmittelbar vor dem request_count-UPDATE. Es ändert weder SQL-Ergebnisse noch die Zähler. Die reale request-code-Route und der memory-Delivery-Service laufen danach normal:

```json
{
  "parallel_requests": 6,
  "statuses": [200,200,200,200,200,200],
  "persisted_request_count": 6,
  "delivered_memory_messages": 6
}
```

Damit wird das zugesagte Limit **maximal 3 Nachrichten/10 Minuten** überschritten. Persistenz alleine ist keine Admission-Control. Der Fehlversuchszähler verbessert sich tatsächlich; sechs 401 sind aber kein Beweis eines aus dem neuesten committed Zustand abgeleiteten 429-Entscheids.

**Remediation:** Budgetreservierung als bedingtes UPDATE mit request_count<limit und Prüfung von rowcount/RETURNING in einer konsistenten Transaktion. Fensterwechsel und Initialanlage ebenfalls konkurrierend korrekt gestalten. Antworten aus aktualisierten skalaren DB-Werten ableiten; refresh/populate_existing behebt veraltete Ansichten, ersetzt jedoch nicht die bedingte Reservierung. Erst nach erfolgreicher Reservierung zustellen. Abnahme: maximal drei Zustellungen im Fenster, restliche Requests 429; auch unter synchronisierter Parallelität und beim Fensterwechsel. Reale SMTP-Zustellung ist für diesen Unit-Test nicht nötig.

## 4. Status der bisherigen Freigabebedingungen

| Bedingung | Status auf e6fa5a4 |
|---|---|
| Identity/Client, C01–C04 | Manifest/Header und Einzel-Logout verbessert; C04 bleibt offen. Installierter Managed-Flow, SMTP-Mailbox und Revocation bei Worker-/DB-Fehlern noch nicht nachgewiesen. |
| Stripe, C05 | Bisherige Mock-/Quarantäne-Beispiele positiv. Tatsächliche Sandbox-Abnahme von Plan, Zeitraum, Zugang und Lifecycle nicht durch diesen Commit ersetzt. |
| RAM/Retention, C06 | Konkrete Idle-Cache-Lücke geschlossen. Worker hält nach Timeout weiterhin Daten (C07). Lifecycle: close setzt nur Flag; bound thread target hält den Cache am Leben, daher __del__ nicht als primären Shutdown-Mechanismus einplanen. Dies ist eine sekundäre Betriebsverbesserung, kein erneuter Idle-Blocker. |
| Worker/Betrieb, C07/A16 | Dateiname im Timeout-Beispiel entfernt; harter Worker-Abbruch widerlegt. Linux-Ressourcen-/Crash-/Migrationsevidenz weiterhin erforderlich. |
| Fachliche/operative Abnahme, C08 | Keine neuen DATEV/BMD-Importprotokolle mit fachlicher Prüfung oder passende nachgewiesene Hosting-/AVV-/TOMs-Abnahme im Änderungsumfang. Synthetische Profilmatrix und ZIP allein reichen nicht. |

Diese Punkte stammen aus [Entscheidung 11](11_RELEASE_DECISION_6e2ae2d_2026-09-09.md), nicht aus nachträglich erweiterten Anforderungen. Die zwei eigenen neuen Proben prüfen genau deren bestehende Invarianten. Die ursprünglichen Skripte geben überwiegend Beobachtungen aus; ihr Exit-Code 0 bedeutet nicht, dass sämtliche Sicherheitskriterien erfüllt sind.

## 5. Verifizierte Artefakte

| Artefakt | SHA-256 |
|---|---|
| Chrome ZIP | `CE4931FAA677E756724BDBA73813F893378857699453F2421224F8608FD866D7` |
| Firefox ZIP | `CB4FA209E20E7F44796D7AFED8521597A9FAADD1340994B49F19DD044565008B` |
| Dockerfile | `161D4D98E91952E162039D2C191902707F9EE8CEE6ECAC63E21BC4EC0792D0B6` |
| requirements.txt | `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64` |

**Full GO wird für e6fa5a4 nicht erteilt.** Synthetische Entwicklung kann fortgesetzt werden. Für eine neue Entscheidung zuerst C04 und C07 anhand der tatsächlichen Zustellungen und Worker-Lebensdauer schließen, anschließend die bereits vereinbarte Betriebs-/fachliche Evidenz am finalen Build vorlegen.
