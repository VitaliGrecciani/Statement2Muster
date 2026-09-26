"""Decision 58: isolated regression, local adversarial probes, read-only live metadata.

Never reads production credentials, changes deployment, or converts live data.
Only synthetic local payloads are used; raw validation/log messages are not saved.
"""
import asyncio
import copy
import csv
import datetime
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
BACKEND = ROOT / "backend"


def isolated_env(directory):
    env = os.environ.copy()
    env.pop("SQLITE_DB_PATH", None)
    env.update(DATABASE_URL="sqlite+aiosqlite:///" + (Path(directory) / "audit.sqlite").as_posix(),
               ENVIRONMENT="test", EMAIL_BACKEND="memory", JWT_PRIVATE_KEY_PEM="",
               JWT_PUBLIC_KEY_PEM="", STRIPE_SECRET_KEY="sk_test_mock",
               STRIPE_WEBHOOK_SECRET="whsec_mock", VERSION="1.0.16")
    return env


def regression():
    with tempfile.TemporaryDirectory(prefix="s2m-r58-tests-") as directory:
        code = "import sys,pytest; sys.path.insert(0,sys.argv[1]); raise SystemExit(pytest.main([sys.argv[1],'-q']))"
        result = subprocess.run([sys.executable, "-E", "-c", code, str(BACKEND)],
                                cwd=directory, env=isolated_env(directory),
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = result.stdout + result.stderr
        (OUT / "pytest_results.txt").write_text(output, encoding="utf-8")
        return {"exit_code": result.returncode, "tail": output[-2500:]}


async def local_probes():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.db.session import init_db, async_session_maker
    from app.db.models import Tenant, Entitlement, UsageReservation
    from app.api.endpoints.gpt_action import gpt_download_cache, gpt_free_tier_tracker
    from app.api.endpoints.plugin_and_mcp import MCP_TOOL_CONVERT_STATEMENT
    from sqlalchemy import select

    logging.getLogger().setLevel(logging.CRITICAL)
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    mcp_logger = logging.getLogger("statement2muster.mcp")
    mcp_logger.propagate = False
    mcp_logger.setLevel(logging.ERROR)
    mcp_logger.addHandler(handler)
    await init_db()
    gpt_download_cache.clear()
    gpt_free_tier_tracker.clear()
    results = {}
    headers = {"Accept": "application/json, text/event-stream"}
    def rpc(method, params=None, number=1):
        return {"jsonrpc": "2.0", "id": number, "method": method, "params": params or {}}
    args = {"bank_name": "Synthetic Bank", "session_id": "r58-demo",
            "export_format": "datev", "default_bank_account": "1200", "transactions": [
                {"booking_date": "2026-03-15", "amount": -189.5, "currency": "EUR",
                 "description": "Synthetic expense", "reference": "TEST-001"},
                {"booking_date": "2026-03-18", "amount": 3400, "currency": "EUR",
                 "description": "Synthetic income", "reference": "TEST-002"}]}
    def call(arguments):
        return rpc("tools/call", {"name": "convert_statement", "arguments": arguments})
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://audit", headers=headers) as client:
        response = await client.post("/api/v1/mcp", json=call(args))
        markdown = response.json()["result"]["content"][0]["text"]
        path = re.search(r"/v1/gpt/download/(s2m_gpt_[a-f0-9]+)", markdown).group(0)
        download = await client.get(path)
        rows = list(csv.reader(io.StringIO(download.content.decode("windows-1252")), delimiter=";"))
        results["summary_vs_download"] = {
            "http": response.status_code, "markdown": markdown,
            "download_http": download.status_code,
            "csv_rows": [{"amount": row[0], "direction": row[1], "bank": row[6]} for row in rows[2:]],
            "expected_net": 3210.5, "privacy_openai_note_present": "OpenAI" in markdown}
        # Backend body limit branch: small, controlled limit, no large allocation/DoS.
        previous = settings.MAX_BATCH_SIZE_BYTES
        settings.MAX_BATCH_SIZE_BYTES = 256
        try:
            for path in ("/v1/gpt/convert", "/api/v1/mcp", "/mcp"):
                response = await client.post(path, content=json.dumps(rpc("ping")),
                                             headers={"content-type": "application/json", "content-length": "257"})
                results["declared_body_budget_" + path] = {"http": response.status_code, "limit": 256}
            async def chunks():
                yield json.dumps(rpc("ping")).encode() + b" " * 300
            for path in ("/v1/gpt/convert", "/api/v1/mcp", "/mcp"):
                response = await client.post(path, content=chunks(), headers={"content-type": "application/json"})
                results["stream_body_budget_" + path] = {"http": response.status_code, "limit": 256}
        finally:
            settings.MAX_BATCH_SIZE_BYTES = previous
        invalid = copy.deepcopy(args)
        invalid["transactions"] = [{"booking_date": "2026-03-15", "amount": "SYNTHETIC_PRIVATE_VALUE",
                                    "currency": "EUR", "description": "Synthetic"}] * 600
        captured.seek(0)
        captured.truncate(0)
        response = await client.post("/api/v1/mcp", json=call(invalid))
        results["manual_validation_error"] = {
            "http": response.status_code, "response_characters": len(response.text),
            "rpc_error_code": response.json().get("error", {}).get("code"),
            "input_echoed_in_response": "SYNTHETIC_PRIVATE_VALUE" in response.text,
            "input_echoed_in_log": "SYNTHETIC_PRIVATE_VALUE" in captured.getvalue(),
            "log_characters": len(captured.getvalue())}
        for key, method, kwargs in [
            ("sse_get", "get", {"headers": {"accept": "text/event-stream"}}),
            ("initialized_notification", "post", {"json": {"jsonrpc": "2.0", "method": "notifications/initialized"}}),
            ("unsupported_protocol_header", "post", {"json": rpc("ping"), "headers": {"MCP-Protocol-Version": "invalid"}}),
            ("untrusted_origin", "post", {"json": rpc("ping"), "headers": {"Origin": "https://untrusted.invalid"}}),
            ("wrong_jsonrpc", "post", {"json": {"jsonrpc": "1.0", "method": "ping", "id": 1}}),
            ("non_object_params", "post", {"json": rpc("tools/call", [1])})]:
            response = await getattr(client, method)("/api/v1/mcp", **kwargs)
            results[key] = {"http": response.status_code, "content_type": response.headers.get("content-type"),
                            "body_prefix": response.text[:140]}
        results["schema"] = {"request_id_exposed": "request_id" in MCP_TOOL_CONVERT_STATEMENT["inputSchema"]["properties"],
                             "license_key_exposed": "license_key" in MCP_TOOL_CONVERT_STATEMENT["inputSchema"]["properties"]}
        # Authenticated local replay using only advertised fields.
        now = datetime.datetime.now(datetime.timezone.utc)
        async with async_session_maker() as db:
            db.add(Tenant(id="r58-starter", email="r58@example.invalid"))
            db.add(Entitlement(tenant_id="r58-starter", plan_code="starter", status="active",
                               source_type="subscription", source_id="r58-sub",
                               current_period_start=now-datetime.timedelta(days=1),
                               valid_until=now+datetime.timedelta(days=29)))
            await db.commit()
        token = create_access_token("r58@example.invalid", "r58-starter")
        paid_headers = {"Authorization": "Bearer " + token}
        downloads = []
        for _ in range(2):
            response = await client.post("/api/v1/mcp", json=call(args), headers=paid_headers)
            downloads.append(re.search(r"s2m_gpt_[a-f0-9]+", response.text).group(0))
        async with async_session_maker() as db:
            ledger = (await db.execute(select(UsageReservation).where(UsageReservation.tenant_id == "r58-starter"))).scalars().all()
            results["advertised_fields_replay"] = {"different_download_ids": downloads[0] != downloads[1],
                                                   "ledger": [{"status": row.status, "units": row.units} for row in ledger]}
        args_with_id = dict(args, request_id="r58-explicit-id")
        responses = [await client.post("/api/v1/mcp", json=call(args_with_id), headers=paid_headers) for _ in range(2)]
        results["undeclared_explicit_request_id_control"] = {"http": [r.status_code for r in responses],
                                                              "identical_response": responses[0].text == responses[1].text}
    return results


async def live_metadata():
    import httpx
    result = {}
    async with httpx.AsyncClient(base_url="https://api.statement2muster.com", timeout=15) as client:
        for path in ("/api/v1/health", "/.well-known/ai-plugin.json", "/api/v1/mcp"):
            try:
                r = await client.get(path, headers={"Accept": "text/event-stream"} if path.endswith("mcp") else {})
                result[path] = {"http": r.status_code, "content_type": r.headers.get("content-type"), "json": r.json()}
            except Exception as ex:
                result[path] = {"network_error": type(ex).__name__}
        for method in ("initialize", "tools/list", "notifications/initialized"):
            payload = {"jsonrpc": "2.0", "method": method}
            if method != "notifications/initialized":
                payload["id"] = 1
            if method == "initialize":
                payload["params"] = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "decision58-audit", "version": "1"}}
            try:
                r = await client.post("/api/v1/mcp", json=payload, headers={"Accept": "application/json, text/event-stream"})
                result[method] = {"http": r.status_code, "json": r.json() if r.content else None}
            except Exception as ex:
                result[method] = {"network_error": type(ex).__name__}
    return result


if __name__ == "__main__":
    if "--local-child" in sys.argv:
        sys.path.insert(0, str(BACKEND))
        data = asyncio.run(local_probes())
        (OUT / "local_probe_results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(data, ensure_ascii=True, indent=2))
    else:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        tested = regression()
        print(tested["tail"])
        with tempfile.TemporaryDirectory(prefix="s2m-r58-probes-") as directory:
            child = subprocess.run([sys.executable, "-E", str(Path(__file__).resolve()), "--local-child"],
                                   cwd=directory, env=isolated_env(directory), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace")
            print("LOCAL_EXIT:", child.returncode)
            print(child.stdout[-11000:])
            if child.returncode:
                print(child.stderr[-2500:])
        live = asyncio.run(live_metadata())
        (OUT / "live_metadata_results.json").write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = {"git_head": head, "scope": "temporary SQLite + ephemeral keys; synthetic local data; live discovery only",
                "regression_exit": tested["exit_code"], "local_probe_exit": child.returncode,
                "live_methods": {k: v.get("http", v.get("network_error")) for k, v in live.items()}}
        (OUT / "audit_run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(meta, indent=2))
