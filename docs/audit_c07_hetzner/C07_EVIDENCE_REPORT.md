# Statement2Muster — C07 Vollständige Betriebsabnahme & Adversarial-Evidenzbericht (V5)
# Финальный отчет об эксплуатационной приемке и стресс-тестировании Блока C07 (V5)

**Datum:** 2026-09-14  
**Zielumgebung:** Hetzner Cloud (Frankfurt am Main, ISO-27001)  
**Host-Kernel:** Linux 6.8.0-137-generic #137-Ubuntu SMP PREEMPT_DYNAMIC x86_64  
**Docker Engine:** 29.2.1 (Compose v5.1.0)  
**Container:** `s2m-backend-api` (`399556c5cbcc7a7001382def832da7edf66444474a8ee90d4bc2c474dff27f82`)  
**Image ID:** `sha256:7df1d46ca7ba19992831dda724950943a13e1fc27a406c2b149499fef9773c62`  
**Git Build-Commit:** `4268c7a9b3c8cef77fa92cdc154c52af17a190c1`  
**Git Audit-HEAD-Commit:** `4268c7a9b3c8cef77fa92cdc154c52af17a190c1`  
**Referenz:** [20_C07_LINUX_V4_REVIEW_2026-09-14.md](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/20_C07_LINUX_V4_REVIEW_2026-09-14.md)  

---

## 1. Behebung der beiden verbliebenen Szenarien aus Entscheidung 20 (Abschnitt 3)

| Szenario aus Entscheidung 20 | Umgesetzte Maßnahme | Empirisches Prüfergebnis ([results_v5.json](results_v5.json)) | Status |
|---|---|---|---|
| **1. OOM / Ressourcen-Recovery unter 512 MiB** | Aggressive Speicherallokation im isolierten Worker-Prozess (`oom_parse`, 40 MiB Chunks) bis zur Überschreitung von `memory.max=536870912`. Überwachung von `/sys/fs/cgroup/memory.events` vor und nach dem Test. | **Cgroups v2 OOM-Ereignis bestätigt**: `oom_kill` Zähler inkrementiert von 1 auf 2 (`oom_kill_increment: 1`, `oom_event_increment: 1`). Der Linux-Kernel tötete den Worker (PID 217) hart per SIGKILL (`exit_code: -9`). Supervisor fing den Absturz ab, reapte den Prozess (`reaped_by_supervisor: true`), gab den Concurrency-Slot frei (`slot_freed: true`). Quoten-Reservierung wurde freigegeben (keine hängende Quote). Unmittelbarer Folgeauftrag auf demselben Supervisor konvertierte erfolgreich (`subsequent_recovery_success: true`, 1 Buchung). DB-Zustand auf `/app/data` intakt. | **Vollständig behoben & verifiziert** |
| **2. Kill/Reap-Fehlschlag & Kontrollierte Recovery** | Kontrollierte Injektion eines unbestätigten Prozessendes im Supervisor-Bereinigungspfad (`_pid_exists` simuliert verbleibenden Prozess; Kill-Versuch simuliert Fehlschlag). | **Keine falsche Erfolgsmeldung**: `last_job_reaped: false`. Expliziter Fehlerstatus: `HTTP 500` mit Detail `Parser worker termination failure: process could not be reaped.`. **Schutz vor unkontrolliertem Spawnen**: Concurrency-Slot wurde in Quarantäne gehalten (`pid_quarantined: true`, `slot_held_preventing_spawns: true`), Semaphore-Wert um 1 reduziert. **Definierter Wiederherstellungspfad**: Aufruf von `reclaim_quarantined_worker(236, force=True)` beendete den Prozess im OS verlässlich (`os_process_confirmed_dead: true`), hob die Quarantäne auf und stellte die volle Parallelität wieder her (`slot_restored_to_max: true`). Folgeauftrag erfolgreich (`subsequent_request_succeeded: true`). | **Vollständig behoben & verifiziert** |
| **Audit-Tool-Härtung (Entscheidung 20, Abs. 2)** | Beseitigung des `repo_manifest = container_manifest` Fallbacks. Strikte Voraussetzung einer extern bereitgestellten `repo_source_manifest.json` mit explizitem Abbruch (`RuntimeError`) bei Fehlen. | **Unabhängige Prüfung ohne Fallback**: [source_comparison.json](source_comparison.json) belegt für alle 31 Quelldateien nach LF-Normalisierung **0 Abweichungen, 0 fehlende, 0 zusätzliche Dateien** (`source_binding_verified: true`). | **Vollständig behoben & verifiziert** |

---

## 2. Statusübersicht aller Betriebsanforderungen für Block C07

| Anforderung | Prüfmethode & Evidenz | Ergebnis V5 | Status |
|---|---|---|---|
| **Cgroups v2 Limits** | `docker exec` Abfrage von `/sys/fs/cgroup/{memory.max, cpu.max}` | `memory.max=536870912` (512.0 MiB), `cpu.max=100000 100000` (1.0 CPU) | **AKZEPTIERT** (Entsch. 17, 20) |
| **Sicherheitsisolation** | `id`, Schreibtest auf RootFS vs. `/tmp` | `uid=10001(appuser)`, `readonly_rootfs=true`, `/tmp` tmpfs 64M | **AKZEPTIERT** (Entsch. 17, 20) |
| **Supervisor Jobidentität & Timeout** | Single-Job Injektion mit IPC-Handshake (PID 153/153) | Timeout 0.2s, HTTP 408, SIGKILL, Reaped, Slot frei | **AKZEPTIERT** (Entsch. 19, 20) |
| **Supervisor Crash-Recovery** | `suicidal_parse` (PID 165 $\rightarrow$ 167) auf demselben Supervisor | SIGKILL abgefangen, gereapt, Folgeauftrag 1 TX erfolgreich | **AKZEPTIERT** (Entsch. 19, 20) |
| **Pure CPU-Burn Recovery** | `while True: pass` Schleife (PID 178) unter 1.0 CPU Limit | SIGKILL nach 0.2s, gereapt, Folgeauftrag erfolgreich | **AKZEPTIERT** (Entsch. 20) |
| **Client-Cancellation** | `asyncio.CancelledError` nach Handshake (PID 189) | Worker getötet, gereapt, Concurrency-Slot freigegeben | **AKZEPTIERT** (Entsch. 20) |
| **Überlastschutz** | Sättigung der Warteschlange (max_queue_depth=2) | Sofortiges HTTP 429 (`Parser queue depth exceeded`), Slot frei | **AKZEPTIERT** (Entsch. 19, 20) |
| **OOM-Recovery (512 MiB)** | Speicherüberlastung bis Kernel-OOM | `oom_kill` Event +1, Exitcode -9 erkannt, gereapt, Folgeauftrag 200 | **V5 NEU BEHOBEN** |
| **Kill/Reap-Fehlschlag** | Injektion unbestätigter Prozessbereinigung | HTTP 500, Slot quarantänisiert, definierter Reclaim erfolgreich | **V5 NEU BEHOBEN** |
| **Zero-Retention Canaries** | 8 Canary-Strings $\times$ 3 Scopes (`/tmp`, `/app/data`, Logs) | **24/24 verifizierter Grep-Exit-Code 1 (CLEAN)**, kein `\|\| true` | **AKZEPTIERT** (Entsch. 20) |
| **Zustands-Persistenz** | SQLite auf Volume `statement2muster_s2m-data:/app/data` | Container-Neustart via Compose, Tenant & PRO-Plan erhalten, 200 OK | **AKZEPTIERT** (Entsch. 18, 20) |
| **Provenienz & Manifeste** | 31 Python-Dateien, 54 Pip-Pakete, Commit `4268c7a` | 31/31 Dateien identisch zu Git blobs (LF-normiert), 0 Diffs | **AKZEPTIERT** (Entsch. 20) |

---

## 3. Artefaktintegrität & Provenienz-Dateien

- **Git Build-Commit**: `4268c7a9b3c8cef77fa92cdc154c52af17a190c1`
- **Git Audit-HEAD-Commit**: `4268c7a9b3c8cef77fa92cdc154c52af17a190c1`
- **Laufende Container-Image-ID**: `sha256:7df1d46ca7ba19992831dda724950943a13e1fc27a406c2b149499fef9773c62` (Linux AMD64)
- **Laufende Container-ID**: `399556c5cbcc7a7001382def832da7edf66444474a8ee90d4bc2c474dff27f82`
- **Vollständiges Quell-Manifest**: [container_source_manifest.json](container_source_manifest.json) (31 Python-Dateien, SHA-256)
- **Vollständiges Paket-Manifest**: [container_pip_manifest.json](container_pip_manifest.json) (54 Pakete, alle Versionen)
- **Unabhängiger Vergleich**: [source_comparison.json](source_comparison.json) (31 identisch, 0 Diffs, 0 Missing, 0 Extra)
- **Persistenter Volume-Mount**: `statement2muster_s2m-data` $\rightarrow$ `/app/data` (Driver: `local`, Mode: `rw`)
- **Cgroups v2**: `memory.max=536870912` (512 MiB), `cpu.max='100000 100000'` (1.0 CPU)
- **Sicherheitsgrenzen**: `uid=10001(appuser)`, `readonly_rootfs=true`, `/tmp` tmpfs 64 MiB

---

## 4. Empirischer Auszug: OOM und Kill-Failure ([results_v5.json](results_v5.json))

```json
{
  "supervisor_oom_recovery": {
    "cgroup_memory_events_before": {
      "oom": 1,
      "oom_kill": 1,
      "max": 1857
    },
    "cgroup_memory_events_after": {
      "oom": 2,
      "oom_kill": 2,
      "max": 3545
    },
    "oom_kill_increment": 1,
    "oom_event_increment": 1,
    "oom_event_confirmed": true,
    "worker_pid": 217,
    "handshake_pid": 217,
    "handshake_matches_spawned": true,
    "worker_dead_after_oom": true,
    "reaped_by_supervisor": true,
    "slot_freed": true,
    "supervisor_error": "Parser worker process crashed unexpectedly (exit_code: -9).",
    "kernel_sigkill_detected": true,
    "subsequent_recovery_success": true,
    "subsequent_tx_count": 1
  },
  "supervisor_kill_failure_injection": {
    "injected_pid": 236,
    "failure_phase": {
      "http_status": 500,
      "http_detail": "Parser worker termination failure: process could not be reaped.",
      "no_false_cleanup": true,
      "pid_quarantined": true,
      "slot_held_preventing_spawns": true,
      "quarantined_count": 1
    },
    "recovery_phase": {
      "reclaim_executed": true,
      "os_process_confirmed_dead": true,
      "slot_restored_to_max": true,
      "quarantine_cleared": true,
      "subsequent_request_succeeded": true
    }
  }
}
```

---

## 5. Antrag auf formale Schließung

Alle vom Chef-Architekten in Entscheidung 20 formulierten Bedingungen sind empirisch erfüllt, reproduzierbar dokumentiert und im Produktionsabbild verifiziert:
1. **OOM-Recovery unter 512 MiB nachgewiesen** (cgroups v2 `oom_kill` Inkrement, SIGKILL-Erkennung, Reaping, Slot-Freigabe, erfolgreicher Folgeauftrag).
2. **Kill/Reap-Fehlschlag nachgewiesen** (HTTP 500, kein falscher Cleanup-Report, Quarantäne-Slot-Schutz gegen unkontrollierte Worker, definierter Reclaim-Pfad, OS-Prozessabbruch bestätigt).
3. **Audit-Tool gehärtet** (strikte externe Manifest-Prüfung ohne Fallback).

Wir beantragen die **vollständige und endgültige formale Schließung des Blocks C07 (FULL GO für den Linux-Container & Laufzeit-Infrastruktur)**.
