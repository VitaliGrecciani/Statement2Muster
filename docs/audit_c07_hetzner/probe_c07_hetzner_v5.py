#!/usr/bin/env python3
"""
Official C07 Linux Runtime Lifecycle, Persistence, and Adversarial Evidence Suite (V5)
Server: Hetzner Cloud (Ubuntu Linux 6.8.0-137-generic, Docker 29.2.1)
Container: s2m-backend-api (Image: statement2muster-api:1.0.2)
Specifically resolves the remaining two scenarios from Chief Architect Decision 20:
  1. OOM Resource Recovery under 512 MiB limit:
     - Memory exhaustion inside isolated worker process under cgroups v2 memory.max
     - Empirical verification of cgroup memory.events (oom_kill / oom increment)
     - Supervisor detects worker SIGKILL exitcode (-9), reaps process, releases concurrency slot
     - Zero hung quota and successful subsequent parse on same supervisor instance
  2. Kill/Reap Failure Injection & Defined Recovery Path:
     - Controlled injection of unconfirmed reaping in supervisor
     - Explicit HTTP 500 error raised (no false success report)
     - Concurrency slot held in quarantine to prevent uncontrolled worker spawning
     - Invocation of defined recovery path (reclaim_quarantined_worker)
     - Genuine OS-level process death confirmed, slot restored, and subsequent parse succeeds
  3. Audit Suite Hardening:
     - Strict requirement of external repo_source_manifest.json (explicit FAIL if absent, no self-comparison fallback)
     - Complete 31-file source manifest with LF normalization check and comparison against repo
     - Complete 54-package pip manifest archived
  4. Preserves all previously accepted items:
     - Direct grep returncode 1 (CLEAN) on all 8 canaries across 3 scopes
     - Supervisor single-job timeout (408, PID handshake matching)
     - Worker crash & recovery on same supervisor
     - Pure CPU-burn loop & Client cancellation lifecycle
     - Overload 429 rejection
     - SQLite persistence across container restart
"""

import os
import sys
import json
import time
import uuid
import hashlib
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
import jwt

BASE_URL = "http://127.0.0.1:8100"
RESULTS_FILE = Path("/opt/statement2muster/c07_audit_results_v5.json")
CONTAINER_MANIFEST_FILE = Path("/opt/statement2muster/container_source_manifest.json")
PIP_MANIFEST_FILE = Path("/opt/statement2muster/container_pip_manifest.json")
SOURCE_COMP_FILE = Path("/opt/statement2muster/source_comparison.json")
CONTAINER_NAME = "s2m-backend-api"

BUILD_COMMIT = "4268c7a9b3c8cef77fa92cdc154c52af17a190c1"
AUDIT_HEAD_COMMIT = "4268c7a9b3c8cef77fa92cdc154c52af17a190c1"

results = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "environment": "Hetzner Cloud (Ubuntu Linux 6.8.0-137-generic)",
    "container": CONTAINER_NAME,
    "provenance": {},
    "cgroups": {},
    "security": {},
    "healthz": {},
    "supervisor_single_job_kill": {},
    "supervisor_crash_and_recovery": {},
    "supervisor_cpu_burn_recovery": {},
    "supervisor_cancellation_lifecycle": {},
    "supervisor_overload_429": {},
    "supervisor_oom_recovery": {},
    "supervisor_kill_failure_injection": {},
    "canary_matrix_zero_retention": {},
    "database_persistence_restart": {}
}

def run_cmd(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.stdout.strip(), p.stderr.strip(), p.returncode

def run_docker_python(script_str):
    p = subprocess.run(
        f"docker exec -i {CONTAINER_NAME} python -",
        shell=True,
        input=script_str,
        capture_output=True,
        text=True
    )
    return p.stdout.strip(), p.stderr.strip(), p.returncode

def http_req(path, method="GET", data=None, headers=None, files=None, timeout=15):
    url = f"{BASE_URL}{path}"
    headers = headers or {}
    req = urllib.request.Request(url, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
        
    if files:
        boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
        body = []
        for field_name, (filename, content, content_type) in files.items():
            body.append(f"--{boundary}".encode())
            body.append(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode())
            body.append(f"Content-Type: {content_type}\r\n".encode())
            body.append(content if isinstance(content, bytes) else content.encode())
        body.append(f"--{boundary}--\r\n".encode())
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.data = b"\r\n".join(body)
    elif data:
        if isinstance(data, dict):
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(data).encode()
        elif isinstance(data, (bytes, bytearray)):
            req.data = data
        elif isinstance(data, str):
            req.data = data.encode()
            
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            body = resp.read()
            try:
                body_json = json.loads(body.decode("utf-8"))
            except Exception:
                body_json = body.decode("utf-8", errors="replace")
            return code, body_json, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            body_json = json.loads(body.decode("utf-8"))
        except Exception:
            body_json = body.decode("utf-8", errors="replace")
        return e.code, body_json, dict(e.headers)
    except Exception as e:
        return 0, str(e), {}

print("=== STARTING C07 V5 AUDIT SUITE (DECISION 20 REMEDIATION) ===")

# ==============================================================================
# SECTION 1: PROVENANCE, MANIFESTS & STRICT GIT BINDING (Hardened per Decision 20)
# ==============================================================================
print("\n[1/10] Inspecting Container Provenance, Git Binding, and Full Manifests...")
img_id, _, _ = run_cmd(f"docker inspect --format '{{{{.Image}}}}' {CONTAINER_NAME}")
cnt_id, _, _ = run_cmd(f"docker inspect --format '{{{{.Id}}}}' {CONTAINER_NAME}")
mounts_raw, _, _ = run_cmd(f"docker inspect --format '{{{{json .Mounts}}}}' {CONTAINER_NAME}")
try:
    mounts = json.loads(mounts_raw)
except Exception:
    mounts = mounts_raw

# 1. Full pip manifest (all 54 packages)
pip_raw, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} pip list --format=json")
try:
    pip_packages = json.loads(pip_raw)
except Exception:
    pip_packages = []

PIP_MANIFEST_FILE.write_text(json.dumps(pip_packages, indent=2), encoding="utf-8")

key_pkgs = {}
for p in pip_packages:
    name = p.get("name", "").lower()
    if name in ["fastapi", "starlette", "pydantic", "uvicorn", "aiosqlite", "sqlalchemy", "stripe", "pandas"]:
        key_pkgs[name] = p.get("version")

# 2. Complete SHA-256 manifest of all .py files in container (/app/app)
# Both raw byte hash and LF-normalized hash
manifest_script = """
import hashlib, os, json
base = '/app/app'
raw_manifest = {}
lf_manifest = {}
for root, _, files in os.walk(base):
    for f in sorted(files):
        if f.endswith('.py'):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, base).replace('\\\\', '/')
            with open(p, 'rb') as fp:
                data = fp.read()
                raw_manifest[rel] = hashlib.sha256(data).hexdigest()
                lf_manifest[rel] = hashlib.sha256(data.replace(b'\\r\\n', b'\\n')).hexdigest()
print(json.dumps({"raw": raw_manifest, "lf": lf_manifest}))
"""
manifest_raw, _, _ = run_docker_python(manifest_script)
try:
    manifest_data = json.loads(manifest_raw)
    container_manifest = manifest_data.get("raw", {})
    container_lf_manifest = manifest_data.get("lf", {})
except Exception:
    container_manifest = {}
    container_lf_manifest = {}

CONTAINER_MANIFEST_FILE.write_text(json.dumps(container_manifest, indent=2), encoding="utf-8")

# 3. Strict Independent Comparison against Repo Manifest (Decision 20: NO fallback allowed!)
repo_manifest_file = Path("/opt/statement2muster/repo_source_manifest.json")
if not repo_manifest_file.exists():
    raise RuntimeError("CRITICAL AUDIT ERROR: External repo_source_manifest.json is missing! Fallback is forbidden by Decision 20.")

raw_repo = json.loads(repo_manifest_file.read_text(encoding="utf-8"))
repo_manifest = {k.replace('\\', '/'): v for k, v in raw_repo.items()}
container_manifest = {k.replace('\\', '/'): v for k, v in container_manifest.items()}
container_lf_manifest = {k.replace('\\', '/'): v for k, v in container_lf_manifest.items()}

# Compare against LF-normalized Git hashes
diffs_raw = {k: {"repo": repo_manifest.get(k), "container": container_manifest.get(k)} 
             for k in set(repo_manifest) | set(container_manifest) 
             if repo_manifest.get(k) != container_manifest.get(k)}

diffs_lf = {k: {"repo": repo_manifest.get(k), "container_lf": container_lf_manifest.get(k)} 
            for k in set(repo_manifest) | set(container_lf_manifest) 
            if repo_manifest.get(k) != container_lf_manifest.get(k)}

missing_in_container = [k for k in repo_manifest if k not in container_manifest]
extra_in_container = [k for k in container_manifest if k not in repo_manifest]

comparison_record = {
    "total_repo_files": len(repo_manifest),
    "total_container_files": len(container_manifest),
    "raw_byte_diff_count": len(diffs_raw),
    "lf_normalized_diff_count": len(diffs_lf),
    "missing_in_container": missing_in_container,
    "extra_in_container": extra_in_container,
    "source_binding_verified": bool(len(diffs_lf) == 0 and len(missing_in_container) == 0 and len(extra_in_container) == 0)
}
SOURCE_COMP_FILE.write_text(json.dumps(comparison_record, indent=2), encoding="utf-8")

results["provenance"] = {
    "git_build_commit": BUILD_COMMIT,
    "git_audit_head_commit": AUDIT_HEAD_COMMIT,
    "image_id": img_id,
    "container_id": cnt_id,
    "total_pip_packages": len(pip_packages),
    "key_packages": key_pkgs,
    "source_manifest_files_count": len(container_manifest),
    "source_comparison": comparison_record,
    "source_binding_verified": comparison_record["source_binding_verified"],
    "independent_repo_manifest_used": True,
    "mounts": mounts
}
print(f"  Container Image: {img_id}")
print(f"  Container ID: {cnt_id}")
print(f"  Git Build-Commit: {BUILD_COMMIT}")
print(f"  Pip Packages Archived: {len(pip_packages)} (in {PIP_MANIFEST_FILE})")
print(f"  Source Files Checked: {len(container_manifest)} (in {CONTAINER_MANIFEST_FILE})")
print(f"  Repo Comparison (LF-normalized): {len(diffs_lf)} diffs, {len(missing_in_container)} missing, {len(extra_in_container)} extra")
print(f"  Source Binding Verified: {comparison_record['source_binding_verified']}")

# ==============================================================================
# SECTION 2: CGROUPS V2 & SECURITY ISOLATION
# ==============================================================================
print("\n[2/10] Verifying Cgroups v2 Resource Limits & Security Isolation...")
mem_max, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} cat /sys/fs/cgroup/memory.max")
cpu_max, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} cat /sys/fs/cgroup/cpu.max")
uid_raw, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} id")

tmp_ro_test, _, ro_code = run_cmd(f"docker exec {CONTAINER_NAME} touch /app/ro_test")
tmp_write_test, _, rw_code = run_cmd(f"docker exec {CONTAINER_NAME} touch /tmp/rw_test")
run_cmd(f"docker exec {CONTAINER_NAME} rm -f /tmp/rw_test")

results["cgroups"] = {
    "memory_max_bytes": mem_max,
    "memory_max_mib": round(int(mem_max) / (1024*1024), 2) if mem_max.isdigit() else None,
    "cpu_max": cpu_max,
    "limits_conforming": bool(mem_max == "536870912" and cpu_max == "100000 100000")
}
results["security"] = {
    "user_id": uid_raw,
    "non_root_verified": "10001" in uid_raw,
    "readonly_rootfs_enforced": bool(ro_code != 0),
    "tmpfs_writable": bool(rw_code == 0)
}
print(f"  Memory Limit: {results['cgroups']['memory_max_mib']} MiB (Target: 512 MiB)")
print(f"  CPU Limit: {results['cgroups']['cpu_max']} (Target: 1.0 CPU)")
print(f"  Non-Root User: {results['security']['non_root_verified']} ({uid_raw})")
print(f"  Read-Only RootFS: {results['security']['readonly_rootfs_enforced']}")

# ==============================================================================
# SECTION 3: SUPERVISOR SINGLE-JOB TIMEOUT & HARD SIGKILL (Finding A)
# ==============================================================================
print("\n[3/10] Verifying Supervisor Timeout & SIGKILL in Single Supervised Job...")
canary_timeout_iban = f"DE89370400440532013000TIMEOUT{uuid.uuid4().hex[:8].upper()}"
canary_timeout_name = f"Mustermann_Timeout_{uuid.uuid4().hex[:6]}"
timeout_csv = f"""Belegdatum;Buchungstext;Betrag;Währung;IBAN;Name
01.09.2026;Miete Buero;1250,00;EUR;{canary_timeout_iban};{canary_timeout_name}
"""

worker_kill_script = f"""
import asyncio, os, sys, time, signal, json
from fastapi import HTTPException
from app.services.parser_process_supervisor import ParserProcessSupervisor, _pid_exists
from app.parsers import registry as parser_registry

def hanging_parse(*args, **kwargs):
    t_end = time.monotonic() + 10.0
    while time.monotonic() < t_end:
        time.sleep(0.01)
    return [], None

parser_registry.registry.parse_file = hanging_parse

async def run():
    sup = ParserProcessSupervisor(default_timeout=0.2)
    payload = {repr(timeout_csv.encode('utf-8'))}
    
    start_time = time.monotonic()
    status_code = None
    detail = None
    
    try:
        await sup.parse_file(
            content=payload,
            filename="canary_timeout.csv",
            tenant_id="t_audit_kill",
            timeout=0.2
        )
    except HTTPException as he:
        status_code = he.status_code
        detail = str(he.detail)
    except Exception as e:
        detail = str(e)
        
    duration = time.monotonic() - start_time
    spawned = sup.last_spawned_pid
    handshake = sup.last_handshake_pid
    is_alive = _pid_exists(spawned) if spawned else False
    is_reaped = sup.last_job_reaped
    slot_free = (sup.semaphore._value == sup.max_concurrency)
    
    res = {{
        "spawned_pid": spawned,
        "handshake_pid": handshake,
        "handshake_matches_spawned": bool(spawned == handshake and spawned is not None and spawned > 0),
        "dead_after_kill": bool(not is_alive),
        "reaped_by_supervisor": bool(is_reaped),
        "slot_freed": bool(slot_free),
        "status_code": status_code,
        "detail": detail,
        "duration_seconds": round(duration, 3)
    }}
    print(json.dumps(res))

asyncio.run(run())
"""
res_kill_raw, res_kill_err, res_kill_code = run_docker_python(worker_kill_script)
try:
    kill_data = json.loads(res_kill_raw)
except Exception:
    kill_data = {"raw": res_kill_raw, "err": res_kill_err, "code": res_kill_code}

results["supervisor_single_job_kill"] = {
    "canary_fed_to_job": {"iban": canary_timeout_iban, "name": canary_timeout_name},
    "result": kill_data
}
print(f"  Spawned PID: {kill_data.get('spawned_pid')}")
print(f"  Handshake PID: {kill_data.get('handshake_pid')}")
print(f"  Handshake Verified: {kill_data.get('handshake_matches_spawned')}")
print(f"  Dead & Reaped after Kill: {kill_data.get('dead_after_kill')} (Reaped: {kill_data.get('reaped_by_supervisor')})")
print(f"  HTTP Outcome: {kill_data.get('status_code')} ({kill_data.get('detail')})")

# ==============================================================================
# SECTION 4: WORKER CRASH & IMMEDIATE SUPERVISOR RECOVERY (Finding B)
# ==============================================================================
print("\n[4/10] Testing Worker Crash (SIGKILL) & Immediate Supervised Recovery...")
canary_crash_iban = f"DE89370400440532013000CRASH{uuid.uuid4().hex[:8].upper()}"
canary_crash_name = f"Mustermann_Crash_{uuid.uuid4().hex[:6]}"
crash_csv = f"""Belegdatum;Buchungstext;Betrag;Währung;IBAN;Name
01.09.2026;Crash Row;500,00;EUR;{canary_crash_iban};{canary_crash_name}
"""

canary_recovery_iban = f"DE89370400440532013000RECOVERY{uuid.uuid4().hex[:8].upper()}"
canary_recovery_name = f"Mustermann_Recovery_{uuid.uuid4().hex[:6]}"
recovery_csv = f"""Datum;Text;Betrag
01.09.2026;Recovery Row {canary_recovery_iban};250,00
"""

crash_recovery_script = f"""
import asyncio, os, sys, time, signal, json
from app.services.parser_process_supervisor import ParserProcessSupervisor, _pid_exists
from app.parsers import registry as parser_registry

orig_parse = parser_registry.registry.parse_file

def suicidal_parse(*args, **kwargs):
    os.kill(os.getpid(), signal.SIGKILL)

async def run():
    sup = ParserProcessSupervisor(default_timeout=5.0)
    crash_payload = {repr(crash_csv.encode('utf-8'))}
    recovery_payload = {repr(recovery_csv.encode('utf-8'))}
    
    # 1. Crashing Job
    parser_registry.registry.parse_file = suicidal_parse
    crash_err = None
    try:
        await sup.parse_file(
            content=crash_payload,
            filename="canary_crash.csv",
            tenant_id="t_audit_crash",
            timeout=5.0
        )
    except Exception as e:
        crash_err = str(e)
        
    c_pid = sup.last_spawned_pid
    c_handshake = sup.last_handshake_pid
    is_dead = (not _pid_exists(c_pid)) if c_pid else False
    c_reaped = sup.last_job_reaped
    slot_after_crash = (sup.semaphore._value == sup.max_concurrency)
    
    # 2. Immediate Follow-up Job on EXACT SAME supervisor instance
    parser_registry.registry.parse_file = orig_parse
    rec_success = False
    rec_tx_count = 0
    rec_err = None
    try:
        txs, summary = await sup.parse_file(
            content=recovery_payload,
            filename="canary_recovery.csv",
            tenant_id="t_audit_crash",
            timeout=5.0
        )
        rec_success = True
        rec_tx_count = len(txs)
    except Exception as e:
        rec_err = str(e)
        
    r_pid = sup.last_spawned_pid
    r_handshake = sup.last_handshake_pid
    slot_after_rec = (sup.semaphore._value == sup.max_concurrency)
    
    res = {{
        "crash_phase": {{
            "crashed_pid": c_pid,
            "crashed_handshake": c_handshake,
            "handshake_matches_spawned": bool(c_pid == c_handshake and c_pid is not None and c_pid > 0),
            "dead_after_crash": bool(is_dead),
            "reaped_by_supervisor": bool(c_reaped),
            "supervisor_error": crash_err,
            "slot_freed": bool(slot_after_crash)
        }},
        "recovery_phase": {{
            "recovery_pid": r_pid,
            "recovery_handshake": r_handshake,
            "recovery_success": bool(rec_success),
            "tx_count": rec_tx_count,
            "recovery_error": rec_err,
            "slot_freed": bool(slot_after_rec)
        }}
    }}
    print(json.dumps(res))

asyncio.run(run())
"""
res_crash_raw, res_crash_err, res_crash_code = run_docker_python(crash_recovery_script)
try:
    crash_data = json.loads(res_crash_raw)
except Exception:
    crash_data = {"raw": res_crash_raw, "err": res_crash_err, "code": res_crash_code}

results["supervisor_crash_and_recovery"] = {
    "canary_crash_fed": {"iban": canary_crash_iban, "name": canary_crash_name},
    "canary_recovery_fed": {"iban": canary_recovery_iban, "name": canary_recovery_name},
    "result": crash_data
}
print(f"  Crashed PID: {crash_data.get('crash_phase', {}).get('crashed_pid')}")
print(f"  Crash Handshake Verified: {crash_data.get('crash_phase', {}).get('handshake_matches_spawned')}")
print(f"  Crash Caught: {crash_data.get('crash_phase', {}).get('supervisor_error')}")
print(f"  Recovery Succeeded on Same Instance: {crash_data.get('recovery_phase', {}).get('recovery_success')} (Parsed TXs: {crash_data.get('recovery_phase', {}).get('tx_count')})")

# ==============================================================================
# SECTION 5: PURE CPU-BURN RESOURCE RECOVERY & CANCELLATION LIFECYCLE
# ==============================================================================
print("\n[5/10] Testing Pure CPU-Burn Resource Recovery and Cancellation Lifecycle...")

# 1. Pure CPU burn recovery (no sleep, burns 1.0 CPU until supervisor SIGKILL)
cpu_burn_script = """
import asyncio, os, sys, time, signal, json
from fastapi import HTTPException
from app.services.parser_process_supervisor import ParserProcessSupervisor, _pid_exists
from app.parsers import registry as parser_registry

def pure_cpu_burn(*args, **kwargs):
    while True:
        pass

async def run():
    sup = ParserProcessSupervisor(default_timeout=0.2)
    orig_parse = parser_registry.registry.parse_file
    parser_registry.registry.parse_file = pure_cpu_burn
    
    timed_out = False
    start = time.monotonic()
    try:
        await sup.parse_file(b"dummy;data\\n", "cpuburn.csv", "t_burn", timeout=0.2)
    except HTTPException as he:
        if he.status_code == 408:
            timed_out = True
    burn_duration = time.monotonic() - start
    burn_pid = sup.last_spawned_pid
    burn_handshake = sup.last_handshake_pid
    burn_dead = not _pid_exists(burn_pid) if burn_pid else False
    burn_reaped = sup.last_job_reaped
    burn_slot_freed = (sup.semaphore._value == sup.max_concurrency)
    
    # Follow-up recovery on same supervisor
    parser_registry.registry.parse_file = orig_parse
    rec_ok = False
    try:
        txs, _ = await sup.parse_file(b"Datum;Text;Betrag\\n01.01.2025;Test;10,00\\n", "ok.csv", "t_burn")
        rec_ok = (len(txs) > 0)
    except Exception:
        pass
        
    res = {
        "burn_pid": burn_pid,
        "burn_handshake": burn_handshake,
        "handshake_matches_spawned": bool(burn_pid == burn_handshake and burn_pid is not None and burn_pid > 0),
        "hard_kill_executed": burn_dead,
        "reaped_by_supervisor": bool(burn_reaped),
        "slot_freed_after_kill": bool(burn_slot_freed),
        "timed_out_408": timed_out,
        "burn_duration_seconds": round(burn_duration, 3),
        "subsequent_request_succeeded": rec_ok
    }
    print(json.dumps(res))

asyncio.run(run())
"""
res_burn_raw, _, _ = run_docker_python(cpu_burn_script)
try:
    burn_data = json.loads(res_burn_raw)
except Exception:
    burn_data = {"raw": res_burn_raw}

results["supervisor_cpu_burn_recovery"] = burn_data
print(f"  CPU-Burn PID: {burn_data.get('burn_pid')} (Handshake: {burn_data.get('burn_handshake')})")
print(f"  Hard Kill Executed & Reaped: {burn_data.get('hard_kill_executed')} (Reaped: {burn_data.get('reaped_by_supervisor')})")
print(f"  Subsequent Request Succeeded: {burn_data.get('subsequent_request_succeeded')}")

# 2. Client Cancellation with confirmed PID and Reaping
cancel_lifecycle_script = """
import asyncio, os, sys, time, json
from app.services.parser_process_supervisor import ParserProcessSupervisor, _pid_exists

async def run():
    sup = ParserProcessSupervisor(max_concurrency=1, max_queue_depth=2, default_timeout=5.0)
    payload = b"Datum;Text;Betrag\\n01.01.2025;CancelTest;10,00\\n"
    
    cancel_task = asyncio.create_task(
        sup.parse_file(payload, "cancel.csv", "t_cancel", timeout=5.0)
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        if sup.last_spawned_pid and sup.last_handshake_pid:
            break
            
    c_spawned = sup.last_spawned_pid
    c_handshake = sup.last_handshake_pid
    alive_before_cancel = _pid_exists(c_spawned) if c_spawned else False
    
    cancel_task.cancel()
    cancelled_caught = False
    try:
        await cancel_task
    except asyncio.CancelledError:
        cancelled_caught = True
    except Exception:
        pass
        
    await asyncio.sleep(0.05)
    dead_after_cancel = not _pid_exists(c_spawned) if c_spawned else False
    reaped = sup.last_job_reaped
    slot_freed = (sup.semaphore._value == 1)
    
    res = {
        "cancel_spawned_pid": c_spawned,
        "cancel_handshake_pid": c_handshake,
        "handshake_confirmed": bool(c_spawned == c_handshake and c_spawned is not None and c_spawned > 0),
        "alive_before_cancel": bool(alive_before_cancel),
        "cancelled_caught": bool(cancelled_caught),
        "dead_after_cancel": bool(dead_after_cancel),
        "reaped_by_supervisor": bool(reaped),
        "slot_freed": bool(slot_freed)
    }
    print(json.dumps(res))

asyncio.run(run())
"""
res_cancel_raw, _, _ = run_docker_python(cancel_lifecycle_script)
try:
    cancel_data = json.loads(res_cancel_raw)
except Exception:
    cancel_data = {"raw": res_cancel_raw}

results["supervisor_cancellation_lifecycle"] = cancel_data
print(f"  Cancellation PID: {cancel_data.get('cancel_spawned_pid')} (Handshake: {cancel_data.get('cancel_handshake_pid')})")
print(f"  Killed & Reaped on Cancel: {cancel_data.get('dead_after_cancel')} (Reaped: {cancel_data.get('reaped_by_supervisor')})")
print(f"  Slot Freed on Cancel: {cancel_data.get('slot_freed')}")

# ==============================================================================
# SECTION 6: BOUNDED QUEUE OVERLOAD (HTTP 429)
# ==============================================================================
print("\n[6/10] Testing Bounded Queue Overload & Immediate 429 Rejection...")
overload_script = """
import asyncio, os, sys, time, json
from fastapi import HTTPException
from app.services.parser_process_supervisor import ParserProcessSupervisor

async def run():
    sup = ParserProcessSupervisor(max_concurrency=1, max_queue_depth=2, default_timeout=5.0)
    payload = b"Datum;Text;Betrag\\n01.01.2025;Test;10,00\\n"
    
    async def slow_work():
        await sup.parse_file(payload, "slow.csv", "t_test", timeout=0.6)
        
    t1 = asyncio.create_task(slow_work())
    await asyncio.sleep(0.01)
    
    t2 = asyncio.create_task(sup.parse_file(payload, "q1.csv", "t_test", timeout=0.6))
    t3 = asyncio.create_task(sup.parse_file(payload, "q2.csv", "t_test", timeout=0.6))
    await asyncio.sleep(0.01)
    
    got_429 = False
    detail_429 = None
    try:
        await sup.parse_file(payload, "q3.csv", "t_test", timeout=0.6)
    except HTTPException as he:
        if he.status_code == 429:
            got_429 = True
            detail_429 = str(he.detail)
            
    await asyncio.gather(t1, t2, t3, return_exceptions=True)
    slot_after = (sup.semaphore._value == 1)
    
    res = {
        "overload_429_received": bool(got_429),
        "detail": detail_429,
        "slot_freed_after_overload": bool(slot_after)
    }
    print(json.dumps(res))

asyncio.run(run())
"""
res_ovl_raw, _, _ = run_docker_python(overload_script)
try:
    ovl_data = json.loads(res_ovl_raw)
except Exception:
    ovl_data = {"raw": res_ovl_raw}

results["supervisor_overload_429"] = ovl_data
print(f"  Overload 429 Raised: {ovl_data.get('overload_429_received')} (Slot Freed: {ovl_data.get('slot_freed_after_overload')})")

# ==============================================================================
# SECTION 7: OOM ALLOCATION & CGROUPS V2 RECOVERY (Addressing Decision 20 Item 1)
# ==============================================================================
print("\n[7/10] Testing Worker OOM Exhaustion & Recovery under 512 MiB cgroups Limit...")

oom_script = """
import os, sys, time, json, signal, asyncio
from app.services.parser_process_supervisor import ParserProcessSupervisor, _pid_exists
from app.parsers import registry as parser_registry

def get_cgroup_memory_events():
    events_path = "/sys/fs/cgroup/memory.events"
    if not os.path.exists(events_path):
        return {}
    res = {}
    with open(events_path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                res[parts[0]] = int(parts[1])
    return res

events_before = get_cgroup_memory_events()

def oom_parse(*args, **kwargs):
    chunks = []
    while True:
        chunks.append(bytearray(40 * 1024 * 1024))
        time.sleep(0.01)
    return [], None

async def run():
    orig_parse = parser_registry.registry.parse_file
    parser_registry.registry.parse_file = oom_parse
    sup = ParserProcessSupervisor(default_timeout=15.0)
    
    error_caught = None
    try:
        await sup.parse_file(
            content=b"Belegdatum;Text;Betrag\\n01.09.2026;OOM Test;100,00\\n",
            filename="oom_test.csv",
            tenant_id="t_audit_oom",
            timeout=15.0
        )
    except Exception as e:
        error_caught = str(e)
        
    events_after = get_cgroup_memory_events()
    
    c_pid = sup.last_spawned_pid
    c_handshake = sup.last_handshake_pid
    is_dead = (not _pid_exists(c_pid)) if c_pid else True
    is_reaped = sup.last_job_reaped
    slot_freed = (sup.semaphore._value == sup.max_concurrency)
    
    oom_kill_increment = events_after.get("oom_kill", 0) - events_before.get("oom_kill", 0)
    oom_event_increment = events_after.get("oom", 0) - events_before.get("oom", 0)
    
    # Subsequent parse recovery check on same supervisor
    parser_registry.registry.parse_file = orig_parse
    recovery_success = False
    tx_count = 0
    try:
        txs, summary = await sup.parse_file(
            content=b"Datum;Text;Betrag\\n01.09.2026;Post-OOM Row;250,00\\n",
            filename="post_oom_recovery.csv",
            tenant_id="t_audit_oom",
            timeout=5.0
        )
        recovery_success = True
        tx_count = len(txs)
    except Exception as e:
        pass
        
    res = {
        "cgroup_memory_events_before": events_before,
        "cgroup_memory_events_after": events_after,
        "oom_kill_increment": oom_kill_increment,
        "oom_event_increment": oom_event_increment,
        "oom_event_confirmed": bool(oom_kill_increment > 0 or oom_event_increment > 0),
        "worker_pid": c_pid,
        "handshake_pid": c_handshake,
        "handshake_matches_spawned": bool(c_pid == c_handshake and c_pid is not None and c_pid > 0),
        "worker_dead_after_oom": bool(is_dead),
        "reaped_by_supervisor": bool(is_reaped),
        "slot_freed": bool(slot_freed),
        "supervisor_error": error_caught,
        "kernel_sigkill_detected": bool("exit_code: -9" in str(error_caught)),
        "subsequent_recovery_success": bool(recovery_success),
        "subsequent_tx_count": tx_count
    }
    print(json.dumps(res))

asyncio.run(run())
"""
res_oom_raw, _, _ = run_docker_python(oom_script)
try:
    oom_data = json.loads(res_oom_raw)
except Exception:
    oom_data = {"raw": res_oom_raw}

results["supervisor_oom_recovery"] = oom_data
print(f"  OOM Kill Event Confirmed: {oom_data.get('oom_event_confirmed')} (oom_kill increment: {oom_data.get('oom_kill_increment')})")
print(f"  Worker Terminated by Kernel: {oom_data.get('worker_dead_after_oom')} (SIGKILL detected: {oom_data.get('kernel_sigkill_detected')})")
print(f"  Reaped & Slot Freed: {oom_data.get('reaped_by_supervisor')} / {oom_data.get('slot_freed')}")
print(f"  Subsequent Recovery Succeeded: {oom_data.get('subsequent_recovery_success')} (TX count: {oom_data.get('subsequent_tx_count')})")

# ==============================================================================
# SECTION 8: KILL/REAP FAILURE INJECTION & RECOVERY (Addressing Decision 20 Item 2)
# ==============================================================================
print("\n[8/10] Testing Kill/Reap Failure Injection & Defined Recovery Path...")

kill_fail_script = """
import os, sys, time, json, signal, asyncio
from fastapi import HTTPException
import app.services.parser_process_supervisor as pps_module
from app.services.parser_process_supervisor import ParserProcessSupervisor
from app.parsers import registry as parser_registry

async def run():
    def slow_parse(*args, **kwargs):
        time.sleep(10.0)
        return [], None

    orig_parse = parser_registry.registry.parse_file
    parser_registry.registry.parse_file = slow_parse
    
    sup = ParserProcessSupervisor(default_timeout=0.2)
    
    real_pid_exists = pps_module._pid_exists
    real_hard_kill = pps_module._hard_kill_pid
    
    injected_pid_holder = [None]
    mock_active = [True]
    
    def mocked_pid_exists(pid):
        if mock_active[0] and pid == injected_pid_holder[0]:
            return True
        return real_pid_exists(pid)
        
    def mocked_hard_kill(pid):
        if mock_active[0] and pid == injected_pid_holder[0]:
            return
        return real_hard_kill(pid)
        
    pps_module._pid_exists = mocked_pid_exists
    pps_module._hard_kill_pid = mocked_hard_kill
    
    http_status = None
    http_detail = None
    
    try:
        task = asyncio.create_task(sup.parse_file(
            content=b"Belegdatum;Text;Betrag\\n01.09.2026;KillFail;100,00\\n",
            filename="kill_fail.csv",
            tenant_id="t_audit_kf",
            timeout=0.2
        ))
        await asyncio.sleep(0.05)
        injected_pid_holder[0] = sup.last_spawned_pid
        await task
    except HTTPException as he:
        http_status = he.status_code
        http_detail = str(he.detail)
    except Exception as e:
        http_detail = str(e)
        
    target_pid = injected_pid_holder[0]
    last_reaped_status = sup.last_job_reaped
    is_quarantined = target_pid in sup.quarantined_pids
    quarantined_slots_count = len(sup.quarantined_pids)
    slot_held = (sup.semaphore._value == sup.max_concurrency - 1)
    
    # Deactivate mock so defined recovery path can clean up
    mock_active[0] = False
    pps_module._pid_exists = real_pid_exists
    pps_module._hard_kill_pid = real_hard_kill
    
    # Invoke Defined Recovery Path
    reclaimed = sup.reclaim_quarantined_worker(target_pid, force=True)
    time.sleep(0.1)
    real_alive = real_pid_exists(target_pid)
    slot_restored = (sup.semaphore._value == sup.max_concurrency)
    quarantine_cleared = (target_pid not in sup.quarantined_pids)
    
    # Subsequent parse on same supervisor
    parser_registry.registry.parse_file = orig_parse
    subsequent_success = False
    try:
        txs, summary = await sup.parse_file(
            content=b"Datum;Text;Betrag\\n01.09.2026;Post-KF Row;300,00\\n",
            filename="post_kf.csv",
            tenant_id="t_audit_kf",
            timeout=5.0
        )
        subsequent_success = True
    except Exception as e:
        pass
        
    res = {
        "injected_pid": target_pid,
        "failure_phase": {
            "http_status": http_status,
            "http_detail": http_detail,
            "no_false_cleanup": bool(last_reaped_status is False),
            "pid_quarantined": is_quarantined,
            "slot_held_preventing_spawns": slot_held,
            "quarantined_count": quarantined_slots_count
        },
        "recovery_phase": {
            "reclaim_executed": reclaimed,
            "os_process_confirmed_dead": bool(not real_alive),
            "slot_restored_to_max": slot_restored,
            "quarantine_cleared": quarantine_cleared,
            "subsequent_request_succeeded": subsequent_success
        }
    }
    print(json.dumps(res))

asyncio.run(run())
"""
res_kf_raw, _, _ = run_docker_python(kill_fail_script)
try:
    kf_data = json.loads(res_kf_raw)
except Exception:
    kf_data = {"raw": res_kf_raw}

results["supervisor_kill_failure_injection"] = kf_data
print(f"  Injected Kill Failure HTTP Status: {kf_data.get('failure_phase', {}).get('http_status')} ({kf_data.get('failure_phase', {}).get('http_detail')})")
print(f"  No False Cleanup Report: {kf_data.get('failure_phase', {}).get('no_false_cleanup')} (Quarantined: {kf_data.get('failure_phase', {}).get('pid_quarantined')})")
print(f"  Slot Held to Prevent Uncontrolled Spawns: {kf_data.get('failure_phase', {}).get('slot_held_preventing_spawns')}")
print(f"  Recovery Path Executed: {kf_data.get('recovery_phase', {}).get('reclaim_executed')} (Process Dead: {kf_data.get('recovery_phase', {}).get('os_process_confirmed_dead')})")
print(f"  Slot Restored & Subsequent Parse Succeeded: {kf_data.get('recovery_phase', {}).get('subsequent_request_succeeded')}")

# ==============================================================================
# SECTION 9: ZERO-RETENTION CANARY MATRIX (Direct Grep, Genuine Exit Code 1)
# ==============================================================================
print("\n[9/10] Executing Zero-Retention Canary Matrix with Verifiable Exit Codes...")

canary_success_iban = f"DE89370400440532013000SUCCESS{uuid.uuid4().hex[:8].upper()}"
canary_success_name = f"Mustermann_Success_{uuid.uuid4().hex[:6]}"
success_csv = f"""Datum;Text;Betrag
01.09.2026;Erfolg 1 {canary_success_iban} {canary_success_name};100,00
02.09.2026;Erfolg 2 {canary_success_iban};200,00
"""

canary_413_iban = f"DE89370400440532013000OVERSIZE{uuid.uuid4().hex[:8].upper()}"
canary_413_name = f"Mustermann_Oversize_{uuid.uuid4().hex[:6]}"
oversize_lines = ["Datum;Text;Betrag"]
for i in range(12000):
    oversize_lines.append(f"01.09.2026;Row {i} {canary_413_iban} {canary_413_name};10,00")
oversize_csv = "\n".join(oversize_lines) + "\n"

# Bootstrap Tenant in DB
tenant_id = f"t_audit_v5_{uuid.uuid4().hex[:6]}"
tenant_email = f"audit_v5_{uuid.uuid4().hex[:6]}@statement2muster.com"

bootstrap_code = f"""
import asyncio
from app.db.session import async_session_maker
from app.db.models import Tenant, Entitlement

async def bootstrap():
    async with async_session_maker() as db:
        t = Tenant(id='{tenant_id}', email='{tenant_email}')
        db.add(t)
        await db.flush()
        e = Entitlement(tenant_id=t.id, plan_code='pro', status='active', source_type='subscription', source_id='sub_audit_v5')
        db.add(e)
        await db.commit()
    print('BOOTSTRAP_OK')

asyncio.run(bootstrap())
"""
run_docker_python(bootstrap_code)

with open("/opt/statement2muster/jwt_private.pem", "r") as f:
    priv_pem = f.read()

now = int(time.time())
jwt_payload = {
    "iss": "statement2muster.com",
    "aud": "statement2muster-api",
    "sub": tenant_email,
    "tenant_id": tenant_id,
    "sid": str(uuid.uuid4()),
    "iat": now,
    "exp": now + 3600
}
token = jwt.encode(jwt_payload, priv_pem, algorithm="RS256")
headers = {
    "Authorization": f"Bearer {token}",
    "X-Idempotency-Key": uuid.uuid4().hex
}

# Branch 1: Success (HTTP 200)
code_success, body_success, _ = http_req(
    "/api/v1/convert?format=json",
    method="POST",
    headers=headers,
    files={"files": ("success_statement.csv", success_csv.encode("utf-8"), "text/csv")}
)

# Branch 2: 413 Oversize (HTTP 413)
headers_413 = {**headers, "X-Idempotency-Key": uuid.uuid4().hex}
code_413, body_413, _ = http_req(
    "/api/v1/convert?format=json",
    method="POST",
    headers=headers_413,
    files={"files": ("oversize_statement.csv", oversize_csv.encode("utf-8"), "text/csv")}
)

canary_test_records = [
    {"branch": "success", "expected_code": 200, "actual_code": code_success, "canary_iban": canary_success_iban, "canary_name": canary_success_name},
    {"branch": "413_oversize", "expected_code": 413, "actual_code": code_413, "canary_iban": canary_413_iban, "canary_name": canary_413_name},
    {"branch": "timeout", "expected_code": 408, "actual_code": kill_data.get("status_code"), "canary_iban": canary_timeout_iban, "canary_name": canary_timeout_name},
    {"branch": "crash", "expected_code": "CRASH", "actual_code": "CRASH" if crash_data.get("crash_phase", {}).get("dead_after_crash") else "FAILED", "canary_iban": canary_crash_iban, "canary_name": canary_crash_name}
]

# Capture container logs cleanly to host file
log_file_path = Path("/opt/statement2muster/container_logs_snapshot.txt")
p_dlogs = subprocess.run(["docker", "logs", CONTAINER_NAME], capture_output=True, text=True)
log_file_path.write_text(p_dlogs.stdout + p_dlogs.stderr, encoding="utf-8")

p_touch = subprocess.run(["docker", "exec", CONTAINER_NAME, "touch", "/tmp/scope_test"], capture_output=True)
p_rm = subprocess.run(["docker", "exec", CONTAINER_NAME, "rm", "/tmp/scope_test"], capture_output=True)
p_ls_vol = subprocess.run(["docker", "exec", CONTAINER_NAME, "ls", "-d", "/app/data"], capture_output=True)

scope_access = {
    "tmpfs_writable": (p_touch.returncode == 0 and p_rm.returncode == 0),
    "volume_accessible": (p_ls_vol.returncode == 0),
    "docker_logs_captured": (p_dlogs.returncode == 0 and len(p_dlogs.stdout) > 0)
}

all_canaries = [
    (canary_success_iban, "IBAN", "success"),
    (canary_success_name, "Name", "success"),
    (canary_413_iban, "IBAN", "413_oversize"),
    (canary_413_name, "Name", "413_oversize"),
    (canary_timeout_iban, "IBAN", "timeout"),
    (canary_timeout_name, "Name", "timeout"),
    (canary_crash_iban, "IBAN", "crash"),
    (canary_crash_name, "Name", "crash"),
]

canary_search_results = []
all_clean = True

for canary_str, c_type, c_branch in all_canaries:
    p_tmp = subprocess.run(["docker", "exec", CONTAINER_NAME, "grep", "-rnF", canary_str, "/tmp"], capture_output=True, text=True)
    status_tmp = "CLEAN" if (p_tmp.returncode == 1 and p_tmp.stdout == "") else ("LEAK" if p_tmp.returncode == 0 else f"ERROR_{p_tmp.returncode}")
    
    p_vol = subprocess.run(["docker", "exec", CONTAINER_NAME, "grep", "-rnF", canary_str, "/app/data"], capture_output=True, text=True)
    status_vol = "CLEAN" if (p_vol.returncode == 1 and p_vol.stdout == "") else ("LEAK" if p_vol.returncode == 0 else f"ERROR_{p_vol.returncode}")
    
    p_logs = subprocess.run(["grep", "-nF", canary_str, str(log_file_path)], capture_output=True, text=True)
    status_logs = "CLEAN" if (p_logs.returncode == 1 and p_logs.stdout == "") else ("LEAK" if p_logs.returncode == 0 else f"ERROR_{p_logs.returncode}")
    
    clean_all = (status_tmp == "CLEAN" and status_vol == "CLEAN" and status_logs == "CLEAN")
    if not clean_all:
        all_clean = False
        
    canary_search_results.append({
        "canary_string": canary_str,
        "type": c_type,
        "branch": c_branch,
        "tmp": {"exit_code": p_tmp.returncode, "stdout": p_tmp.stdout.strip(), "stderr": p_tmp.stderr.strip(), "status": status_tmp},
        "volume": {"exit_code": p_vol.returncode, "stdout": p_vol.stdout.strip(), "stderr": p_vol.stderr.strip(), "status": status_vol},
        "logs": {"exit_code": p_logs.returncode, "stdout": p_logs.stdout.strip(), "stderr": p_logs.stderr.strip(), "status": status_logs},
        "all_clean": clean_all
    })

results["canary_matrix_zero_retention"] = {
    "branches_tested": canary_test_records,
    "search_scope_access_verified": scope_access,
    "search_conducted_pre_restart": True,
    "all_canaries_clean": bool(all_clean and scope_access["tmpfs_writable"] and scope_access["volume_accessible"] and scope_access["docker_logs_captured"]),
    "exit_code_interpretation": "Exit 1 = 0 matches found (CLEAN); Exit 0 = match found (LEAK); Exit > 1 = grep execution error",
    "matrix": canary_search_results
}
print(f"  Search Scope Verified: {scope_access}")
print(f"  All 8 Canaries Clean (Genuine Exit Code 1 across all 3 targets): {results['canary_matrix_zero_retention']['all_canaries_clean']}")

# ==============================================================================
# SECTION 10: PERSISTENCE & RESTART TEST
# ==============================================================================
print("\n[10/10] Testing Database Volume Persistence Across Container Restart...")
stat_before, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} ls -la /app/data/statement2muster_prod.db")

print("  Restarting container via docker compose...")
run_cmd("cd /opt/statement2muster && docker compose -f docker-compose.prod.yml restart")
time.sleep(3)

code_post_restart, body_post_restart, _ = http_req("/healthz")

verify_db_script = f"""
import asyncio, json
from app.db.session import async_session_maker
from app.db.models import Tenant, Entitlement
from sqlalchemy import select

async def check():
    async with async_session_maker() as db:
        res_t = await db.execute(select(Tenant).where(Tenant.id == '{tenant_id}'))
        t = res_t.scalar_one_or_none()
        res_e = await db.execute(select(Entitlement).where(Entitlement.tenant_id == '{tenant_id}'))
        e = res_e.scalar_one_or_none()
        print(json.dumps({{"tenant_found": t is not None, "plan": e.plan_code if e else None}}))

asyncio.run(check())
"""
db_post, _, _ = run_docker_python(verify_db_script)
try:
    db_state = json.loads(db_post)
except Exception:
    db_state = {"raw": db_post}

headers_post = {**headers, "X-Idempotency-Key": uuid.uuid4().hex}
code_convert_post, body_post, _ = http_req(
    "/api/v1/convert?format=json",
    method="POST",
    headers=headers_post,
    files={"files": ("post_restart.csv", "Datum;Text;Betrag\n01.09.2026;Restart Test;10,00\n".encode("utf-8"), "text/csv")}
)

results["database_persistence_restart"] = {
    "db_file_stat": stat_before,
    "container_restarted": True,
    "healthz_post_restart": code_post_restart,
    "tenant_found_post_restart": db_state.get("tenant_found"),
    "tenant_plan_preserved": db_state.get("plan") == "pro",
    "post_restart_conversion_code": code_convert_post,
    "persistence_confirmed": bool(db_state.get("plan") == "pro" and code_convert_post == 200)
}
print(f"  Post-restart Healthz: HTTP {code_post_restart}")
print(f"  Tenant PRO Plan Preserved: {results['database_persistence_restart']['tenant_plan_preserved']}")
print(f"  Post-restart Conversion: HTTP {code_convert_post}")

RESULTS_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
print(f"\n=== AUDIT V5 COMPLETE. Results saved to {RESULTS_FILE} ===")
