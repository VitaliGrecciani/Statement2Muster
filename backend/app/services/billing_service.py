import logging
import datetime
from typing import Dict, Any, Optional
import stripe
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.core.config import settings
from app.db.models import Tenant, CustomerMapping, Entitlement, StripeEventInbox

logger = logging.getLogger("statement2muster.billing")
stripe.api_key = settings.STRIPE_SECRET_KEY

def verify_stripe_signature(payload_bytes: bytes, sig_header: str) -> Dict[str, Any]:
    """Validates raw request body against Stripe webhook secret."""
    try:
        event = stripe.Webhook.construct_event(
            payload_bytes, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
        if hasattr(event, "to_dict"):
            return event.to_dict()
        return dict(event)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload"
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature header"
        )

async def process_stripe_event(db: AsyncSession, event: Any) -> Dict[str, Any]:
    """
    Idempotently processes Stripe event and updates entitlements (ADR-001).
    """
    if hasattr(event, "to_dict"):
        event = event.to_dict()
    elif not isinstance(event, dict):
        event = dict(event)

    event_id = event.get("id")
    event_type = event.get("type")
    
    if not event_id or not event_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed event data")

    # 1. Check idempotency inbox
    query = select(StripeEventInbox).where(StripeEventInbox.event_id == event_id)
    res = await db.execute(query)
    existing_event = res.scalars().first()
    if existing_event:
        logger.info(f"Stripe event {event_id} already processed. Skipping.")
        return {"status": "already_processed", "event_id": event_id}

    # Record into inbox immediately
    inbox_entry = StripeEventInbox(event_id=event_id, event_type=event_type, status="processing")
    db.add(inbox_entry)
    await db.flush()

    event_data = event.get("data", {}).get("object", {})

    try:
        if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            await _handle_checkout_completed(db, event_data, is_async_success=(event_type == "checkout.session.async_payment_succeeded"))
        elif event_type == "invoice.paid":
            await _handle_invoice_paid(db, event_data)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(db, event_data)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(db, event_data)
        elif event_type == "charge.refunded":
            await _handle_charge_refunded(db, event_data)
        
        inbox_entry.status = "processed"
        await db.flush()
        return {"status": "success", "event_id": event_id, "type": event_type}

    except Exception as e:
        logger.error(f"Error handling Stripe event {event_id} ({event_type}): {e}", exc_info=True)
        inbox_entry.status = "failed"
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process billing event: {str(e)}"
        )

async def _get_or_create_tenant_by_email(db: AsyncSession, email: str) -> Tenant:
    query = select(Tenant).where(Tenant.email == email)
    res = await db.execute(query)
    tenant = res.scalars().first()
    if not tenant:
        tenant = Tenant(email=email, name=email.split('@')[0])
        db.add(tenant)
        await db.flush()
    return tenant

async def _handle_checkout_completed(db: AsyncSession, session: Dict[str, Any], is_async_success: bool = False):
    payment_status = session.get("payment_status", "").lower()
    if is_async_success:
        payment_status = "paid"
    if payment_status != "paid":
        logger.warning(f"Checkout session {session.get('id')} has status '{payment_status}'. Skipping entitlement grant.")
        return

    customer_id = session.get("customer")
    customer_email = session.get("customer_details", {}).get("email") or session.get("customer_email")
    client_ref_id = session.get("client_reference_id")
    mode = session.get("mode") # payment or subscription

    if not customer_email and not client_ref_id:
        logger.warning("Checkout session missing both email and client_reference_id")
        return

    currency = (session.get("currency") or "eur").lower()
    if currency != "eur":
        logger.warning(f"Unsupported currency {currency} for checkout session {session.get('id')}")
        return

    amount_total = session.get("amount_total", 0) # in cents

    tenant = None
    if client_ref_id:
        t_res = await db.execute(select(Tenant).where(Tenant.id == client_ref_id))
        tenant = t_res.scalars().first()

    if not tenant and customer_email:
        tenant = await _get_or_create_tenant_by_email(db, customer_email)

    if not tenant:
        return

    # Map Stripe customer ID
    if customer_id:
        c_query = select(CustomerMapping).where(CustomerMapping.tenant_id == tenant.id)
        cm = (await db.execute(c_query)).scalars().first()
        if not cm:
            db.add(CustomerMapping(tenant_id=tenant.id, stripe_customer_id=customer_id))
            await db.flush()

    session_id = session.get("id")
    pi_id = session.get("payment_intent")

    # Map price_id to plan_code
    line_items_data = session.get("line_items", {}).get("data", [])
    price_id = None
    if line_items_data:
        price_id = line_items_data[0].get("price", {}).get("id")

    # Authoritative line items retrieval from Stripe API if missing from webhook payload
    if not price_id and session_id and settings.STRIPE_SECRET_KEY and settings.STRIPE_SECRET_KEY != "sk_test_mock":
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            items = stripe.checkout.Session.list_line_items(session_id, limit=5)
            if items and getattr(items, "data", None):
                price_id = items.data[0].price.id
        except Exception as e:
            logger.warning(f"Could not retrieve authoritative line items from Stripe API for session {session_id}: {e}")

    plan_code = None
    if price_id:
        if price_id in (settings.STRIPE_PRICE_LIFETIME, "price_lifetime_8900", "price_lifetime_14900"):
            plan_code = "lifetime"
        elif price_id in (settings.STRIPE_PRICE_PRO_MONTHLY, "price_pro_2900", "price_pro_1900"):
            plan_code = "pro"
        elif price_id in (settings.STRIPE_PRICE_STARTER_MONTHLY, "price_starter_490"):
            plan_code = "starter"
        else:
            plan_code = None # Explicitly unrecognized price catalog ID
    else:
        plan_code = None

    # Unknown or missing price catalog ID must be quarantined, NEVER granted active access (B06 / Architect decision)
    ent_status = "active" if plan_code else "quarantined"

    if mode == "payment":
        # Check existing entitlement for idempotent upsert
        existing = (await db.execute(select(Entitlement).where(Entitlement.source_id == session_id))).scalars().first()
        if existing:
            # If existing entitlement was quarantined / unfulfilled and authoritative plan arrives, update it
            if existing.plan_code is None and plan_code is not None:
                existing.plan_code = plan_code
                existing.status = ent_status
                existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
                await db.flush()
                logger.info(f"Idempotent fulfillment: updated session {session_id} to active plan {plan_code}")
                return
            logger.info(f"Entitlement for session {session_id} already exists, skipping duplicate event.")
            return

        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code=plan_code,
            status=ent_status,
            source_type="one_time",
            source_id=session_id,
            payment_intent=pi_id,
            valid_until=None
        )
        db.add(ent)
        await db.flush()
    elif mode == "subscription":
        sub_id = session.get("subscription")
        if not sub_id:
            logger.warning(f"Subscription checkout session {session_id} missing subscription ID.")
            return

        existing_sub = (await db.execute(select(Entitlement).where(Entitlement.source_id == sub_id))).scalars().first()
        if existing_sub:
            if plan_code:
                existing_sub.plan_code = plan_code
            existing_sub.status = ent_status
            existing_sub.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await db.flush()
            return

        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code=plan_code,
            status=ent_status,
            source_type="subscription",
            source_id=sub_id,
            payment_intent=pi_id,
            valid_until=None
        )
        db.add(ent)
        await db.flush()

async def _handle_invoice_paid(db: AsyncSession, invoice: Dict[str, Any]):
    sub_id = invoice.get("subscription")
    if not sub_id:
        return
    query = select(Entitlement).where(Entitlement.source_id == sub_id)
    ent = (await db.execute(query)).scalars().first()
    if ent:
        if ent.status == "canceled":
            logger.warning(f"Subscription {sub_id} is already canceled. Ignoring late invoice.paid.")
            return
        if ent.plan_code is None:
            logger.warning(f"Subscription {sub_id} has plan_code=None. Preserving quarantined status (C05).")
            ent.status = "quarantined"
        else:
            ent.status = "active"
        ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()

async def _handle_subscription_updated(db: AsyncSession, sub: Dict[str, Any]):
    sub_id = sub.get("id")
    status_val = sub.get("status") # active, past_due, canceled, unpaid
    mapped_status = "active" if status_val in ("active", "trialing") else ("past_due" if status_val == "past_due" else "canceled")
    
    query = select(Entitlement).where(Entitlement.source_id == sub_id)
    ent = (await db.execute(query)).scalars().first()
    if ent:
        if ent.status == "canceled":
            logger.warning(f"Subscription {sub_id} is already canceled. Ignoring stale subscription.updated.")
            return
        if mapped_status == "active" and ent.plan_code is None:
            logger.warning(f"Subscription {sub_id} has plan_code=None. Preserving quarantined status (C05).")
            ent.status = "quarantined"
        else:
            ent.status = mapped_status
        ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()

async def _handle_subscription_deleted(db: AsyncSession, sub: Dict[str, Any]):
    sub_id = sub.get("id")
    query = select(Entitlement).where(Entitlement.source_id == sub_id)
    ent = (await db.execute(query)).scalars().first()
    if ent:
        ent.status = "canceled"
        ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()

async def _handle_charge_refunded(db: AsyncSession, charge: Dict[str, Any]):
    # If refund corresponds to a lifetime or subscription checkout, cancel entitlement
    from sqlalchemy import or_
    payment_intent = str(charge.get("payment_intent") or "").strip()
    charge_id = str(charge.get("id") or "").strip()
    filters = []
    if payment_intent:
        filters.append(Entitlement.payment_intent == payment_intent)
        filters.append(Entitlement.source_id == payment_intent)
    if charge_id:
        filters.append(Entitlement.source_id == charge_id)
    if not filters:
        return
    query = select(Entitlement).where(or_(*filters))
    ent = (await db.execute(query)).scalars().first()
    if ent:
        ent.status = "canceled"
        ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()
