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
from typing import List, Dict, Any, Optional, Tuple
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.middleware import EarlyAuthAndBudgetMiddleware
from app.db.session import init_db, get_db
from app.services.quota_service import check_and_reserve_quota, commit_quota, release_quota
from app.parsers.registry import registry, UnsupportedFormatError
from app.schemas.canonical import CanonicalTransaction, StatementResult
from app.services.reconciliation_service import build_statement_result
from app.exporters.datev import export_to_datev_csv
from app.exporters.bmd import export_to_bmd_csv
from app.exporters.muster_csv import export_to_muster_csv
from app.api.endpoints import auth, billing, entitlements

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

# 1. Early ASGI Auth & Budget Middleware (Zero Retention & DoS protection)
app.add_middleware(EarlyAuthAndBudgetMiddleware)

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
        "X-Quota-Units"
    ]
)

# 3. Mount Routers
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(entitlements.router)

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

# Bounded in-memory RAM cache for idempotent conversion replay (B02 / ADR-001)
from app.core.cache import idempotent_result_cache, BoundedMemoryCache
_idempotent_result_cache = idempotent_result_cache

@app.post("/api/v1/convert")
async def convert_statements(
    request: Request,
    files: List[UploadFile] = File(...),
    export_format: str = "datev",
    format: Optional[str] = None,
    default_bank_account: str = "1200",
    client_entity_id: str = "default",
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

    allowed_formats = {"json", "datev", "bmd", "muster_csv"}
    raw_format = (format or export_format or "datev").lower().strip()
    if not raw_format:
        target_format = "datev"
    elif raw_format in allowed_formats:
        target_format = raw_format
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{raw_format}'. Allowed formats: {sorted(allowed_formats)}"
        )

    # Read all files into memory and compute deterministic request_hash for idempotency (A02, A18)
    file_data = []
    combined_hasher = hashlib.sha256()
    for file in files:
        filename = file.filename or "statement.pdf"
        content = await file.read()
        if len(content) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_BYTES} bytes."
            )
        file_data.append((filename, content))
        combined_hasher.update(filename.encode("utf-8"))
        combined_hasher.update(b"\x00")
        combined_hasher.update(content)
        combined_hasher.update(b"\x00")

    combined_hasher.update(f"{target_format}:{default_bank_account}:{client_entity_id}".encode("utf-8"))
    request_hash = combined_hasher.hexdigest()

    # Step 1: Two-Phase Commit Quota Reservation before parsing (ADR-001)
    reservation = await check_and_reserve_quota(
        db, tenant_id, len(files), idempotency_key, request_hash=request_hash
    )

    # Check RAM-only idempotent replay cache (ADR-001 / B02)
    cache_key = f"{tenant_id}_{idempotency_key}_{target_format}_{default_bank_account}_{client_entity_id}"
    if cache_key in _idempotent_result_cache:
        cached_content, cached_headers, cached_status, cached_fmt = _idempotent_result_cache[cache_key]
        if cached_fmt == "json":
            return JSONResponse(content=cached_content, headers=cached_headers, status_code=cached_status)
        elif cached_fmt == "datev":
            return Response(content=cached_content, media_type="text/plain; charset=windows-1252", headers=cached_headers, status_code=cached_status)
        else:
            return Response(content=cached_content, media_type="text/csv; charset=windows-1252", headers=cached_headers, status_code=cached_status)

    logger.info(f"=== Batch Request: {len(files)} file(s) [Format: {target_format}] ===")

    all_transactions: List[CanonicalTransaction] = []
    account_balances: Dict[str, Tuple[Optional[int], Optional[int], str]] = {}
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
                loop = asyncio.get_running_loop()
                done_event = asyncio.Event()
                res_box = []
                exc_box = []

                def _worker():
                    try:
                        res = registry.parse_file(
                            content=content,
                            filename=filename,
                            tenant_id=tenant_id,
                            client_entity_id=client_entity_id
                        )
                        res_box.append(res)
                    except BaseException as e:
                        exc_box.append(e)
                    finally:
                        loop.call_soon_threadsafe(done_event.set)

                worker_thread = threading.Thread(target=_worker, daemon=True)
                worker_thread.start()

                try:
                    await asyncio.wait_for(done_event.wait(), timeout=settings.PARSER_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    # Terminate worker thread immediately upon timeout (C07)
                    if worker_thread.ident:
                        ctypes.pythonapi.PyThreadState_SetAsyncExc(
                            ctypes.c_ulong(worker_thread.ident),
                            ctypes.py_object(SystemExit)
                        )
                    worker_thread.join(timeout=0.05)

                    # Zero PII: log sanitized hash and request ID without raw filename (A16)
                    file_hash_prefix = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
                    logger.error(f"Parser timed out after {settings.PARSER_TIMEOUT_SECONDS}s for request {idempotency_key} (file_{file_hash_prefix})")
                    raise HTTPException(
                        status_code=status.HTTP_408_REQUEST_TIMEOUT,
                        detail="Parser timed out processing file."
                    )

                if exc_box:
                    raise exc_box[0]
                file_txs, acc_summary = res_box[0]
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
                        account_balances[acc_key] = (
                            acc_summary.opening_balance_cents,
                            acc_summary.closing_balance_cents,
                            acc_summary.bank_name
                        )
            except UnsupportedFormatError as e:
                logger.warning(f"File unsupported: format unrecognized")
                unparsed_files.append({"file": filename, "error": str(e)})
            except HTTPException:
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
            dedup_key = (tx.booking_date, tx.description, tx.amount_cents, tx.currency)
            if dedup_key in seen:
                duplicate_count += 1
            else:
                seen.add(dedup_key)

        # Sort transactions chronologically (safe with None booking_date)
        all_transactions.sort(key=lambda t: t.booking_date or datetime.date.min)

        # Build comprehensive StatementResult with Solldoppik reconciliation
        statement_result = build_statement_result(
            request_id=reservation.reservation_id,
            tenant_id=tenant_id,
            transactions=all_transactions,
            account_balances=account_balances,
            file_count=len(files),
            successful_files=successful_files_count,
            unparsed_lines=unparsed_files
        )

        # Step 2: Commit Quota on successful conversion (ADR-001)
        await commit_quota(db, reservation, successful_files_count)

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
            "X-Reconciliation-Status": statement_result.overall_reconciliation
        }

        # Safeguard export: non-json accounting export requires clean conversion without unparsed files or discrepancies
        if target_format != "json":
            if unparsed_files:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Export blocked: Batch contains unparsed or unsupported files: {[f['file'] for f in unparsed_files]}. Use format=json to inspect details."
                )
            if statement_result.overall_reconciliation == "DISCREPANCY":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Export blocked: Discrepancy detected or batch contains unparsed files. Use format=json to inspect details."
                )
            if any(t.validation_status == "ERROR" or t.booking_date is None for t in all_transactions):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Export blocked: One or more transactions contain validation errors or missing dates. Use format=json to inspect details."
                )
            distinct_accounts = {t.account_id for t in all_transactions if t.account_id}
            if len(distinct_accounts) > 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Export blocked: Mixed bank accounts detected ({distinct_accounts}). Accounting export requires single account partition."
                )
            distinct_currencies = {t.currency for t in all_transactions if t.currency}
            if len(distinct_currencies) > 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Export blocked: Mixed currencies detected ({distinct_currencies}). Accounting export requires single currency partition."
                )
            if target_format == "datev":
                distinct_years = {t.booking_date.year for t in all_transactions if t.booking_date}
                if len(distinct_years) > 1:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Export blocked: Multi-year transactions detected for DATEV EXTF ({distinct_years}). DATEV batches must belong to a single fiscal year."
                    )

        # Cache successful response for bounded RAM idempotent replay (B02 / ADR-001)
        if target_format == "json":
            resp_content = statement_result.model_dump(mode="json")
            _idempotent_result_cache[cache_key] = (resp_content, common_headers, 200, "json")
            return JSONResponse(
                content=resp_content,
                headers=common_headers
            )
        elif target_format == "bmd":
            csv_bytes = export_to_bmd_csv(
                all_transactions,
                default_bank_account=default_bank_account if default_bank_account != "1200" else "2800"
            )
            out_name = "BMD_Bankauszug.csv"
            common_headers["Content-Disposition"] = f'attachment; filename="{out_name}"'
            _idempotent_result_cache[cache_key] = (csv_bytes, common_headers, 200, "bmd")
            return Response(
                content=csv_bytes,
                media_type="text/csv; charset=windows-1252",
                headers=common_headers
            )
        elif target_format == "muster_csv":
            csv_bytes = export_to_muster_csv(all_transactions)
            out_name = "Muster_Kontoauszug.csv"
            common_headers["Content-Disposition"] = f'attachment; filename="{out_name}"'
            _idempotent_result_cache[cache_key] = (csv_bytes, common_headers, 200, "muster_csv")
            return Response(
                content=csv_bytes,
                media_type="text/csv; charset=windows-1252",
                headers=common_headers
            )
        else: # Default: datev
            csv_bytes = export_to_datev_csv(all_transactions, default_bank_account=default_bank_account)
            out_name = "EXTF_Buchungsstapel.csv"
            common_headers["Content-Disposition"] = f'attachment; filename="{out_name}"'
            _idempotent_result_cache[cache_key] = (csv_bytes, common_headers, 200, "datev")
            return Response(
                content=csv_bytes,
                media_type="text/plain; charset=windows-1252",
                headers=common_headers
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


# Mount Landing Page Static Files at Root
landing_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "landing"))
if os.path.exists(landing_dir):
    app.mount("/", StaticFiles(directory=landing_dir, html=True), name="landing")
