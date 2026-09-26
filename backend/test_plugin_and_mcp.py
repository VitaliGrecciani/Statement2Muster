"""
Unit & Integration Tests for OpenAI Plugin Manifest & MCP Server Endpoints.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_plugin_manifest_endpoint():
    """Verify /.well-known/ai-plugin.json adheres strictly to OpenAI 2026 specs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/.well-known/ai-plugin.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "v1"
        assert data["name_for_model"] == "statement2muster"
        assert "DATEV" in data["description_for_human"]
        assert data["auth"]["type"] == "none"
        assert "openapi.json" in data["api"]["url"]
        assert "statement2muster.com/logo.png" in data["logo_url"]
        assert "datenschutz.html" in data["legal_info_url"]

@pytest.mark.asyncio
async def test_mcp_get_status():
    """Verify GET /api/v1/mcp returns protocolVersion and tool metadata."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/mcp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["protocolVersion"] == "2024-11-05"
        assert "convert_statement" in data["tools"]

@pytest.mark.asyncio
async def test_mcp_rpc_initialize():
    """Verify MCP initialize method handshake."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {}
            }
        }
        resp = await ac.post("/api/v1/mcp", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["result"]["protocolVersion"] == "2024-11-05"
        assert "tools" in data["result"]["capabilities"]

@pytest.mark.asyncio
async def test_mcp_rpc_tools_list():
    """Verify MCP tools/list exposes convert_statement schema."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 2
        }
        resp = await ac.post("/api/v1/mcp", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        tools = data["result"]["tools"]
        assert len(tools) >= 1
        tool = next(t for t in tools if t["name"] == "convert_statement")
        assert "bank_name" in tool["inputSchema"]["properties"]
        assert "transactions" in tool["inputSchema"]["properties"]

@pytest.mark.asyncio
async def test_mcp_rpc_tools_call_success():
    """Verify MCP tools/call converts transactions and returns markdown summary + download link."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 3,
            "params": {
                "name": "convert_statement",
                "arguments": {
                    "bank_name": "American Express Business",
                    "export_format": "datev",
                    "default_bank_account": "1200",
                    "session_id": "test_mcp_sess_001",
                    "transactions": [
                        {
                            "booking_date": "2026-03-15",
                            "amount": -450.50,
                            "currency": "EUR",
                            "description": "Lufthansa Flugbuchung FRA-BER",
                            "reference": "LH-987654"
                        },
                        {
                            "booking_date": "2026-03-16",
                            "amount": 1200.00,
                            "currency": "EUR",
                            "description": "Kundenrückerstattung",
                            "reference": "REF-1122"
                        }
                    ]
                }
            }
        }
        resp = await ac.post("/api/v1/mcp", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 3
        result = data["result"]
        assert result["isError"] is False
        content_text = result["content"][0]["text"]
        assert "Auszug erfolgreich konvertiert" in content_text
        assert "DATEV EXTF Buchungsstapel herunterladen" in content_text
        assert "Zero Durable Storage" in content_text
