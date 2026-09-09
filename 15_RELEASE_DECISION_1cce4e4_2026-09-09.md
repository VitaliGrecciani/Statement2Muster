# Statement2Muster — Entscheidung zu 1cce4e4

Datum: 2026-09-09. Geprüfter HEAD: `1cce4e47ffb918f8ec5d0db66cd32250e8c618e1`.

**NO-GO für reale Kundenauszüge. C07 ist weiter verbessert, aber nicht vollständig geschlossen.** Die einheitliche Prozessroute und die 413-Weitergabe sind bestätigt. Die Admission-Deadline liefert jedoch keine reguläre HTTP-Antwort; konfigurierte Parallelitäts-/Queue-Grenzen werden ignoriert. Die bereits verlangten CPU-/RAM- und Betriebsnachweise bleiben offen.

## 1. Bestätigte Ergebnisse

- **25 passed, 2 warnings in 13.70s** im verfügbaren Windows-Python-3.12-Runtime; FastAPI 0.141.1/Starlette 1.6.0, weiterhin kein Test des gepinnten Linux-Images.
- Default Prozessisolation true; echte /convert-Route führt ohne Funktionsnamen-Sonderzweig durch den Supervisor. Die früheren Sleep-/Frame-/ctypes-Thread-Abbruchpfade wurden aus der Route entfernt.
- Echtes einzeiliges CSV: 200. Zwei Zeilen bei MAX_ROWS_PER_FILE=1: **413**, jetzt korrekt.
- Direkter Supervisor-Timeout: 408, keine lebenden Kindprozesse danach. Der kurze Timeout belegt dieses Lifecycle-Beispiel, keine umfassende native CPU-/Crash-/OOM-Abnahme.
- Der direkte Admission-Task ist nach Ablauf nicht mehr pending. Die Interpretation als korrektes HTTP-Verhalten ist allerdings unzutreffend, siehe unten.
- Alle vier angegebenen Hashes entsprechen den unveränderten Artefakten. Ein neuer ZIP-Inhaltsvergleich wurde in diesem begrenzten Folgeaudit nicht wiederholt.

Evidenz: [docs/audit_1cce4e4](docs/audit_1cce4e4/), insbesondere probe_isolated_route.py, isolated-route-results.json, isolated-run.txt und pytest.txt. Separate synthetische SQLite-Datenbank, keine echten Bankauszüge, E-Mails oder Zahlungen. Produktcode nicht verändert.

## 2. Offene Befunde und Remediation

### P1 — C07/A18: Admission-Timeout bricht den Request ohne HTTP-Antwort ab

Der Supervisor wandelt das Ablaufen von semaphore.acquire in **asyncio.CancelledError** um. Dies ist eine Task-Cancellation, kein HTTP-Timeout. Die Fehlerbehandlung der Route fängt HTTPException und Exception; CancelledError fällt nicht darunter.

Die eigene Probe belegt alle Supervisor-Slots und ruft die tatsächliche /convert-Route mit einer kurzen Warte-Deadline auf. Ergebnis im vorhandenen ASGI-Middleware-Stack:

```json
{"route_admission":{"escaped_exception":"RuntimeError","message":"No response returned."}}
```

Es kam keine auswertbare reguläre HTTP-Antwort zurück. Unter einem realen ASGI-Server kann sich das als interner Fehler bzw. abgebrochene Antwort zeigen; dieses konkrete Serververhalten wurde hier nicht behauptet oder getestet. Das direkte Probe-Ergebnis still_pending_after_80ms=false allein unterscheidet erfolgreiche Deadline-Behandlung nicht von Cancellation.

**Korrektur:** selbst ausgelöste Warte-Timeouts in einen expliziten HTTP-Status (z.B. 408, oder dokumentiertes Überlast-503) übersetzen. Echte externe Task-Cancellation getrennt behandeln und Cleanup/Quota-Abwicklung sicherstellen. Abnahme muss den HTTP-Status und abgeschlossenen Request prüfen, nicht nur task.done().

### P1 — C07/A18: Konfigurierte Betriebsgrenzen werden ignoriert

Settings liest PARSER_WORKER_CONCURRENCY und PARSER_MAX_QUEUE_DEPTH, aber der Singleton wird weiterhin als `ParserProcessSupervisor()` mit Defaults erzeugt.

Unabhängiger Lauf mit gesetzter Umgebung:

```json
{
  "settings_concurrency":1,
  "actual_concurrency":4,
  "settings_queue_depth":2,
  "actual_queue_depth":8
}
```

Eine auf geringere Ressourcen ausgelegte Installation erhält damit mehr Parallelität als konfiguriert. Die neu hinzugefügte waiting_count-Grenze ist eine Verbesserung gegenüber der unbegrenzten Semaphore-Warteliste; sie berücksichtigt aber nur Aufrufe innerhalb des Supervisors. Die Route liest Datei-Inhalte vorher ein. „Admission vor jeder teuren Datenhaltung“ ist daher nicht durch diesen Zähler nachgewiesen.

**Korrektur:** Supervisor explizit aus validierten Settings im App-Lifecycle erzeugen. Queue/Parallelitätsgrenzen mit abweichenden Werten testen; deploymentweite Anzahl der API-Worker einbeziehen. Aufnahme-/Byte-Budgets so abstimmen, dass Uploads und wartende Requests nicht außerhalb des kalkulierten Limits liegen.

### P1 — C07/A18–A20: RAM-/CPU-Grenzen und vollständige Lifecycle-Abnahme fehlen

Es gibt weiterhin keine wirksamen RAM-/CPU-Grenzen im Supervisor oder neue Release-Linux-Evidenz dafür. Getrennte Prozesse und begrenzte Anzahl verhindern allein keinen Container-OOM. Dieser Punkt war bereits in Entscheidung 14 verlangt; eine komplette Umsetzung aller sechs Anforderungen ist nicht belegt.

Auch die behauptete „iterative zweifach verifizierte“ Beendigung ist im Code nur ein begrenzter zweiter Kill-/Join-Versuch: Nach dem zweiten Versuch erfolgt keine zwingende finale Erfolgsentscheidung, bevor „Killed and reaped“ protokolliert wird. Der einfache Timeout-Test ist positiv und bleibt anerkannt. Daraus folgt nicht, dass Kill-/IPC-/Start-/Crash-/Cancellation-Fehler vollständig abgenommen sind.

**Korrektur:** durchsetzbare OS-/Container-Limits und bestätigte Prozessbeendigung mit explizitem Fehlerzustand bei fehlgeschlagenem Cleanup. Testmatrix im tatsächlich freizugebenden Linux-Image mit Worker-Handshake für blockierende Arbeit, CPU, Crash, Cancellation und Recovery. Bereits bekannte Hilfsfunktions-PID-Proben ersetzen diese Integrationstests nicht.

### P2 — neuer globaler Eingriff in asyncio.run bei Child-Import

main.py überschreibt in jedem Nicht-MainProcess `asyncio.run` durch eine Lambda, die nichts ausführt. Das ist kein regulärer Windows-Spawn-Guard: Ein importiertes Bibliotheksmodul ändert damit global die Semantik anderer Kindprozess-Aufrufe. Dass die früheren Thread-Hacks entfernt wurden, wird anerkannt; diese neue Test-Runner-Sonderbehandlung sollte dennoch nicht im Produktcode bleiben.

**Korrektur:** ausführbare Test-/CLI-Einstiegspunkte mit `if __name__ == '__main__'` schützen und den Worker-Importpfad klar trennen. asyncio.run unverändert lassen. Ein konkreter Ausfall des aktuellen OCR-Pfads durch diese Zuweisung wurde hier nicht reproduziert.

## 3. Gesamtergebnis der erweiterten Route-Probe

```json
{
  "default_process_isolation":true,
  "one_row":{"http":200,"detail":null},
  "over_row_limit":{"http":413,"detail":"File 'synthetic.csv' exceeds maximum allowed limit of 1 rows."},
  "route_admission":{"escaped_exception":"RuntimeError","message":"No response returned."},
  "config_wiring":{"settings_concurrency":1,"actual_concurrency":4,"settings_queue_depth":2,"actual_queue_depth":8},
  "admission":{"timeout_seconds":0.01,"still_pending_after_80ms":false},
  "real_supervisor_timeout":{"http":408,"live_children_after_response":[]}
}
```

Die Zusatzprobe verändert keine Parserfunktion. Sie belegt bewusst die vorhandenen Slots, um die echte Route auf dem Wartepfad zu prüfen, und gibt sie anschließend frei. Die nicht mehr wartende direkte Coroutine endet derzeit durch CancelledError; dieses Ergebnis ist kein Nachweis einer regulären Timeout-Antwort.

## 4. Freigabe und nächste Abnahme

Die zuvor bestätigten C04-Admission- und C06-Idle-Korrekturen werden nicht zurückgenommen. Für C07 sind jetzt insbesondere HTTP-Verhalten bei Aufnahme-Timeout, Settings-Verdrahtung, Ressourcenlimits und vollständiges Cleanup offen. Erst diese Punkte am Produktionspfad abnehmen; keine Probe so umdeuten, dass beliebiges Task-Ende als erfolgreiche Fehlerbehandlung gilt.

Unabhängig davon bleiben die bereits vereinbarten Full-GO-Nachweise ausstehend: installierter Managed-Flow mit SMTP, Stripe-Sandbox-Lifecycle, Revocation bei Worker-/DB-Fehlern, Release-Linux-Migration/Retention sowie reale DATEV/BMD-Importprotokolle mit fachlicher Prüfung und passende Hosting-/Privacy-/AVV-Unterlagen. Diese werden durch den vorliegenden Code-/Hash-Nachweis nicht ersetzt.

## 5. Verifizierte Hashes

| Artefakt | SHA-256 |
|---|---|
| Chrome ZIP | `CE4931FAA677E756724BDBA73813F893378857699453F2421224F8608FD866D7` |
| Firefox ZIP | `CB4FA209E20E7F44796D7AFED8521597A9FAADD1340994B49F19DD044565008B` |
| Dockerfile | `161D4D98E91952E162039D2C191902707F9EE8CEE6ECAC63E21BC4EC0792D0B6` |
| requirements.txt | `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64` |

**Full GO für 1cce4e4 wird nicht erteilt.** Synthetische Entwicklung und gezielte Abnahme der verbliebenen Bedingungen können fortgesetzt werden.
