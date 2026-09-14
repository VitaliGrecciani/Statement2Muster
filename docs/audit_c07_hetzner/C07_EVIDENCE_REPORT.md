# Statement2Muster — C07 Vollständige Betriebsabnahme & Adversarial-Evidenzbericht (V4)

**Datum:** 2026-09-14  
**Zielumgebung:** Hetzner Cloud (Frankfurt am Main, ISO-27001)  
**Host-Kernel:** Linux 6.8.0-137-generic #137-Ubuntu SMP PREEMPT_DYNAMIC x86_64  
**Docker Engine:** 29.2.1 (Compose v5.1.0)  
**Container:** `s2m-backend-api` (`8105a6c17b1059139a856966fcfd1060877ce62241aaf6e71fae109d8be46d1c`)  
**Image ID (dynamisch ermittelt):** `sha256:a08b5c98025262d635ef9cbd51d253f3618e498dc00a6cafe87825960606e346`  
**Git Build-Commit:** `c9482a23004ee7bc7aeea17bfd0ad3bda0c56f8e`  
**Git Audit-HEAD-Commit:** `71b75089e4f600187a1b5f4e7800d1152de0a99a`  
**Referenz:** [19_C07_LINUX_V3_REVIEW_2026-09-14.md](file:///c:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/19_C07_LINUX_V3_REVIEW_2026-09-14.md)  

---

## 1. Behebung der verbliebenen Befunde aus Entscheidung 19

| Befund aus Entscheidung 19 | Umgesetzte Maßnahme | Empirisches Prüfergebnis | Status |
|---|---|---|---|
| **C. Verdeckte Exit-Codes durch `\|\| true`** | Alle `\|\| true`-Konstrukte vollständig entfernt. Original-Grep-Befehle (`grep -rnF`) direkt ausgeführt. Container-Logs vorab mit geprüftem Returncode erfasst und als Datei durchsucht. Scope-Zugriff (`tmpfs_writable`, `volume_accessible`, `docker_logs_captured`) aus echten Returncodes abgeleitet. | **Verifizierter Grep-Exit-Code 1 (CLEAN)** für alle 8 Canary-Strings in `/tmp`, `/app/data` und Container-Logs. Standardgemäß: Exit 1 = 0 Treffer (sauber), Exit 0 = Fund (Leck), Exit > 1 = Fehler. Alle Aufrufe lieferten `exit_code: 1` mit leerem `stdout` und leerem `stderr`. Keine Datenfunde. | **Vollständig behoben** |
| **D. Git-Commit-Auflösung & vollständige Manifeste** | Tatsächlicher Build-Commit `c9482a23004ee7bc7aeea17bfd0ad3bda0c56f8e` gebunden. Vollständige Archivierung aller 31 Quell-Hashes in `container_source_manifest.json` und aller 54 Pip-Pakete in `container_pip_manifest.json`. Pfad- und Hashabgleich gegen Repo. | **0 Abweichungen bewiesen**: 31 von 31 Quelldateien zwischen Repo und Container exakt identisch (`identical_files_count: 31`, `diff_count: 0`, `missing: []`, `extra: []`, `source_binding_verified: true`). Vollständiges Pip-Manifest mit allen 54 Paketen ohne Lücken archiviert. | **Vollständig behoben** |
| **Cancellation PID & Reaping** | Test des Abbruchs via `asyncio.CancelledError` mit expliziter Prüfung auf Prozessstart, Handshake-PID, Tötung und Reaping. | **PID 126**: `handshake_confirmed: true`, `alive_before_cancel: true`, `cancelled_caught: true`, `dead_after_cancel: true`, `reaped_by_supervisor: true`, `slot_freed: true`. Prozess wird bei Cancellation verlässlich getötet und gereapt. | **Vollständig behoben** |
| **Ressourcen-Recovery / Pure CPU-Burn Loop** | Worker führt reine CPU-Vollastschleife (`while True: pass`, kein Sleep) aus. Supervisor-Timeout (0.2s) greift unter cgroup-Limit 1.0 CPU. | **PID 116**: Supervisor beendet die CPU-Schleife hart per SIGKILL: `timed_out_408: true`, `hard_kill_executed: true`, `reaped_by_supervisor: true`, `slot_freed_after_kill: true`. Unmittelbarer Folgeauftrag auf demselben Supervisor konvertiert sofort erfolgreich (`subsequent_request_succeeded: true`). | **Vollständig behoben** |
| **A & B (Bereits in V3 anerkannt)** | Einheitliche Supervisor-Jobidentität (PID 91 / 91) und Supervisor Crash/Recovery (PID 103 $\rightarrow$ PID 105). | Bestätigt und erneut reproduziert. Slot-Freigabe und Folgeauftrag 100% erfolgreich. | **Anerkannt** |
| **P1: Zustands-Persistenz** | Erhalt von Tenants und PRO-Entitlement auf `s2m-data:/app/data` über `docker compose restart` hinweg. | Erneut reproduziert: Tenant und PRO-Plan erhalten, post-restart Healthz 200, post-restart Konvertierung 200 OK. | **Anerkannt** |

---

## 2. Artefaktintegrität & Provenienz-Dateien

- **Git Build-Commit**: `c9482a23004ee7bc7aeea17bfd0ad3bda0c56f8e`
- **Git Audit-HEAD-Commit**: `71b75089e4f600187a1b5f4e7800d1152de0a99a`
- **Laufende Container-Image-ID**: `sha256:a08b5c98025262d635ef9cbd51d253f3618e498dc00a6cafe87825960606e346` (Linux AMD64)
- **Laufende Container-ID**: `8105a6c17b1059139a856966fcfd1060877ce62241aaf6e71fae109d8be46d1c`
- **Vollständiges Quell-Manifest**: [container_source_manifest.json](container_source_manifest.json) (31 Python-Dateien, SHA-256)
- **Vollständiges Paket-Manifest**: [container_pip_manifest.json](container_pip_manifest.json) (54 Pakete, alle Versionen)
- **Abgleich Repo vs. Container**: 31 identisch, 0 Diffs, 0 Missing, 0 Extra (`source_binding_verified: true`)
- **Backend Dockerfile Hash**: `108B6402B688655104146B16FEE88B9D0D19513F9F158BF26B7F98B68CB2333C`
- **Persistenter Volume-Mount**: `statement2muster_s2m-data` $\rightarrow$ `/app/data` (Driver: `local`, Mode: `rw`)
- **Cgroups v2**: `memory.max=536870912` (512 MiB), `cpu.max='100000 100000'` (1.0 CPU)
- **Sicherheitsgrenzen**: `uid=10001(appuser)`, `readonly_rootfs=true`, `/tmp` tmpfs 64 MiB

---

## 3. Empirisches Protokoll ([results_v4.json](results_v4.json))

```json
{
  "timestamp": "2026-09-14T11:41:40Z",
  "environment": "Hetzner Cloud (Ubuntu Linux 6.8.0-137-generic)",
  "container": "s2m-backend-api",
  "provenance": {
    "git_build_commit": "c9482a23004ee7bc7aeea17bfd0ad3bda0c56f8e",
    "git_audit_head_commit": "71b75089e4f600187a1b5f4e7800d1152de0a99a",
    "image_id": "sha256:a08b5c98025262d635ef9cbd51d253f3618e498dc00a6cafe87825960606e346",
    "container_id": "8105a6c17b1059139a856966fcfd1060877ce62241aaf6e71fae109d8be46d1c",
    "total_pip_packages": 54,
    "source_manifest_files_count": 31,
    "comparison_against_repo": {
      "identical_files_count": 31,
      "diff_count": 0,
      "diffs": {},
      "missing_in_container": [],
      "extra_in_container": [],
      "source_binding_verified": true
    }
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
      "iban": "DE89370400440532013000TIMEOUT6E648E44",
      "name": "Mustermann_Timeout_5dfa7c"
    },
    "result": {
      "spawned_pid": 91,
      "handshake_pid": 91,
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
      "crashed_pid": 103,
      "crashed_handshake": 103,
      "handshake_matches_spawned": true,
      "dead_after_crash": true,
      "reaped_by_supervisor": true,
      "supervisor_error": "Parser worker process crashed unexpectedly.",
      "slot_freed": true
    },
    "recovery_phase": {
      "recovery_pid": 105,
      "recovery_handshake": 105,
      "recovery_success": true,
      "tx_count": 1,
      "recovery_error": null,
      "slot_freed": true
    }
  },
  "supervisor_cpu_burn_recovery": {
    "burn_pid": 116,
    "burn_handshake": 116,
    "handshake_matches_spawned": true,
    "hard_kill_executed": true,
    "reaped_by_supervisor": true,
    "slot_freed_after_kill": true,
    "timed_out_408": true,
    "burn_duration_seconds": 0.21,
    "subsequent_request_succeeded": true
  },
  "supervisor_cancellation_lifecycle": {
    "cancel_spawned_pid": 126,
    "cancel_handshake_pid": 126,
    "handshake_confirmed": true,
    "alive_before_cancel": true,
    "cancelled_caught": true,
    "dead_after_cancel": true,
    "reaped_by_supervisor": true,
    "slot_freed": true
  },
  "supervisor_overload_429": {
    "overload_429_received": true,
    "detail": "Parser queue depth exceeded. Please retry.",
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
      "tmpfs_writable": true,
      "volume_accessible": true,
      "docker_logs_captured": true
    },
    "search_conducted_pre_restart": true,
    "all_canaries_clean": true,
    "exit_code_interpretation": "Exit 1 = 0 matches found (CLEAN); Exit 0 = match found (LEAK); Exit > 1 = grep execution error",
    "matrix_sample_verified_exit_codes": [
      {
        "canary_string": "DE89370400440532013000SUCCESS7E1E6246",
        "tmp": { "exit_code": 1, "stdout": "", "stderr": "", "status": "CLEAN" },
        "volume": { "exit_code": 1, "stdout": "", "stderr": "", "status": "CLEAN" },
        "logs": { "exit_code": 1, "stdout": "", "stderr": "", "status": "CLEAN" },
        "all_clean": true
      }
    ]
  },
  "database_persistence_restart": {
    "db_file_stat": "-rw-r--r-- 1 appuser appuser 122880 Sep 14 11:41 /app/data/statement2muster_prod.db",
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

## 4. Fazit & Antrag auf endgültige Schließung von Block C07

Alle offenen Punkte aus Entscheidung 19 sind lückenlos und empirisch nachgewiesen:
1. **Verifizierte Grep-Statuswerte**: Jeder Suchbefehl liefert echten Exit-Code 1 (ohne `|| true`), saubere Ausgaben und geprüfte Scope-Berechtigung.
2. **Quell- und Paketprovenienz**: Exakte Bindung an Commit `c9482a23004ee7bc7aeea17bfd0ad3bda0c56f8e`, 31/31 Quelldateien identisch (0 Diffs), vollständige Manifeste archiviert.
3. **Ressourcen-Recovery & Cancellation**: Pure CPU-Vollastschleife durch SIGKILL beendet und gereapt; Cancellation reapt Worker und gibt Slot frei; Überlast führt zu regulärem 429.
4. **Zustands-Persistenz (P1)**: Erhalt von Tenants und Entitlements auf `s2m-data` über Neustarts hinweg bestätigt.

Wir beantragen die **vollständige und formale Schließung des Blocks C07** durch den Chef-Architekten.


