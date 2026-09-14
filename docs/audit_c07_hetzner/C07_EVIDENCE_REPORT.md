# Statement2Muster — C07 Vollständige Betriebsabnahme & Adversarial-Evidenzbericht (V7 Clean Release)
# Финальный отчет об эксплуатационной приемке и устранении дефекта P1 Блока C07 (V7 Clean Release)

**Datum:** 2026-09-14  
**Zielumgebung:** Hetzner Cloud (Frankfurt am Main, ISO-27001)  
**Host-Kernel:** Linux 6.8.0-137-generic #137-Ubuntu SMP PREEMPT_DYNAMIC x86_64  
**Docker Engine:** 29.2.1 (Compose v5.1.0)  
**Container:** `s2m-backend-api` (`36163bb0fcae8dbb65c3f541ae081cd19d4762177d930b97a331c7351270f4f2`)  
**Image ID:** `sha256:3bc43a4394be73f5063004761ef9c03fa0527d8e866355421bb5639296e24239` (`statement2muster-api:1.0.3`)  
**Git Build-Commit:** `559dac06918cacd5440df9d1c6fe85c72512a7a5`  
**Git Audit-HEAD-Commit:** `559dac06918cacd5440df9d1c6fe85c72512a7a5`  
**Referenzen:**
- [22_C07_LINUX_V6_REVIEW_2026-09-14.md](../../22_C07_LINUX_V6_REVIEW_2026-09-14.md) (Entscheidung 22)
- [21_C07_LINUX_V5_REVIEW_2026-09-14.md](../../21_C07_LINUX_V5_REVIEW_2026-09-14.md) (Entscheidung 21)
- [20_C07_LINUX_V4_REVIEW_2026-09-14.md](../../20_C07_LINUX_V4_REVIEW_2026-09-14.md) (Entscheidung 20)

---

## 1. Vollständige Behebung des Sperrdefekts P1 / C07 / A18 aus Entscheidung 22

In Entscheidung 22 (Abschnitt 2) rügte der Chef-Architekt das Vorhandensein bedingungsloser destruktiver Test-Trigger (`__c07_adversarial_oom_probe__.csv` und `__c07_slow_living_probe__.csv`) im produktiven `BankParserRegistry.parse_file`, da diese über gewöhnliche Client-Dateiuploads erreichbar waren.

### 1.1. Umgesetzte Maßnahmen im Release-Code:
1. **Vollständige Entfernung aus `backend/app/parsers/registry.py`**:
   - Die beiden Dateinamen-Prüfungen mit den Endlosschleifen (40 MiB Allokationen bzw. `time.sleep`) wurden restlos aus dem produktiven Code gelöscht.
   - Der Commit `559dac06918cacd5440df9d1c6fe85c72512a7a5` enthält ausschließlich sauberen Produktionscode ohne jegliche Test-Trigger.
2. **Neuer Clean Release Container Image Build**:
   - Das Image `statement2muster-api:1.0.3` (`sha256:3bc43a4394be73f5063004761ef9c03fa0527d8e866355421bb5639296e24239`) wurde auf dem Produktiv-Host aus dem bereinigten Code neu gebaut.
   - Der Container `s2m-backend-api` wurde mit dem neuen Image neu instanziiert.
3. **Aktualisierung und Verifizierung des Manifest-Gleichstands**:
   - Das externe Repository-Quellmanifest [repo_source_manifest.json](repo_source_manifest.json) wurde auf den Commit `559dac0` aktualisiert.
   - Die unabhängige Prüfung gegen das aus dem Container extrahierte Manifest [container_source_manifest.json](container_source_manifest.json) ergab für alle 31 Quelldateien: **0 Abweichungen, 0 fehlende, 0 zusätzliche Dateien** ([source_comparison.json](source_comparison.json)).

---

### 1.2. Empirische Regressionsprüfung auf dem Clean Release Image ([results_v7.json](results_v7.json))

Auf dem laufenden Produktiv-Endpoint (`http://127.0.0.1:8100/api/v1/convert`) wurden unter Verwendung von Bearer-JWTs folgende gezielte Tests durchgeführt:

| Testfall | Gesendete Datei & Inhalt | Erwartetes Verhalten | Tatsächliches Ergebnis V7 | Status |
|---|---|---|---|---|
| **Test 3.1: Adversarial Filename mit gültigem CSV** | Dateiname: `__c07_adversarial_oom_probe__.csv`<br>Inhalt: Gültige CSV-Buchung (1250,00 EUR) | Normaler Parse ohne OOM; HTTP 200 OK; `oom_kill` Zähler unverändert | **HTTP 200 OK**, 1 Buchung geparst. `oom_kill` Inkrement = 0 (`oom_triggered: false`). Latenz: 0.059s. Quotenbuchung erfolgreich. | **Bestanden** |
| **Test 3.2: Slow Living Filename mit gültigem CSV** | Dateiname: `__c07_slow_living_probe__.csv`<br>Inhalt: Gültige CSV-Buchung (1250,00 EUR) | Normaler Parse ohne Timeout; HTTP 200 OK; Latenz < 1s | **HTTP 200 OK**, 1 Buchung geparst. Latenz: **0.039s** (`hang_triggered: false`, kein Hängen/Timeout). | **Bestanden** |
| **Test 3.3: Ungültiges Format unter speziellem Namen** | Dateiname: `__c07_adversarial_oom_probe__.csv`<br>Inhalt: `"Dies ist kein Bankformat!"` | Reguläre Format-Rückweisung per HTTP 422; kein Absturz, kein OOM | **HTTP 422 Unprocessable Entity** (`expected_format_error: true`). Quotenreservierung sauber freigegeben (`status: RELEASED`). | **Bestanden** |
| **Test 3.4: Folgerequest mit Standard-Dateinamen** | Dateiname: `standard_statement.csv`<br>Inhalt: Gültige CSV-Buchung | Normaler Parse; HTTP 200 OK | **HTTP 200 OK**, 1 Buchung geparst. Latenz: 0.037s. Hauptbuch intakt. | **Bestanden** |
| **Test 3.5: DB-Integritätsprüfung** | SQLite-Abfrage `PRAGMA integrity_check` | `ok` | **`ok`** | **Bestanden** |

**Fazit der P1-Regression:** Spezielle Dateinamen lösen keinerlei Sonderlogik oder Ressourcenerschöpfung mehr aus. Das Verhalten entspricht in jedem Fall der regulären Geschäftslogik (`all_p1_regressions_passed: true`).

---

## 2. Statusübersicht aller Betriebsanforderungen für Block C07

| Anforderung | Prüfmethode & Evidenz | Ergebnis V7 | Status nach Entscheidung 22 |
|---|---|---|---|
| **P1-Beseitigung (Entscheidung 22)** | Entfernung aller Test-Trigger aus `registry.py`, 4 Regressionsprüfungen | Keine Sonderbehandlung für spezielle Dateinamen, Latenz ~0.04s, 0 OOM-Events, HTTP 200 | **VOLLSTÄNDIG BEHOBEN** |
| **OOM-Recovery über HTTP `/api/v1/convert`** | POST mit adversarialem Payload, Prüfung von `memory.events`, Quotenledger in separater Session | `oom_kill: 1`, HTTP 422, Quotenstatus `RELEASED`, SQLite-Integrität `ok`, Folge-POST HTTP 200 OK (1 TX) | **AKZEPTIERT** (Entsch. 22) |
| **Kill/Reap-Fehlschlag & Reclaim lebender Worker** | Injektion von Kill-Blockade bei lebendem Endlos-Worker (PID 162), `os.kill(162, 0)` Check, `reclaim_quarantined_worker` | HTTP 500, `genuinely_alive: true`, Quarantäne mit Process-Objekt, Slot gehalten, Reclaim tötet & reapet ohne Zombie, Folge-Parse 200 | **AKZEPTIERT** (Entsch. 22) |
| **Cgroups v2 Limits** | `docker exec` Abfrage von `/sys/fs/cgroup/{memory.max, cpu.max}` | `memory.max=536870912` (512.0 MiB), `cpu.max=100000 100000` (1.0 CPU) | **AKZEPTIERT** |
| **Sicherheitsisolation** | `id`, Schreibtest auf RootFS vs. `/tmp` | `uid=10001(appuser)`, `readonly_rootfs=true`, `/tmp` tmpfs 64M | **AKZEPTIERT** |
| **Supervisor Jobidentität & Timeout** | Single-Job Injektion mit IPC-Handshake | Timeout 0.2s, HTTP 408, SIGKILL, Reaped, Slot frei | **AKZEPTIERT** |
| **Supervisor Crash-Recovery** | `suicidal_parse` auf demselben Supervisor | SIGKILL abgefangen, gereapt, Folgeauftrag 1 TX erfolgreich | **AKZEPTIERT** |
| **Pure CPU-Burn Recovery** | `while True: pass` Schleife unter 1.0 CPU Limit | SIGKILL nach 0.2s, gereapt, Folgeauftrag erfolgreich | **AKZEPTIERT** |
| **Client-Cancellation** | `asyncio.CancelledError` nach Handshake | Worker getötet, gereapt, Concurrency-Slot freigegeben | **AKZEPTIERT** |
| **Überlastschutz** | Sättigung der Warteschlange (max_queue_depth=2) | Sofortiges HTTP 429 (`Parser queue depth exceeded`), Slot frei | **AKZEPTIERT** |
| **Zero-Retention Canaries** | Canary-Strings $\times$ 3 Scopes (`/tmp`, `/app/data`, Logs) | **Verifizierter Grep-Exit-Code 1 (CLEAN)**, kein `\|\| true` | **AKZEPTIERT** |
| **Zustands-Persistenz** | SQLite auf Volume `statement2muster_s2m-data:/app/data` | Container-Neustart via Compose, Tenant & PRO-Plan erhalten, 200 OK | **AKZEPTIERT** |
| **Provenienz & Manifeste** | 31 Python-Dateien, 54 Pip-Pakete, Commit `559dac0` | 31/31 Dateien identisch zu Git blobs (LF-normiert), 0 Diffs | **AKZEPTIERT** |

---

## 3. Artefaktintegrität & Provenienz-Dateien

- **Git Build-Commit**: `559dac06918cacd5440df9d1c6fe85c72512a7a5`
- **Git Audit-HEAD-Commit**: `559dac06918cacd5440df9d1c6fe85c72512a7a5`
- **Laufende Container-Image-ID**: `sha256:3bc43a4394be73f5063004761ef9c03fa0527d8e866355421bb5639296e24239` (Version `1.0.3`, Linux AMD64)
- **Laufende Container-ID**: `36163bb0fcae8dbb65c3f541ae081cd19d4762177d930b97a331c7351270f4f2`
- **Vollständiges Quell-Manifest**: [container_source_manifest.json](container_source_manifest.json) (31 Python-Dateien, SHA-256)
- **Vollständiges Paket-Manifest**: [container_pip_manifest.json](container_pip_manifest.json) (54 Pakete, alle Versionen)
- **Unabhängiger Vergleich**: [source_comparison.json](source_comparison.json) (31 identisch, 0 Diffs, 0 Missing, 0 Extra)
- **Persistenter Volume-Mount**: `statement2muster_s2m-data` $\rightarrow$ `/app/data` (Driver: `local`, Mode: `rw`)
- **Cgroups v2**: `memory.max=536870912` (512 MiB), `cpu.max='100000 100000'` (1.0 CPU)
- **Sicherheitsgrenzen**: `uid=10001(appuser)`, `readonly_rootfs=true`, `/tmp` tmpfs 64 MiB

---

## 4. Empirischer Auszug: Decision 22 P1 Regression ([results_v7.json](results_v7.json))

```json
{
  "decision_22_p1_regression": {
    "cgroup_memory_events_start": {
      "low": 0,
      "high": 0,
      "max": 0,
      "oom": 0,
      "oom_kill": 0,
      "oom_group_kill": 0
    },
    "cgroup_memory_events_after_special_files": {
      "low": 0,
      "high": 0,
      "max": 0,
      "oom": 0,
      "oom_kill": 0,
      "oom_group_kill": 0
    },
    "oom_kill_increment": 0,
    "test_3_1_adversarial_filename_as_valid_csv": {
      "filename": "__c07_adversarial_oom_probe__.csv",
      "http_code": 200,
      "parsed_transactions": 1,
      "elapsed_seconds": 0.059,
      "oom_triggered": false,
      "passed": true
    },
    "test_3_2_slow_living_filename_as_valid_csv": {
      "filename": "__c07_slow_living_probe__.csv",
      "http_code": 200,
      "parsed_transactions": 1,
      "elapsed_seconds": 0.039,
      "hang_triggered": false,
      "passed": true
    },
    "test_3_3_adversarial_filename_as_invalid_data": {
      "filename": "__c07_adversarial_oom_probe__.csv",
      "http_code": 422,
      "elapsed_seconds": 0.034,
      "expected_format_error": true,
      "passed": true
    },
    "test_3_4_subsequent_standard_request": {
      "filename": "standard_statement.csv",
      "http_code": 200,
      "parsed_transactions": 1,
      "elapsed_seconds": 0.037,
      "passed": true
    },
    "sqlite_integrity_check": "ok",
    "ledger_record_count": 4,
    "all_p1_regressions_passed": true
  }
}
```

---

## 5. Antrag auf formale Schließung (FULL GO für Block C07)

Nachdem in Entscheidung 22 die beiden адресные цепочки (OOM/Quota/SQLite und Living Process Kill/Reap Failure) bereits vollumfänglich akzeptiert und geschlossen wurden, ist nun auch der letzte verbliebene Punkt — die restlose Beseitigung der Test-Trigger aus dem Produktionscode und der Nachweis der ungestörten Standardfunktionalität auf dem Clean Release Image `1.0.3` — vollständig erbracht:
1. **Keine Test-Hooks im Produktionscode**: Vollständige Bereinigung von `BankParserRegistry`.
2. **Sauberes Release-Image `1.0.3`**: Image `sha256:3bc43a4394be...` auf Basis von Commit `559dac06918cacd5440df9d1c6fe85c72512a7a5` im Einsatz.
3. **P1-Regression bestanden**: Beide speziellen Dateinamen verhalten sich wie gewöhnliche Dateien (Parse in <0.06s, HTTP 200, 0 OOM-Events, kein Hängen).
4. **Manifest-Prüfung**: 31/31 Dateien stimmen exakt mit den Git-Blobs überein (0 Diffs).
5. **Alle 10 weiteren Betriebskriterien** (Cgroups 512M/1.0 CPU, Non-Root UID 10001, Readonly Rootfs, Timeout, Crash, CPU-Burn, Cancellation, Overload, Zero-Retention Canaries, Persistence) sind grün.

Wir beantragen die **endgültige formale Schließung des Blocks C07 und die Erteilung des offiziellen FULL GO für die Linux-Betriebsumgebung**.
