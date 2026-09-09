# Statement2Muster v1.0.2 — Entscheidung zu 6e2ae2d

Datum: 2026-09-09. Geprüfter HEAD: `6e2ae2dac505e5daf27b83c5686d433ebda23c4a`.

**Entscheidung: NO-GO für den Kanzlei-Pilotbetrieb mit realen Kundenauszügen.** Mehrere konkrete Fehler wurden erfolgreich behoben. Die vollständige Schließung von C01–C08 und der fünf Freigabebedingungen aus [Entscheidung 10](10_RELEASE_DECISION_88269784_2026-09-09.md) ist jedoch widerlegt beziehungsweise nicht nachgewiesen. Synthetische Tests können fortgesetzt werden.

## 1. Bestätigte Verbesserungen und Prüfumfang

- Pytest unabhängig wiederholt: **25 passed, 3 warnings in 2.70s**.
- probe_auth_ui.cjs: Beide Builds senden nun `Bearer synthetic-token` aus storage.local.
- probe_final.py reproduziert den gemeldeten JSON: Logout blockiert den geprüften Token mit 401; memory schreibt keine Outbox-Datei; ungültiger file-Pfad liefert false; Stripe-Lookup wird im Mock aufgerufen; quarantined/null bleibt nach invoice.paid quarantined/null.
- Die bisherigen Round-3/4-Szenarien zu Quoten, Hash-Bindung, Exportbarrieren und Quarantäne wurden wiederholt. Stripe-Lookups dieser älteren Skripte wurden mittels run_offline.py an der Lookup-Grenze gemockt, um keine externen Anfragen mit synthetischen Schlüsseln zu senden. Dies ist kein Stripe-Sandbox-End-to-End-Nachweis.
- probe_fulfillment.py und probe_preview.cjs wurden ebenfalls wiederholt. Die einfachen quoted DATEV/BMD/Muster-Fixtures bleiben korrekt.
- Alle vier Artefakthashes entsprechen dem Antrag; ZIP-Abweichungen: Chrome 0, Firefox 0.
- Profilmatrix beschränkt sich jetzt ausdrücklich auf synthetisch geprüfte CSV/PDF-Profile; die unbestätigte Zertifizierung und CAMT/MT940-Freigabe wurden korrigiert.

Prüfumgebung: Windows Python 3.12, FastAPI 0.141.1, Starlette 1.6.0, multipart 0.0.32, SQLAlchemy 2.0.52. Der unveränderte Dockerfile verwendet Python 3.11; requirements pinnt unter anderem FastAPI 0.110.0. Kein Linux-Image-, SMTP-Mailbox- oder realer DATEV/BMD-Importlauf in diesem Audit. Ausschließlich separate synthetische SQLite-Datenbanken, keine produktive Datenbank und keine echten Bankauszüge. Produktcode blieb unverändert.

Evidenz: [docs/audit_6e2ae2d](docs/audit_6e2ae2d/), insbesondere final-results.json, auth-ui-results.json, idle-timeout-results.json und rate-race-results.json.

## 2. Verbleibende Gegenbeispiele

### C06 bleibt offen — P1, A17/A18: Beobachtung löst die vermeintlich aktive Bereinigung aus

ExpiringOrderedDict bereinigt bei __len__/get/items usw. Ohne Aufruf läuft weiterhin kein Timer und kein Hintergrundprozess. Der alte Test `len(cache._entries)` ist durch das neue __len__ selbst zur Mutation geworden. Sein Ergebnis false beweist deshalb keine Bereinigung vor dem Zugriff.

Neue Probe mit echter kurzer TTL und Wartezeit; die unveränderte Basisklassenmethode OrderedDict.__len__ liest den Container ohne den neuen Purge-Hook:

```json
{"raw_entries_after_ttl":1,"bytes_after_ttl":14,"entries_after_instrumented_len":0}
```

Das synthetische Finanzpayload ist nach TTL weiter referenziert und wird erst durch die instrumentierte Inspektion entfernt. get liefert weiterhin korrekt kein abgelaufenes Ergebnis; das wird ausdrücklich anerkannt. Es geht um die zugesagte Lebensdauer im RAM, nicht um einen behaupteten Disk-Write.

**Erforderlich:** aktiver, lifecycle-verwalteter Sweeper mit begrenztem Intervall oder anderes nachweisbares Freigabeverfahren, auch im Leerlauf. Abnahmetest darf keine bereinigende Operation verwenden. Freigabe von Referenzen ist keine Garantie physischer Speicherüberschreibung. Payload-Budget und tatsächliches Prozessspeicherbudget getrennt dokumentieren.

### C07 bleibt offen — P1, A18/A20: HTTP-Timeout beendet den Parser nicht

main.py verwendet jetzt wait_for(to_thread(...)). Das entlastet die Event Loop und begrenzt die Wartezeit des Requests. Es stoppt keinen bereits laufenden synchronen Parser-Thread.

Die neue Probe ersetzt ausschließlich registry.parse_file durch eine kurze synthetische Arbeit und ruft den echten /convert-Endpoint auf:

```json
{"http":408,"worker_started":true,"worker_still_running_when_response_received":true,"worker_completed_after_response":true}
```

Nach dem 408 werden weiterhin Ressourcen verbraucht und die Eingabeargumente vom Worker gehalten. Ein hängender oder speicherintensiver Parser bleibt im API-Prozess. Das entspricht der dokumentierten Semantik laufender Futures: [Python concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Future.cancel).

**Erforderlich:** beendbarer isolierter Worker/Prozess mit CPU-/RAM-/Wall-Time-Budget und begrenzter Queue. Timeout muss tatsächliches Ende und Bereinigung nachweisen; bloßer Wechsel zu einem ProcessPool mit Future.cancel reicht ebenfalls nicht als Kill-Nachweis. Tests für success/error/timeout/crash im freizugebenden Linux-Image.

**Regression A16, P1 im Datenverarbeitungsumfang:** Der neue Timeout-Logger schreibt den rohen filename. Die Probe protokolliert `Parser timed out ... processing 'SYNTHETIC_PRIVATE_NAME.csv'`. Request-ID statt Dateiname verwenden; canary-Prüfung muss auch Fehlerpfade erfassen.

### C04 bleibt offen — P1, A01/A02: Persistenz verhindert keine verlorenen Updates

AuthRateLimit wird per SELECT gelesen und anschließend mit `rl.failed_attempts += 1` überschrieben. Persistentes commit ist hilfreich, aber keine atomare Zählererhöhung.

probe_rate_race.py synchronisiert sechs unabhängige Sessions nach dem Lesen des Rate-Limit-Zustands vor der Challenge-Abfrage. Es verändert weder den Zähler noch das Ergebnis der SQL-Abfragen:

```json
{"parallel_attempts":6,"statuses":[401,401,401,401,401,401],"persisted_failed_attempts":1,"lockout_set":false}
```

Dies ist ein erzwungenes zulässiges Interleaving, keine Behauptung über seine Häufigkeit unter normaler Last. Die Invariante „fünf Fehler sperren“ gilt unter Parallelität nicht. request_count verwendet dasselbe Read/Modify/Write-Muster und benötigt ebenfalls eine atomare Lösung; hierfür wurde kein eigener Konkurrenzlauf durchgeführt.

**Erforderlich:** transaktionale atomare Inkremente/bedingte Updates oder geeignete Serialisierung mit Retry; Initialanlage konfliktfest. Der Sperrentscheid muss aus dem aktualisierten Zustand folgen. Nach Parallelversuchen müssen alle gezählten Fehlversuche und die Sperre erhalten bleiben, auch nach Worker-Wechsel/Neustart. E-Mail/IP-Abuse-Budgets bleiben Teil der bisherigen Abnahme.

### C01 bleibt teilweise offen — Managed Endpoint nicht vollständig integriert

Token-Header und Fehlerbehandlung wurden korrigiert, managed URL steht nun in candidates. Beide manifest.json enthalten jedoch keine Host-Berechtigung für `https://api.statement2muster.com/*`; vorhandenes `https://statement2muster.com/*` umfasst diese Subdomain nicht. Ein URL-Eintrag allein ist keine nachgewiesene Extension-Netzwerkintegration. Siehe [Chrome Cross-origin network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests).

**Erforderlich:** eng begrenzte Berechtigung für den tatsächlichen API-Host; installierte ZIP in sauberem Browserprofil gegen den verwalteten Endpoint testen. Dieses Audit hat keinen Browser-Netzwerkfehler auf dem Live-Host reproduziert; Befund ist die statische Lücke und der fehlende End-to-End-Nachweis.

## 3. Status der übrigen C-Punkte

| ID | Angenommene Korrektur | Verbleibender Umfang |
|---|---|---|
| C01 | Token-Header, explizite Fehler, Logout-Header, managed candidate | Manifest/API-Host und installierter E2E-Flow |
| C02 | Der getestete Token wird nach Logout abgewiesen; DB-Modell hinzugefügt | Multiworker-/DB-Fehlerabnahme fehlt. security.py ignoriert DB-Fallback-Fehler und liefert false; Fallback unterstützt nur SQLite. Kein Nachweis robuster Revocation bei DB-Ausfall. |
| C03 | Getrennte memory/file/smtp-Zweige; smtplib statt undeclared dependency | Echter SMTP-Test aus Release-Image, Production-Konfigurationsprüfung. Settings erlaubt weiterhin default memory; Produktionsausschluss ist nicht erkennbar. |
| C04 | Dauerhafte Speicherung; sequentieller Lockout; 3 Request-Codes/10 Minuten | Atomarität unter Parallelität durch neue Probe widerlegt |
| C05 | Test-Key-Lookup, invoice-Quarantäne und previous upsert-Beispiel | Stripe Sandbox mit tatsächlichen line items, plan/period/access und Lifecycle-Abnahme bleibt ausstehend; ein Mock-Aufruf ist keine bezahlte Bereitstellung |
| C06 | Erweiterte Bereinigung bei Zugriff | Keine aktive Idle-Bereinigung; neue Probe widerlegt Schließung |
| C07 | Event Loop wird entlastet; Request liefert 408 | Worker läuft weiter; keine harte Isolation; Dateinamen-Logging wieder eingeführt |
| C08 | Ehrliche synthetische Profilmatrix; ZIP stimmt | DATEV/BMD-Importbelege mit fachlicher Prüfung, Linux-Betriebsnachweise und passende privacy/AVV/TOMs bleiben offen |

C02-Fehlerpfad ist eine statische Feststellung, kein in diesem Lauf reproduzierter Multiworker-Angriff. Der erfolgreiche Logout-Einzeltest wird nicht zurückgenommen. C08 fordert weiterhin die bereits vereinbarte fachliche und operative Abnahme; eine Profilmatrix für synthetische Tests ersetzt sie nicht.

## 4. Konkrete nächste Abnahme für Antigravity

1. **C04:** atomare Budgets; die gespeicherten Werte und Sperren nach echter Parallelität prüfen, nicht nur HTTP-Codes sequentieller Aufrufe.
2. **C06:** aktive Idle-Bereinigung; Test beobachtet Referenzlebensdauer ohne Purge-Hook. Nicht die Messfunktion so ändern, dass sie selbst den gewünschten Zustand herstellt.
3. **C07/A16:** beendbarer begrenzter Worker und vollständige Logs ohne Dateinamen; nach Timeout/crash darf der Job nicht weiterarbeiten.
4. **C01–C03/C05:** installierter Managed-Flow, SMTP-Testmailbox, Revocation bei Worker-Wechsel und DB-Fehler, Stripe-Sandbox-E2E. Keine produktiven Zahlungen für die Tests nötig.
5. **C08:** konkret eingeschränkter Pilotkorpus mit DATEV/BMD-Importprotokollen und fachlicher Freigabe; bestätigte Linux-Konfiguration/Migration/Retention und dazu passende Datenschutz-/AVV-Unterlagen. Anschließend ZIP neu bauen und Hashes fixieren.

Für Full GO müssen diese Nachweise am freizugebenden Build vorliegen. Reine Output-Skripte sollten Sicherheitsinvarianten mit Assertions prüfen; Exit 0 allein ist keine Abnahme. Die bisherigen 25 Tests und positiven Einzelbeispiele bleiben gültige Regressionsevidenz für ihren tatsächlichen Umfang.

## 5. Artefakte

| Artefakt | Verifizierter SHA-256 |
|---|---|
| Chrome ZIP | `13EFD53EF4DAEA605FB75B85D31FE5976509847B7E92AA0EAF6215120F46A214` |
| Firefox ZIP | `88F793BF62663FDA9C1145F79B3E46D773B051B19C64C8D8F080E66360325A54` |
| Dockerfile | `161D4D98E91952E162039D2C191902707F9EE8CEE6ECAC63E21BC4EC0792D0B6` |
| requirements.txt | `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64` |

**Full GO für 6e2ae2d wird nicht erteilt.** Die Entscheidung beruht auf reproduzierten verbleibenden Invariantenverletzungen und ausstehender vereinbarter Abnahme, nicht auf der Aberkennung bestätigter Verbesserungen.
