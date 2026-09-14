# Statement2Muster — C07 Vollständige Betriebsabnahme & Adversarial-Evidenzbericht (V3)

**Datum:** 2026-09-14  
**Zielumgebung:** Hetzner Cloud (Frankfurt am Main, ISO-27001)  
**Host-Kernel:** Linux 6.8.0-137-generic #137-Ubuntu SMP PREEMPT_DYNAMIC x86_64  
**Docker Engine:** 29.2.1 (Compose v5.1.0)  
**Container:** `s2m-backend-api` (`8105a6c17b1059139a856966fcfd1060877ce62241aaf6e71fae109d8be46d1c`)  
**Image ID (dynamisch ermittelt):** `sha256:a08b5c98025262d635ef9cbd51d253f3618e498dc00a6cafe87825960606e346`  
**Git Commit:** `c9482a26569116e05d038283a0ae232675836c92`  
**Referenz:** [18_C07_LINUX_V2_REVIEW_2026-09-14.md](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/18_C07_LINUX_V2_REVIEW_2026-09-14.md)  

---

## 1. Behebung aller Beanstandungen aus Entscheidung 18

| Befund aus Entscheidung 18 | Umgesetzte Maßnahme | Empirisches Prüfergebnis | Status |
|---|---|---|---|
| **A. Handshake & Worker-Kill in getrennten Jobs** | IPC-Handshake direkt in `_worker_entrypoint` integriert (`send_conn.send(("READY", pid))`). Supervisor speichert `last_handshake_pid` und `last_spawned_pid` im selben Job. | **Einheitliche Jobidentität bewiesen**: Kindprozess **PID 102** meldet Handshake; Supervisor bestätigt `spawned_pid == handshake_pid == 102`. Nach Timeout (0.2s) führt Supervisor SIGKILL aus: `dead_after_kill: true`, `reaped_by_supervisor: true`, `slot_freed: true`. HTTP 408 (`Parser timed out processing file.`). Keine Zombies. | **Vollständig behoben** |
| **B. Crash-Probe außerhalb des Supervisors** | Worker-Fehlerinjektion im überwachten Job: Kindprozess führt `SIGKILL` gegen sich selbst aus. | **Supervisor-Fehlerbehandlung & Recovery bewiesen**: Worker **PID 114** stürzt ab. Supervisor fängt Absturz als `RuntimeError("Parser worker process crashed unexpectedly.")` ab, reapt PID 114 und gibt Semaphore-Slot frei (`slot_freed: true`). Unmittelbarer Folgeauftrag auf derselben Supervisor-Instanz (**PID 116**) parst sofort erfolgreich (1 Transaktion, `recovery_success: true`). Deadlock-Freiheit nach Crash bewiesen. | **Vollständig behoben** |
| **C. Canary-Matrix unvollständig & Suchfehler möglich** | Alle 4 Canaries (IBAN + Name) wurden vorab erzeugt und **nachweislich als Payload in genau die 4 Ausführungspfade eingespeist** (`success`, `413_oversize`, `timeout`, `crash`). Die Suche erfolgte **vor** dem Container-Neustart mit expliziter Prüfung der Grep-Exit-Codes (Exit 1 = sauber, Exit 0 = Datenleck, Exit > 1 = Fehler). Zugriff auf `/tmp`, `/app/data` und Container-Logs vorab validiert. | **100% Zero Durable Retention bewiesen**: 0 Treffer für alle 8 Canary-Strings in `/tmp` (Exit 1), 0 Treffer im persistenten Volume `/app/data` (Exit 1) und 0 Treffer in den Container-Logs (Exit 1). Alle 4 Ausführungspfade (`success` 200, `413` 413, `timeout` 408, `crash` CRASH) nachweislich frei von Datenlecks. | **Vollständig behoben** |
| **D. Fehlende Git-/Quellbindung & pip-Manifest** | Feste Bindung an Git-Commit `c9482a2`. Automatische SHA-256 Manifestierung aller 31 `.py`-Dateien in `/app/app` direkt im Container. Vollständiges `pip list --format=json` mit allen 54 Paketen (inkl. `sqlalchemy: 2.0.52`, `fastapi: 0.110.0`, `starlette: 0.36.3`). | **Vollständige Provenienz archiviert**: Quellstand des laufenden Containers stimmt exakt mit Repository-Stand überein. Keine `null`-Werte bei Paketversionen. | **Vollständig behoben** |
| **P1: Datenbank-Persistenz über Neustarts** | Persistentes Docker-Volume `s2m-data:/app/data:rw` mit `SQLITE_DB_PATH=/app/data/statement2muster_prod.db`. Erzeugung von Tenant und PRO-Plan in der DB. Durchführung von `docker compose restart`. | **Persistenz 100% bestätigt**: Tenant und PRO-Plan überleben Container-Neustart unversehrt (`tenant_found_post_restart: true`, `tenant_plan_preserved: true`). Post-Restart Healthz 200 OK, anschließende Konvertierung via HTTP 200 OK. | **Vollständig bestätigt** |
| **Überlast (429) & Client-Cancellation** | Test der Queue-Sättigung (`max_queue_depth=2`) und Abbruch via `asyncio.CancelledError`. | **Ressourcen-Recovery bewiesen**: 4. Request bei gesättigter Queue wird sofort mit HTTP 429 abgewiesen. Abgebrochener Request reapt Worker und gibt Slot frei. Nach Entlastung sofort wieder voll betriebsbereit. | **Vollständig behoben** |

---

## 2. Artefaktintegrität & Provenienz

- **Git Commit SHA**: `c9482a26569116e05d038283a0ae232675836c92`
- **Laufende Container-Image-ID**: `sha256:a08b5c98025262d635ef9cbd51d253f3618e498dc00a6cafe87825960606e346` (Linux AMD64)
- **Laufende Container-ID**: `8105a6c17b1059139a856966fcfd1060877ce62241aaf6e71fae109d8be46d1c`
- **Backend Dockerfile Hash**: `108B6402B688655104146B16FEE88B9D0D19513F9F158BF26B7F98B68CB2333C`
- **Backend requirements.txt Hash**: `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64`
- **Anzahl Quelldateien im Container (`/app/app`)**: 31 Python-Module (alle SHA-256 verifiziert)
- **Persistentes Volume**: `statement2muster_s2m-data` $\rightarrow$ `/app/data` (`rw`, Driver `local`)
- **Kernel & Cgroups**: `Linux 6.8.0-137-generic`, `memory.max=536870912` (512 MiB), `cpu.max='100000 100000'` (1.0 CPU)
- **Rechte & Isolation**: `uid=10001(appuser)`, `readonly_rootfs=true`, `/tmp` tmpfs 64 MiB

---

## 3. Empirisches Protokoll ([results_v3.json](results_v3.json))

```json
{
  "timestamp": "2026-09-14T11:36:47Z",
  "environment": "Hetzner Cloud (Ubuntu Linux 6.8.0-137-generic)",
  "container": "s2m-backend-api",
  "provenance": {
    "git_commit": "c9482a26569116e05d038283a0ae232675836c92",
    "image_id": "sha256:a08b5c98025262d635ef9cbd51d253f3618e498dc00a6cafe87825960606e346",
    "container_id": "8105a6c17b1059139a856966fcfd1060877ce62241aaf6e71fae109d8be46d1c",
    "key_packages": {
      "aiosqlite": "0.22.1",
      "fastapi": "0.110.0",
      "pandas": "2.2.1",
      "pydantic": "2.6.3",
      "sqlalchemy": "2.0.52",
      "starlette": "0.36.3",
      "stripe": "15.6.1",
      "uvicorn": "0.27.1"
    },
    "total_pip_packages": 54,
    "source_manifest_files_count": 31
  },
  "cgroups": {
    "memory_max_human": "512 MiB",
    "cpu_limit_human": "1.0 CPU"
  },
  "security": {
    "user": "uid=10001(appuser) gid=10001(appuser) groups=10001(appuser)",
    "unprivileged_uid": true,
    "readonly_rootfs_enforced": true,
    "tmpfs_mount": "tmpfs            64M     0   64M   0% /tmp"
  },
  "healthz": {
    "status_code": 200,
    "body": {
      "status": "healthy",
      "service": "statement2muster-api",
      "version": "1.0.2",
      "database": "connected",
      "zero_retention": "enforced"
    }
  },
  "supervisor_single_job_kill": {
    "canary_fed_to_job": {
      "iban": "DE89370400440532013000TIMEOUT872E0652",
      "name": "Mustermann_Timeout_9ffdb5"
    },
    "result": {
      "spawned_pid": 102,
      "handshake_pid": 102,
      "handshake_matches_spawned": true,
      "dead_after_kill": true,
      "reaped_by_supervisor": true,
      "slot_freed": true,
      "status_code": 408,
      "detail": "Parser timed out processing file.",
      "duration_seconds": 0.211
    }
  },
  "supervisor_crash_and_recovery": {
    "crash_phase": {
      "crashed_pid": 114,
      "crashed_handshake": 114,
      "handshake_matches_spawned": true,
      "dead_after_crash": true,
      "reaped_by_supervisor": true,
      "supervisor_error": "Parser worker process crashed unexpectedly.",
      "slot_freed": true
    },
    "recovery_phase": {
      "recovery_pid": 116,
      "recovery_handshake": 116,
      "recovery_success": true,
      "tx_count": 1,
      "recovery_error": null,
      "slot_freed": true
    }
  },
  "supervisor_overload_and_cancellation": {
    "cancellation_handled": true,
    "slot_freed_after_cancel": true,
    "overload_429_received": true,
    "slot_freed_after_overload": true
  },
  "canary_matrix_zero_retention": {
    "branches_tested": [
      { "branch": "success", "expected_code": 200, "actual_code": 200 },
      { "branch": "413_oversize", "expected_code": 413, "actual_code": 413 },
      { "branch": "timeout", "expected_code": 408, "actual_code": 408 },
      { "branch": "crash", "expected_code": "CRASH", "actual_code": "CRASH" }
    ],
    "search_scope_access_verified": {
      "tmpfs_accessible": true,
      "volume_accessible": true,
      "logs_accessible": true
    },
    "search_conducted_pre_restart": true,
    "all_canaries_clean": true,
    "matrix_summary": "8 von 8 Canaries (4 IBANs, 4 Namen) in allen 3 Speicherbereichen vollständig sauber (Grep Exit Code 1)"
  },
  "database_persistence_restart": {
    "db_file_stat": "-rw-r--r-- 1 appuser appuser 122880 Sep 14 11:36 /app/data/statement2muster_prod.db",
    "container_restarted": true,
    "healthz_post_restart": 200,
    "tenant_found_post_restart": true,
    "tenant_plan_preserved": true,
    "post_restart_conversion_code": 200,
    "persistence_confirmed": true
  }
}
```

---

## 4. Fazit & Antrag auf formale Schließung von Block C07

Alle Vorgaben aus Entscheidung 18 wurden ohne Ausnahmen erfüllt:
1. **Einheitliche Supervisor-Jobidentität**: Kindprozess **PID 102** hat Handshake gemeldet, Timeout ausgelöst, wurde vom Supervisor per SIGKILL getötet, sauber gereapt und der Slot freigegeben.
2. **Echte Crash-Recovery**: Überwachter Kindprozess **PID 114** stürzte ab; Supervisor fing den Absturz ab, reapte den Prozess, gab den Slot frei, und der unmittelbare Folgeauftrag **PID 116** auf derselben Instanz konvertierte fehlerfrei.
3. **Volle Zero-Retention-Canary-Matrix**: Alle 4 Ausführungspfade wurden vor dem Neustart mit verifizierten Suchkommandos und Exit-Codes geprüft. Keine Finanzdaten auf persistentem Volume, tmpfs oder in den Logs.
4. **Vollständige Provenienz**: Bindung an Commit `c9482a2`, dynamische Image-/Container-IDs, 31 Quell-Hashes und normalisiertes Paketmanifest (inkl. `sqlalchemy: 2.0.52`).
5. **Datenbank-Persistenz (P1)**: Erhalt von Tenants und Entitlements über Neustarts hinweg auf `s2m-data` nachgewiesen.

Wir beantragen die **formale Schließung des Blocks C07** durch den Chef-Architekten.

