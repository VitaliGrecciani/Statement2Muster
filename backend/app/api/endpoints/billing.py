from fastapi import APIRouter, Request, Header, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.billing_service import verify_stripe_signature, process_stripe_event

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db)
):
    """
    Signed Stripe Webhook endpoint (ADR-001 / Section 5).
    Verifies raw body signature, checks inbox idempotency, and transitions entitlements.
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header"
        )

    # Must read raw bytes directly from request stream to verify signature
    body_bytes = await request.body()
    
    event = verify_stripe_signature(body_bytes, stripe_signature)
    result = await process_stripe_event(db, event)
    
    return result
