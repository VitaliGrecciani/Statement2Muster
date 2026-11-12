import io
import json
import logging
import os
import uuid
import hashlib
import datetime
import asyncio
import threading
import ctypes
import time
from typing import List, Dict, Any, Optional, Tuple
from contextlib import asynccontextmanager
import multiprocessing




import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends, Header, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.middleware import EarlyAuthAndBudgetMiddleware
from app.core.security import get_current_tenant
from app.db.session import init_db, get_db
from app.services.quota_service import check_and_reserve_quota, commit_quota, release_quota
from app.parsers.registry import registry, UnsupportedFormatError
from app.schemas.canonical import CanonicalTransaction, StatementResult
from app.services.reconciliation_service import build_statement_result
from app.exporters.formats import (
    normalize_format_key,
    get_format_spec,
    compute_export_blocks,
    validate_accounting_export,
    validate_account_code,
    render_export_bytes,
)
from app.services.parser_process_supervisor import parser_supervisor
from app.api.endpoints import auth, billing, entitlements, gpt, gpt_action, plugin_and_mcp, social_auth, kanzlei_invites

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("statement2muster")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema on startup
    await init_db()
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

MAX_VALIDATION_ERRORS = 5

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    raw_errors = exc.errors()
    total_errors = len(raw_errors)
    errors = []
    for err in raw_errors[:MAX_VALIDATION_ERRORS]:
        err_copy = dict(err)
        if "input" in err_copy:
            val = err_copy["input"]
            if isinstance(val, (str, bytes)):
                val_str = str(val)
                if len(val_str) > 50:
                    err_copy["input"] = val_str[:47] + "..."
            elif isinstance(val, (list, dict)):
                err_copy["input"] = "[Complex object truncated]"
        errors.append(err_copy)

    if total_errors > MAX_VALIDATION_ERRORS:
        errors.append({
            "loc": ["body"],
            "msg": f"{total_errors - MAX_VALIDATION_ERRORS} weitere Validierungsfehler wurden abgeschnitten (Gesamtanzahl: {total_errors}).",
            "type": "too_many_errors"
        })

    resp_data = {"detail": errors}
    encoded_json = json.dumps(resp_data, ensure_ascii=False)
    # Architect F03: Hard platform limit check (OpenAI action limit is 100k, we keep under 8k chars)
    if len(encoded_json) > 8000:
        resp_data = {
            "detail": [
                {
                    "loc": ["body"],
                    "msg": f"Anfrage enthält {total_errors} Validierungsfehler. Details wurden zur Einhaltung des Größenlimits gekürzt.",
                    "type": "too_many_errors"
                }
            ]
        }
        encoded_json = json.dumps(resp_data, ensure_ascii=False)

    return Response(
        content=encoded_json,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        media_type="application/json"
    )

# 1. Early ASGI Auth & Budget Middleware (Zero Retention & DoS protection)
app.add_middleware(EarlyAuthAndBudgetMiddleware)

# Short-lived signed state cookie for browser OAuth authorization code flows.
from app.core.security import _PRIV_KEY
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.OAUTH_SESSION_SECRET or hashlib.sha256(_PRIV_KEY).hexdigest(),
    same_site="lax",
    https_only=settings.ENVIRONMENT.lower() == "production",
    max_age=600,
)

# 2. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Mixed-Accounts",
        "X-Accounts-Found",
        "X-Duplicates-Count",
        "X-Reconciliation-Status",
        "Content-Disposition",
        "X-Reservation-Id",
        "X-Quota-Units",
        "X-Operation-Id",
        "X-Export-Eligible"
    ]
)

# 3. Mount Routers
app.include_router(auth.router)
app.include_router(social_auth.router)
app.include_router(kanzlei_invites.router)
app.include_router(billing.router)
app.include_router(entitlements.router)
app.include_router(gpt.router)
app.include_router(plugin_and_mcp.router)

@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "message": "Statement2Muster API is running", "version": settings.VERSION}

@app.get("/healthz")
@app.get("/api/v1/healthz")
async def healthz_check(db: AsyncSession = Depends(get_db)):
    """Kubernetes/Container liveness & readiness probe verifying DB connectivity and Zero-Retention status."""
    from sqlalchemy import text
    try:
        res = await db.execute(text("SELECT 1"))
        _ = res.scalar()
    except Exception as e:
        logger.error(f"Healthcheck DB failure: {e}")
        raise HTTPException(status_code=503, detail="Database unresponsive")

    return {
        "status": "healthy",
        "service": "statement2muster-api",
        "version": settings.VERSION,
        "database": "connected",
        "zero_retention": "enforced"
    }

@app.get("/auth/jwks.json", tags=["auth"])
@app.get("/.well-known/jwks.json", tags=["auth"])
async def jwks_endpoint():
    """Root and well-known aliases for RFC 7517 JWKS."""
    from app.core.security import get_jwks
    return get_jwks()

# Bounded in-memory RAM cache with ONE shared byte budget (R62-2 / R62-8)
from app.core.cache import idempotent_result_cache, BoundedMemoryCache, shared_ram_budget
_idempotent_result_cache = idempotent_result_cache
canonical_operation_cache = BoundedMemoryCache(
    ttl_seconds=settings.RAM_CACHE_TTL_SECONDS,
    max_bytes=settings.RAM_CACHE_MAX_BYTES,
    max_entries=settings.RAM_CACHE_MAX_ENTRIES,
    shared_budget=shared_ram_budget,
)

NO_STORE_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
}

@app.post("/api/v1/convert")
async def convert_statements(
    request: Request,
    files: List[UploadFile] = File(...),
    export_format: str = "datev",
    format: Optional[str] = None,
    target_format: Optional[str] = None,
    default_bank_account: str = "1200",
    client_entity_id: str = "default",
    use_valuta_as_booking_date: bool = False,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db)
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # EarlyAuthAndBudgetMiddleware has validated the Bearer token
    tenant_info = getattr(request.state, "tenant", None)
    if not tenant_info:
        raise HTTPException(status_code=401, detail="Authentication required")

    tenant_id = tenant_info.get("tenant_id")
    idempotency_key = x_idempotency_key or str(uuid.uuid4())

    # Validate bank account code early (R62-7)
    validated_bank_account = validate_account_code(default_bank_account, "default_bank_account", default="1200")

    # Allow optional overrides from multipart form fields if caller sent them in FormData
    try:
        form_data = await request.form()
    except Exception:
        form_data = {}
    form_format = form_data.get("format") or form_data.get("export_format")
    raw_format = format or form_format or export_format or "datev"
    requested_response_format = normalize_format_key(str(raw_format), default="datev")

    raw_target_format = target_format or form_data.get("target_format")
    accounting_target_format: Optional[str] = None
    if requested_response_format != "json":
        accounting_target_format = requested_response_format
    elif raw_target_format:
        norm_target = normalize_format_key(str(raw_target_format), default="datev")
        accounting_target_format = None if norm_target == "json" else norm_target

    raw_valuta_flag = form_data.get("use_valuta_as_booking_date")
    effective_use_valuta = bool(
        use_valuta_as_booking_date
        or (str(raw_valuta_flag).strip().lower() in ("1", "true", "yes", "on") if raw_valuta_flag is not None else False)
    )

    # Read all files into memory and compute deterministic request_hash for idempotency (A02, A18)
    file_data = []
    base_hasher = hashlib.sha256()
    for file in files:
        filename = file.filename or "statement.pdf"
        content = await file.read()
        if len(content) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_BYTES} bytes."
            )
        file_data.append((filename, content))
        base_hasher.update(filename.encode("utf-8"))
        base_hasher.update(b"\x00")
        base_hasher.update(content)
        base_hasher.update(b"\x00")

    v2_hasher = base_hasher.copy()
    v2_hasher.update(
        f"v2:{requested_response_format}:{accounting_target_format or ''}:{validated_bank_account}:{client_entity_id}:{effective_use_valuta}".encode("utf-8")
    )
    request_hash = v2_hasher.hexdigest()

    acceptable_hashes = [request_hash]
    if not raw_target_format:
        raw_fmt_clean = str(raw_format).lower().strip() or "datev"
        for legacy_fmt in {requested_response_format, raw_fmt_clean}:
            # Decision-61 hash format (before v2 + target_format)
            d61_h = base_hasher.copy()
            d61_h.update(f"{legacy_fmt}:{validated_bank_account}:{client_entity_id}:{effective_use_valuta}".encode("utf-8"))
            acceptable_hashes.append(d61_h.hexdigest())
            if not effective_use_valuta:
                # Pre-61 legacy ledger format (before use_valuta flag)
                leg_h = base_hasher.copy()
                leg_h.update(f"{legacy_fmt}:{validated_bank_account}:{client_entity_id}".encode("utf-8"))
                acceptable_hashes.append(leg_h.hexdigest())

    # Step 1: Two-Phase Commit Quota Reservation before parsing (ADR-001)
    reservation = await check_and_reserve_quota(
        db, tenant_id, len(files), idempotency_key,
        request_hash=request_hash,
        acceptable_hashes=acceptable_hashes,
    )

    cache_key = f"{tenant_id}_{idempotency_key}_{requested_response_format}_{accounting_target_format or ''}_{validated_bank_account}_{client_entity_id}_{effective_use_valuta}"

    # Strict Replay Handling for COMMITTED operations (R62-2): NEVER re-run parser or extend TTL!
    if reservation.status == "COMMITTED":
        idem_entry = _idempotent_result_cache.get(cache_key)
        if isinstance(idem_entry, tuple):
            cached_content, cached_headers, cached_status, cached_fmt = idem_entry
            hdrs = {**dict(cached_headers or {}), **NO_STORE_HEADERS}
            if cached_fmt == "json":
                return JSONResponse(content=cached_content, headers=hdrs, status_code=cached_status)
            spec = get_format_spec(cached_fmt)
            return Response(content=cached_content, media_type=spec.media_type, headers=hdrs, status_code=cached_status)

        if isinstance(idem_entry, dict):
            cached_op_id = idem_entry.get("operation_id")
            op_entry = canonical_operation_cache.get(cached_op_id) if cached_op_id else None
            if op_entry:
                hdrs = {**dict(op_entry.get("headers") or {}), **NO_STORE_HEADERS}
                if requested_response_format == "json":
                    return JSONResponse(content=op_entry["result"], headers=hdrs, status_code=200)
                result_obj = StatementResult.model_validate(op_entry["result"])
                validate_accounting_export(result_obj, requested_response_format)
                eff_acct = validated_bank_account or op_entry.get("default_bank_account") or "1200"
                ts_iso = op_entry.get("export_timestamp")
                op_ts = datetime.datetime.fromisoformat(ts_iso) if ts_iso else None
                csv_bytes = render_export_bytes(
                    result_obj.transactions,
                    requested_response_format,
                    default_bank_account=eff_acct,
                    export_timestamp=op_ts,
                )
                spec = get_format_spec(requested_response_format)
                hdrs["Content-Disposition"] = f'attachment; filename="{spec.filename}"'
                return Response(content=csv_bytes, media_type=spec.media_type, headers=hdrs, status_code=200)
            _idempotent_result_cache.delete(cache_key)

        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Konvertierungs-Ergebnis im RAM-Cache abgelaufen oder nicht mehr verfügbar (600s TTL / Zero-Retention). Bitte starten Sie eine neue Konvertierung.",
            headers=NO_STORE_HEADERS,
        )

    logger.info(f"=== Batch Request: {len(files)} file(s) [Format: {requested_response_format}, Target: {accounting_target_format}, ValutaMode: {effective_use_valuta}] ===")

    all_transactions: List[CanonicalTransaction] = []
    account_segments: Dict[str, List[Dict[str, Any]]] = {}
    account_warnings: Dict[str, List[str]] = {}
    successful_files_count = 0
    unparsed_files = []

    try:
        for file_idx, (filename, content) in enumerate(file_data):
            if not filename.lower().endswith(('.csv', '.pdf', '.txt')):
                unparsed_files.append({"file": filename, "error": f"Unsupported file extension for '{filename}'"})
                continue
            if not content:
                unparsed_files.append({"file": filename, "error": f"Empty file: '{filename}'"})
                continue

            logger.info(f"Parsing file {file_idx+1}/{len(file_data)}: {len(content)} bytes in-memory")

            try:
                file_txs, acc_summary = await parser_supervisor.parse_file(
                    content=content,
                    filename=filename,
                    tenant_id=tenant_id,
                    client_entity_id=client_entity_id,
                    timeout=float(settings.PARSER_TIMEOUT_SECONDS),
                    request_id=idempotency_key,
                    max_rows=settings.MAX_ROWS_PER_FILE,
                    use_valuta_as_booking_date=effective_use_valuta,
                )
                if file_txs:
                    if len(file_txs) > settings.MAX_ROWS_PER_FILE:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File '{filename}' exceeds maximum allowed limit of {settings.MAX_ROWS_PER_FILE} rows."
                        )
                    all_transactions.extend(file_txs)
                    successful_files_count += 1
                    if acc_summary:
                        acc_key = f"{acc_summary.client_entity_id}_{acc_summary.account_id}" if acc_summary.account_id else acc_summary.client_entity_id
                        account_segments.setdefault(acc_key, []).append({
                            "opening_cents": acc_summary.opening_balance_cents,
                            "closing_cents": acc_summary.closing_balance_cents,
                            "bank_name": acc_summary.bank_name,
                            "file": filename,
                            "txs": file_txs,
                            "order": file_idx,
                            "statement_numbers": list(acc_summary.statement_numbers or []),
                            "segment_fingerprint": acc_summary.segment_fingerprint,
                        })
                        if acc_summary.warnings:
                            existing_w = account_warnings.setdefault(acc_key, [])
                            for w in acc_summary.warnings:
                                if w not in existing_w:
                                    existing_w.append(w)
            except UnsupportedFormatError as e:
                logger.warning(f"File unsupported: format unrecognized")
                unparsed_files.append({"file": filename, "error": str(e)})
            except (HTTPException, asyncio.CancelledError):
                await release_quota(db, reservation)
                raise
            except Exception as e:
                logger.error(f"Error parsing file in memory", exc_info=True)
                unparsed_files.append({"file": filename, "error": "Internal parser error"})

        if not all_transactions:
            await release_quota(db, reservation)
            raise HTTPException(
                status_code=422,
                detail="Keine Buchungssätze in den bereitgestellten Dateien gefunden oder Formate werden nicht unterstützt."
            )

        # Deduplication check (non-destructive: keep all transactions, count duplicates)
        seen = set()
        duplicate_count = 0
        for tx in all_transactions:
            dedup_key = (tx.booking_date, tx.value_date, tx.description, tx.amount_cents, tx.currency)
            if dedup_key in seen:
                duplicate_count += 1
            else:
                seen.add(dedup_key)

        # Sort transactions chronologically (safe with None booking_date, fall back to value_date)
        all_transactions.sort(key=lambda t: (t.booking_date or t.value_date or datetime.date.min))

        # Build comprehensive StatementResult with Solldoppik reconciliation across multi-file segments
        statement_result = build_statement_result(
            request_id=reservation.reservation_id,
            tenant_id=tenant_id,
            transactions=all_transactions,
            account_balances=account_segments,
            file_count=len(files),
            successful_files=successful_files_count,
            unparsed_lines=unparsed_files,
            account_warnings=account_warnings,
        )

        operation_id = f"op_{uuid.uuid4().hex}"
        export_blocks = compute_export_blocks(
            statement_result,
            canonical_format=accounting_target_format,
        )
        statement_result.export_blocks = export_blocks
        statement_result.export_eligible = len(export_blocks) == 0

        # Accounts info for client
        accounts_list = [
            {"account_id": a.account_id, "name": a.bank_name, "count": a.transaction_count, "reconciliation": a.reconciliation_status}
            for a in statement_result.accounts.values()
        ]
        is_mixed = len(statement_result.accounts) > 1

        common_headers = {
            "X-Mixed-Accounts": "true" if is_mixed else "false",
            "X-Accounts-Found": json.dumps(accounts_list),
            "X-Duplicates-Count": str(duplicate_count),
            "X-Reservation-Id": reservation.reservation_id,
            "X-Quota-Units": str(successful_files_count),
            "X-Reconciliation-Status": statement_result.overall_reconciliation,
            "X-Operation-Id": operation_id,
            "X-Export-Eligible": "true" if statement_result.export_eligible else "false",
            **NO_STORE_HEADERS,
        }

        # Pre-commit Export Eligibility Gate (R62-1):
        # Neither CSV nor UI JSON conversion may charge quota or mint an operation_id when accounting export is blocked!
        if export_blocks:
            statement_result.operation_id = None
            await release_quota(db, reservation)
            blocked_headers = {
                **common_headers,
                "X-Quota-Units": "0",
                "X-Export-Eligible": "false",
            }
            blocked_headers.pop("X-Operation-Id", None)
            if requested_response_format == "json" and accounting_target_format is None:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content=statement_result.model_dump(mode="json"),
                    headers=blocked_headers,
                )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "detail": f"Export blocked: {' '.join(export_blocks)} Use format=json to inspect details.",
                    "export_blocks": export_blocks,
                    "result": statement_result.model_dump(mode="json"),
                },
                headers=blocked_headers,
            )

        # Safeguard accounting export & dry-run serialization BEFORE quota commit (R62-1 + R62-7 + R63-4)
        op_created_at = datetime.datetime.now()
        rendered_bytes: Optional[bytes] = None
        if accounting_target_format is not None:
            validate_accounting_export(statement_result, accounting_target_format)
            rendered_bytes = render_export_bytes(
                all_transactions,
                accounting_target_format,
                default_bank_account=validated_bank_account,
                export_timestamp=op_created_at,
            )
        else:
            # Verify serialization & contra_account validity even on bare format=json
            _ = render_export_bytes(
                all_transactions,
                "bmd",
                default_bank_account=validated_bank_account,
                export_timestamp=op_created_at,
            )

        statement_result.operation_id = operation_id
        resp_content = statement_result.model_dump(mode="json")

        # Atomically admit BOTH canonical operation & replay ref into shared-budget RAM cache BEFORE quota commit (R63-1)
        admitted = shared_ram_budget.admit_batch([
            (
                canonical_operation_cache,
                operation_id,
                {
                    "tenant_id": tenant_id,
                    "result": resp_content,
                    "headers": dict(common_headers),
                    "default_bank_account": validated_bank_account,
                    "export_timestamp": op_created_at.isoformat(),
                },
            ),
            (
                _idempotent_result_cache,
                cache_key,
                {"operation_id": operation_id, "target_format": requested_response_format},
            ),
        ])
        if not admitted:
            canonical_operation_cache.delete(operation_id)
            _idempotent_result_cache.delete(cache_key)
            await release_quota(db, reservation)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Konvertierungs-Ergebnis überschreitet das Arbeitsspeicher-Cache-Limit und kann nicht zur Formatumschaltung zwischengespeichert werden.",
                headers=NO_STORE_HEADERS,
            )

        # Step 2: Commit Quota ONLY AFTER validation, serialization, and RAM admission succeed!
        await commit_quota(db, reservation, successful_files_count)

        if requested_response_format == "json":
            return JSONResponse(
                content=resp_content,
                headers=common_headers,
            )

        spec = get_format_spec(requested_response_format)
        csv_headers = dict(common_headers)
        csv_headers["Content-Disposition"] = f'attachment; filename="{spec.filename}"'
        return Response(
            content=rendered_bytes,
            media_type=spec.media_type,
            headers=csv_headers,
        )

    except HTTPException:
        if reservation.status == "RESERVED":
            await release_quota(db, reservation)
        raise
    except Exception as e:
        logger.error(f"Unexpected conversion error: {e}", exc_info=True)
        if reservation.status == "RESERVED":
            await release_quota(db, reservation)
        raise HTTPException(status_code=500, detail="Internal conversion error")


@app.get("/api/v1/operations/{operation_id}/export")
async def export_cached_operation(
    operation_id: str,
    format: str = Query("datev"),
    default_bank_account: Optional[str] = Query(None),
    tenant_info: Dict[str, Any] = Depends(get_current_tenant),
):
    """
    Re-exports an already converted canonical batch in another target format
    without re-uploading files or deducting quota again (ephemeral 600s RAM cache).
    """
    target_format = normalize_format_key(format, default="datev")
    if default_bank_account is not None:
        validate_account_code(default_bank_account, "default_bank_account")

    op_entry = canonical_operation_cache.get(operation_id)
    if not op_entry:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Operation abgelaufen oder im Arbeitsspeicher nicht mehr vorhanden (600s TTL). Bitte Datei erneut konvertieren.",
            headers=NO_STORE_HEADERS,
        )

    if op_entry.get("tenant_id") != tenant_info.get("tenant_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Zugriff auf diese Konvertierungs-Operation verweigert.",
            headers=NO_STORE_HEADERS,
        )

    result_obj = StatementResult.model_validate(op_entry["result"])
    base_headers = {**dict(op_entry.get("headers") or {}), **NO_STORE_HEADERS}

    if target_format == "json":
        return JSONResponse(content=op_entry["result"], headers=base_headers)

    validate_accounting_export(result_obj, target_format)
    spec = get_format_spec(target_format)
    eff_bank_acct = validate_account_code(
        default_bank_account if default_bank_account is not None else op_entry.get("default_bank_account"),
        "default_bank_account",
        default="1200",
    )
    ts_iso = op_entry.get("export_timestamp")
    op_ts = datetime.datetime.fromisoformat(ts_iso) if ts_iso else None
    rendered_bytes = render_export_bytes(
        result_obj.transactions,
        target_format,
        default_bank_account=eff_bank_acct,
        export_timestamp=op_ts,
    )
    out_headers = dict(base_headers)
    out_headers["Content-Disposition"] = f'attachment; filename="{spec.filename}"'
    return Response(
        content=rendered_bytes,
        media_type=spec.media_type,
        headers=out_headers,
    )


# Mount Landing Page Static Files at Root
landing_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "landing"))
if os.path.exists(landing_dir):
    app.mount("/", StaticFiles(directory=landing_dir, html=True), name="landing")
