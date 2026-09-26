import io
import re
import uuid
import base64
import datetime
import logging
import threading
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal, Tuple
from fastapi import APIRouter, HTTPException, Request, Response, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.core.config import settings
from app.core.cache import BoundedMemoryCache
from app.core.security import decode_access_token
from app.db.session import get_db
from app.db.models import Tenant, Entitlement, UsageReservation
from app.services.quota_service import check_and_reserve_quota, commit_quota, release_quota
from app.schemas.canonical import CanonicalTransaction
from app.exporters.datev import export_to_datev_csv
from app.exporters.bmd import export_to_bmd_csv
from app.exporters.muster_csv import export_to_muster_csv
from app.services.parser_process_supervisor import parser_supervisor
from app.parsers.registry import UnsupportedFormatError

logger = logging.getLogger("statement2muster.gpt_action")

router = APIRouter(tags=["gpt-action"])

# Dedicated volatile in-memory cache for ChatGPT download links (Zero Durable Retention)
# TTL = 30 minutes (1800s), budget = 30 MiB, max 300 files
gpt_download_cache = BoundedMemoryCache(
    ttl_seconds=1800,
    max_bytes=30 * 1024 * 1024,
    max_entries=300
)

# In-memory free tier usage tracker for anonymous demo sessions
# Thread-safe with atomic locking to prevent concurrent race condition bypasses (G02)
gpt_free_tier_tracker = BoundedMemoryCache(
    ttl_seconds=86400 * 30,
    max_bytes=5 * 1024 * 1024,
    max_entries=10000
)
_anon_quota_lock = threading.Lock()

# Standard verified Stripe pricing checkout links
STRIPE_LINKS = {
    "starter": "https://buy.stripe.com/cNi6oH9vDcnL2v0dWTebu03",
    "pro": "https://buy.stripe.com/14AfZh6jr2NbedI6urebu04",
    "lifetime": "https://buy.stripe.com/14A00j6jrfzX2v0bOLebu05"
}

MAX_FREE_CONVERSIONS = 3


def parse_strict_date(date_str: Optional[str], field_name: str = "booking_date", row_idx: int = 0) -> datetime.date:
    """
    Parses dates strictly without silent fallback to today() (Architect G05).
    Raises HTTP 422 if date is missing or invalid.
    """
    if not date_str or not isinstance(date_str, str) or not date_str.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Fehlendes Datum für '{field_name}' in Zeile {row_idx + 1}."
        )
    cleaned = date_str.strip()
    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%d.%m.%y",
        "%d/%m/%y"
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Ungültiges Datumsformat '{cleaned}' für '{field_name}' in Zeile {row_idx + 1}. Erwartet wird YYYY-MM-DD oder DD.MM.YYYY."
    )


def normalize_currency(curr: Optional[str]) -> str:
    """Normalizes currency symbols to ISO 4217 standard."""
    if not curr:
        return "EUR"
    c = curr.strip().upper()
    if c in ("€", "EUR", "EURO"):
        return "EUR"
    if c in ("$", "USD", "DOLLAR"):
        return "USD"
    if c in ("£", "GBP"):
        return "GBP"
    if c in ("CHF", "FR"):
        return "CHF"
    return c[:3] if len(c) >= 3 else "EUR"


def parse_amount_to_cents(amt_val: Any) -> int:
    """Robust conversion of float/int/str amounts to integer cents avoiding floating-point drift."""
    if isinstance(amt_val, int):
        return amt_val * 100
    if isinstance(amt_val, float):
        return int(round(Decimal(str(amt_val)) * 100))
    
    val_str = str(amt_val).strip()
    is_negative = False
    upper = val_str.upper()
    if upper.startswith('-') or upper.endswith('-') or upper.endswith('S'):
        is_negative = True
        val_str = re.sub(r'[\-sS]', '', val_str)
    elif upper.startswith('+') or upper.endswith('+') or upper.endswith('H'):
        is_negative = False
        val_str = re.sub(r'[\+hH]', '', val_str)

    cleaned = re.sub(r'[^\d,\.]', '', val_str).strip()
    if not cleaned:
        return 0

    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        cleaned = cleaned.replace(',', '.')

    try:
        dec = Decimal(cleaned)
        cents = int(round(dec * 100))
        return -cents if is_negative else cents
    except Exception:
        return 0


# --- Request / Response Models ---

class GptTransactionItem(BaseModel):
    booking_date: str = Field(
        ...,
        description="Booking date in ISO YYYY-MM-DD or DD.MM.YYYY format",
        json_schema_extra={"example": "2026-03-15"}
    )
    value_date: Optional[str] = Field(
        None,
        description="Optional valuta/value date (YYYY-MM-DD or DD.MM.YYYY)",
        json_schema_extra={"example": "2026-03-16"}
    )
    amount: float = Field(
        ...,
        description="Transaction amount. Negative for expense/debit (Lastschrift), positive for revenue/credit (Gutschrift)",
        json_schema_extra={"example": -145.20}
    )
    currency: Optional[str] = Field(
        "EUR",
        description="ISO 4217 currency code (e.g. EUR, USD, CHF, GBP)",
        json_schema_extra={"example": "EUR"}
    )
    description: str = Field(
        ...,
        description="Transaction description, payee, or payment purpose (DATEV Buchungstext)",
        json_schema_extra={"example": "AWS EMEA SARL Cloud Services"}
    )
    reference: Optional[str] = Field(
        None,
        description="Invoice, voucher or reference ID (DATEV Belegfeld 1)",
        json_schema_extra={"example": "INV-2026-98102"}
    )
    contra_account: Optional[str] = Field(
        None,
        description="Optional pre-assigned bookkeeping contra account / Gegenkonto (e.g. '4900' for SKR03, '6800' for SKR04)",
        json_schema_extra={"example": "4900"}
    )


class GptConvertRequest(BaseModel):
    session_id: Optional[str] = Field(
        None,
        description="Optional ChatGPT conversation or session identifier to track demo usage",
        json_schema_extra={"example": "chatgpt-sess-88123"}
    )
    email: Optional[str] = Field(
        None,
        description="Optional user email. Note: Paid rights require authentication via Bearer token or signed token in license_key.",
        json_schema_extra={"example": "founder@startup.de"}
    )
    license_key: Optional[str] = Field(
        None,
        description="Optional signed JWT access token or API license token to activate paid entitlements without Authorization header",
        json_schema_extra={"example": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."}
    )
    bank_name: Optional[str] = Field(
        "Bank Statement",
        description="Name of the financial institution or card provider (e.g. American Express, Wise, PayPal, Sparkasse)",
        json_schema_extra={"example": "American Express Business"}
    )
    export_format: Literal["datev", "bmd", "muster_csv"] = Field(
        "datev",
        description="Target accounting export format: 'datev' (EXTF 700 Windows-1252), 'bmd' (NTCS 5.1), or 'muster_csv'",
        json_schema_extra={"example": "datev"}
    )
    default_bank_account: Optional[str] = Field(
        None,
        description="Bank ledger account (e.g. '1200' for SKR03, '1800' for SKR04, '2800' for BMD NTCS). Defaults to 1200 for DATEV and 2800 for BMD.",
        json_schema_extra={"example": "1200"}
    )
    transactions: Optional[List[GptTransactionItem]] = Field(
        None,
        description="Array of structured transactions extracted by ChatGPT from the bank statement document."
    )
    raw_content: Optional[str] = Field(
        None,
        description="Optional raw CSV or plaintext content of statement if transactions were not extracted into structured items."
    )
    file_base64: Optional[str] = Field(
        None,
        description="Optional base64-encoded PDF or CSV statement document to be processed by backend parser supervisor."
    )
    filename: Optional[str] = Field(
        "statement.csv",
        description="Original statement filename hint (e.g. amex_march_2026.pdf)."
    )


class FinancialSummary(BaseModel):
    transaction_count: int = Field(..., description="Total number of processed bookings")
    total_debit: float = Field(..., description="Total sum of expenses/debits (negative or outgoing money)")
    total_credit: float = Field(..., description="Total sum of incomes/credits (incoming money)")
    net_balance: float = Field(..., description="Net balance turnover for the statement period")
    currency: str = Field("EUR", description="Primary currency")
    date_from: Optional[str] = Field(None, description="Earliest booking date in batch (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="Latest booking date in batch (YYYY-MM-DD)")


class FreeTierStatus(BaseModel):
    is_unlimited: bool = Field(False, description="True if request is covered by active Pro/Starter/Lifetime entitlement")
    plan: Optional[str] = Field(None, description="Active plan code (starter, pro, lifetime) if licensed")
    conversions_used: int = Field(0, description="Number of conversions used by this session/user")
    remaining_free_conversions: int = Field(0, description="Remaining free conversions (0 if limit reached)")
    max_free_conversions: int = Field(3, description="Maximum free conversions allowed without license")
    limit_reached: bool = Field(False, description="True if free limit has been reached and upgrade is required")


class GptConvertResponse(BaseModel):
    status: Literal["success", "warning", "error", "limit_reached"] = "success"
    message: str = Field(..., description="Status message explaining outcome")
    export_format: str = Field(..., description="Target export format produced")
    filename: str = Field(..., description="Generated export file name")
    download_id: str = Field(..., description="Ephemeral token for downloading the file")
    download_url: Optional[str] = Field(None, description="Direct temporary URL to download the generated file")
    file_base64: Optional[str] = Field(None, description="Base64-encoded CSV content for small files (omitted on large batches to respect ChatGPT 100k char limit)")
    expires_in_minutes: int = Field(30, description="Time until the download link expires (RAM-only retention)")
    summary: FinancialSummary = Field(..., description="Financial turnover summary for accounting verification")
    preview_csv: str = Field(..., description="First 5 lines preview of the generated DATEV/BMD file")
    free_tier_status: FreeTierStatus = Field(..., description="Information on free tier usage and remaining balance")
    notes: List[str] = Field(default_factory=list, description="Compliance and accounting notes")
    upgrade_info: Dict[str, str] = Field(default_factory=dict, description="Links to unlock unlimited conversions")


# --- Authenticated Identity & Entitlement Verification (G01 & G02) ---

PLAN_PRIORITY = {"lifetime": 1, "pro": 2, "starter": 3, "trial": 4}

async def resolve_verified_tenant(
    request: Request,
    license_key: Optional[str],
    db: AsyncSession
) -> Optional[Tuple[str, str, Entitlement]]:
    """
    Authoritative verification of tenant identity and paid entitlement (Architect G01).
    Requirements:
    1. Authenticates via Bearer JWT from Authorization header OR signed JWT token in license_key.
       (Bare unauthenticated email or fake ID prefixes are STRICTLY REJECTED).
    2. Queries authoritative DB for active entitlements. Rejects canceled/past_due/expired.
    3. Fails-closed on DB operational errors (raises HTTP 503).
    Returns (tenant_id, plan_code, active_entitlement) or None if unauthenticated.
    """
    token_str = None
    # A. Check Bearer token decoded by EarlyAuthAndBudgetMiddleware
    tenant_payload = getattr(request.state, "tenant", None)
    if not tenant_payload:
        # Check Authorization header directly
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token_str = auth_header[7:].strip()
    
    # B. Check license_key if passed as signed JWT
    if not token_str and license_key and len(license_key.strip()) > 20:
        token_str = license_key.strip()

    if token_str and not tenant_payload:
        try:
            tenant_payload = decode_access_token(token_str)
        except Exception:
            tenant_payload = None

    if not tenant_payload:
        return None

    tenant_id = tenant_payload.get("tenant_id")
    if not tenant_id:
        return None

    # Query authoritative DB Entitlements with Fail-Closed semantics
    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        query = select(Entitlement).where(
            and_(
                Entitlement.tenant_id == tenant_id,
                Entitlement.status == "active"
            )
        )
        res = await db.execute(query)
        all_ents = res.scalars().all()
    except Exception as e:
        logger.error(f"Database operational error during entitlement verification for tenant {tenant_id}: {e}", exc_info=True)
        # Architect G01: Fail-closed on DB operational errors!
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database operational error verifying subscription. Please retry."
        )

    if not all_ents:
        return None

    # Filter out expired entitlements and sort by plan priority
    valid_ents = []
    for ent in all_ents:
        if not ent.plan_code:
            continue
        if ent.valid_until is not None:
            exp = ent.valid_until if ent.valid_until.tzinfo else ent.valid_until.replace(tzinfo=datetime.timezone.utc)
            if exp <= now_utc:
                continue
        valid_ents.append(ent)

    if not valid_ents:
        return None

    valid_ents.sort(key=lambda e: PLAN_PRIORITY.get(e.plan_code.lower(), 99))
    chosen_ent = valid_ents[0]
    return tenant_id, chosen_ent.plan_code.lower(), chosen_ent


# --- Endpoints ---

@router.post("/v1/gpt/convert", response_model=GptConvertResponse)
@router.post("/api/v1/gpt/convert", response_model=GptConvertResponse)
async def gpt_convert_statement(
    req: GptConvertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    ChatGPT Action: Converts bank transactions into DATEV EXTF 700 or BMD NTCS 5.1 format.
    Processes data strictly in volatile RAM with 30-minute auto-purge.
    """
    # 1. Input Budget and DoS Checks (Architect G04)
    if req.transactions is not None:
        if len(req.transactions) > settings.MAX_ROWS_PER_FILE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Batch exceeds maximum allowed limit of {settings.MAX_ROWS_PER_FILE} rows."
            )
        for idx, item in enumerate(req.transactions):
            if len(item.description or "") > 500:
                item.description = item.description[:500]
            if len(item.reference or "") > 100:
                item.reference = item.reference[:100]

    if req.raw_content is not None:
        raw_bytes_len = len(req.raw_content.encode("utf-8"))
        if raw_bytes_len > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Raw content size ({raw_bytes_len} bytes) exceeds maximum limit of {settings.MAX_FILE_SIZE_BYTES} bytes."
            )

    if req.file_base64 is not None:
        raw_b64 = req.file_base64.strip()
        # Fast length check before base64 decode:
        if len(raw_b64) > (settings.MAX_FILE_SIZE_BYTES * 4 // 3 + 1024):
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_BYTES // (1024*1024)} MiB."
            )

    # 2. Authoritative Identity & License Verification (Architect G01)
    verified_auth = await resolve_verified_tenant(request, req.license_key, db)
    
    tenant_id = None
    plan_code = None
    is_licensed = False
    active_entitlement = None

    if verified_auth:
        tenant_id, plan_code, active_entitlement = verified_auth
        is_licensed = plan_code in ("starter", "pro", "lifetime")

    # 3. Quota & Free Tier Reservation (Architect G02)
    reservation = None
    idempotency_key = req.session_id or str(uuid.uuid4())
    client_sess_id = req.session_id.strip() if (req.session_id and req.session_id.strip()) else "guest"

    if is_licensed and tenant_id:
        # A. Authenticated Paid Tenant -> Use Core Quota Service (Two-Phase Commit Ledger)
        # Starter plan enforces 20 files/month; Pro/Lifetime enforces concurrency control
        try:
            reservation = await check_and_reserve_quota(
                db=db,
                tenant_id=tenant_id,
                file_count=1,
                idempotency_key=idempotency_key
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Quota reservation error for tenant {tenant_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal quota service error.")
    else:
        # B. Anonymous Guest / Unauthenticated Demo Mode -> Thread-Safe Atomic Reservation
        anon_key = f"used_sess_{client_sess_id}"
        with _anon_quota_lock:
            current_used = gpt_free_tier_tracker.get(anon_key, 0)
            if current_used >= MAX_FREE_CONVERSIONS:
                return GptConvertResponse(
                    status="limit_reached",
                    message=(
                        f"Demo-Kontingent erreicht: Sie haben Ihre {MAX_FREE_CONVERSIONS} kostenlosen Test-Auszüge verbraucht. "
                        "Bitte erwerben Sie einen Starter- oder Pro-Tarif, um unbegrenzt fortzufahren."
                    ),
                    export_format=req.export_format,
                    filename="",
                    download_id="",
                    download_url=None,
                    file_base64=None,
                    expires_in_minutes=0,
                    summary=FinancialSummary(
                        transaction_count=0,
                        total_debit=0.0,
                        total_credit=0.0,
                        net_balance=0.0,
                        currency="EUR"
                    ),
                    preview_csv="",
                    free_tier_status=FreeTierStatus(
                        is_unlimited=False,
                        plan=None,
                        conversions_used=current_used,
                        remaining_free_conversions=0,
                        max_free_conversions=MAX_FREE_CONVERSIONS,
                        limit_reached=True
                    ),
                    notes=[
                        f"Demo-Modus: Kontingent ({MAX_FREE_CONVERSIONS} Auszüge) für diese Session erreicht.",
                        "Melden Sie sich mit Ihrem Pro-Account an oder erwerben Sie ein Abonnement.",
                        "Starter: €4.90 / Monat (20 Auszüge monatlich)",
                        "Business Pro: €29.00 / Monat (Unbegrenzte Auszüge & Multi-Upload)"
                    ],
                    upgrade_info=STRIPE_LINKS
                )
            # Atomically reserve unit
            gpt_free_tier_tracker.set(anon_key, current_used + 1)

    # 4. Transaction Ingestion & Validation (Architect G05)
    canonical_txs: List[CanonicalTransaction] = []
    bank_name = req.bank_name or "Bank Statement"

    try:
        # Branch A: Structured transactions list extracted by ChatGPT
        if req.transactions and len(req.transactions) > 0:
            for idx, item in enumerate(req.transactions):
                # Strict date parsing: Raises HTTP 422 if invalid; NO fallback to today() (G05)
                booking_dt = parse_strict_date(item.booking_date, "booking_date", idx)
                value_dt = parse_strict_date(item.value_date, "value_date", idx) if item.value_date else booking_dt
                curr = normalize_currency(item.currency)
                amount_cents = parse_amount_to_cents(item.amount)

                tx = CanonicalTransaction(
                    transaction_id=str(uuid.uuid4()),
                    tenant_id=tenant_id or f"anon_{client_sess_id}",
                    client_entity_id="chatgpt-session",
                    account_id="",
                    bank_name=bank_name,
                    source_file_id=req.filename or "chatgpt_input.pdf",
                    source_row_page=str(idx + 1),
                    booking_date=booking_dt,
                    value_date=value_dt,
                    amount_cents=amount_cents,
                    currency=curr,
                    description=(item.description or "").strip(),
                    reference=(item.reference or "").strip(),
                    contra_account=item.contra_account
                )
                canonical_txs.append(tx)

        # Branch B: Base64-encoded PDF or CSV document provided
        elif req.file_base64 and len(req.file_base64.strip()) > 0:
            try:
                file_bytes = base64.b64decode(req.file_base64.strip(), validate=True)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ungültiger base64-Inhalt in 'file_base64': {str(e)}"
                )

            if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Dateigröße ({len(file_bytes)} Bytes) überschreitet das Limit von {settings.MAX_FILE_SIZE_BYTES} Bytes."
                )

            # Supervised child-process execution (C07 compliance, OOM guard 512 MiB, 30s timeout)
            parsed_txs, _ = await parser_supervisor.parse_file(
                content=file_bytes,
                filename=req.filename or "statement.pdf",
                tenant_id=tenant_id or f"anon_{client_sess_id}",
                timeout=float(settings.PARSER_TIMEOUT_SECONDS)
            )
            canonical_txs = parsed_txs

        # Branch C: Raw CSV or plaintext content provided
        elif req.raw_content and len(req.raw_content.strip()) > 0:
            raw_bytes = req.raw_content.encode("utf-8")
            parsed_txs, _ = await parser_supervisor.parse_file(
                content=raw_bytes,
                filename=req.filename or "statement.csv",
                tenant_id=tenant_id or f"anon_{client_sess_id}",
                timeout=float(settings.PARSER_TIMEOUT_SECONDS)
            )
            canonical_txs = parsed_txs
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Weder 'transactions'-Array noch 'file_base64' oder 'raw_content' übergeben."
            )

        if not canonical_txs:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Keine Buchungssätze in den bereitgestellten Daten gefunden."
            )

        # 5. Financial & Accounting Safeguard Invariants (Architect G05)
        # A. Currency consistency check: Mixed currencies cannot be merged into single sum
        distinct_currencies = {tx.currency for tx in canonical_txs if tx.currency}
        if len(distinct_currencies) > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Export blockiert: Gemischte Währungen erkannt ({sorted(distinct_currencies)}). Buchhaltungsexport erfordert eine einheitliche Währung."
            )

        # B. DATEV EXTF Single Fiscal Year Invariant
        target_format = req.export_format.lower().strip()
        if target_format == "datev":
            distinct_years = {tx.booking_date.year for tx in canonical_txs if tx.booking_date}
            if len(distinct_years) > 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Export blockiert: Buchungen über mehrere Geschäftsjahre erkannt ({sorted(distinct_years)}). DATEV-Buchungsstapel müssen genau einem Geschäftsjahr angehören."
                )

        # Sort transactions chronologically
        canonical_txs.sort(key=lambda t: t.booking_date or datetime.date.min)

        # 6. Exporter Selection and File Generation
        now = datetime.datetime.now()
        sanitized_bank = re.sub(r'[^a-zA-Z0-9_-]', '_', bank_name).strip('_') or "Bank"

        if target_format == "bmd":
            default_acc = req.default_bank_account or "2800"
            csv_bytes = export_to_bmd_csv(canonical_txs, default_bank_account=default_acc)
            out_filename = f"BMD_NTCS_{sanitized_bank}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
            media_type = "text/csv"
        elif target_format == "muster_csv":
            csv_bytes = export_to_muster_csv(canonical_txs)
            out_filename = f"MUSTER_{sanitized_bank}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
            media_type = "text/csv"
        else:  # Default to datev
            default_acc = req.default_bank_account or "1200"
            csv_bytes = export_to_datev_csv(canonical_txs, default_bank_account=default_acc)
            out_filename = f"DATEV_EXTF_{sanitized_bank}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
            media_type = "text/csv"

        # 7. Commit Quota if licensed reservation exists (Architect G02)
        if reservation:
            await commit_quota(db, reservation, successful_count=1)

    except HTTPException:
        if reservation:
            await release_quota(db, reservation)
        raise
    except Exception as exc:
        if reservation:
            await release_quota(db, reservation)
        logger.error(f"Unexpected conversion failure: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Interner Verarbeitungsfehler: {str(exc)}"
        )

    # 8. Store in Zero-Retention Volatile RAM Cache (30 min TTL)
    download_id = f"s2m_gpt_{uuid.uuid4().hex}"
    gpt_download_cache.set(
        key=download_id,
        value={
            "bytes": csv_bytes,
            "filename": out_filename,
            "media_type": media_type,
            "created_at": now.isoformat()
        },
        ttl_seconds=1800
    )

    # 9. Public Download URL & Bounded Base64 Payload (Architect G06)
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "api.statement2muster.com")
    base_url = f"{proto}://{host}"
    download_url = f"{base_url}/v1/gpt/download/{download_id}"

    # Only include inline base64 if small batch (< 100 rows and < 20 KB),
    # otherwise omit to strictly respect OpenAI's 100k character response budget (G06)
    file_b64 = None
    if len(canonical_txs) <= 100 and len(csv_bytes) <= 20000:
        file_b64 = base64.b64encode(csv_bytes).decode("ascii")

    # 10. Financial Summary Calculation
    total_debit_cents = sum(tx.amount_cents for tx in canonical_txs if tx.amount_cents < 0)
    total_credit_cents = sum(tx.amount_cents for tx in canonical_txs if tx.amount_cents > 0)
    net_cents = sum(tx.amount_cents for tx in canonical_txs)

    dates = [tx.booking_date for tx in canonical_txs if tx.booking_date]
    min_date = min(dates).isoformat() if dates else None
    max_date = max(dates).isoformat() if dates else None

    # First 5 lines for chat preview
    preview_text = ""
    try:
        decoded = csv_bytes.decode("windows-1252", errors="replace")
        preview_lines = decoded.splitlines()[:5]
        preview_text = "\n".join(preview_lines)
    except Exception:
        preview_text = "(Preview generation unavailable)"

    # Free tier status calculation
    if is_licensed:
        ft_status = FreeTierStatus(
            is_unlimited=plan_code in ("pro", "lifetime"),
            plan=plan_code,
            conversions_used=0,
            remaining_free_conversions=9999,
            max_free_conversions=MAX_FREE_CONVERSIONS,
            limit_reached=False
        )
    else:
        current_used = gpt_free_tier_tracker.get(f"used_sess_{client_sess_id}", 1)
        remaining = max(0, MAX_FREE_CONVERSIONS - current_used)
        ft_status = FreeTierStatus(
            is_unlimited=False,
            plan=None,
            conversions_used=current_used,
            remaining_free_conversions=remaining,
            max_free_conversions=MAX_FREE_CONVERSIONS,
            limit_reached=False
        )

    # Privacy disclosures adhering strictly to Architect G03
    notes = [
        "Zero Durable Storage auf unserem Server: Die Datei wird ausschließlich im flüchtigen RAM vorgehalten und nach 30 Minuten unwiderruflich gelöscht.",
        "Hinweis: Daten und Chatverläufe in ChatGPT unterliegen den Datenschutzeinstellungen Ihres OpenAI-Kontos.",
        f"Export kodiert in Windows-1252 mit CRLF-Zeilenenden für native {target_format.upper()}-Kompatibilität.",
        f"Buchungskonto: {req.default_bank_account or ('1200 (SKR03)' if target_format == 'datev' else '2800')}"
    ]

    if is_licensed:
        notes.append(f"Lizenzstatus: Aktiv ({plan_code.upper()}).")
    else:
        notes.append(
            f"Demo-Modus: Auszug {ft_status.conversions_used} von {MAX_FREE_CONVERSIONS} verbraucht. "
            f"Noch {ft_status.remaining_free_conversions} Test-Konvertierung(en) für diese Session verfügbar."
        )

    return GptConvertResponse(
        status="success",
        message=f"Erfolgreich {len(canonical_txs)} Buchungssätze in {target_format.upper()} konvertiert.",
        export_format=target_format,
        filename=out_filename,
        download_id=download_id,
        download_url=download_url,
        file_base64=file_b64,
        expires_in_minutes=30,
        summary=FinancialSummary(
            transaction_count=len(canonical_txs),
            total_debit=round(total_debit_cents / 100.0, 2),
            total_credit=round(total_credit_cents / 100.0, 2),
            net_balance=round(net_cents / 100.0, 2),
            currency=canonical_txs[0].currency if canonical_txs else "EUR",
            date_from=min_date,
            date_to=max_date
        ),
        preview_csv=preview_text,
        free_tier_status=ft_status,
        notes=notes,
        upgrade_info=STRIPE_LINKS
    )


@router.get("/v1/gpt/download/{download_id}")
@router.get("/api/v1/gpt/download/{download_id}")
async def gpt_download_file(download_id: str):
    """
    Downloads the generated DATEV/BMD file directly from ephemeral RAM cache.
    Zero Durable Retention: File data is served directly from RAM without disk touches.
    """
    item = gpt_download_cache.get(download_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Download-Link ist abgelaufen oder existiert nicht. "
                "Gemäß unserer Zero-Durable-Retention Datenschutzrichtlinie werden Dateien nach 30 Minuten vollständig aus dem Speicher gelöscht. "
                "Bitte führen Sie die Konvertierung in ChatGPT erneut durch."
            )
        )

    data = item["bytes"]
    filename = item["filename"]
    media_type = item.get("media_type", "text/csv")

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": f"{media_type}; charset=windows-1252",
        "Cache-Control": "no-store, no-cache, must-revalidate, private",
        "X-Zero-Retention": "enforced-in-memory-only",
        "X-Statement2Muster-Format": filename.split('_')[0]
    }

    return Response(
        content=data,
        status_code=200,
        media_type=media_type,
        headers=headers
    )
