# Statement2Muster — Entscheidung zu ea2498b

Datum: 2026-09-09. Geprüfter HEAD: `ea2498b8ce21786432d464132ab2a4ee4e51d8aa`.

**Die konkreten Admission-/Settings-Gegenbeispiele aus Entscheidung 15 sind geschlossen. Full GO für reale Kundenauszüge wird noch nicht erteilt.** C07 bleibt hinsichtlich Ressourcen- und vollständiger Betriebsabnahme teilweise offen. Diese Entscheidung nimmt bestätigte Korrekturen an und trennt sie von noch fehlender Freigabeevidenz.

## 1. Unabhängige Bestätigung

- **25 passed, 2 warnings in 18.61s.** Verfügbarer Windows-Python-3.12-Runtime mit FastAPI 0.141.1/Starlette 1.6.0; kein Test des gepinnten Linux-Images Python 3.11/FastAPI 0.110.0.
- Echte /convert-Route: einzeiliges CSV 200; zwei Zeilen bei Limit 1 korrekt 413.
- Belegte Supervisor-Slots und abgelaufene Warte-Deadline: reguläres **HTTP 408**, kein entwichener RuntimeError.
- Mit ausdrücklich abweichenden Umgebungswerten PARSER_WORKER_CONCURRENCY=1 und PARSER_MAX_QUEUE_DEPTH=2 zeigt der Supervisor ebenfalls **1 und 2**. Damit ist nicht nur die Übereinstimmung identischer Defaults geprüft.
- Einfacher tatsächlicher Supervisor-Timeout: 408 und keine lebenden Kindprozesse unmittelbar danach.
- Codeprüfung bestätigt: zusätzliche finale Erfolgsprüfung im Timeout-Kill-Pfad und expliziter 500-Fehler bei nicht bestätigter Beendigung; asyncio.run-Zuweisung entfernt.
- Alle vier angegebenen SHA-256 stimmen. Die ZIP-Inhalte wurden nicht erneut separat verglichen; ihre Hashes entsprechen den bereits geprüften unveränderten Archiven.

Evidenz: [docs/audit_ea2498b](docs/audit_ea2498b/), insbesondere isolated-route-results.json, probe_isolated_route.py und pytest.txt. Ausschließlich separate synthetische Datenbank/Dateien, keine echten Bankauszüge, E-Mails oder Zahlungen. Produktcode unverändert. Nicht jede in früheren Audits vorhandene Probe wurde in diesem begrenzten Folgeaudit wiederholt.

```json
{
  "default_process_isolation":true,
  "one_row":{"http":200,"detail":null},
  "over_row_limit":{"http":413,"detail":"File 'synthetic.csv' exceeds maximum allowed limit of 1 rows."},
  "route_admission":{"http":408},
  "config_wiring":{"settings_concurrency":1,"actual_concurrency":1,"settings_queue_depth":2,"actual_queue_depth":2},
  "admission":{"timeout_seconds":0.01,"still_pending_after_80ms":false},
  "real_supervisor_timeout":{"http":408,"live_children_after_response":[]}
}
```

## 2. Was damit geschlossen ist — und was nicht

| Bestandteil aus Entscheidung 15 | Entscheidung |
|---|---|
| Admission ohne reguläre HTTP-Antwort | Konkretes Gegenbeispiel geschlossen: 408 auf echter Route |
| Ignorierte konfigurierte Parallelität/Queue-Tiefe | Konkretes Gegenbeispiel für beim Start gesetzte Werte geschlossen: 1/2 statt 4/8 |
| Unzutreffende Erfolgsmeldung nach zweitem Timeout-Kill | Finale Prüfung im Code ergänzt; einfacher erfolgreicher Timeout bestätigt. Kill-Fehlerinjektion und alle weiteren Cleanup-Pfade nicht vollständig abgenommen |
| Globaler Eingriff in asyncio.run | Entfernt, Code-Korrektur angenommen |
| Ressourcen-/Linux-/Lifecycle-Abnahme | Weiter offen; nicht durch die vier obigen Korrekturen ersetzt |

Die Doppelvererbung von HTTPException und CancelledError funktioniert im geprüften FastAPI-Pfad. Sie sollte dennoch nicht als Beweis gelten, dass fachlicher Admission-Timeout und externe Task-Cancellation semantisch identisch sind. Ein einfaches HTTP-Timeout mit separater Cancellation-Behandlung wäre klarer; der bestehende direkte Probe-catch darf die Produktsemantik nicht bestimmen. Daraus wird hier kein neuer eigenständiger P1 abgeleitet.

Die behauptete dynamische Synchronisation im laufenden Betrieb ist weitergehend als die nachgewiesene Startkonfiguration: Die semaphore-Property erzeugt bei Limitänderung ein neues Semaphore. Bereits laufende/wartende Aufrufe gehören dann zum alten Objekt, während finally das aktuell zurückgegebene Objekt freigibt. Diese statisch erkennbare Umschaltproblematik wurde nicht mit laufenden OS-Jobs reproduziert. Bis zu einem eigenen Resize-Protokoll sollten Limits für die App-Lebensdauer unveränderlich sein und Änderungen per kontrolliertem Neustart erfolgen.

## 3. Verbleibende Freigabebedingungen

### C07/A18–A20 — Ressourcen und vollständiger Betrieb

Präzisierung gegenüber pauschalen Formulierungen früherer Berichte: **Der Deployment-Leitfaden enthält bereits einen Compose-Beispielblock mit 1 CPU und 512 MiB.** Es wäre daher falsch zu behaupten, es existiere keinerlei dokumentierter Ressourcenwert. Nicht belegt sind die tatsächliche Deployment-Konfiguration, deren wirksame Durchsetzung und Recovery bei speicherintensivem Parser, Crash oder OOM. Der Supervisor selbst fügt keine RAM-/CPU-Grenze hinzu.

Vor der Schließung dieses Umfangs erforderlich:

1. Release-Linux-Image mit exakt deklarierter Abhängigkeitensammlung starten; effektive Limits, Worker-Anzahl und Queue-Größe festhalten.
2. Reale Supervisor-/Route-Proben mit Worker-Handshake für Blocking-Wait, CPU, Crash, externe Cancellation und Kill-Fehler. Die wiederholt vorgelegte Hilfsfunktions-PID-Probe baut ihre Blocking-/CPU-Timeout-Schleife selbst und ersetzt diese Integration nicht.
3. OOM-/Überlast-/Recovery-Nachweis sowie Retention-Canaries auf success/error/timeout/crash einschließlich Proxy, temporären Dateien und Logs. Queue-Zähler sitzt weiterhin hinter dem Einlesen der Uploads; vorgelagerte Byte-/Aufnahmegrenzen mit dem Gesamtbudget abstimmen.
4. Finale Cleanup-Prüfung auf allen erforderlichen Pfaden, nicht nur im Timeout-except. Insbesondere externe Cancellation, IPC-/Startfehler und Recovery nach fehlgeschlagenem Kill müssen eine nachvollziehbare Zustandsentscheidung erhalten.

### Full-GO-Evidenz außerhalb des einzelnen C07-Fixes

Weiterhin fehlen die bereits vereinbarten Nachweise für installierten Managed-Flow/SMTP, Stripe-Sandbox-Lifecycle, Revocation bei Worker-/DB-Fehlern, Migration der vorgesehenen Datenbank sowie tatsächliche DATEV/BMD-Importprotokolle mit fachlicher Prüfung und passende Hosting-/Privacy-/AVV-Unterlagen. Diese Punkte werden nicht durch wiederholte synthetische Parser-Tests oder identische Hashes geschlossen.

Der vorhandene Deployment-Beispielblock setzt ENVIRONMENT=production, nennt aber kein EMAIL_BACKEND= smtp oder SMTP-Konfiguration. Mit dem inzwischen eingeführten memory-Verbot darf dieser Beispielblock nicht ungeprüft als lauffähige Produktionskonfiguration ausgegeben werden. Eine reale Mailzustellung wurde in diesem Audit nicht durchgeführt.

## 4. Nächster sinnvoller Abnahmeschritt

Die bestätigten Admission-/IPC-/Settings-Proben müssen nicht erneut als offene Defekte behandelt werden. Als nächstes ist ein überprüfbares Release-Betriebspaket sinnvoll: konkretes Deployment-Manifest, Image-Digest, wirksame Ressourcenwerte, Lifecycle-/Recovery-Protokolle und die fachlichen Importbelege. Geheimnisse und reale Kundendaten gehören nicht in den Audit-Ordner; Testkonten und synthetische bzw. ordnungsgemäß freigegebene Testdaten genügen für technische Nachweise.

## 5. Artefakthashes

| Artefakt | SHA-256 |
|---|---|
| Chrome ZIP | `CE4931FAA677E756724BDBA73813F893378857699453F2421224F8608FD866D7` |
| Firefox ZIP | `CB4FA209E20E7F44796D7AFED8521597A9FAADD1340994B49F19DD044565008B` |
| Dockerfile | `161D4D98E91952E162039D2C191902707F9EE8CEE6ECAC63E21BC4EC0792D0B6` |
| requirements.txt | `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64` |

**Ergebnis: bestätigte Code-Fortschritte angenommen; Full GO auf ea2498b weiterhin ausstehend.** Synthetische Entwicklung und gezielte Betriebs-/fachliche Abnahme können fortgesetzt werden.
