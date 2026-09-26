"""
OpenAI Plugin Manifest & Model Context Protocol (MCP) Server Endpoint for Statement2Muster.

Complies with:
- OpenAI Plugin Manifest Specification & .codex-plugin packaging (2026 guidelines)
- Model Context Protocol (MCP) JSON-RPC 2.0 specification (protocolVersion: 2024-11-05 / Streamable HTTP)
- Zero Durable Storage & In-Memory processing standards (Architect G07 / ADR-001)
- Chief Architect Decision 58 remediations (R58-1, R58-2, R58-3, R58-4, R58-5, R58-6)
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
import pydantic
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
# 1. OPENAI PLUGIN MANIFEST & MCP DISCOVERY MANIFESTS
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
            "(American Express, Wise, PayPal, Stripe, Sparkasse, Deutsche Bank etc.) in "
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


@router.get("/.well-known/mcp.json", include_in_schema=False)
@router.get("/mcp.json", include_in_schema=False)
async def get_mcp_discovery_manifest():
    """Serves modern MCP discovery manifest."""
    return JSONResponse(
        content={
            "mcpServers": {
                "statement2muster": {
                    "url": "https://api.statement2muster.com/api/v1/mcp",
                    "protocolVersion": "2024-11-05"
                }
            }
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600"
        }
    )


# ==============================================================================
# 2. MODEL CONTEXT PROTOCOL (MCP) TOOL SPECIFICATION (R58-3, R58-4)
# ==============================================================================

MCP_PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-06-18", "2025-03-26")

MCP_TOOL_CONVERT_STATEMENT = {
    "name": "convert_statement",
    "description": (
        "Konvertiert extrahierte Transaktionsdaten eines Bank- oder Kreditkartenauszugs "
        "in DATEV EXTF 700 oder BMD NTCS 5.1 Buchungsstapel inklusive Saldenabstimmung "
        "und direktem Download-Link (Zero Durable Storage, 30 Min. flüchtiger RAM-Speicher)."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["bank_name", "transactions"],
        "properties": {
            "request_id": {
                "type": "string",
                "maxLength": 100,
                "description": (
                    "Eindeutige Operations- / Idempotenz-ID des Clients (z. B. 'req-amex-2026-03'). "
                    "Bei unverändertem Payload und identischer request_id wird das bereits erzeugte "
                    "Ergebnis ohne erneute Quota-Belastung zurückgegeben (Replay-Schutz)."
                )
            },
            "bank_name": {
                "type": "string",
                "maxLength": 100,
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
                "maxLength": 20,
                "pattern": "^[0-9]{3,9}$",
                "default": "1200",
                "description": "Sachkonto des Geldkontos (3-9 Ziffern, z. B. '1200' für SKR03, '1800' für SKR04, '2800' für BMD)"
            },
            "session_id": {
                "type": "string",
                "maxLength": 100,
                "description": "Optionale Sitzungs-ID zur Zählung des kostenlosen Demo-Kontingents (3 Test-Auszüge für anonyme Demo-Nutzer)"
            },
            "license_key": {
                "type": "string",
                "maxLength": 4096,
                "description": "Optionaler signierter Statement2Muster JWT Auth-Token zur Freischaltung von Starter/Pro/Lifetime-Tarifen (sofern kein Authorization: Bearer Header gesendet wird)"
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
                            "maxLength": 20,
                            "description": "Buchungsdatum im Format YYYY-MM-DD oder DD.MM.YYYY"
                        },
                        "value_date": {
                            "type": "string",
                            "maxLength": 20,
                            "description": "Valutadatum (falls vorhanden, YYYY-MM-DD oder DD.MM.YYYY)"
                        },
                        "amount": {
                            "type": "number",
                            "description": "Vorzeichenbehafteter Betrag: Negativ für Lastschriften/Ausgaben (z. B. -49.90), Positiv für Gutschriften (z. B. 1250.00)"
                        },
                        "currency": {
                            "type": "string",
                            "maxLength": 10,
                            "default": "EUR",
                            "description": "Währungscode (z. B. 'EUR'). Alle Zeilen müssen dieselbe Währung haben."
                        },
                        "description": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 300,
                            "description": "Buchungstext oder Verwendungszweck (DATEV Buchungstext, max. 300 Zeichen)"
                        },
                        "reference": {
                            "type": "string",
                            "maxLength": 50,
                            "description": "Belegfeld 1 / Rechnungsnummer (max. 50 Zeichen)"
                        },
                        "contra_account": {
                            "type": "string",
                            "maxLength": 20,
                            "pattern": "^[0-9]{3,9}$",
                            "description": "Gegenkonto (3-9 Ziffern, z. B. '4900' für Reisekosten)"
                        }
                    }
                }
            }
        }
    }
}


# ==============================================================================
# 3. ERROR SANITIZATION (R58-2)
# ==============================================================================

def sanitize_pydantic_validation_error(exc: pydantic.ValidationError) -> str:
    """
    Sanitizes Pydantic ValidationError per Architect R58-2:
    - Never leaks customer financial values or raw input contents into errors or logs.
    - Limits to at most 5 items and caps output to <= 4,000 characters.
    """
    raw_errors = exc.errors()
    total_errors = len(raw_errors)
    formatted = []
    for err in raw_errors[:5]:
        loc = ".".join(str(p) for p in err.get("loc", []))
        msg = err.get("msg", "Ungültiger Wert")
        err_type = err.get("type", "value_error")
        formatted.append(f"- Parameter '{loc}': {msg} ({err_type})")

    if total_errors > 5:
        formatted.append(f"- ... und {total_errors - 5} weitere Validierungsfehler abgeschnitten.")

    summary = (
        f"Validierungsfehler in Eingabeparametern ({total_errors} Fehler gefunden):\n" +
        "\n".join(formatted)
    )
    if len(summary) > 4000:
        summary = summary[:3990] + "..."
    return summary


# ==============================================================================
# 4. RESPONSE FORMATTER (R58-3)
# ==============================================================================

def format_mcp_conversion_text(resp_data: Dict[str, Any], requested_bank: Optional[str] = None) -> str:
    """
    Formats conversion response dictionary into standard Markdown per Architect R58-3:
    - Maps canonical summary fields: transaction_count, total_debit, total_credit, net_balance, date_from, date_to.
    - Uses exact accounting terminology: Abflüsse (Ausgaben) / Zuflüsse (Einnahmen) / Saldo (Periodensaldo).
    - Distinct handling for DATEV EXTF 700 vs BMD NTCS 5.1.
    - Preserves RAM TTL disclosures and OpenAI privacy notes.
    - Removes unproven 'zertifizierte' claims.
    """
    resp_status = resp_data.get("status")
    if resp_status == "limit_reached":
        return (
            "⚠️ **Kostenloses Demo-Kontingent aufgebraucht**\n\n"
            f"Sie haben das kostenlose Kontingent ({MAX_FREE_CONVERSIONS} Test-Auszüge) für diese Session genutzt.\n\n"
            "**Verfügbare Tarife für erweiterte Nutzung:**\n"
            f"- **Starter (€4.90 / Monat):** [Hier buchen]({STRIPE_LINKS['starter']}) (20 Auszüge monatlich)\n"
            f"- **Business PRO (€29.00 / Monat):** [Hier buchen]({STRIPE_LINKS['pro']}) (Unbegrenzte Auszüge & Multi-Upload)\n"
            f"- **Lifetime License (€89.00 einmalig):** [Hier buchen]({STRIPE_LINKS['lifetime']}) (Einmalzahlung, dauerhaft unbegrenzt)\n\n"
            "Haben Sie bereits einen Account? Übergeben Sie Ihren Token im Feld `license_key`."
        )

    # Success formatting
    summary = resp_data.get("summary") or {}
    export_format = (resp_data.get("export_format") or "datev").lower()
    filename = resp_data.get("filename") or ("DATEV_Export.csv" if export_format == "datev" else "BMD_Export.csv")
    download_url = resp_data.get("download_url") or ""
    bank_title = requested_bank or "Bank"

    currency = summary.get("currency") or "EUR"
    tx_count = summary.get("transaction_count", 0)
    total_debit = float(summary.get("total_debit", 0.0))
    total_credit = float(summary.get("total_credit", 0.0))
    net_bal = float(summary.get("net_balance", 0.0))
    d_from = summary.get("date_from") or "N/A"
    d_to = summary.get("date_to") or "N/A"

    format_name = "BMD NTCS 5.1" if export_format == "bmd" else "DATEV EXTF 700"

    text_lines = [
        f"✅ **{bank_title} Auszug erfolgreich konvertiert!**",
        "",
        "### Finanz- & Saldenübersicht",
        f"- **Buchungszeilen:** {tx_count}",
        f"- **Abflüsse (Ausgaben):** {total_debit:.2f} {currency}",
        f"- **Zuflüsse (Einnahmen):** {total_credit:.2f} {currency}",
        f"- **Saldo (Periodensaldo):** {net_bal:+.2f} {currency}",
        f"- **Zeitraum:** {d_from} bis {d_to}",
        "",
        "### Download bereitgestellt",
        f"👉 **[📥 {format_name} Buchungsstapel herunterladen ({filename})]({download_url})**",
        ""
    ]

    # Target-specific accounting import instructions
    if export_format == "bmd":
        text_lines.append("**BMD NTCS Import-Anleitung:** Finanzen ➔ Buchungserfassung ➔ Extras ➔ Import / Export ➔ ASCII-Import ➔ BMD 5.1 Stapel einlesen.")
    else:
        text_lines.append("**DATEV Import-Anleitung:** Bestand ➔ Importieren ➔ Stapelverarbeitung ➔ ASCII-Import / DATEV-Format ➔ Datei einlesen.")

    text_lines.append("")

    # Notes (RAM TTL, Privacy boundary disclosures from resp_data.notes)
    notes = resp_data.get("notes") or []
    if notes:
        text_lines.append("### Sicherheit & Datenschutz")
        for note in notes:
            text_lines.append(f"- 🛡️ *{note}*")
    else:
        text_lines.append("### Sicherheit & Datenschutz")
        text_lines.append("- 🛡️ *Server-Zwischenspeicher (RAM-only): Der Download-Link verfällt nach 30 Minuten (TTL 1800s) aus dem flüchtigen Speicher.*")
        text_lines.append("- 🛡️ *Datenschutzhinweis: Im Chatverlauf angezeigte Daten verbleiben gemäß den Datenschutzeinstellungen Ihres KI-Kontos.*")

    return "\n".join(text_lines)


# ==============================================================================
# 5. MODEL CONTEXT PROTOCOL (MCP) JSON-RPC 2.0 HANDLER (R58-1, R58-2, R58-4, R58-5)
# ==============================================================================

@router.post("/api/v1/mcp", tags=["plugin_and_mcp"])
@router.post("/mcp", include_in_schema=False)
async def mcp_rpc_handler(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None)
):
    """
    Handles Model Context Protocol (MCP) JSON-RPC 2.0 requests with strict validation.
    Complies with:
    - Protocol header MCP-Protocol-Version validation (R58-5)
    - JSON-RPC envelope validation (jsonrpc == '2.0', params type validation) (R58-5)
    - Safe error sanitization without input leaks (R58-2)
    - Full idempotency replay via request_id (R58-4)
    - Early DoS budget enforcement via EarlyAuthAndBudgetMiddleware (R58-1)
    """
    # 0. Protocol version header check (R58-5)
    mcp_version_header = request.headers.get("mcp-protocol-version")
    if mcp_version_header and mcp_version_header not in SUPPORTED_PROTOCOL_VERSIONS:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": f"Unsupported MCP-Protocol-Version: '{mcp_version_header}'. Supported versions: {', '.join(SUPPORTED_PROTOCOL_VERSIONS)}"
                }
            }
        )

    # 1. Read and parse JSON body
    try:
        body_bytes = await request.body()
        if not body_bytes:
            payload = {}
        else:
            payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error: Invalid JSON payload"
                }
            }
        )

    # Envelope validation: must be a JSON dictionary
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: Request body must be a JSON object"
                }
            }
        )

    jsonrpc = payload.get("jsonrpc")
    req_id = payload.get("id")

    # Strict JSON-RPC 2.0 specification requirement (R58-5)
    if jsonrpc != "2.0":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32600,
                    "message": f"Invalid Request: 'jsonrpc' must be exactly '2.0', received '{jsonrpc}'"
                }
            }
        )

    method = payload.get("method")
    if not method or not isinstance(method, str):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: 'method' must be a non-empty string"
                }
            }
        )

    raw_params = payload.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": f"Invalid params: 'params' must be a JSON object/dictionary, received {type(raw_params).__name__}"
                }
            }
        )
    params = raw_params or {}

    # 2. Method: ping
    if method == "ping":
        return JSONResponse(content={"jsonrpc": "2.0", "id": req_id, "result": {}})

    # 3. Method: initialize
    if method == "initialize":
        negotiated_version = mcp_version_header if mcp_version_header in SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": negotiated_version,
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

    # 4. Method: notifications/initialized (MCP specification: 202 Accepted without body, R58-5)
    if method == "notifications/initialized":
        return Response(status_code=status.HTTP_202_ACCEPTED)

    # 5. Method: tools/list
    if method == "tools/list":
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [MCP_TOOL_CONVERT_STATEMENT]
                }
            }
        )

    # 6. Method: tools/call
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments")

        if not isinstance(arguments, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Invalid params: 'arguments' must be a JSON object/dictionary, received {type(arguments).__name__}"
                    }
                }
            )

        if tool_name != "convert_statement":
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "jsonrpc": "2.0",
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

            # Delegate to canonical gpt_convert_statement logic (handles replay cache, quota, RAM storage)
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

            formatted_markdown = format_mcp_conversion_text(resp_data, requested_bank=gpt_req.bank_name)
            is_err = resp_data.get("status") in ("limit_reached", "error")

            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
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

        except pydantic.ValidationError as val_err:
            # Architect R58-2: Never leak customer values to logs or responses; cap size <= 4,000 chars
            logger.warning("MCP tool validation error: %d parameter validation issues detected", len(val_err.errors()))
            safe_msg = sanitize_pydantic_validation_error(val_err)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,  # Invalid params
                        "message": safe_msg
                    }
                }
            )

        except HTTPException as he:
            # Handle conflict (409) or gone (410) or unprocessable (422) explicitly
            if he.status_code in (status.HTTP_409_CONFLICT, status.HTTP_410_GONE, status.HTTP_422_UNPROCESSABLE_ENTITY):
                return JSONResponse(
                    status_code=he.status_code,
                    content={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32602,
                            "message": str(he.detail)
                        }
                    }
                )
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
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
            # Architect R58-2: Unexpected errors return correlation ID, never raw trace or customer inputs
            err_correlation_id = uuid.uuid4().hex[:8]
            logger.error("MCP tool call unexpected error [%s]: %s", err_correlation_id, type(ex).__name__, exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Interner Verarbeitungsfehler (Referenz: {err_correlation_id})"
                    }
                }
            )

    # 7. Unknown JSON-RPC method
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Unknown JSON-RPC method: '{method}'"
            }
        }
    )


# ==============================================================================
# 6. STREAMABLE HTTP TRANSPORT & DIAGNOSTICS (R58-5)
# ==============================================================================

@router.get("/api/v1/mcp", tags=["plugin_and_mcp"])
@router.get("/mcp", include_in_schema=False)
async def mcp_get_not_allowed(request: Request):
    """
    Per Model Context Protocol (Streamable HTTP):
    Direct GET on MCP endpoint without active stream returns 405 Method Not Allowed.
    MCP commands use JSON-RPC 2.0 via POST /api/v1/mcp.
    For server diagnostics and capabilities, see GET /api/v1/mcp/status.
    """
    return JSONResponse(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        headers={"Allow": "POST, OPTIONS"},
        content={
            "jsonrpc": "2.0",
            "error": {
                "code": -32601,
                "message": "Method Not Allowed. MCP endpoint accepts JSON-RPC 2.0 via POST. Diagnostics available at GET /api/v1/mcp/status"
            }
        }
    )


@router.get("/api/v1/mcp/status", tags=["plugin_and_mcp"])
@router.get("/api/v1/mcp/health", tags=["plugin_and_mcp"])
async def mcp_status_diagnostic():
    """Returns general server capabilities, version, and metadata for monitoring."""
    return JSONResponse(
        content={
            "name": "statement2muster-mcp-server",
            "version": settings.VERSION,
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "supportedProtocolVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
            "description": "Statement2Muster Model Context Protocol (MCP) Server for DATEV and BMD statement conversion.",
            "tools": ["convert_statement"],
            "manifest_url": "https://api.statement2muster.com/.well-known/ai-plugin.json",
            "discovery_url": "https://api.statement2muster.com/.well-known/mcp.json"
        },
        headers={"Access-Control-Allow-Origin": "*"}
    )
