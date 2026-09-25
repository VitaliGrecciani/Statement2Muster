import io
import re
import uuid
import datetime
import logging
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal
from fastapi import APIRouter, HTTPException, Request, Response, status, Header
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.cache import BoundedMemoryCache
from app.schemas.canonical import CanonicalTransaction
from app.exporters.datev import export_to_datev_csv
from app.exporters.bmd import export_to_bmd_csv
from app.exporters.muster_csv import export_to_muster_csv
from app.parsers.registry import registry, UnsupportedFormatError

logger = logging.getLogger("statement2muster.gpt")

router = APIRouter(prefix="/api/v1/gpt", tags=["gpt-action"])

# Dedicated volatile in-memory cache for ChatGPT download links (Zero Durable Retention)
# TTL = 30 minutes (1800s), budget = 30 MiB, max 300 files
gpt_download_cache = BoundedMemoryCache(
    ttl_seconds=1800,
    max_bytes=30 * 1024 * 1024,
    max_entries=300
)

# Standard verified Stripe pricing checkout links
STRIPE_LINKS = {
    "starter": "https://buy.stripe.com/cNi6oH9vDcnL2v0dWTebu03",
    "pro": "https://buy.stripe.com/14AfZh6jr2NbedI6urebu04",
    "lifetime": "https://buy.stripe.com/14A00j6jrfzX2v0bOLebu05"
}

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
        "%m/%d/%Y"
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

# --- Request / Response Models ---

class GptTransactionItem(BaseModel):
    booking_date: str = Field(
        ...,
        description="Booking date in YYYY-MM-DD or DD.MM.YYYY format",
        example="2026-03-15"
    )
    value_date: Optional[str] = Field(
        None,
        description="Optional value/valuta date in YYYY-MM-DD or DD.MM.YYYY format",
        example="2026-03-16"
    )
    amount: float = Field(
        ...,
        description="Transaction amount. Negative for expense/debit, positive for income/credit",
        example=-145.20
    )
    currency: Optional[str] = Field(
        "EUR",
        description="ISO 4217 currency code (e.g. EUR, USD, CHF, GBP)",
        example="EUR"
    )
    description: str = Field(
        ...,
        description="Transaction description, payee, or payment purpose (Buchungstext)",
        example="AWS EMEA SARL Cloud Services"
    )
    reference: Optional[str] = Field(
        None,
        description="Invoice, voucher or reference ID (Belegfeld 1 / Belegnummer)",
        example="INV-2026-98102"
    )
    contra_account: Optional[str] = Field(
        None,
        description="Optional pre-assigned bookkeeping contra account / Gegenkonto (e.g. '4900' for SKR03)",
        example="4900"
    )

class GptConvertRequest(BaseModel):
    bank_name: Optional[str] = Field(
        "Bank Statement",
        description="Name of the financial institution or card provider (e.g. American Express, Wise, PayPal, Sparkasse)",
        example="American Express"
    )
    export_format: Literal["datev", "bmd", "muster_csv"] = Field(
        "datev",
        description="Target accounting export format: 'datev' (EXTF 700 Windows-1252), 'bmd' (NTCS 5.1), or 'muster_csv'",
        example="datev"
    )
    default_bank_account: Optional[str] = Field(
        None,
        description="Bank ledger account (e.g. '1200' for SKR03, '1800' for SKR04, '2800' for BMD NTCS). Defaults to 1200 for DATEV and 2800 for BMD.",
        example="1200"
    )
    transactions: Optional[List[GptTransactionItem]] = Field(
        None,
        description="Array of structured transactions extracted by ChatGPT from the bank statement document."
    )
    raw_content: Optional[str] = Field(
        None,
        description="Optional raw CSV or plaintext content of statement if transactions were not extracted by ChatGPT."
    )
    filename: Optional[str] = Field(
        "statement.csv",
        description="Original statement filename hint."
    )
    license_key: Optional[str] = Field(
        None,
        description="Optional Statement2Muster Pro or Lifetime license key to bypass free quota limits."
    )

class FinancialSummary(BaseModel):
    transaction_count: int = Field(..., description="Total number of processed bookings")
    total_debit: float = Field(..., description="Total sum of expenses/debits (negative or outgoing money)")
    total_credit: float = Field(..., description="Total sum of incomes/credits (incoming money)")
    net_balance: float = Field(..., description="Net balance turnover for the statement period")
    currency: str = Field("EUR", description="Primary currency")
    date_from: Optional[str] = Field(None, description="Earliest booking date in batch (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="Latest booking date in batch (YYYY-MM-DD)")

class GptConvertResponse(BaseModel):
    status: Literal["success", "warning", "error"] = "success"
    message: str = Field(..., description="Status message explaining outcome")
    export_format: str = Field(..., description="Target export format produced")
    filename: str = Field(..., description="Generated export file name")
    download_id: str = Field(..., description="Ephemeral token for downloading the file")
    download_url: str = Field(..., description="Direct temporary URL to download the generated file")
    expires_in_minutes: int = Field(30, description="Time until the download link expires (RAM-only retention)")
    summary: FinancialSummary = Field(..., description="Financial turnover summary for accounting verification")
    preview_csv: str = Field(..., description="First 5 lines preview of the generated DATEV/BMD file")
    notes: List[str] = Field(default_factory=list, description="Compliance and accounting notes")
    upgrade_info: Dict[str, str] = Field(default_factory=dict, description="Links to unlock unlimited conversions")

# --- Endpoints ---

@router.post("/convert", response_model=GptConvertResponse)
async def gpt_convert_statement(req: GptConvertRequest, request: Request):
    """
    OpenAPI Action for ChatGPT Custom GPT:
    Converts bank transactions (extracted from PDF or CSV) into official DATEV EXTF 700 or BMD NTCS 5.1 files.
    
    Adheres strictly to Zero Durable Storage:
    Outputs are placed into ephemeral RAM-only cache with 30-minute TTL and immediate eviction.
    """
    canonical_txs: List[CanonicalTransaction] = []
    bank_name = req.bank_name or "Bank Statement"

    # Branch A: Structured transactions list provided by ChatGPT
    if req.transactions and len(req.transactions) > 0:
        # Free-tier limit check (50 transactions per conversion for unlicensed requests)
        max_free_txs = 50
        has_license = bool(req.license_key and len(req.license_key.strip()) > 8)
        tx_items = req.transactions
        limit_applied = False

        if not has_license and len(tx_items) > max_free_txs:
            tx_items = tx_items[:max_free_txs]
            limit_applied = True

        for idx, item in enumerate(tx_items):
            booking_dt = parse_flexible_date(item.booking_date)
            if not booking_dt:
                # Fallback to today if unparseable
                booking_dt = datetime.date.today()

            value_dt = parse_flexible_date(item.value_date) if item.value_date else booking_dt
            curr = normalize_currency(item.currency)
            
            # Integer cents conversion to eliminate float rounding errors
            try:
                dec_val = Decimal(str(item.amount))
                amount_cents = int(round(dec_val * 100))
            except Exception:
                amount_cents = int(round(item.amount * 100))

            tx = CanonicalTransaction(
                transaction_id=str(uuid.uuid4()),
                tenant_id="chatgpt-user",
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

    # Branch B: Raw CSV/plaintext content provided
    elif req.raw_content and len(req.raw_content.strip()) > 0:
        raw_bytes = req.raw_content.encode("utf-8")
        try:
            parsed_txs, _ = registry.parse_file(
                content=raw_bytes,
                filename=req.filename or "statement.csv",
                tenant_id="chatgpt-user"
            )
            canonical_txs = parsed_txs
            limit_applied = False
        except UnsupportedFormatError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse raw statement: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Raw content parse failure: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal parsing error: {str(e)}"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'transactions' array or 'raw_content' string must be provided."
        )

    if not canonical_txs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid transactions could be parsed from input."
        )

    # 2. Exporter selection and byte generation
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
    else: # Default to datev
        default_acc = req.default_bank_account or "1200"
        csv_bytes = export_to_datev_csv(canonical_txs, default_bank_account=default_acc)
        out_filename = f"DATEV_EXTF_{sanitized_bank}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        media_type = "text/csv"

    # 3. Store in Zero-Retention Volatile RAM Cache (30 min TTL)
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

    # 4. Construct Public Download URL
    # Respect Forwarded / Host header or fallback to settings.BASE_PUBLIC_URL
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "api.statement2muster.com")
    base_url = f"{proto}://{host}"
    download_url = f"{base_url}/api/v1/gpt/download/{download_id}"

    # 5. Financial Summary Calculation
    total_debit_cents = sum(tx.amount_cents for tx in canonical_txs if tx.amount_cents < 0)
    total_credit_cents = sum(tx.amount_cents for tx in canonical_txs if tx.amount_cents > 0)
    net_cents = sum(tx.amount_cents for tx in canonical_txs)
    
    dates = [tx.booking_date for tx in canonical_txs if tx.booking_date]
    min_date = min(dates).isoformat() if dates else None
    max_date = max(dates).isoformat() if dates else None

    # First 5 lines for chat preview (decode Windows-1252 safely)
    preview_text = ""
    try:
        decoded = csv_bytes.decode("windows-1252", errors="replace")
        preview_lines = decoded.splitlines()[:5]
        preview_text = "\n".join(preview_lines)
    except Exception:
        preview_text = "(Preview generation unavailable)"

    notes = [
        "100% DSGVO & Zero Durable Storage: File is stored in volatile RAM only and expires in 30 minutes.",
        f"Export encoded in Windows-1252 with CRLF line endings for native {target_format.upper()} compatibility.",
        f"Bank account: {req.default_bank_account or ('1200 (SKR03)' if target_format == 'datev' else '2800')}"
    ]

    status_code_str = "success"
    if limit_applied:
        status_code_str = "warning"
        notes.append(
            f"Free Tier Limit: First {max_free_txs} transactions were converted. Upgrade to Pro for unlimited exports and multi-month upload."
        )

    return GptConvertResponse(
        status=status_code_str,
        message=f"Successfully generated {target_format.upper()} file with {len(canonical_txs)} transactions.",
        export_format=target_format,
        filename=out_filename,
        download_id=download_id,
        download_url=download_url,
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
        notes=notes,
        upgrade_info=STRIPE_LINKS
    )


@router.get("/download/{download_id}")
async def gpt_download_file(download_id: str):
    """
    Downloads the generated DATEV/BMD file from ephemeral RAM cache.
    Zero Durable Retention: File data is served directly from RAM without disk touches.
    """
    item = gpt_download_cache.get(download_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Download link has expired or does not exist. "
                "Per our Zero Durable Retention privacy policy, files are purged from memory after 30 minutes. "
                "Please run the conversion again in ChatGPT."
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
