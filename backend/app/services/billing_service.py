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

PRICE_CATALOG = {
    settings.STRIPE_PRICE_STARTER_MONTHLY: {"plan": "starter", "amount_cents": 490, "currency": "eur", "expected_mode": "subscription", "interval": "month"},
    "price_starter_490": {"plan": "starter", "amount_cents": 490, "currency": "eur", "expected_mode": "subscription", "interval": "month"},
    settings.STRIPE_PRICE_PRO_MONTHLY: {"plan": "pro", "amount_cents": 2900, "currency": "eur", "expected_mode": "subscription", "interval": "month"},
    "price_pro_2900": {"plan": "pro", "amount_cents": 2900, "currency": "eur", "expected_mode": "subscription", "interval": "month"},
    "price_pro_1900": {"plan": "pro", "amount_cents": 1900, "currency": "eur", "expected_mode": "subscription", "interval": "month"},
    settings.STRIPE_PRICE_LIFETIME: {"plan": "lifetime", "amount_cents": 8900, "currency": "eur", "expected_mode": "payment", "interval": None},
    "price_lifetime_8900": {"plan": "lifetime", "amount_cents": 8900, "currency": "eur", "expected_mode": "payment", "interval": None},
    "price_lifetime_14900": {"plan": "lifetime", "amount_cents": 14900, "currency": "eur", "expected_mode": "payment", "interval": None},
}

def to_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Ensures datetime is timezone-aware UTC for safe comparisons across DB backends."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)

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
    raw_event_created = event.get("created")
    event_created_ts = raw_event_created if (isinstance(raw_event_created, int) and raw_event_created > 0) else None

    try:
        if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            await _handle_checkout_completed(
                db,
                event_data,
                is_async_success=(event_type == "checkout.session.async_payment_succeeded"),
                event_created_ts=event_created_ts
            )
        elif event_type == "invoice.paid":
            await _handle_invoice_paid(db, event_data, event_created_ts=event_created_ts)
        elif event_type == "invoice.payment_failed":
            await _handle_invoice_payment_failed(db, event_data, event_created_ts=event_created_ts)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(db, event_data, event_created_ts=event_created_ts)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(db, event_data, event_created_ts=event_created_ts)
        elif event_type == "charge.refunded":
            await _handle_charge_refunded(db, event_data, event_created_ts=event_created_ts)
        
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

async def _handle_checkout_completed(
    db: AsyncSession,
    session: Dict[str, Any],
    is_async_success: bool = False,
    event_created_ts: Optional[int] = None
):
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

    tenant = None
    if client_ref_id:
        t_res = await db.execute(select(Tenant).where(Tenant.id == client_ref_id))
        tenant = t_res.scalars().first()
        if not tenant:
            email_to_use = customer_email or f"{client_ref_id}@autogen.invalid"
            tenant = Tenant(id=client_ref_id, email=email_to_use, name=email_to_use.split('@')[0], version=0)
            db.add(tenant)
            await db.flush()

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

    raw_currency = session.get("currency")
    amount_total = session.get("amount_total")

    plan_code = None
    ent_status = "quarantined"

    # Strict catalog, currency, amount and mode verification (Decision 32: S01, S04)
    # Financial policy: All catalog plans have strict fixed EUR gross amounts (VAT included).
    # No client-side discounts, 0 amounts, negative values or missing fields are permitted.
    if not isinstance(raw_currency, str) or raw_currency.strip().lower() != "eur":
        logger.warning(f"Invalid or missing currency '{raw_currency}' for checkout session {session_id}. Quarantining.")
    elif not price_id or price_id not in PRICE_CATALOG:
        logger.warning(f"Unrecognized or missing price ID '{price_id}' for session {session_id}. Quarantining.")
    else:
        expected = PRICE_CATALOG[price_id]
        # Strict validation of amount_total: must be int, > 0, exact match with catalog (S01)
        if type(amount_total) is not int or amount_total <= 0 or amount_total != expected["amount_cents"]:
            logger.warning(
                f"Amount validation failed for price {price_id}: expected {expected['amount_cents']}, got {amount_total} (type={type(amount_total).__name__}). Quarantining."
            )
        # Strict validation of mode vs catalog plan (S04)
        elif mode != expected.get("expected_mode"):
            logger.warning(
                f"Mode mismatch for price {price_id}: expected '{expected.get('expected_mode')}', got '{mode}'. Quarantining."
            )
        else:
            plan_code = expected["plan"]
            ent_status = "active"

    if mode == "payment":
        # Check existing entitlement for idempotent upsert
        existing = (await db.execute(select(Entitlement).where(Entitlement.source_id == session_id))).scalars().first()
        if existing:
            # S02: If existing entitlement was canceled/refunded, do NOT revive it!
            if existing.status == "canceled":
                logger.warning(f"One-time payment {session_id} is already canceled/refunded. Ignoring late checkout session.")
                return
            # S03: Out-of-order check
            if existing.last_event_created_at and event_created_ts and event_created_ts < existing.last_event_created_at:
                logger.warning(f"Late out-of-order checkout session {session_id}. Ignoring.")
                return
            # If existing entitlement was quarantined / unfulfilled and authoritative plan arrives, update it
            if existing.plan_code is None and plan_code is not None:
                existing.plan_code = plan_code
                existing.status = ent_status
                if event_created_ts:
                    existing.last_event_created_at = event_created_ts
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
            valid_until=None, # Lifetime access never expires
            last_event_created_at=event_created_ts or 0
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
            # S02: If existing subscription is canceled, do NOT revive it!
            if existing_sub.status == "canceled":
                logger.warning(f"Subscription {sub_id} is already canceled. Ignoring late checkout session {session_id}.")
                return
            # S03: Out-of-order check
            if existing_sub.last_event_created_at and event_created_ts and event_created_ts < existing_sub.last_event_created_at:
                logger.warning(f"Late out-of-order checkout session {session_id} for subscription {sub_id}. Ignoring.")
                return
            if plan_code and existing_sub.status == "quarantined" and ent_status == "active":
                existing_sub.plan_code = plan_code
                existing_sub.status = "active"
            if event_created_ts and (not existing_sub.last_event_created_at or event_created_ts > existing_sub.last_event_created_at):
                existing_sub.last_event_created_at = event_created_ts
            existing_sub.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await db.flush()
            return

        now_ts = datetime.datetime.now(datetime.timezone.utc)
        initial_period_start = now_ts - datetime.timedelta(seconds=10)
        initial_valid_until = (now_ts + datetime.timedelta(days=30)) if ent_status == "active" else None
        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code=plan_code,
            status=ent_status,
            source_type="subscription",
            source_id=sub_id,
            payment_intent=pi_id,
            current_period_start=initial_period_start if ent_status == "active" else None,
            valid_until=initial_valid_until,
            last_event_created_at=event_created_ts or 0
        )
        db.add(ent)
        await db.flush()

    else:
        logger.warning(f"Unknown checkout mode '{mode}' for session {session_id}. Quarantining.")
        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code=None,
            status="quarantined",
            source_type="unknown",
            source_id=session_id,
            payment_intent=pi_id,
            valid_until=None,
            last_event_created_at=event_created_ts or 0
        )
        db.add(ent)
        await db.flush()

async def _handle_invoice_paid(db: AsyncSession, invoice: Dict[str, Any], event_created_ts: Optional[int] = None):
    sub_id = invoice.get("subscription")
    if not sub_id:
        return
    query = select(Entitlement).where(Entitlement.source_id == sub_id)
    ent = (await db.execute(query)).scalars().first()
    if not ent:
        return

    # S02: Canceled subscription cannot be revived by late invoice.paid
    if ent.status == "canceled":
        logger.warning(f"Subscription {sub_id} is already canceled. Ignoring late invoice.paid.")
        return

    # S03: Out-of-order check based on event creation timestamp
    if event_created_ts and ent.last_event_created_at and event_created_ts < ent.last_event_created_at:
        logger.warning(
            f"Stale invoice.paid for subscription {sub_id}: event ts {event_created_ts} < last processed {ent.last_event_created_at}. Ignoring."
        )
        return

    # S03 & Section 3: Authoritative period tracking
    lines = invoice.get("lines", {}).get("data", [])
    period_start_ts = None
    period_end_ts = None
    if lines:
        period_start_ts = lines[0].get("period", {}).get("start")
        period_end_ts = lines[0].get("period", {}).get("end")
    if not period_end_ts:
        period_end_ts = invoice.get("period_end")

    if period_end_ts:
        new_valid_until = datetime.datetime.fromtimestamp(period_end_ts, tz=datetime.timezone.utc)
        cur_valid = to_utc(ent.valid_until)
        if cur_valid and new_valid_until < cur_valid:
            logger.warning(
                f"Stale invoice.paid for subscription {sub_id}: period end {new_valid_until} < current valid_until {cur_valid}. Ignoring."
            )
            return
        if cur_valid is None or new_valid_until >= cur_valid:
            ent.valid_until = new_valid_until
            if period_start_ts:
                ent.current_period_start = datetime.datetime.fromtimestamp(period_start_ts, tz=datetime.timezone.utc)
            elif ent.current_period_start is None:
                ent.current_period_start = new_valid_until - datetime.timedelta(days=30)

    if ent.plan_code is None:
        logger.warning(f"Subscription {sub_id} has plan_code=None. Preserving quarantined status (C05).")
        ent.status = "quarantined"
    else:
        ent.status = "active"

    if event_created_ts and (not ent.last_event_created_at or event_created_ts > ent.last_event_created_at):
        ent.last_event_created_at = event_created_ts

    ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()

async def _handle_invoice_payment_failed(db: AsyncSession, invoice: Dict[str, Any], event_created_ts: Optional[int] = None):
    sub_id = invoice.get("subscription")
    if not sub_id:
        return
    query = select(Entitlement).where(Entitlement.source_id == sub_id)
    ent = (await db.execute(query)).scalars().first()
    if not ent:
        return

    # S02: Canceled subscription cannot transition to past_due
    if ent.status == "canceled":
        logger.warning(f"Subscription {sub_id} is already canceled. Ignoring invoice.payment_failed.")
        return

    # S03: Out-of-order check based on event creation timestamp
    if event_created_ts and ent.last_event_created_at and event_created_ts < ent.last_event_created_at:
        logger.warning(
            f"Stale invoice.payment_failed for subscription {sub_id}: event ts {event_created_ts} < last processed {ent.last_event_created_at}. Ignoring."
        )
        return

    # S03: Period ordering check: if current valid_until is ahead of the failed invoice period, ignore
    lines = invoice.get("lines", {}).get("data", [])
    period_end_ts = None
    if lines:
        period_end_ts = lines[0].get("period", {}).get("end")
    if not period_end_ts:
        period_end_ts = invoice.get("period_end")

    if period_end_ts and ent.valid_until:
        failed_period_end = datetime.datetime.fromtimestamp(period_end_ts, tz=datetime.timezone.utc)
        cur_valid = to_utc(ent.valid_until)
        if cur_valid and failed_period_end < cur_valid:
            logger.warning(
                f"Stale invoice.payment_failed for subscription {sub_id}: failed period {failed_period_end} < current valid_until {cur_valid}. Ignoring."
            )
            return

    ent.status = "past_due"
    if event_created_ts and (not ent.last_event_created_at or event_created_ts > ent.last_event_created_at):
        ent.last_event_created_at = event_created_ts

    ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()
    logger.info(f"Subscription {sub_id} marked as past_due due to invoice.payment_failed.")

async def _handle_subscription_updated(db: AsyncSession, sub: Dict[str, Any], event_created_ts: Optional[int] = None):
    sub_id = sub.get("id")
    status_val = sub.get("status") # active, past_due, canceled, unpaid
    cancel_at_period_end = sub.get("cancel_at_period_end", False)
    current_period_end_ts = sub.get("current_period_end")
    
    query = select(Entitlement).where(Entitlement.source_id == sub_id)
    ent = (await db.execute(query)).scalars().first()
    if not ent:
        return

    # S02: Canceled subscription cannot be revived
    if ent.status == "canceled":
        logger.warning(f"Subscription {sub_id} is already canceled. Ignoring stale subscription.updated.")
        return

    # S03: Out-of-order check based on event creation timestamp
    if event_created_ts and ent.last_event_created_at and event_created_ts < ent.last_event_created_at:
        logger.warning(
            f"Stale subscription.updated for subscription {sub_id}: event ts {event_created_ts} < last processed {ent.last_event_created_at}. Ignoring."
        )
        return

    # Update valid_until forward only
    if current_period_end_ts:
        new_valid = datetime.datetime.fromtimestamp(current_period_end_ts, tz=datetime.timezone.utc)
        cur_valid = to_utc(ent.valid_until)
        if cur_valid is None or new_valid >= cur_valid:
            ent.valid_until = new_valid

    # S04: Check items and price ID in catalog.
    # An unknown price ID or incompatible mode must NOT preserve existing privileges!
    items = sub.get("items", {}).get("data", [])
    if items:
        p_id = items[0].get("price", {}).get("id")
        if p_id in PRICE_CATALOG:
            cat_entry = PRICE_CATALOG[p_id]
            if cat_entry.get("expected_mode") != "subscription":
                logger.warning(f"Subscription {sub_id} item price {p_id} has invalid mode {cat_entry.get('expected_mode')}. Quarantining.")
                ent.plan_code = None
                ent.status = "quarantined"
            else:
                ent.plan_code = cat_entry["plan"]
        else:
            logger.warning(f"Subscription {sub_id} item price '{p_id}' unknown in catalog. Stripping plan_code and quarantining.")
            ent.plan_code = None
            ent.status = "quarantined"

    if ent.status != "quarantined":
        if status_val == "canceled":
            mapped_status = "canceled"
        elif status_val == "past_due":
            mapped_status = "past_due"
        elif cancel_at_period_end and status_val in ("active", "trialing"):
            # Grace period active until valid_until
            mapped_status = "active"
        elif status_val in ("active", "trialing"):
            mapped_status = "active"
        else:
            mapped_status = "canceled"

        if mapped_status == "active" and ent.plan_code is None:
            logger.warning(f"Subscription {sub_id} has plan_code=None. Preserving quarantined status (C05).")
            ent.status = "quarantined"
        else:
            ent.status = mapped_status

    if event_created_ts and (not ent.last_event_created_at or event_created_ts > ent.last_event_created_at):
        ent.last_event_created_at = event_created_ts

    ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()

async def _handle_subscription_deleted(db: AsyncSession, sub: Dict[str, Any], event_created_ts: Optional[int] = None):
    sub_id = sub.get("id")
    query = select(Entitlement).where(Entitlement.source_id == sub_id)
    ent = (await db.execute(query)).scalars().first()
    if ent:
        ent.status = "canceled"
        if event_created_ts and (not ent.last_event_created_at or event_created_ts > ent.last_event_created_at):
            ent.last_event_created_at = event_created_ts
        ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()

async def _handle_charge_refunded(db: AsyncSession, charge: Dict[str, Any], event_created_ts: Optional[int] = None):
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
        if event_created_ts and (not ent.last_event_created_at or event_created_ts > ent.last_event_created_at):
            ent.last_event_created_at = event_created_ts
        ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()
