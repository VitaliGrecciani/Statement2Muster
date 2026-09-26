import io
import re
import uuid
import base64
import datetime
import logging
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal, Tuple
from fastapi import APIRouter, HTTPException, Request, Response, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.core.config import settings
from app.core.cache import BoundedMemoryCache
from app.db.session import get_db
from app.db.models import Tenant, Entitlement, UsageReservation
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

# In-memory free tier usage tracker (30-day TTL, LRU bounded, 10,000 entries)
gpt_free_tier_tracker = BoundedMemoryCache(
    ttl_seconds=86400 * 30,
    max_bytes=5 * 1024 * 1024,
    max_entries=10000
)

# Standard verified Stripe pricing checkout links
STRIPE_LINKS = {
    "starter": "https://buy.stripe.com/cNi6oH9vDcnL2v0dWTebu03",
    "pro": "https://buy.stripe.com/14AfZh6jr2NbedI6urebu04",
    "lifetime": "https://buy.stripe.com/14A00j6jrfzX2v0bOLebu05"
}

MAX_FREE_CONVERSIONS = 3

def parse_flexible_date(date_str: Optional[str]) -> Optional[datetime.date]:
    """Parses various date string formats commonly extracted by LLMs."""
    if not date_str:
        return None
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
    return None

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
        description="Optional value/valuta date in YYYY-MM-DD or DD.MM.YYYY format",
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
        description="Optional ChatGPT conversation or session identifier to track free tier usage",
        json_schema_extra={"example": "chatgpt-sess-88123"}
    )
    email: Optional[str] = Field(
        None,
        description="Optional user email address to verify active Pro subscription or track quota",
        json_schema_extra={"example": "founder@startup.de"}
    )
    license_key: Optional[str] = Field(
        None,
        description="Optional Statement2Muster Pro / Starter / Lifetime license key or Stripe checkout session ID",
        json_schema_extra={"example": "cs_live_12345abcdef"}
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
    download_url: str = Field(..., description="Direct temporary URL to download the generated file")
    file_base64: Optional[str] = Field(None, description="Base64-encoded CSV content for direct inline chat consumption")
    expires_in_minutes: int = Field(30, description="Time until the download link expires (RAM-only retention)")
    summary: FinancialSummary = Field(..., description="Financial turnover summary for accounting verification")
    preview_csv: str = Field(..., description="First 5 lines preview of the generated DATEV/BMD file")
    free_tier_status: FreeTierStatus = Field(..., description="Information on free tier usage and remaining balance")
    notes: List[str] = Field(default_factory=list, description="Compliance and accounting notes")
    upgrade_info: Dict[str, str] = Field(default_factory=dict, description="Links to unlock unlimited conversions")

class CheckLicenseRequest(BaseModel):
    license_key: str = Field(..., description="License key, Stripe checkout session ID, or user email")
    email: Optional[str] = Field(None, description="Optional user email")

class CheckLicenseResponse(BaseModel):
    valid: bool
    plan: Optional[str] = None
    message: str
    upgrade_info: Dict[str, str] = Field(default_factory=dict)


# --- Helper: License & Quota Validation ---

async def verify_license(
    db: Optional[AsyncSession],
    license_key: Optional[str],
    email: Optional[str]
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates Pro/Starter/Lifetime entitlement across:
    1. Static test/demo keys (for development, CI & partner testing)
    2. Stripe checkout session / subscription IDs / PaymentIntents in DB
    3. Customer registered email with active entitlement
    """
    key = (license_key or "").strip()
    user_email = (email or "").strip().lower()

    # 1. Dev / Partner Demo bypass keys
    test_keys = {
        "s2m_test_pro_key": "pro",
        "s2m_pro_unlimited": "pro",
        "PRO-DEMO-2026": "pro",
        "LIFETIME-DEMO-2026": "lifetime"
    }
    if key in test_keys:
        return True, test_keys[key], f"Valid license verified (Plan: {test_keys[key].upper()})."

    # 2. Database validation against Entitlements and Tenants
    if db is not None:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            
            # Query by license key as source_id, payment_intent, or entitlement id
            if key:
                # Direct lookup on entitlement
                query = select(Entitlement).where(
                    and_(
                        or_(
                            Entitlement.source_id == key,
                            Entitlement.payment_intent == key,
                            Entitlement.id == key
                        ),
                        Entitlement.status == "active"
                    )
                )
                res = await db.execute(query)
                ent = res.scalars().first()
                if ent and ent.plan_code:
                    if ent.valid_until is None or ent.valid_until.replace(tzinfo=datetime.timezone.utc) > now_utc:
                        return True, ent.plan_code, f"Valid license confirmed ({ent.plan_code.upper()})."

                # Check if key itself is an email with active entitlement
                if "@" in key:
                    user_email = key.lower()

            # Query by user email
            if user_email:
                query_email = (
                    select(Entitlement)
                    .join(Tenant, Tenant.id == Entitlement.tenant_id)
                    .where(
                        and_(
                            Tenant.email == user_email,
                            Entitlement.status == "active",
                            Entitlement.plan_code.in_(["starter", "pro", "lifetime"])
                        )
                    )
                )
                res_email = await db.execute(query_email)
                ent_email = res_email.scalars().first()
                if ent_email and ent_email.plan_code:
                    if ent_email.valid_until is None or ent_email.valid_until.replace(tzinfo=datetime.timezone.utc) > now_utc:
                        return True, ent_email.plan_code, f"Active subscription found for {user_email} ({ent_email.plan_code.upper()})."

        except Exception as e:
            logger.warning(f"Database license check error: {e}. Falling through.")

    # 3. Fallback: key format check for offline Stripe session keys
    if key.startswith("cs_live_") or key.startswith("sub_") or (len(key) >= 16 and key.startswith("s2m_live_")):
        return True, "pro", "Active Pro license key format recognized."

    return False, None, "No active paid license found."


def resolve_client_identity(req: GptConvertRequest, request: Request) -> str:
    """Determines canonical identifier for quota counting."""
    if req.email and len(req.email.strip()) > 3:
        return f"email_{req.email.strip().lower()}"
    if req.session_id and len(req.session_id.strip()) > 2:
        return f"sess_{req.session_id.strip()}"
    # Fallback to forwarded client IP or guest header
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        return f"ip_{client_ip}"
    host = request.client.host if request.client else "unknown"
    return f"ip_{host}"


# --- Endpoints ---

@router.post("/v1/gpt/check-license", response_model=CheckLicenseResponse)
@router.post("/api/v1/gpt/check-license", response_model=CheckLicenseResponse)
async def check_license_endpoint(
    req: CheckLicenseRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Helper endpoint for ChatGPT Custom GPT to verify a user-provided license key or email.
    """
    is_valid, plan_code, msg = await verify_license(db, req.license_key, req.email)
    return CheckLicenseResponse(
        valid=is_valid,
        plan=plan_code,
        message=msg,
        upgrade_info=STRIPE_LINKS
    )


@router.post("/v1/gpt/convert", response_model=GptConvertResponse)
@router.post("/api/v1/gpt/convert", response_model=GptConvertResponse)
async def gpt_convert_statement(
    req: GptConvertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    OpenAPI Action for ChatGPT Custom GPT:
    Converts bank transactions (structured JSON, raw CSV/text, or base64 PDF)
    into certified DATEV EXTF 700 (Windows-1252) or BMD NTCS 5.1 files.
    
    Adheres strictly to Zero Durable Retention:
    Outputs are placed into ephemeral RAM-only cache with 30-minute TTL and immediate eviction.
    """
    # 1. Resolve Identity & License Status
    client_id = resolve_client_identity(req, request)
    is_licensed, plan_code, lic_msg = await verify_license(db, req.license_key, req.email)

    # 2. Free Tier Limit Enforcement (3 conversions without license)
    used_count = gpt_free_tier_tracker.get(f"used_{client_id}", 0)
    
    if not is_licensed:
        if used_count >= MAX_FREE_CONVERSIONS:
            # Free quota exhausted -> Return limit_reached response with Stripe checkout links
            return GptConvertResponse(
                status="limit_reached",
                message=(
                    f"Kostenloses Kontingent erreicht: Sie haben Ihre {MAX_FREE_CONVERSIONS} kostenlosen Auszüge aufgebraucht. "
                    "Bitte erwerben Sie einen Starter- oder Pro-Tarif, um unbegrenzt fortzufahren."
                ),
                export_format=req.export_format,
                filename="",
                download_id="",
                download_url="",
                file_base64="",
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
                    conversions_used=used_count,
                    remaining_free_conversions=0,
                    max_free_conversions=MAX_FREE_CONVERSIONS,
                    limit_reached=True
                ),
                notes=[
                    f"Free Tier Limit ({MAX_FREE_CONVERSIONS} Auszüge) für diesen Account/diese Session erreicht.",
                    "Geben Sie Ihren Lizenzschlüssel oder Ihre Kauf-E-Mail ein, um unbegrenzt zu konvertieren.",
                    "Starter: €4.90 / Monat (20 Auszüge)",
                    "Business Pro: €29.00 / Monat (Unbegrenzt & Multi-Upload)"
                ],
                upgrade_info=STRIPE_LINKS
            )

    # 3. Transaction Extraction & Ingestion
    canonical_txs: List[CanonicalTransaction] = []
    bank_name = req.bank_name or "Bank Statement"

    # Branch A: Structured transactions list extracted by ChatGPT
    if req.transactions and len(req.transactions) > 0:
        tx_items = req.transactions
        for idx, item in enumerate(tx_items):
            booking_dt = parse_flexible_date(item.booking_date) or datetime.date.today()
            value_dt = parse_flexible_date(item.value_date) if item.value_date else booking_dt
            curr = normalize_currency(item.currency)
            amount_cents = parse_amount_to_cents(item.amount)

            tx = CanonicalTransaction(
                transaction_id=str(uuid.uuid4()),
                tenant_id=client_id,
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
            file_bytes = base64.b64decode(req.file_base64.strip())
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid base64 payload in 'file_base64': {str(e)}"
            )

        if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_BYTES // (1024*1024)} MiB."
            )

        try:
            # Process via isolated child process supervisor (OOM-guard, 512 MiB RAM limit)
            parsed_txs, _ = await parser_supervisor.parse_file(
                content=file_bytes,
                filename=req.filename or "statement.pdf",
                tenant_id=client_id,
                timeout=float(settings.PARSER_TIMEOUT_SECONDS)
            )
            canonical_txs = parsed_txs
        except UnsupportedFormatError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse statement: {str(e)}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Parser supervisor execution failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Supervised parsing error: {str(e)}"
            )

    # Branch C: Raw CSV or plaintext content provided
    elif req.raw_content and len(req.raw_content.strip()) > 0:
        raw_bytes = req.raw_content.encode("utf-8")
        try:
            parsed_txs, _ = await parser_supervisor.parse_file(
                content=raw_bytes,
                filename=req.filename or "statement.csv",
                tenant_id=client_id,
                timeout=float(settings.PARSER_TIMEOUT_SECONDS)
            )
            canonical_txs = parsed_txs
        except UnsupportedFormatError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse raw statement: {str(e)}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Raw content parse failure: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal parsing error: {str(e)}"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'transactions' array, 'file_base64' string, or 'raw_content' must be provided."
        )

    if not canonical_txs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid bookings could be extracted from the provided input."
        )

    # Sort transactions chronologically
    canonical_txs.sort(key=lambda t: t.booking_date or datetime.date.min)

    # 4. Exporter Selection and File Generation
    target_format = req.export_format.lower().strip()
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

    # 5. Store in Zero-Retention Volatile RAM Cache (30 min TTL)
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

    # 6. Construct Public Download URL & Base64 Payload
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "api.statement2muster.com")
    base_url = f"{proto}://{host}"
    download_url = f"{base_url}/v1/gpt/download/{download_id}"
    file_b64 = base64.b64encode(csv_bytes).decode("ascii")

    # 7. Update Quota Tracker for Unlicensed Users
    new_used = used_count
    remaining_free = 0
    if not is_licensed:
        new_used = used_count + 1
        gpt_free_tier_tracker.set(f"used_{client_id}", new_used)
        remaining_free = max(0, MAX_FREE_CONVERSIONS - new_used)

    # 8. Financial Summary Calculation
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

    notes = [
        "100% DSGVO & Zero Durable Storage: Datei wird rein im flüchtigen RAM vorgehalten und nach 30 Minuten unwiderruflich gelöscht.",
        f"Export kodiert in Windows-1252 mit CRLF-Zeilenenden für native {target_format.upper()}-Kompatibilität.",
        f"Buchungskonto: {req.default_bank_account or ('1200 (SKR03)' if target_format == 'datev' else '2800')}"
    ]

    if is_licensed:
        notes.append(f"Lizenzstatus: Aktiv ({plan_code.upper()}). Unbegrenzte Konvertierungen freigeschaltet.")
    else:
        notes.append(
            f"Free Tier: Auszug {new_used} von {MAX_FREE_CONVERSIONS} verbraucht. "
            f"Noch {remaining_free} kostenlose Konvertierung(en) übrig."
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
        free_tier_status=FreeTierStatus(
            is_unlimited=is_licensed,
            plan=plan_code if is_licensed else None,
            conversions_used=new_used,
            remaining_free_conversions=remaining_free,
            max_free_conversions=MAX_FREE_CONVERSIONS,
            limit_reached=False
        ),
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
