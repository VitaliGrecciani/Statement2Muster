# Statement2Muster — Entscheidung zu 8892de1

Datum: 2026-09-09. HEAD: `8892de1fbec872d1f756ce559701d8d8ecfae07f`.

**C07 teilweise umgesetzt, nicht geschlossen. NO-GO für reale Kundenauszüge.** Ein echter Prozess-Supervisor existiert und funktioniert in einfachen Erfolgs-/Timeout-Fällen. Die sichere Integration, begrenzte Aufnahme wartender Jobs und Ressourcengarantien sind jedoch nicht vollständig umgesetzt.

## 1. Was unabhängig bestätigt wurde

- **25 passed, 3 warnings in 2.61s** im verfügbaren Windows-Python-3.12-Runtime. Wie zuvor kein Release-Linux-Image-Test; FastAPI 0.141.1 statt gepinntem 0.110.0.
- Eine echte /convert-Anfrage mit explizit aktivierter Prozessisolation und gültigem einzeiligem CSV liefert 200.
- Ein direkter Aufruf des tatsächlichen Supervisors mit kurzer Deadline liefert 408; unmittelbar danach sind keine lebenden Kindprozesse mehr vorhanden. Dieser Test läuft über den Supervisor, nicht über eine nachgebaute Kill-Schleife. Er prüft einen frühen Timeout während Start/Verarbeitung, keine separat bestätigte laufende native CPU-Schleife.
- Die bereitgestellte probe_process_worker.py wurde wiederholt und liefert die gemeldeten Ergebnisse. Ihr Erfolgsfall verwendet den Supervisor. Ihre Blocking-/CPU-Fälle starten und töten hingegen eigene Prozesse mit eigener Timeout-Schleife und _hard_kill_pid. Diese Teile prüfen die Kill-Hilfsfunktion, nicht die Supervisor-Integration. Zudem gibt es vor dem Kill kein Handshake, das den Eintritt in die CPU-/Wait-Funktion bestätigt.
- Alle vier angegebenen SHA-256 stimmen. Die unveränderten ZIP-Hashes entsprechen den bereits geprüften Archiven; eine neue ZIP-Inhaltsvergleichsprobe wurde in diesem begrenzten Folgeaudit nicht ausgeführt.

Evidenz: [docs/audit_8892de1](docs/audit_8892de1/), insbesondere probe_isolated_route.py, isolated-route-results.json, process-worker-results.json und pytest.txt. Keine Produktcodeänderungen; separate synthetische Datenbank, keine realen Bankdaten, keine externen E-Mails oder Zahlungen.

## 2. Verbleibende Befunde

| Befund | Priorität / Bezug | Nachweis und Konsequenz |
|---|---|---|
| Prozessisolation standardmäßig aus | P1, C07 | config.py setzt PARSER_PROCESS_ISOLATION standardmäßig false. Unabhängiges Ergebnis: default_process_isolation=false. Dockerfile/Deployment-Guide aktivieren sie nicht. Die normale Route läuft damit weiterhin im manipulierenden Thread-Pfad. |
| Produktionspfad hängt am Funktionsnamen | P1, C07 | main.py:227 wählt bei registry.parse_file.__name__ != 'parse_file' den Thread-Pfad, selbst bei aktivierter Isolation. Instrumentierung/Wrapper ändern so die Sicherheitsarchitektur. Alte monkeypatchende Audit-Proben attestieren deshalb überwiegend diesen Sonderpfad. |
| Semaphore ist keine begrenzte Queue | P1, A18/C07 | Semaphore begrenzt laufende Prozesse, nicht die Zahl wartender Requests. Die Deadline beginnt erst nach Aufnahme und proc.start(). Im Test bleibt ein wartender Job mit timeout=0.01 nach 80 ms pending. Wartende parse_file-Aufrufe halten ihre content-Argumente im Elternprozess. |
| Ressourcen- und Konfigurationsgrenzen nicht durchgängig | P1, A18/C07 | Der Supervisor setzt keine CPU-/RAM-Grenze. parser_supervisor wird mit Defaults konstruiert; settings.PARSER_WORKER_CONCURRENCY wird dort nicht gelesen. 4 gilt pro Supervisor/API-Prozess, nicht automatisch deploymentweit. Ein eigener OS-Prozess verhindert allein kein OOM des Containers. |
| Budgetfehler über IPC falsch abgebildet | P2, A18/A30 | Kindprozess serialisiert HTTPException als ERROR mit Typ/str; Supervisor macht daraus RuntimeError. Reale /convert-Probe mit MAX_ROWS_PER_FILE=1 und zwei CSV-Zeilen liefert 422 „keine Buchungssätze“, statt 413. Einzeilige Kontrollprobe liefert 200. Alte grüne Tests ersetzen diese Prozesspfad-Abnahme nicht. |
| Beendigung nicht auf allen Pfaden bewiesen | P1, C07 | Timeout prüft einmal is_dead, versucht ggf. erneut Kill/join und meldet anschließend ohne zweite Erfolgsprüfung „Killed and reaped“. finally verwendet ebenfalls begrenztes join. Der einfache direkte Test ist positiv; die universelle Bestätigung für Kill-Fehler/Crash/Cancellation folgt daraus nicht. proc.start liegt vor dem try/finally; Startfehler benötigen ebenfalls Cleanup. |

### Thread-Sonderpfad und Zero Retention

_scoped_worker_sleep setzt weiterhin das globale Modulattribut time.sleep. Ein Kontextmanager macht diese Zuweisung nicht threadlokal. Überlappende Kontexte können verschiedene „Originalwerte“ speichern und in anderer Reihenfolge wiederherstellen. Die Timeout-Behandlung liest fremde Frames, leert kwargs und ruft auf gefundenen Objekten set()/release() auf. Das ist kein kontrolliertes Cancellation-Protokoll und kann gemeinsam genutzte Synchronisierung verändern. Dieser Code gehört nicht in den produktiven Parserpfad.

Das Leeren eines beobachteten Dictionary beweist nicht die Vernichtung sämtlicher Kopien. Der Elternprozess hält content/file_data während der Verarbeitung; wartende Coroutine-Argumente und die gewollten Ergebnis-Caches bestehen ebenfalls unabhängig vom Kindprozess. Prozessende gibt dessen Adressraum frei, nicht den gesamten Datenbestand des Dienstes. Es wurde keine tatsächliche dauerhafte Speicherung von Bankdaten durch den neuen Supervisor behauptet oder nachgewiesen; die Aussage „keine Payload-Referenzen im Hauptprozess“ ist aber bereits durch die Aufrufstruktur nicht haltbar.

## 3. Reproduzierte Prozesspfad-Ergebnisse

```json
{
  "default_process_isolation": false,
  "one_row": {"http":200,"detail":null},
  "over_row_limit": {"http":422,"detail":"Keine Buchungssätze in den bereitgestellten Dateien gefunden oder Formate werden nicht unterstützt."},
  "admission": {"timeout_seconds":0.01,"still_pending_after_80ms":true},
  "real_supervisor_timeout": {"http":408,"live_children_after_response":[]}
}
```

Die Admission-Probe hält den einzigen Slot absichtlich belegt und bricht ihren eigenen wartenden Task anschließend sauber ab. Sie beweist fehlende Warte-Deadline; es wurden keine massenhaften Requests erzeugt. Der row-budget-Test setzt das Limit sowohl im Elternprozess als auch per Umgebung für den gespawnten Kindprozess. Die echte registry.parse_file-Funktion blieb unverändert.

## 4. Konkrete Remediation und Abnahme

1. **Ein Produktionspfad:** Prozessisolation verpflichtend für die freizugebende Konfiguration. Kein Sicherheitswechsel anhand __name__. Frame-Manipulation, globale Sleep-Zuweisungen und ctypes-Thread-Abbruch entfernen. Tests injizieren Fehler innerhalb des isolierten Workers, ohne auf Threads umzuschalten.
2. **Admission vor teurer Datenhaltung:** begrenzte Warteschlange/sofortige Überlastantwort mit definiertem 429/503-Verhalten. Deadline umfasst Wartezeit, Start, Parsing und Ergebnisübertragung. Parallelität aus Settings übernehmen und deploymentweite Ressourcen kalkulieren.
3. **OS-Ressourcen:** wirksame Prozess-/Container-RAM-/CPU-Grenzen, begrenzte Queue und nachgewiesene Recovery. Linux-Image unter der vorgesehenen Konfiguration testen.
4. **Strukturiertes IPC:** stabile Fehlercodes für 413/422/408 und interne Fehler; keine beliebigen Exception-Texte als öffentliches Protokoll. Den oben reproduzierten Zwei-Zeilen-Test bei Limit 1 als 413-Regression absichern.
5. **Lifecycle:** Start/IPC/Erfolg/Fehler/Timeout/Cancellation in einen garantierten Cleanup-Pfad aufnehmen; Prozessende wirklich prüfen und reapen. Wenn Kill/Join scheitert, darf der Dienst nicht erfolgreiche Bereinigung behaupten. Handles schließen und Bereitschaft/Recovery nachvollziehbar halten.
6. **Integration statt Hilfsfunktionsprobe:** tatsächlichen Supervisor mit Worker-Handshake bei Blocking-Wait, CPU-Loop, Crash und Cancellation prüfen; zusätzlich reale /convert-Requests. Retention-Canaries dürfen nicht durch den Test selbst gelöscht werden.

## 5. Freigabestatus ohne Erweiterung des Umfangs

Entscheidung 13 bestätigte die konkrete C04-Admission-Korrektur und den C06-Idle-Fix. Sie erklärte ausdrücklich, dass die übrigen Auth-/SMTP-/Revocation- und Betriebsbedingungen dadurch nicht pauschal attestiert sind. Die Aussage im neuen Antrag, C01 und C03 seien vollständig offiziell geschlossen und C07 der einzige verbleibende Freigabegrund, ist daher zu weitgehend.

Die bereits vereinbarten Nachweise bleiben erforderlich: installierter Managed-Flow mit SMTP und Stripe-Sandbox-Lifecycle, Revocation bei Worker-/DB-Fehlern, Release-Linux-Ressourcen/Migration/Retention sowie tatsächliche DATEV/BMD-Importprotokolle mit fachlicher Prüfung und dazu passende Hosting-/Privacy-/AVV-Unterlagen. Die neuen lokalen Tests stellen diese Evidenz nicht bereit. Dies ist keine erneute vollständige Bewertung von A01–A31; bestehende einzelne Korrekturen bleiben anerkannt.

## 6. Artefakthashes

| Artefakt | Verifizierter SHA-256 |
|---|---|
| Chrome ZIP | `CE4931FAA677E756724BDBA73813F893378857699453F2421224F8608FD866D7` |
| Firefox ZIP | `CB4FA209E20E7F44796D7AFED8521597A9FAADD1340994B49F19DD044565008B` |
| Dockerfile | `161D4D98E91952E162039D2C191902707F9EE8CEE6ECAC63E21BC4EC0792D0B6` |
| requirements.txt | `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64` |

**NO-GO für reale Kundenauszüge auf 8892de1.** Der Prozess-Supervisor ist ein substanzieller Fortschritt; für die Schließung von C07 müssen seine tatsächliche Nutzung und die genannten Grenzen am Release-Pfad nachgewiesen werden.
