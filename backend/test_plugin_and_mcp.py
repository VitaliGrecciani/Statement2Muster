"""
Unit & Integration Tests for OpenAI Plugin Manifest & MCP Server Endpoints (Release 1.0.17).

Verifies full remediation of Chief Architect Decision 58:
- R58-1: Early budget check (413 Payload Too Large) on MCP endpoints
- R58-2: Input validation error sanitization (no customer input leak, capped <= 4000 chars, code -32602)
- R58-3: Accurate financial summary mapping (Abflüsse, Zuflüsse, Saldo, DATEV vs BMD)
- R58-4: Idempotent replay contract via declared request_id (same download, 409 on conflict)
- R58-5: JSON-RPC 2.0 protocol validation (envelope, array params reject, 202 notification, 405 on GET)
"""

import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings


@pytest.mark.asyncio
async def test_plugin_manifest_endpoint():
    """Verify /.well-known/ai-plugin.json adheres strictly to OpenAI 2026 specs without unproven claims."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/.well-known/ai-plugin.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "v1"
        assert data["name_for_model"] == "statement2muster"
        assert "DATEV" in data["description_for_human"]
        assert "zertifizierte" not in data["description_for_model"]
        assert data["auth"]["type"] == "none"
        assert "openapi.json" in data["api"]["url"]
        assert "statement2muster.com/logo.png" in data["logo_url"]
        assert "datenschutz.html" in data["legal_info_url"]


@pytest.mark.asyncio
async def test_mcp_discovery_manifest():
    """Verify modern MCP discovery manifest at /.well-known/mcp.json."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/.well-known/mcp.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "mcpServers" in data
        assert "statement2muster" in data["mcpServers"]
        assert data["mcpServers"]["statement2muster"]["protocolVersion"] == "2024-11-05"


@pytest.mark.asyncio
async def test_mcp_streamable_get_405_and_diagnostic_status():
    """Verify R58-5: Direct GET on /api/v1/mcp returns 405 Method Not Allowed, status endpoint returns 200."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # GET on MCP endpoint returns 405
        resp_mcp = await ac.get("/api/v1/mcp")
        assert resp_mcp.status_code == 405
        assert "Method Not Allowed" in resp_mcp.json()["error"]["message"]

        # GET on status/health returns 200 with diagnostics
        resp_status = await ac.get("/api/v1/mcp/status")
        assert resp_status.status_code == 200
        data = resp_status.json()
        assert data["protocolVersion"] == "2024-11-05"
        assert "convert_statement" in data["tools"]
        assert data["version"] == settings.VERSION


@pytest.mark.asyncio
async def test_mcp_early_budget_exceeded_r58_1():
    """Verify R58-1: Early budget check rejects oversized MCP payload before JSON parsing with 413."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        oversized_headers = {
            "Content-Length": str(settings.MAX_MCP_PAYLOAD_BYTES + 1024),
            "Content-Type": "application/json"
        }
        resp = await ac.post("/api/v1/mcp", headers=oversized_headers, content=b"{}")
        assert resp.status_code == 413
        assert resp.json()["error"] == "payload_too_large"


@pytest.mark.asyncio
async def test_mcp_rpc_protocol_envelope_validation_r58_5():
    """Verify R58-5: Protocol validation rejects invalid JSON-RPC envelope, wrong version, and array params."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Invalid jsonrpc version: '1.0'
        resp_ver = await ac.post("/api/v1/mcp", json={"jsonrpc": "1.0", "method": "ping", "id": 1})
        assert resp_ver.status_code == 400
        assert resp_ver.json()["error"]["code"] == -32600

        # 2. Params sent as list/array instead of dict
        resp_arr = await ac.post("/api/v1/mcp", json={"jsonrpc": "2.0", "method": "ping", "id": 2, "params": [1, 2, 3]})
        assert resp_arr.status_code == 400
        assert resp_arr.json()["error"]["code"] == -32602

        # 3. Unsupported MCP-Protocol-Version header
        resp_hdr = await ac.post(
            "/api/v1/mcp",
            headers={"mcp-protocol-version": "1999-01-01"},
            json={"jsonrpc": "2.0", "method": "ping", "id": 3}
        )
        assert resp_hdr.status_code == 400
        assert resp_hdr.json()["error"]["code"] == -32600

        # 4. Valid ping
        resp_ping = await ac.post("/api/v1/mcp", json={"jsonrpc": "2.0", "method": "ping", "id": 4})
        assert resp_ping.status_code == 200
        assert resp_ping.json()["result"] == {}


@pytest.mark.asyncio
async def test_mcp_rpc_lifecycle():
    """Verify initialize and notifications/initialized lifecycle (202 Accepted)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # initialize
        resp_init = await ac.post(
            "/api/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": "init-1",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}}
            }
        )
        assert resp_init.status_code == 200
        assert resp_init.json()["result"]["protocolVersion"] == "2024-11-05"

        # notifications/initialized returns 202 without body
        resp_notif = await ac.post(
            "/api/v1/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert resp_notif.status_code == 202
        assert resp_notif.content == b""


@pytest.mark.asyncio
async def test_mcp_tools_list_declares_request_id_r58_4():
    """Verify R58-4: tools/list schema declares request_id with idempotency explanation and no unproven claims."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": "list-1"})
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        tool = next(t for t in tools if t["name"] == "convert_statement")
        
        props = tool["inputSchema"]["properties"]
        assert "request_id" in props
        assert "Replay-Schutz" in props["request_id"]["description"]
        assert props["request_id"]["maxLength"] == 100
        assert "zertifizierte" not in tool["description"]


@pytest.mark.asyncio
async def test_mcp_validation_error_sanitization_r58_2():
    """
    Verify R58-2: 600 synthetic invalid transactions return code -32602,
    response size <= 4000 characters, and raw customer input values are NOT leaked.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        secret_marker = "CUSTOMER_SECRET_TAX_ID_99999"
        # 600 invalid items with non-numeric amount containing marker
        bad_transactions = [
            {
                "booking_date": "2026-03-01",
                "amount": f"INVALID_{secret_marker}_{i}",  # type mismatch: string instead of number
                "currency": "EUR",
                "description": f"Test transaction {i}"
            }
            for i in range(600)
        ]

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "err-test-1",
            "params": {
                "name": "convert_statement",
                "arguments": {
                    "bank_name": "Test Bank",
                    "transactions": bad_transactions
                }
            }
        }

        resp = await ac.post("/api/v1/mcp", json=payload)
        assert resp.status_code == 400
        data = resp.json()
        assert data["id"] == "err-test-1"
        assert data["error"]["code"] == -32602  # Invalid params
        error_msg = data["error"]["message"]

        # 1. Size budget check (must be well under 8000 chars)
        assert len(error_msg) < 4000

        # 2. No leakage of raw customer input values
        assert secret_marker not in error_msg

        # 3. Truncation notice present
        assert "Validierungsfehler" in error_msg
        assert "weitere Validierungsfehler abgeschnitten" in error_msg


@pytest.mark.asyncio
async def test_mcp_financial_summary_mapping_r58_3():
    """
    Verify R58-3: MCP accurately reports non-zero financial values:
    2 rows: -189.50 and +3400.00 EUR -> net balance +3210.50 EUR.
    Also verifies DATEV vs BMD distinctions and privacy disclosures.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # A. Test DATEV format
        payload_datev = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "call-datev",
            "params": {
                "name": "convert_statement",
                "arguments": {
                    "bank_name": "Sparkasse",
                    "export_format": "datev",
                    "session_id": "test_sess_datev_58",
                    "transactions": [
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
                }
            }
        }
        resp_datev = await ac.post("/api/v1/mcp", json=payload_datev)
        assert resp_datev.status_code == 200
        text_datev = resp_datev.json()["result"]["content"][0]["text"]

        # Verify accurate non-zero values
        assert "- **Buchungszeilen:** 2" in text_datev
        assert "- **Abflüsse (Ausgaben):** -189.50 EUR" in text_datev
        assert "- **Zuflüsse (Einnahmen):** 3400.00 EUR" in text_datev
        assert "- **Saldo (Periodensaldo):** +3210.50 EUR" in text_datev
        assert "- **Zeitraum:** 2026-03-01 bis 2026-03-15" in text_datev

        # Verify DATEV export button & instructions
        assert "DATEV EXTF 700 Buchungsstapel herunterladen" in text_datev
        assert "DATEV Import-Anleitung:" in text_datev
        assert "TTL 1800s" in text_datev

        # B. Test BMD format
        payload_bmd = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "call-bmd",
            "params": {
                "name": "convert_statement",
                "arguments": {
                    "bank_name": "Erste Bank",
                    "export_format": "bmd",
                    "default_bank_account": "2800",
                    "session_id": "test_sess_bmd_58",
                    "transactions": [
                        {
                            "booking_date": "2026-04-01",
                            "amount": -50.00,
                            "currency": "EUR",
                            "description": "Software Lizenz"
                        }
                    ]
                }
            }
        }
        resp_bmd = await ac.post("/api/v1/mcp", json=payload_bmd)
        assert resp_bmd.status_code == 200
        text_bmd = resp_bmd.json()["result"]["content"][0]["text"]
        assert "BMD NTCS 5.1 Buchungsstapel herunterladen" in text_bmd
        assert "BMD NTCS Import-Anleitung:" in text_bmd


@pytest.mark.asyncio
async def test_mcp_replay_contract_r58_4():
    """
    Verify R58-4: Replay with stable request_id returns identical download link
    without duplicate processing, and payload mismatch triggers HTTP 409 Conflict.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        op_id = "test-replay-op-2026-09-26"
        txs = [
            {
                "booking_date": "2026-03-10",
                "amount": -99.90,
                "currency": "EUR",
                "description": "Adobe Creative Cloud"
            }
        ]

        # Call A: Initial conversion
        payload_a = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "req-a",
            "params": {
                "name": "convert_statement",
                "arguments": {
                    "request_id": op_id,
                    "bank_name": "Wise Bank",
                    "transactions": txs
                }
            }
        }
        resp_a = await ac.post("/api/v1/mcp", json=payload_a)
        assert resp_a.status_code == 200
        text_a = resp_a.json()["result"]["content"][0]["text"]
        assert "Wise Bank Auszug erfolgreich konvertiert" in text_a

        # Call Replay: Exactly identical request_id and payload -> Clean replay hit
        payload_replay = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "req-replay",
            "params": {
                "name": "convert_statement",
                "arguments": {
                    "request_id": op_id,
                    "bank_name": "Wise Bank",
                    "transactions": txs
                }
            }
        }
        resp_replay = await ac.post("/api/v1/mcp", json=payload_replay)
        assert resp_replay.status_code == 200
        text_replay = resp_replay.json()["result"]["content"][0]["text"]
        # Must return the identical text and download link
        assert text_a == text_replay

        # Call Conflict: Same request_id, but altered payload (different amount)
        payload_conflict = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "req-conflict",
            "params": {
                "name": "convert_statement",
                "arguments": {
                    "request_id": op_id,
                    "bank_name": "Wise Bank",
                    "transactions": [
                        {
                            "booking_date": "2026-03-10",
                            "amount": -500.00,  # Changed amount
                            "currency": "EUR",
                            "description": "Adobe Creative Cloud"
                        }
                    ]
                }
            }
        }
        resp_conflict = await ac.post("/api/v1/mcp", json=payload_conflict)
        assert resp_conflict.status_code == 409
        assert resp_conflict.json()["error"]["code"] == -32602
        assert "different request payload" in resp_conflict.json()["error"]["message"]
