"""
OpenAI Plugin Manifest & Model Context Protocol (MCP) Server Endpoint for Statement2Muster.

Complies with:
- OpenAI Plugin Manifest Specification (2026 guidelines)
- Model Context Protocol (MCP) JSON-RPC 2.0 specification (protocolVersion: 2024-11-05)
- Zero Durable Storage & In-Memory processing standards (Architect G07 / ADR-001)
"""

import json
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.api.endpoints.gpt_action import (
    GptConvertRequest,
    GptConvertResponse,
    gpt_convert_statement,
    STRIPE_LINKS,
    MAX_FREE_CONVERSIONS
)

logger = logging.getLogger("statement2muster.mcp")

router = APIRouter(tags=["plugin_and_mcp"])


# ==============================================================================
# 1. OPENAI PLUGIN MANIFEST (/.well-known/ai-plugin.json)
# ==============================================================================

def build_plugin_manifest() -> Dict[str, Any]:
    """Generates canonical OpenAI Plugin manifest matching current environment."""
    return {
        "schema_version": "v1",
        "name_for_human": "Statement2Muster • DATEV & BMD Auszugskonverter",
        "name_for_model": "statement2muster",
        "description_for_human": (
            "Wandelt Kreditkarten- und Bankauszüge (Amex, Wise, PayPal, Sparkasse u.v.m.) "
            "in DATEV EXTF 700 & BMD NTCS 5.1 Buchungsstapel um."
        ),
        "description_for_model": (
            "Konvertiert vorstrukturierte Bank-, Kreditkarten- und Zahlungsdienstleisterauszüge "
            "(American Express, Wise, PayPal, Stripe, Sparkasse, Deutsche Bank etc.) in zertifizierte "
            "Buchungsstapel für Steuerberater und Buchhalter im DACH-Raum (DATEV EXTF 700 Windows-1252 ANSI "
            "oder BMD NTCS 5.1). Unterstützt Einzelkonten (SKR03/SKR04), periodengerechte Saldenabstimmung "
            "und Zero Durable Storage (flüchtige 30-Minuten-RAM-Verarbeitung)."
        ),
        "auth": {
            "type": "none"
        },
        "api": {
            "type": "openapi",
            "url": "https://api.statement2muster.com/openapi.json",
            "is_user_authenticated": False
        },
        "logo_url": "https://statement2muster.com/logo.png",
        "contact_email": "support@statement2muster.com",
        "legal_info_url": "https://statement2muster.com/datenschutz.html"
    }


@router.get("/.well-known/ai-plugin.json", include_in_schema=False)
@router.get("/ai-plugin.json", include_in_schema=False)
@router.get("/api/v1/plugin-manifest.json", tags=["plugin_and_mcp"])
async def get_ai_plugin_manifest():
    """Serves the official OpenAI Plugin Manifest."""
    return JSONResponse(
        content=build_plugin_manifest(),
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600"
        }
    )


# ==============================================================================
# 2. MODEL CONTEXT PROTOCOL (MCP) JSON-RPC 2.0 SERVER
# ==============================================================================

MCP_PROTOCOL_VERSION = "2024-11-05"

MCP_TOOL_CONVERT_STATEMENT = {
    "name": "convert_statement",
    "description": (
        "Konvertiert extrahierte Transaktionsdaten eines Bank- oder Kreditkartenauszugs "
        "in zertifizierte DATEV EXTF 700 oder BMD NTCS 5.1 Buchungsstapel inklusive Saldenabstimmung "
        "und direktem Download-Link (Zero Durable Storage, 30 Min. flüchtiger RAM-Speicher)."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["bank_name", "transactions"],
        "properties": {
            "bank_name": {
                "type": "string",
                "description": "Name des Finanzinstituts oder der Karte (z. B. 'American Express', 'Wise', 'PayPal', 'Sparkasse')"
            },
            "export_format": {
                "type": "string",
                "enum": ["datev", "bmd"],
                "default": "datev",
                "description": "Zielformat: 'datev' (Deutschland, EXTF 700) oder 'bmd' (Österreich, NTCS 5.1)"
            },
            "default_bank_account": {
                "type": "string",
                "default": "1200",
                "description": "Sachkonto des Geldkontos (z. B. '1200' für SKR03, '1800' für SKR04, '2800' für BMD)"
            },
            "session_id": {
                "type": "string",
                "description": "Optionale Sitzungs-ID zur Steuerung des kostenlosen Demo-Kontingents (3 Auszüge) und Idempotenz"
            },
            "license_key": {
                "type": "string",
                "description": "Optionaler Statement2Muster Auth-Token oder Lizenzschlüssel zur Freischaltung unbegrenzter Kontingente"
            },
            "transactions": {
                "type": "array",
                "description": "Liste der vorstrukturierten Buchungszeilen",
                "items": {
                    "type": "object",
                    "required": ["booking_date", "amount", "currency", "description"],
                    "properties": {
                        "booking_date": {
                            "type": "string",
                            "description": "Buchungsdatum im Format YYYY-MM-DD oder DD.MM.YYYY"
                        },
                        "value_date": {
                            "type": "string",
                            "description": "Valutadatum (falls vorhanden)"
                        },
                        "amount": {
                            "type": "number",
                            "description": "Vorzeichenbehafteter Betrag: Negativ für Lastschriften/Ausgaben (z. B. -49.90), Positiv für Gutschriften (z. B. 1250.00)"
                        },
                        "currency": {
                            "type": "string",
                            "description": "Währungscode (z. B. 'EUR'). Alle Zeilen müssen dieselbe Währung haben."
                        },
                        "description": {
                            "type": "string",
                            "description": "Buchungstext oder Verwendungszweck"
                        },
                        "reference": {
                            "type": "string",
                            "description": "Belegfeld 1 / Rechnungsnummer"
                        },
                        "contra_account": {
                            "type": "string",
                            "description": "Gegenkonto (z. B. '4900' für Reisekosten)"
                        }
                    }
                }
            }
        }
    }
}


class McpRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: Optional[Any] = None
    params: Optional[Dict[str, Any]] = None


def format_mcp_conversion_text(resp_data: Dict[str, Any]) -> str:
    """Formats conversion response dictionary into standard human- and model-readable Markdown."""
    resp_status = resp_data.get("status")
    if resp_status == "limit_reached":
        return (
            "⚠️ **Kostenloses Demo-Kontingent aufgebraucht**\n\n"
            f"Sie haben das kostenlose Kontingent ({MAX_FREE_CONVERSIONS} Test-Auszüge) für diese Session genutzt.\n\n"
            "**Verfügbare Tarife für unbegrenzte Nutzung:**\n"
            f"- **Starter (€4.90 / Monat):** [Hier buchen]({STRIPE_LINKS['starter']}) (20 Auszüge monatlich)\n"
            f"- **Business PRO (€29.00 / Monat):** [Hier buchen]({STRIPE_LINKS['business_pro']}) (Unbegrenzte Auszüge & Multi-Upload)\n"
            f"- **Lifetime License (€89.00 einmalig):** [Hier buchen]({STRIPE_LINKS['lifetime']})\n\n"
            "Haben Sie bereits einen Account? Übergeben Sie Ihren Token im Feld `license_key`."
        )

    # Success formatting
    summary = resp_data.get("financial_summary") or {}
    bank_name = resp_data.get("bank_name") or "Bank"
    filename = resp_data.get("filename") or "DATEV_Export.csv"
    download_url = resp_data.get("download_url") or ""
    currency = summary.get("currency") or "EUR"
    total_tx = summary.get("total_transactions", 0)
    total_debit = float(summary.get("total_debit", 0.0))
    total_credit = float(summary.get("total_credit", 0.0))
    net_bal = float(summary.get("net_balance", 0.0))
    earliest = summary.get("earliest_date") or "N/A"
    latest = summary.get("latest_date") or "N/A"

    text_lines = [
        f"✅ **{bank_name} Auszug erfolgreich konvertiert!**",
        "",
        "### Finanz- & Saldenübersicht",
        f"- **Buchungszeilen:** {total_tx}",
        f"- **Ausgaben (Soll):** {total_debit:.2f} {currency}",
        f"- **Einnahmen (Haben):** {total_credit:.2f} {currency}",
        f"- **Periodensaldo:** {net_bal:.2f} {currency}",
        f"- **Zeitraum:** {earliest} bis {latest}",
        "",
        "### Download bereitgestellt",
        f"👉 **[📥 DATEV EXTF Buchungsstapel herunterladen ({filename})]({download_url})**",
        "",
        "🛡️ *Zero Durable Storage: Die Exportdatei verfällt nach 30 Minuten (TTL 1800s) aus dem flüchtigen RAM-Speicher.*",
        "",
        "**DATEV Import-Anleitung:** Bestand ➔ Importieren ➔ Stapelverarbeitung ➔ ASCII-Import / DATEV-Format ➔ Datei einlesen."
    ]
    return "\n".join(text_lines)


@router.post("/api/v1/mcp", tags=["plugin_and_mcp"])
@router.post("/mcp", include_in_schema=False)
async def mcp_rpc_handler(
    payload: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None)
):
    """
    Handles Model Context Protocol (MCP) JSON-RPC 2.0 requests.
    Supports methods:
    - initialize
    - notifications/initialized
    - ping
    - tools/list
    - tools/call
    """
    jsonrpc = payload.get("jsonrpc", "2.0")
    method = payload.get("method")
    req_id = payload.get("id")
    params = payload.get("params") or {}

    # 1. ping
    if method == "ping":
        return JSONResponse(content={"jsonrpc": jsonrpc, "id": req_id, "result": {}})

    # 2. initialize
    if method == "initialize":
        return JSONResponse(
            content={
                "jsonrpc": jsonrpc,
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False
                        }
                    },
                    "serverInfo": {
                        "name": "statement2muster-mcp-server",
                        "version": settings.VERSION
                    }
                }
            }
        )

    # 3. notifications/initialized
    if method == "notifications/initialized":
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # 4. tools/list
    if method == "tools/list":
        return JSONResponse(
            content={
                "jsonrpc": jsonrpc,
                "id": req_id,
                "result": {
                    "tools": [MCP_TOOL_CONVERT_STATEMENT]
                }
            }
        )

    # 5. tools/call
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}

        if tool_name != "convert_statement":
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "jsonrpc": jsonrpc,
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method/Tool '{tool_name}' not found"
                    }
                }
            )

        try:
            # Parse arguments into canonical GptConvertRequest
            gpt_req = GptConvertRequest(**arguments)

            # Delegate to canonical gpt_convert_statement logic
            gpt_resp = await gpt_convert_statement(
                req=gpt_req,
                request=request,
                db=db
            )

            if isinstance(gpt_resp, Response):
                resp_data = json.loads(gpt_resp.body.decode("utf-8"))
            elif hasattr(gpt_resp, "model_dump"):
                resp_data = gpt_resp.model_dump()
            elif isinstance(gpt_resp, dict):
                resp_data = gpt_resp
            else:
                resp_data = dict(gpt_resp)

            formatted_markdown = format_mcp_conversion_text(resp_data)
            is_err = resp_data.get("status") in ("limit_reached", "error")

            return JSONResponse(
                content={
                    "jsonrpc": jsonrpc,
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": formatted_markdown
                            }
                        ],
                        "isError": is_err
                    }
                }
            )

        except HTTPException as he:
            return JSONResponse(
                content={
                    "jsonrpc": jsonrpc,
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"❌ Fehler bei der Konvertierung: {he.detail}"
                            }
                        ],
                        "isError": True
                    }
                }
            )
        except Exception as ex:
            logger.error(f"MCP tool call error: {ex}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "jsonrpc": jsonrpc,
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Internal server error: {str(ex)}"
                    }
                }
            )

    # Unknown method
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "jsonrpc": jsonrpc,
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Unknown JSON-RPC method: '{method}'"
            }
        }
    )


@router.get("/api/v1/mcp", tags=["plugin_and_mcp"])
@router.get("/mcp", include_in_schema=False)
async def mcp_status_get():
    """Returns general server capabilities and metadata for GET requests."""
    return JSONResponse(
        content={
            "name": "statement2muster-mcp-server",
            "version": settings.VERSION,
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "description": "Statement2Muster Model Context Protocol (MCP) Server for DATEV and BMD statement conversion.",
            "tools": ["convert_statement"],
            "manifest_url": "https://api.statement2muster.com/.well-known/ai-plugin.json"
        },
        headers={"Access-Control-Allow-Origin": "*"}
    )
