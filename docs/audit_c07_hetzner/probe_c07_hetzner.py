#!/usr/bin/env python3
"""
Official C07 Linux Runtime & Security Evidence Probe on Hetzner Cloud
Target: Hetzner Cloud (Ubuntu Linux 6.8.0-137-generic, Docker 29.2.1)
Container: s2m-backend-api (Image: statement2muster-api:1.0.2)
"""

import os
import sys
import json
import time
import uuid
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
import jwt

BASE_URL = "http://127.0.0.1:8100"
RESULTS_FILE = Path("/opt/statement2muster/c07_audit_results.json")
CONTAINER_NAME = "s2m-backend-api"

results = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "environment": "Hetzner Cloud (Ubuntu Linux 6.8.0-137-generic)",
    "container": CONTAINER_NAME,
    "image_id": "sha256:20d892a00069b45b527546e90bd368b48d6d244eda210cf8ed6b6b6102fbf128",
    "cgroups": {},
    "security": {},
    "healthz": {},
    "jwks": {},
    "normal_conversion": {},
    "row_limit_413": {},
    "supervisor_wiring": {},
    "supervisor_real_timeout": {},
    "process_tree_verification": {},
    "zero_retention_canary": {},
    "smtp_configuration": {}
}

def run_cmd(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.stdout.strip(), p.stderr.strip(), p.returncode

def http_req(path, method="GET", data=None, headers=None, files=None):
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
        req.data = b"\r\n".join(body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    elif data:
        if isinstance(data, dict):
            req.data = json.dumps(data).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        elif isinstance(data, bytes):
            req.data = data
        else:
            req.data = data.encode("utf-8")
            
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except:
                parsed = body
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except:
            parsed = body
        return e.code, parsed
    except Exception as e:
        return 0, str(e)

print("=== 1. Checking Cgroups & Container Security ===")
mem_max, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} cat /sys/fs/cgroup/memory.max")
cpu_max, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} cat /sys/fs/cgroup/cpu.max")
user_id, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} id")
readonly_test, _, ro_code = run_cmd(f"docker exec {CONTAINER_NAME} touch /app/cant_write 2>&1")
tmp_df, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} df -h /tmp")

results["cgroups"] = {
    "memory_max_bytes": int(mem_max) if mem_max.isdigit() else mem_max,
    "memory_max_human": "512 MiB" if mem_max == "536870912" else mem_max,
    "cpu_max": cpu_max,
    "cpu_limit_human": "1.0 CPU" if cpu_max.startswith("100000 100000") else cpu_max
}
results["security"] = {
    "user": user_id,
    "unprivileged_uid": "10001" in user_id,
    "readonly_rootfs_enforced": ro_code != 0 and "Read-only file system" in readonly_test,
    "tmpfs_mount": tmp_df.split("\n")[-1] if tmp_df else ""
}
print(f"Cgroups: {results['cgroups']}")
print(f"Security: {results['security']}")

print("\n=== 2. Checking /healthz and /api/v1/auth/jwks.json ===")
st_h, body_h = http_req("/healthz")
results["healthz"] = {"status_code": st_h, "body": body_h}
print(f"Healthz: {st_h} -> {body_h}")

st_j, body_j = http_req("/api/v1/auth/jwks.json")
key_count = len(body_j.get("keys", [])) if isinstance(body_j, dict) else 0
results["jwks"] = {"status_code": st_j, "key_count": key_count}
print(f"JWKS: {st_j} -> keys={key_count}")

print("\n=== 3. Bootstrap DB Tenant & Generate RS256 Bearer Token ===")
tenant_id = str(uuid.uuid4())
tenant_email = "audit_c07@statement2muster.com"

bootstrap_code = f"""
import asyncio
from app.db.session import async_session_maker
from app.db.models import Tenant, Entitlement

async def bootstrap():
    async with async_session_maker() as db:
        t = Tenant(id='{tenant_id}', email='{tenant_email}')
        db.add(t)
        await db.flush()
        e = Entitlement(tenant_id=t.id, plan_code='pro', status='active', source_type='subscription', source_id='sub_audit_c07')
        db.add(e)
        await db.commit()
    print('BOOTSTRAP_OK')

asyncio.run(bootstrap())
"""
p = subprocess.run(f"docker exec -i {CONTAINER_NAME} python -", shell=True, input=bootstrap_code, capture_output=True, text=True)
print(f"DB Bootstrap: {p.stdout.strip()} ({p.stderr.strip()})")

with open("/opt/statement2muster/jwt_private.pem", "r") as f:
    priv_pem = f.read()

now = int(time.time())
payload = {
    "iss": "statement2muster.com",
    "aud": "statement2muster-api",
    "sub": tenant_email,
    "tenant_id": tenant_id,
    "sid": str(uuid.uuid4()),
    "iat": now,
    "exp": now + 600
}
token = jwt.encode(payload, priv_pem, algorithm="RS256")
auth_headers = {"Authorization": f"Bearer {token}"}

print("\n=== 4. Testing Normal Conversion Route with Canary Tokens ===")
canary_iban = f"CANARY_IBAN_DE99{uuid.uuid4().hex[:16].upper()}"
canary_name = f"CANARY_NAME_{uuid.uuid4().hex[:8].upper()}"

csv_content = f"Datum;Text;Betrag\n01.01.2025;{canary_name} {canary_iban};150,00\n02.01.2025;Büromaterial;45,50\n"

st_conv, body_conv = http_req(
    "/api/v1/convert?format=json",
    method="POST",
    headers={**auth_headers, "X-Idempotency-Key": uuid.uuid4().hex},
    files={"files": ("statement_canary.csv", csv_content.encode("utf-8"), "text/csv")}
)

results["normal_conversion"] = {
    "status_code": st_conv,
    "success": st_conv == 200,
    "transactions_count": len(body_conv.get("transactions", [])) if isinstance(body_conv, dict) else 0
}
print(f"Conversion: {st_conv} -> {results['normal_conversion']}")

print("\n=== 5. Testing Oversize Row Limit (413) ===")
big_csv_lines = ["Datum;Text;Betrag"] + [f"01.01.2025;Row {i};1,00" for i in range(10005)]
big_csv_content = "\n".join(big_csv_lines)

st_413, body_413 = http_req(
    "/api/v1/convert?format=json",
    method="POST",
    headers={**auth_headers, "X-Idempotency-Key": uuid.uuid4().hex},
    files={"files": ("oversize.csv", big_csv_content.encode("utf-8"), "text/csv")}
)
results["row_limit_413"] = {
    "status_code": st_413,
    "detail": body_413.get("detail") if isinstance(body_413, dict) else str(body_413)
}
print(f"Row limit: {st_413} -> {results['row_limit_413']}")

print("\n=== 6. Checking Supervisor Wiring Inside Linux Container ===")
wiring_code = """
import json
from app.services.parser_process_supervisor import parser_supervisor
from app.core.config import settings

data = {
    "concurrency": parser_supervisor.max_concurrency,
    "queue_depth": parser_supervisor.max_queue_depth,
    "timeout_seconds": parser_supervisor.default_timeout,
    "process_isolation": settings.PARSER_PROCESS_ISOLATION,
    "email_backend": settings.EMAIL_BACKEND,
    "environment": settings.ENVIRONMENT
}
print(json.dumps(data))
"""
p_wire = subprocess.run(f"docker exec -i {CONTAINER_NAME} python -", shell=True, input=wiring_code, capture_output=True, text=True)
try:
    wiring_data = json.loads(p_wire.stdout.strip())
except Exception as e:
    wiring_data = {"error": str(e), "raw": p_wire.stdout}

results["supervisor_wiring"] = {
    "data": wiring_data,
    "concurrency_2": wiring_data.get("concurrency") == 2,
    "queue_depth_4": wiring_data.get("queue_depth") == 4,
    "process_isolation_enforced": wiring_data.get("process_isolation") is True,
    "production_environment": wiring_data.get("environment") == "production"
}
print(f"Supervisor Wiring: {results['supervisor_wiring']}")

print("\n=== 7. Testing Real Supervisor Timeout & Hard Kill Cleanup ===")
timeout_probe_code = """
import asyncio
import json
import multiprocessing
from fastapi import HTTPException
from app.services.parser_process_supervisor import ParserProcessSupervisor

async def test():
    # Supervisor with short timeout 0.01s
    sup = ParserProcessSupervisor(max_concurrency=1, default_timeout=0.01)
    status_code = None
    detail = None
    try:
        # Pass valid CSV with extreme short timeout so worker receives it but times out
        await sup.parse_file(b"Datum;Text;Betrag\\n01.01.2025;A;1\\n", "test.csv", "test_tenant", timeout=0.001)
        status_code = 200
    except HTTPException as e:
        status_code = e.status_code
        detail = str(e.detail)
    
    # Check active children of this python process immediately after
    active_pids = [p.pid for p in multiprocessing.active_children() if p.is_alive()]
    print(json.dumps({"status_code": status_code, "detail": detail, "active_children": active_pids}))

asyncio.run(test())
"""
p_to = subprocess.run(f"docker exec -i {CONTAINER_NAME} python -", shell=True, input=timeout_probe_code, capture_output=True, text=True)
try:
    to_data = json.loads(p_to.stdout.strip())
except Exception as e:
    to_data = {"error": str(e), "raw": p_to.stdout}

results["supervisor_real_timeout"] = {
    "data": to_data,
    "http_408_returned": to_data.get("status_code") == 408,
    "live_children_after_response": to_data.get("active_children", []),
    "clean_termination": len(to_data.get("active_children", [1])) == 0
}
print(f"Supervisor Timeout Probe: {results['supervisor_real_timeout']}")

print("\n=== 8. Verifying Process Tree via Docker Top (Zero Lingering Workers / Zero Zombies) ===")
top_out, _, _ = run_cmd(f"docker top {CONTAINER_NAME}")
top_lines = [l for l in top_out.strip().split("\n") if l.strip()]
pids = top_lines[1:] if len(top_lines) > 1 else []

results["process_tree_verification"] = {
    "running_processes_count": len(pids),
    "processes": pids,
    "single_uvicorn_master_running": len(pids) == 1,
    "zero_zombies": all("<defunct>" not in p for p in pids)
}
print(f"Process Tree: {results['process_tree_verification']}")

print("\n=== 9. Testing Zero-Retention Canaries (0 Disk / 0 Logs Trace) ===")
grep_tmp, _, _ = run_cmd(f"docker exec {CONTAINER_NAME} grep -rn '{canary_iban}' /tmp 2>&1")
grep_logs, _, _ = run_cmd(f"docker logs {CONTAINER_NAME} 2>&1 | grep '{canary_iban}'")

results["zero_retention_canary"] = {
    "canary_iban": canary_iban,
    "tmp_matches": grep_tmp,
    "tmp_clean": grep_tmp == "",
    "logs_matches": grep_logs,
    "logs_clean": grep_logs == ""
}
print(f"Canary check: tmp_clean={results['zero_retention_canary']['tmp_clean']}, logs_clean={results['zero_retention_canary']['logs_clean']}")

print("\n=== 10. Checking SMTP Delivery & Error Handling ===")
st_otp, body_otp = http_req("/api/v1/auth/request-code", method="POST", data={"email": "audit_smtp@statement2muster.com"})
results["smtp_configuration"] = {
    "request_code_status": st_otp,
    "request_code_response": body_otp,
    "graceful_502_on_unreachable_smtp": st_otp == 502,
    "safe_error_message": body_otp.get("detail") if isinstance(body_otp, dict) else str(body_otp)
}
print(f"SMTP Configuration: {results['smtp_configuration']}")

print("\n=== Saving Results ===")
RESULTS_FILE.write_text(json.dumps(results, indent=2))
print(f"Results written to {RESULTS_FILE}")
print(json.dumps(results, indent=2))
