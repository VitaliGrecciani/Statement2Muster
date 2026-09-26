"""
Statement2Muster Release 1.0.17 Deployment & Live Verification Runner.

Performs:
1. Local packaging of updated backend and docker-compose.prod.yml.
2. Secure SCP transfer to Hetzner production host (46.225.95.36).
3. Docker build (statement2muster-api:1.0.17) and container recreation.
4. Healthcheck and sanitized container inspection.
5. End-to-end live HTTPS validation against https://api.statement2muster.com
   covering all Decision 58 audit conditions (R58-1 through R58-6).
6. Evidence collection in docs/audit_release1017_decision59_2026-09-26/.
"""

import os
import sys
import json
import time
import tarfile
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT_DIR / "docs" / "audit_release1017_decision59_2026-09-26"
HETZNER_HOST = "root@46.225.95.36"
REMOTE_DIR = "/opt/statement2muster"
API_BASE = "https://api.statement2muster.com"

AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd_list, check=True):
    print(f"[*] Running: {' '.join(cmd_list)}")
    res = subprocess.run(cmd_list, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"[!] Error (exit {res.returncode}):\n{res.stderr}")
        raise RuntimeError(f"Command failed: {cmd_list}")
    return res


def package_and_upload():
    tar_path = ROOT_DIR / "release_1017.tar.gz"
    print(f"[*] Packaging backend into {tar_path}...")
    with tarfile.open(tar_path, "w:gz") as tar:
        # Add backend app directory
        backend_dir = ROOT_DIR / "backend"
        for item in backend_dir.glob("**/*"):
            if ".venv" in item.parts or "__pycache__" in item.parts or ".pytest_cache" in item.parts:
                continue
            arcname = item.relative_to(ROOT_DIR)
            tar.add(item, arcname=str(arcname))
        # Add docker-compose.prod.yml
        tar.add(ROOT_DIR / "docker-compose.prod.yml", arcname="docker-compose.prod.yml")
        # Add .codex-plugin and plugin.json
        if (ROOT_DIR / ".codex-plugin").exists():
            tar.add(ROOT_DIR / ".codex-plugin", arcname=".codex-plugin")
        if (ROOT_DIR / "plugin.json").exists():
            tar.add(ROOT_DIR / "plugin.json", arcname="plugin.json")

    print("[*] Uploading package to Hetzner host...")
    run_cmd(["scp", str(tar_path), f"{HETZNER_HOST}:{REMOTE_DIR}/release_1017.tar.gz"])
    tar_path.unlink()

    print("[*] Unpacking on server...")
    unpack_cmd = f"cd {REMOTE_DIR} && tar -xzf release_1017.tar.gz && rm release_1017.tar.gz"
    run_cmd(["ssh", HETZNER_HOST, unpack_cmd])


def build_and_deploy():
    print("[*] Building Docker image statement2muster-api:1.0.17 on Hetzner...")
    build_cmd = (
        f"cd {REMOTE_DIR} && "
        "docker compose -f docker-compose.prod.yml build"
    )
    res = run_cmd(["ssh", HETZNER_HOST, build_cmd])
    print(res.stdout[-500:])

    print("[*] Recreating container s2m-backend-api...")
    up_cmd = (
        f"cd {REMOTE_DIR} && "
        "docker compose -f docker-compose.prod.yml up -d --force-recreate"
    )
    run_cmd(["ssh", HETZNER_HOST, up_cmd])

    print("[*] Waiting for container health check...")
    for i in range(15):
        time.sleep(2)
        ps_cmd = 'docker inspect --format="{{.State.Health.Status}}" s2m-backend-api'
        res = run_cmd(["ssh", HETZNER_HOST, ps_cmd], check=False)
        health_status = res.stdout.strip()
        print(f"    Health attempt {i+1}: {health_status}")
        if health_status == "healthy":
            break
    else:
        raise RuntimeError("Container did not become healthy within 30 seconds!")


def inspect_production():
    print("[*] Collecting sanitized container inspect metadata...")
    inspect_cmd = "docker inspect s2m-backend-api"
    res = run_cmd(["ssh", HETZNER_HOST, inspect_cmd])
    raw_data = json.loads(res.stdout)[0]

    # Sanitize env vars per R58-6 (zero secrets in artifacts)
    raw_env = raw_data.get("Config", {}).get("Env", [])
    sanitized_env = []
    for e in raw_env:
        k = e.split("=", 1)[0]
        if any(sec in k.upper() for sec in ("SECRET", "KEY", "PASS", "TOKEN", "AUTH", "CRED")):
            sanitized_env.append(f"{k}=[REDACTED]")
        else:
            sanitized_env.append(e)

    container_id = raw_data.get("Id", "")
    image_id = raw_data.get("Image", "")
    created = raw_data.get("Created", "")
    status_val = raw_data.get("State", {}).get("Status", "")
    health_val = raw_data.get("State", {}).get("Health", {}).get("Status", "")

    git_rev = run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()

    metadata = {
        "git_commit": git_rev,
        "release_version": "1.0.17",
        "container_id": container_id,
        "image_id": image_id,
        "created": created,
        "status": status_val,
        "health": health_val,
        "sanitized_env": sanitized_env,
        "limits": {
            "cpus": raw_data.get("HostConfig", {}).get("NanoCpus", 0) / 1e9,
            "memory_bytes": raw_data.get("HostConfig", {}).get("Memory", 0),
            "read_only_rootfs": raw_data.get("HostConfig", {}).get("ReadonlyRootfs", False),
            "cap_drop": raw_data.get("HostConfig", {}).get("CapDrop", [])
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    with open(AUDIT_DIR / "production_inspect.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"[*] Saved production metadata: Container {container_id[:12]} Image {image_id[:12]} Status: {status_val}/{health_val}")
    return metadata


def http_request(url, method="GET", headers=None, body=None):
    if headers is None:
        headers = {}
    data = None
    if body is not None:
        if isinstance(body, dict) or isinstance(body, list):
            data = json.dumps(body).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        elif isinstance(body, (bytes, bytearray)):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
            return {
                "status_code": resp.status,
                "headers": dict(resp.headers),
                "body": content.decode("utf-8", errors="replace")
            }
    except urllib.error.HTTPError as e:
        content = e.read()
        return {
            "status_code": e.code,
            "headers": dict(e.headers),
            "body": content.decode("utf-8", errors="replace")
        }
    except Exception as e:
        return {
            "status_code": 0,
            "error": str(e)
        }


def run_live_probes():
    print("[*] Running comprehensive live HTTPS probes against production...")
    probes = {}

    # 1. Healthcheck (R58-6 version bump)
    print("    1. Healthcheck...")
    h_resp = http_request(f"{API_BASE}/api/v1/health")
    h_data = json.loads(h_resp["body"])
    assert h_resp["status_code"] == 200
    assert h_data["version"] == "1.0.17", f"Expected version 1.0.17, got {h_data['version']}"
    probes["health"] = {"status": h_resp["status_code"], "body": h_data}

    # 2. OpenAI Plugin Manifest
    print("    2. Plugin Manifest...")
    m_resp = http_request(f"{API_BASE}/.well-known/ai-plugin.json")
    m_data = json.loads(m_resp["body"])
    assert m_resp["status_code"] == 200
    assert m_data["schema_version"] == "v1"
    assert "zertifizierte" not in m_data["description_for_model"]
    probes["plugin_manifest"] = {"status": m_resp["status_code"], "schema_version": m_data["schema_version"]}

    # 3. Modern MCP Manifest
    print("    3. MCP Discovery Manifest...")
    mcp_m_resp = http_request(f"{API_BASE}/.well-known/mcp.json")
    mcp_m_data = json.loads(mcp_m_resp["body"])
    assert mcp_m_resp["status_code"] == 200
    assert "statement2muster" in mcp_m_data["mcpServers"]
    probes["mcp_discovery"] = {"status": mcp_m_resp["status_code"], "servers": list(mcp_m_data["mcpServers"].keys())}

    # 4. Streamable HTTP GET protection (R58-5: returns 405 Method Not Allowed)
    print("    4. Streamable HTTP GET -> 405...")
    get_mcp_resp = http_request(f"{API_BASE}/api/v1/mcp", method="GET")
    assert get_mcp_resp["status_code"] == 405
    probes["streamable_get_405"] = {"status": get_mcp_resp["status_code"]}

    # 5. MCP Diagnostics endpoint
    print("    5. MCP Diagnostics GET -> 200...")
    status_resp = http_request(f"{API_BASE}/api/v1/mcp/status", method="GET")
    assert status_resp["status_code"] == 200
    status_data = json.loads(status_resp["body"])
    assert status_data["version"] == "1.0.17"
    probes["mcp_diagnostics"] = {"status": status_resp["status_code"], "version": status_data["version"]}

    # 6. Protocol Envelope Validation: jsonrpc '1.0' rejected (R58-5)
    print("    6. Protocol envelope reject jsonrpc 1.0 -> 400...")
    p1_resp = http_request(
        f"{API_BASE}/api/v1/mcp",
        method="POST",
        body={"jsonrpc": "1.0", "method": "ping", "id": 1}
    )
    assert p1_resp["status_code"] == 400
    assert json.loads(p1_resp["body"])["error"]["code"] == -32600
    probes["reject_jsonrpc_1_0"] = {"status": p1_resp["status_code"], "code": -32600}

    # 7. Protocol Envelope Validation: array params rejected (R58-5)
    print("    7. Protocol envelope reject array params -> 400...")
    p2_resp = http_request(
        f"{API_BASE}/api/v1/mcp",
        method="POST",
        body={"jsonrpc": "2.0", "method": "ping", "id": 2, "params": [1, 2, 3]}
    )
    assert p2_resp["status_code"] == 400
    assert json.loads(p2_resp["body"])["error"]["code"] == -32602
    probes["reject_array_params"] = {"status": p2_resp["status_code"], "code": -32602}

    # 8. MCP Lifecycle: initialize & notifications/initialized (R58-5)
    print("    8. MCP initialize & notification 202...")
    init_resp = http_request(
        f"{API_BASE}/api/v1/mcp",
        method="POST",
        body={"jsonrpc": "2.0", "method": "initialize", "id": "init-live"}
    )
    assert init_resp["status_code"] == 200
    notif_resp = http_request(
        f"{API_BASE}/api/v1/mcp",
        method="POST",
        body={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert notif_resp["status_code"] == 202
    probes["lifecycle"] = {"init_status": init_resp["status_code"], "notif_status": notif_resp["status_code"]}

    # 9. tools/list schema declares request_id (R58-4)
    print("    9. tools/list schema declaring request_id...")
    tools_resp = http_request(
        f"{API_BASE}/api/v1/mcp",
        method="POST",
        body={"jsonrpc": "2.0", "method": "tools/list", "id": "tools-live"}
    )
    assert tools_resp["status_code"] == 200
    tools_data = json.loads(tools_resp["body"])
    tool_conv = next(t for t in tools_data["result"]["tools"] if t["name"] == "convert_statement")
    assert "request_id" in tool_conv["inputSchema"]["properties"]
    assert "zertifizierte" not in tool_conv["description"]
    probes["tools_list"] = {"declared_request_id": True, "properties": list(tool_conv["inputSchema"]["properties"].keys())}

    # 10. Live Conversion with 2 transactions & accurate financial summary (R58-3)
    print("    10. Live Conversion & Non-Zero Financial Summary (R58-3)...")
    op_req_id = f"live-test-req-{int(time.time())}"
    tx_items = [
        {
            "booking_date": "2026-03-01",
            "amount": -189.50,
            "currency": "EUR",
            "description": "Büromaterial Staples"
        },
        {
            "booking_date": "2026-03-15",
            "amount": 3400.00,
            "currency": "EUR",
            "description": "Zahlungseingang Kunde Müller"
        }
    ]
    call_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": "live-call-1",
        "params": {
            "name": "convert_statement",
            "arguments": {
                "request_id": op_req_id,
                "bank_name": "Sparkasse",
                "export_format": "datev",
                "session_id": "live_probe_session_1017",
                "transactions": tx_items
            }
        }
    }
    conv_resp = http_request(f"{API_BASE}/api/v1/mcp", method="POST", body=call_payload)
    assert conv_resp["status_code"] == 200
    conv_data = json.loads(conv_resp["body"])
    assert conv_data["result"]["isError"] is False
    markdown_text = conv_data["result"]["content"][0]["text"]

    # Verify R58-3 non-zero financial summary fields
    assert "- **Buchungszeilen:** 2" in markdown_text
    assert "- **Abflüsse (Ausgaben):** -189.50 EUR" in markdown_text
    assert "- **Zuflüsse (Einnahmen):** 3400.00 EUR" in markdown_text
    assert "- **Saldo (Periodensaldo):** +3210.50 EUR" in markdown_text
    assert "- **Zeitraum:** 2026-03-01 bis 2026-03-15" in markdown_text
    assert "DATEV EXTF 700 Buchungsstapel herunterladen" in markdown_text
    assert "TTL 1800s" in markdown_text
    probes["conversion_summary"] = {
        "tx_count": 2,
        "debit": -189.50,
        "credit": 3400.00,
        "saldo": "+3210.50 EUR",
        "text_preview": markdown_text[:250]
    }

    # Extract download URL and verify download from RAM cache
    import re
    m_url = re.search(r"\(https://api\.statement2muster\.com/v1/gpt/download/[^\)]+\)", markdown_text)
    assert m_url is not None
    download_url = m_url.group(0)[1:-1]
    dl_resp = http_request(download_url)
    assert dl_resp["status_code"] == 200
    assert "189,50" in dl_resp["body"]
    assert "3400,00" in dl_resp["body"]
    probes["ram_download_verified"] = {"url": download_url, "status": dl_resp["status_code"], "bytes": len(dl_resp["body"])}

    # 11. Live Idempotent Replay (R58-4)
    print("    11. Live Replay Idempotency (R58-4)...")
    replay_resp = http_request(f"{API_BASE}/api/v1/mcp", method="POST", body=call_payload)
    assert replay_resp["status_code"] == 200
    replay_data = json.loads(replay_resp["body"])
    assert replay_data["result"]["content"][0]["text"] == markdown_text, "Replay did not return identical output"
    probes["replay_verified"] = {"idempotent_match": True, "request_id": op_req_id}

    # 12. Live Replay Conflict on Payload Mismatch (R58-4)
    print("    12. Live Replay Conflict (409)...")
    conflict_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": "live-conflict",
        "params": {
            "name": "convert_statement",
            "arguments": {
                "request_id": op_req_id,
                "session_id": "live_probe_session_1017",
                "bank_name": "Sparkasse",
                "transactions": [
                    {
                        "booking_date": "2026-03-01",
                        "amount": -999.00,  # Changed amount
                        "currency": "EUR",
                        "description": "Changed amount"
                    }
                ]
            }
        }
    }
    conflict_resp = http_request(f"{API_BASE}/api/v1/mcp", method="POST", body=conflict_payload)
    assert conflict_resp["status_code"] == 409
    assert any("application/json" in v.lower() for k, v in conflict_resp["headers"].items() if k.lower() == "content-type")
    assert "different request payload" in json.loads(conflict_resp["body"])["error"]["message"]
    probes["replay_conflict_409"] = {"status": conflict_resp["status_code"], "error": json.loads(conflict_resp["body"])["error"]}

    # 13. Live Validation Error Sanitization & Length Capping (R58-2)
    print("    13. Live 600 Validation Errors Sanitization (R58-2)...")
    secret_marker = "LIVE_CUSTOMER_SECRET_987654321"
    bad_txs = [
        {
            "booking_date": "2026-03-01",
            "amount": f"INVALID_{secret_marker}_{i}",
            "currency": "EUR",
            "description": f"Test item {i}"
        }
        for i in range(600)
    ]
    err_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": "live-err-600",
        "params": {
            "name": "convert_statement",
            "arguments": {
                "bank_name": "Sparkasse",
                "transactions": bad_txs
            }
        }
    }
    err_resp = http_request(f"{API_BASE}/api/v1/mcp", method="POST", body=err_payload)
    assert err_resp["status_code"] == 400
    err_data = json.loads(err_resp["body"])
    assert err_data["error"]["code"] == -32602
    err_msg = err_data["error"]["message"]
    assert len(err_msg) < 4000
    assert secret_marker not in err_msg
    probes["validation_error_sanitization"] = {
        "status": err_resp["status_code"],
        "code": -32602,
        "msg_length": len(err_msg),
        "secret_leaked": False,
        "capped_under_4000": True
    }

    # 14. Live Early Budget DoS Rejection (R58-1)
    print("    14. Live Early Budget DoS 413 (R58-1)...")
    oversized_data = b'{"jsonrpc":"2.0"}' + b' ' * (10 * 1024 * 1024 + 2048)
    dos_resp = http_request(
        f"{API_BASE}/api/v1/mcp",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=oversized_data
    )
    assert dos_resp["status_code"] == 413
    assert "payload_too_large" in dos_resp["body"]
    probes["early_budget_dos_413"] = {"status": dos_resp["status_code"], "detail": json.loads(dos_resp["body"])}

    with open(AUDIT_DIR / "live_probe_results.json", "w", encoding="utf-8") as f:
        json.dump(probes, f, indent=2)

    print("[+] All 14 live verification probes PASSED successfully!")
    return probes


def main():
    print("=== STATEMENT2MUSTER RELEASE 1.0.17 DEPLOYMENT & REMEDIATION VERIFIER ===")
    package_and_upload()
    build_and_deploy()
    metadata = inspect_production()
    probes = run_live_probes()
    print("\n[SUCCESS] Release 1.0.17 successfully deployed and fully verified.")


if __name__ == "__main__":
    main()
