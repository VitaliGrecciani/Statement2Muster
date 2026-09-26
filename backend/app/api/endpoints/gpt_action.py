import io
import re
import json
import uuid
import base64
import hashlib
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
    Parses dates strictly using unambiguous standard formats (Architect G05 / F04).
    Accepted formats:
      - ISO 8601: YYYY-MM-DD
      - German/Austrian standard: DD.MM.YYYY
    Ambiguous formats (such as slash-separated DD/MM/YYYY vs MM/DD/YYYY or 2-digit years)
    are strictly rejected with HTTP 422 to prevent silent date corruption.
    """
    if not date_str or not isinstance(date_str, str) or not date_str.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Fehlendes Datum für '{field_name}' in Zeile {row_idx + 1}."
        )
    cleaned = date_str.strip()

    # Reject ambiguous slash-separated dates explicitly (F04)
    if "/" in cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Mehrdeutiges Datumsformat '{cleaned}' für '{field_name}' in Zeile {row_idx + 1}. "
                f"Aus Sicherheitsgründen werden nur eindeutige Formate akzeptiert: YYYY-MM-DD (ISO) oder DD.MM.YYYY (DATEV/BMD)."
            )
        )

    # Check ISO: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", cleaned):
        try:
            return datetime.datetime.strptime(cleaned, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Check German standard dot format: DD.MM.YYYY
    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}$", cleaned):
        try:
            return datetime.datetime.strptime(cleaned, "%d.%m.%Y").date()
        except ValueError:
            pass

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"Ungültiges Datumsformat '{cleaned}' für '{field_name}' in Zeile {row_idx + 1}. "
            f"Erwartet wird YYYY-MM-DD oder DD.MM.YYYY."
        )
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
        max_length=20,
        description="Booking date in ISO YYYY-MM-DD or German DD.MM.YYYY format",
        json_schema_extra={"example": "2026-03-15"}
    )
    value_date: Optional[str] = Field(
        None,
        max_length=20,
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
        max_length=10,
        description="ISO 4217 currency code (e.g. EUR, USD, CHF, GBP)",
        json_schema_extra={"example": "EUR"}
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Transaction description, payee, or payment purpose (DATEV Buchungstext, max 300 chars)",
        json_schema_extra={"example": "AWS EMEA SARL Cloud Services"}
    )
    reference: Optional[str] = Field(
        None,
        max_length=50,
        description="Invoice, voucher or reference ID (DATEV Belegfeld 1, max 50 chars)",
        json_schema_extra={"example": "INV-2026-98102"}
    )
    contra_account: Optional[str] = Field(
        None,
        max_length=20,
        pattern=r"^[0-9]{3,9}$",
        description="Optional pre-assigned bookkeeping contra account / Gegenkonto (3-9 digits, e.g. '4900' for SKR03, '6800' for SKR04)",
        json_schema_extra={"example": "4900"}
    )


class GptConvertRequest(BaseModel):
    request_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Optional unique client operation or idempotency ID",
        json_schema_extra={"example": "req-2026-03-10-001"}
    )
    session_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Optional ChatGPT conversation or session identifier to track demo usage",
        json_schema_extra={"example": "chatgpt-sess-88123"}
    )
    email: Optional[str] = Field(
        None,
        max_length=120,
        description="Optional user email. Note: Paid rights require authentication via Bearer token or signed token in license_key.",
        json_schema_extra={"example": "founder@startup.de"}
    )
    license_key: Optional[str] = Field(
        None,
        max_length=4096,
        description="Optional signed JWT access token or API license token to activate paid entitlements without Authorization header",
        json_schema_extra={"example": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."}
    )
    bank_name: Optional[str] = Field(
        "Bank Statement",
        max_length=100,
        description="Name of the financial institution or card provider (max 100 chars)",
        json_schema_extra={"example": "American Express Business"}
    )
    export_format: Literal["datev", "bmd", "muster_csv"] = Field(
        "datev",
        description="Target accounting export format: 'datev' (EXTF 700 Windows-1252), 'bmd' (NTCS 5.1), or 'muster_csv'",
        json_schema_extra={"example": "datev"}
    )
    default_bank_account: Optional[str] = Field(
        None,
        max_length=20,
        pattern=r"^[0-9]{3,9}$",
        description="Bank ledger account (3-9 digits, e.g. '1200' for SKR03, '1800' for SKR04, '2800' for BMD NTCS). Defaults to 1200 for DATEV and 2800 for BMD.",
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
        max_length=100,
        description="Original statement filename hint (e.g. amex_march_2026.pdf)."
    )


def compute_payload_hash(req: GptConvertRequest) -> str:
    """
    Computes deterministic SHA-256 hash of the canonical conversion payload and export settings (Architect F02).
    Uses a structured dictionary with named keys and json.dumps(sort_keys=True) to eliminate
    parameter boundary ambiguities and distinguish all relevant fields.
    """
    tx_repr = None
    if req.transactions:
        tx_repr = []
        for t in req.transactions:
            tx_repr.append({
                "booking_date": (t.booking_date or "").strip(),
                "value_date": (t.value_date or "").strip() if t.value_date else None,
                "amount": t.amount,
                "currency": (t.currency or "EUR").strip().upper(),
                "description": (t.description or "").strip(),
                "reference": (t.reference or "").strip() if t.reference else None,
                "contra_account": (t.contra_account or "").strip() if t.contra_account else None
            })

    canonical_data = {
        "export_format": (req.export_format or "datev").strip().lower(),
        "default_bank_account": (req.default_bank_account or "").strip(),
        "bank_name": (req.bank_name or "").strip(),
        "filename": (req.filename or "").strip(),
        "transactions": tx_repr,
        "raw_content": req.raw_content,
        "file_base64": req.file_base64,
    }
    encoded = json.dumps(canonical_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    if not token_str and license_key and license_key.strip():
        candidate = license_key.strip()
        # Explicit JWT structure (header.payload.signature)
        if candidate.count(".") == 2:
            token_str = candidate

    if token_str and not tenant_payload:
        # F01: Any failure to validate an explicitly presented JWT must fail closed!
        # Do NOT catch HTTPException (401, 503) and silently fall back to anonymous success!
        tenant_payload = decode_access_token(token_str)

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
    # 1. Input Validation and Budget Checks (Architect G04 / F03)
    if req.default_bank_account:
        acc_str = req.default_bank_account.strip()
        if not re.match(r"^[0-9]{3,9}$", acc_str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Ungültiges Bankkonto '{acc_str[:20]}'. Erwartet wird eine 3- bis 9-stellige Ziffernfolge (z.B. 1200 für SKR03, 1800 für SKR04, 2800 für BMD)."
            )

    if req.transactions is not None:
        if len(req.transactions) > settings.MAX_ROWS_PER_FILE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Batch exceeds maximum allowed limit of {settings.MAX_ROWS_PER_FILE} rows."
            )
        for idx, item in enumerate(req.transactions):
            if len(item.description or "") > 300:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Buchungstext in Zeile {idx + 1} überschreitet das Maximum von 300 Zeichen."
                )
            if item.reference and len(item.reference) > 50:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Belegfeld 1 in Zeile {idx + 1} überschreitet das Maximum von 50 Zeichen."
                )

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

    # 2. Transaction Ingestion & Invariant Validation BEFORE Quota Reservation (Architect G05 / F02)
    canonical_txs: List[CanonicalTransaction] = []
    bank_name = req.bank_name or "Bank Statement"
    client_sess_id = req.session_id.strip() if (req.session_id and req.session_id.strip()) else "guest"

    # Branch A: Structured transactions list extracted by ChatGPT
    if req.transactions and len(req.transactions) > 0:
        for idx, item in enumerate(req.transactions):
            # Strict date parsing: Raises HTTP 422 on invalid or ambiguous formats (F04)
            booking_dt = parse_strict_date(item.booking_date, "booking_date", idx)
            value_dt = parse_strict_date(item.value_date, "value_date", idx) if item.value_date else booking_dt
            curr = normalize_currency(item.currency)
            amount_cents = parse_amount_to_cents(item.amount)

            tx = CanonicalTransaction(
                transaction_id=str(uuid.uuid4()),
                tenant_id=f"sess_{client_sess_id}",
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

        parsed_txs, _ = await parser_supervisor.parse_file(
            content=file_bytes,
            filename=req.filename or "statement.pdf",
            tenant_id=f"sess_{client_sess_id}",
            timeout=float(settings.PARSER_TIMEOUT_SECONDS)
        )
        canonical_txs = parsed_txs

    # Branch C: Raw CSV or plaintext content provided
    elif req.raw_content and len(req.raw_content.strip()) > 0:
        raw_bytes = req.raw_content.encode("utf-8")
        parsed_txs, _ = await parser_supervisor.parse_file(
            content=raw_bytes,
            filename=req.filename or "statement.csv",
            tenant_id=f"sess_{client_sess_id}",
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

    # Accounting Safeguards:
    # Currency consistency check
    distinct_currencies = {tx.currency for tx in canonical_txs if tx.currency}
    if len(distinct_currencies) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Export blockiert: Gemischte Währungen erkannt ({sorted(distinct_currencies)}). Buchhaltungsexport erfordert eine einheitliche Währung."
        )

    # DATEV single fiscal year check
    target_format = req.export_format.lower().strip()
    if target_format == "datev":
        distinct_years = {tx.booking_date.year for tx in canonical_txs if tx.booking_date}
        if len(distinct_years) > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Export blockiert: Buchungen über mehrere Geschäftsjahre erkannt ({sorted(distinct_years)}). DATEV-Buchungsstapel müssen genau einem Geschäftsjahr angehören."
            )

    canonical_txs.sort(key=lambda t: t.booking_date or datetime.date.min)

    # 3. Authoritative Identity & License Verification (Architect G01 / F01)
    verified_auth = await resolve_verified_tenant(request, req.license_key, db)
    
    tenant_id = None
    plan_code = None
    is_licensed = False
    active_entitlement = None

    if verified_auth:
        tenant_id, plan_code, active_entitlement = verified_auth
        is_licensed = plan_code in ("starter", "pro", "lifetime")
        for tx in canonical_txs:
            tx.tenant_id = tenant_id

    # 4. Quota, Idempotency & Free Tier Reservation (Architect G02 / F02)
    reservation = None
    payload_hash = compute_payload_hash(req)

    has_client_request_id = bool(req.request_id and req.request_id.strip())
    if has_client_request_id:
        idempotency_key = f"gpt_{req.request_id.strip()}"
        # Check RAM-only replay cache first (Architect F02 / Decision 51 section 4.1)
        cached_op = gpt_download_cache.get(f"op_{idempotency_key}")
        if cached_op:
            if cached_op.get("payload_hash") != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key reused with different request payload"
                )
            return Response(content=cached_op["response_json"], media_type="application/json")
    else:
        # Separate unique operation per conversion call (F02)
        sess_part = req.session_id.strip() if req.session_id else "op"
        idempotency_key = f"gpt_{sess_part}_{payload_hash[:16]}_{uuid.uuid4().hex[:8]}"

    if is_licensed and tenant_id:
        # A. Authenticated Paid Tenant -> Core Quota Service
        try:
            reservation = await check_and_reserve_quota(
                db=db,
                tenant_id=tenant_id,
                file_count=1,
                idempotency_key=idempotency_key,
                request_hash=payload_hash
            )
            if reservation.status == "COMMITTED":
                # Result expired from volatile RAM cache (Architect F02 / Decision 51 section 4.1)
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail=(
                        "Das Ergebnis für diesen Vorgang ist im flüchtigen RAM-Zwischenspeicher abgelaufen (TTL 30 Minuten). "
                        "Das Kontingent wurde für diesen Vorgang bereits verbucht. "
                        "Bitte starten Sie eine neue Konvertierung mit einer neuen request_id."
                    )
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Quota reservation error for tenant {tenant_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal quota service error.")
    else:
        # B. Anonymous Guest Demo Mode
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
            gpt_free_tier_tracker.set(anon_key, current_used + 1)

    # 5. Exporter Execution
    try:
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

        # Commit quota only if newly reserved (status == RESERVED)
        if reservation and reservation.status == "RESERVED":
            await commit_quota(db, reservation, successful_count=1)

    except HTTPException:
        if reservation and reservation.status == "RESERVED":
            await release_quota(db, reservation)
        raise
    except Exception as exc:
        if reservation and reservation.status == "RESERVED":
            await release_quota(db, reservation)
        logger.error(f"Unexpected conversion failure: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Interner Verarbeitungsfehler: {str(exc)}"
        )

    # 6. Ephemeral RAM Cache (30 min TTL)
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

    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "api.statement2muster.com")
    base_url = f"{proto}://{host}"
    download_url = f"{base_url}/v1/gpt/download/{download_id}"

    # Bounded Base64 payload (omitted on large batches or when > 20 KB)
    file_b64 = None
    if len(canonical_txs) <= 100 and len(csv_bytes) <= 20000:
        file_b64 = base64.b64encode(csv_bytes).decode("ascii")

    # 7. Financial Summary Calculation
    total_debit_cents = sum(tx.amount_cents for tx in canonical_txs if tx.amount_cents < 0)
    total_credit_cents = sum(tx.amount_cents for tx in canonical_txs if tx.amount_cents > 0)
    net_cents = sum(tx.amount_cents for tx in canonical_txs)

    dates = [tx.booking_date for tx in canonical_txs if tx.booking_date]
    min_date = min(dates).isoformat() if dates else None
    max_date = max(dates).isoformat() if dates else None

    # First 5 lines preview, bounded to 1000 characters
    preview_text = ""
    try:
        decoded = csv_bytes.decode("windows-1252", errors="replace")
        preview_lines = decoded.splitlines()[:5]
        preview_text = "\n".join(preview_lines)
        if len(preview_text) > 1000:
            preview_text = preview_text[:997] + "..."
    except Exception:
        preview_text = "(Preview generation unavailable)"

    # 8. Free Tier / Starter Real Quota Calculation (F02)
    if is_licensed and active_entitlement:
        if plan_code == "starter":
            period_start = active_entitlement.current_period_start or (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30))
            if period_start.tzinfo is None:
                period_start = period_start.replace(tzinfo=datetime.timezone.utc)
            sum_query = select(func.sum(UsageReservation.units)).where(
                and_(
                    UsageReservation.tenant_id == tenant_id,
                    UsageReservation.status == "COMMITTED",
                    UsageReservation.created_at >= period_start
                )
            )
            used_units = (await db.execute(sum_query)).scalar() or 0
            starter_max = 20
            remaining = max(0, starter_max - used_units)
            ft_status = FreeTierStatus(
                is_unlimited=False,
                plan="starter",
                conversions_used=used_units,
                remaining_free_conversions=remaining,
                max_free_conversions=starter_max,
                limit_reached=(remaining <= 0)
            )
        else:
            ft_status = FreeTierStatus(
                is_unlimited=True,
                plan=plan_code,
                conversions_used=0,
                remaining_free_conversions=9999,
                max_free_conversions=9999,
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

    # 9. Privacy disclosures adhering strictly to Architect G03 / F05
    notes = [
        "Server-Zwischenspeicher (RAM-only): Der Download-Link und die temporären Exportdaten im flüchtigen Arbeitsspeicher verfallen nach 30 Minuten (TTL 1800s) und werden aus dem Server-Cache freigegeben.",
        "Datenschutzhinweis: Im Chatverlauf von ChatGPT angezeigte Auszüge, Tabellen und generierte Inhalte verbleiben gemäß den Datenschutzeinstellungen Ihres OpenAI-Kontos.",
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

    resp_obj = GptConvertResponse(
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

    # Strict JSON size bounding under 40,000 chars (Architect F03)
    resp_json = resp_obj.model_dump_json()
    if len(resp_json) > 40000:
        resp_obj.file_base64 = None
        resp_json = resp_obj.model_dump_json()
        if len(resp_json) > 40000:
            resp_obj.preview_csv = resp_obj.preview_csv[:300] + "\n...(abgeschnitten)"
            resp_json = resp_obj.model_dump_json()
            if len(resp_json) > 40000:
                resp_obj.preview_csv = "(Vorschau wegen Größenbegrenzung gekürzt)"
                resp_obj.notes = resp_obj.notes[:2]
                resp_json = resp_obj.model_dump_json()

    if has_client_request_id:
        # Cache operation response for idempotent replay (Architect F02 / Decision 51)
        gpt_download_cache.set(
            key=f"op_{idempotency_key}",
            value={
                "payload_hash": payload_hash,
                "response_json": resp_json,
                "download_id": download_id
            },
            ttl_seconds=1800
        )

    return Response(content=resp_json, media_type="application/json")


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
                "Temporäre Exportdaten im flüchtigen RAM-Zwischenspeicher verfallen nach 30 Minuten. "
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
