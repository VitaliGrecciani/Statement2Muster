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
        if not tenant and customer_email:
            t_res_email = await db.execute(select(Tenant).where(Tenant.email == customer_email.lower().strip()))
            tenant = t_res_email.scalars().first()
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

            # Decision 34 Point 3: Tenant Hijacking defense!
            # If subscription was pre-provisioned or already belongs to tenant A,
            # a subsequent checkout with a different tenant B CANNOT hijack the subscription!
            if existing_sub.tenant_id and existing_sub.tenant_id != tenant.id:
                logger.error(
                    f"Security Alert: Tenant mismatch for subscription {sub_id}. "
                    f"Existing tenant {existing_sub.tenant_id} != session tenant {tenant.id}. Quarantining."
                )
                existing_sub.status = "quarantined"
                existing_sub.plan_code = None
                existing_sub.updated_at = datetime.datetime.now(datetime.timezone.utc)
                await db.flush()
                return

            if plan_code and existing_sub.status == "quarantined" and ent_status == "active":
                existing_sub.plan_code = plan_code
                existing_sub.status = "active"

            if pi_id and not existing_sub.payment_intent:
                existing_sub.payment_intent = pi_id

            if event_created_ts and (not existing_sub.last_event_created_at or event_created_ts > existing_sub.last_event_created_at):
                existing_sub.last_event_created_at = event_created_ts
            existing_sub.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await db.flush()
            return

        # Decision 34 Point 2: Bounded provisional deadline (72 hours)
        # Check if explicit authoritative period bounds are provided in session payload or subscription object
        explicit_period_start = session.get("current_period_start") or session.get("period_start")
        explicit_period_end = session.get("current_period_end") or session.get("period_end") or session.get("subscription_period_end")
        sub_obj = session.get("subscription")
        if isinstance(sub_obj, dict):
            if not explicit_period_start:
                explicit_period_start = sub_obj.get("current_period_start")
            if not explicit_period_end:
                explicit_period_end = sub_obj.get("current_period_end")

        now_ts = datetime.datetime.now(datetime.timezone.utc)
        PROVISIONAL_DEADLINE_HOURS = 72

        if explicit_period_start and explicit_period_end:
            init_start = datetime.datetime.fromtimestamp(explicit_period_start, tz=datetime.timezone.utc)
            init_valid = datetime.datetime.fromtimestamp(explicit_period_end, tz=datetime.timezone.utc)
            has_authoritative = 1
            prov_deadline = None
            paid_thr = init_valid
        else:
            # Provisional access with strict bounded deadline (72 hours)
            # NEVER set valid_until=None for a subscription, which would grant infinite access!
            init_start = now_ts
            prov_deadline = now_ts + datetime.timedelta(hours=PROVISIONAL_DEADLINE_HOURS)
            init_valid = prov_deadline
            has_authoritative = 0
            paid_thr = None

        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code=plan_code,
            status=ent_status,
            source_type="subscription",
            source_id=sub_id,
            payment_intent=pi_id,
            current_period_start=init_start if ent_status == "active" else None,
            valid_until=init_valid if ent_status == "active" else None,
            paid_through=paid_thr if ent_status == "active" else None,
            provisional_deadline=prov_deadline if ent_status == "active" else None,
            has_authoritative_period=has_authoritative,
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
            has_authoritative_period=0,
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

    lines = invoice.get("lines", {}).get("data", [])
    period_start_ts = None
    period_end_ts = None
    if lines:
        period_start_ts = lines[0].get("period", {}).get("start")
        period_end_ts = lines[0].get("period", {}).get("end")
    if not period_end_ts:
        period_end_ts = invoice.get("period_end")
    if not period_start_ts:
        period_start_ts = invoice.get("period_start")

    # Delayed checkout delivery handling:
    # If invoice.paid arrives BEFORE checkout.session.completed, pre-provision entitlement
    if not ent:
        # Decision 34 Point 3: Early invoice.paid MUST satisfy strict catalog policy, amount, currency, and period bounds!
        if not lines:
            logger.warning(f"Early invoice.paid for subscription {sub_id} has no lines.data. Ignoring.")
            return

        p_id = lines[0].get("price", {}).get("id")
        amount_paid = invoice.get("amount_paid") if invoice.get("amount_paid") is not None else invoice.get("total")
        currency = invoice.get("currency")

        is_valid = True
        plan_code = None

        # 1. Price Catalog validation
        if not p_id or p_id not in PRICE_CATALOG:
            logger.warning(f"Early invoice for subscription {sub_id} has unknown price {p_id}. Quarantining.")
            is_valid = False
        else:
            cat_entry = PRICE_CATALOG[p_id]
            if cat_entry.get("expected_mode") != "subscription":
                logger.warning(f"Early invoice price {p_id} expected_mode mismatch ({cat_entry.get('expected_mode')}). Quarantining.")
                is_valid = False
            else:
                # 2. Strict amount & currency validation (S01)
                if not (isinstance(amount_paid, int) and amount_paid == cat_entry["amount_cents"]):
                    logger.warning(f"Early invoice amount {amount_paid} != expected {cat_entry['amount_cents']}. Quarantining.")
                    is_valid = False
                if not (isinstance(currency, str) and currency.lower() == "eur"):
                    logger.warning(f"Early invoice currency {currency} != eur. Quarantining.")
                    is_valid = False
                if is_valid:
                    plan_code = cat_entry["plan"]

        # 3. Period completeness validation (Decision 34 Point 3)
        if not period_start_ts or not period_end_ts or period_end_ts <= period_start_ts:
            logger.warning(f"Early invoice has invalid or missing period bounds ({period_start_ts}, {period_end_ts}). Quarantining.")
            is_valid = False
            plan_code = None

        email = invoice.get("customer_email")
        tenant_id = invoice.get("client_reference_id") or invoice.get("metadata", {}).get("tenant_id")
        tenant = None
        if tenant_id:
            tenant = await db.get(Tenant, tenant_id)
            if not tenant and email:
                tenant = (await db.execute(select(Tenant).where(Tenant.email == email.lower().strip()))).scalars().first()
            if not tenant:
                email_to_use = email or f"{tenant_id}@placeholder.banksync.internal"
                tenant = Tenant(id=tenant_id, email=email_to_use.lower().strip(), name=email_to_use.split('@')[0])
                db.add(tenant)
                await db.flush()
        elif email:
            tenant = (await db.execute(select(Tenant).where(Tenant.email == email.lower().strip()))).scalars().first()
            if not tenant:
                tenant = Tenant(email=email.lower().strip(), name=email.split("@")[0])
                db.add(tenant)
                await db.flush()

        if not tenant:
            cus_id = invoice.get("customer") or sub_id
            placeholder_email = f"{cus_id}@placeholder.banksync.internal"
            tenant = Tenant(email=placeholder_email, name="Pending Fulfillment")
            db.add(tenant)
            await db.flush()

        valid_until_dt = datetime.datetime.fromtimestamp(period_end_ts, tz=datetime.timezone.utc) if (is_valid and period_end_ts) else None
        period_start_dt = datetime.datetime.fromtimestamp(period_start_ts, tz=datetime.timezone.utc) if (is_valid and period_start_ts) else None

        ent = Entitlement(
            tenant_id=tenant.id,
            plan_code=plan_code,
            status="active" if is_valid else "quarantined",
            source_type="subscription",
            source_id=sub_id,
            current_period_start=period_start_dt or datetime.datetime.now(datetime.timezone.utc),
            valid_until=valid_until_dt,
            paid_through=valid_until_dt if is_valid else None,
            provisional_deadline=None,
            has_authoritative_period=1 if is_valid else 0,
            last_invoice_id=invoice.get("id"),
            last_invoice_status="paid" if is_valid else "quarantined",
            last_event_created_at=event_created_ts or 0
        )
        db.add(ent)
        await db.flush()
        logger.info(f"Pre-provisioned entitlement for subscription {sub_id} from early invoice.paid (status={ent.status}, plan={ent.plan_code}).")
        return

    # S02: Canceled subscription cannot be revived by late invoice.paid
    if ent.status == "canceled":
        logger.warning(f"Subscription {sub_id} is already canceled. Ignoring late invoice.paid.")
        return

    # S03: Out-of-order check based on event creation timestamp
    # Decision 34 Point 1: Check before ANY mutation!
    if event_created_ts and ent.last_event_created_at and event_created_ts < ent.last_event_created_at:
        logger.warning(
            f"Stale invoice.paid for subscription {sub_id}: event ts {event_created_ts} < last processed {ent.last_event_created_at}. Ignoring without mutation."
        )
        return

    # Decision 34 Point 1 & Decision 35: Check period monotonicity against paid_through BEFORE mutating ent!
    candidate_valid_until = None
    if period_end_ts:
        candidate_valid_until = datetime.datetime.fromtimestamp(period_end_ts, tz=datetime.timezone.utc)
    
    cur_paid = to_utc(ent.paid_through)
    cur_valid = to_utc(ent.valid_until)

    # Decision 35: If entitlement has an authoritative paid period, an invoice for an earlier period is STALE and MUST NOT mutate ent!
    if ent.has_authoritative_period and cur_paid and candidate_valid_until and candidate_valid_until < cur_paid:
        logger.warning(
            f"Stale invoice.paid for subscription {sub_id}: period end {candidate_valid_until} < current paid_through {cur_paid}. Ignoring without mutation."
        )
        return

    # Determine candidate plan from invoice lines
    candidate_plan = ent.plan_code
    if lines:
        p_obj = lines[0].get("price")
        if p_obj and isinstance(p_obj, dict) and p_obj.get("id"):
            p_id = p_obj.get("id")
            if p_id in PRICE_CATALOG:
                cat_entry = PRICE_CATALOG[p_id]
                if cat_entry.get("expected_mode") == "subscription":
                    candidate_plan = cat_entry["plan"]
                else:
                    candidate_plan = None
            else:
                candidate_plan = None

    # All validations passed! Apply changes atomically to ent:
    ent.plan_code = candidate_plan
    if candidate_plan is None:
        ent.status = "quarantined"
    else:
        ent.status = "active"

    if candidate_valid_until:
        if not ent.has_authoritative_period or cur_paid is None:
            # First authoritative period confirmed from invoice (reconciles provisional access)
            ent.valid_until = candidate_valid_until
            ent.paid_through = candidate_valid_until
            if period_start_ts:
                ent.current_period_start = datetime.datetime.fromtimestamp(period_start_ts, tz=datetime.timezone.utc)
            elif ent.current_period_start is None:
                ent.current_period_start = candidate_valid_until - datetime.timedelta(days=30)
            ent.has_authoritative_period = 1
            ent.provisional_deadline = None
        else:
            # Decision 35: Compare candidate_valid_until against cur_paid (NOT cur_valid)!
            # Even if subscription.updated moved valid_until ahead, a new invoice payment with candidate_valid_until > cur_paid
            # is a NEW PAID PERIOD and MUST advance current_period_start and reset quota!
            if candidate_valid_until > cur_paid:
                ent.valid_until = max(candidate_valid_until, cur_valid) if cur_valid else candidate_valid_until
                ent.paid_through = candidate_valid_until
                if period_start_ts:
                    ent.current_period_start = datetime.datetime.fromtimestamp(period_start_ts, tz=datetime.timezone.utc)
                ent.has_authoritative_period = 1
                ent.provisional_deadline = None
            elif candidate_valid_until == cur_paid:
                # Same period duplicate/adjustment:
                # Do NOT shift current_period_start and do NOT reset quota!
                ent.paid_through = candidate_valid_until
                ent.has_authoritative_period = 1
                ent.provisional_deadline = None

    ent.last_invoice_id = invoice.get("id")
    ent.last_invoice_status = "paid"
    if event_created_ts and (not ent.last_event_created_at or event_created_ts > ent.last_event_created_at):
        ent.last_event_created_at = event_created_ts

    ent.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()
    logger.info(f"Subscription {sub_id} updated from invoice.paid (status={ent.status}, plan={ent.plan_code}, valid_until={ent.valid_until}).")

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

    invoice_id = invoice.get("id")

    # 1. Check Invoice ID identity:
    # If this exact invoice was already marked "paid", this is an older/concurrent failed attempt
    if invoice_id and ent.last_invoice_id == invoice_id and ent.last_invoice_status == "paid":
        logger.warning(
            f"Ignoring invoice.payment_failed for invoice {invoice_id} as this invoice is already paid."
        )
        return

    # 2. Paid-through check (Decision 34 Point 4):
    # Use paid_through (NOT valid_until), because valid_until can be advanced by subscription.updated without payment!
    lines = invoice.get("lines", {}).get("data", [])
    period_end_ts = None
    if lines:
        period_end_ts = lines[0].get("period", {}).get("end")
    if not period_end_ts:
        period_end_ts = invoice.get("period_end")

    cur_paid = to_utc(ent.paid_through)
    if period_end_ts and cur_paid:
        failed_period_end = datetime.datetime.fromtimestamp(period_end_ts, tz=datetime.timezone.utc)
        # If subscription is active and has ALREADY been paid through cur_paid:
        # Only failures for periods <= paid_through are superseded by confirmed payment!
        if ent.status == "active" and failed_period_end <= cur_paid:
            logger.warning(
                f"Ignoring invoice.payment_failed for subscription {sub_id}: failed period {failed_period_end} <= current paid_through {cur_paid}."
            )
            return

    # 3. Check event timestamp:
    if event_created_ts and ent.last_event_created_at:
        if event_created_ts < ent.last_event_created_at:
            logger.warning(
                f"Stale invoice.payment_failed for subscription {sub_id}: event ts {event_created_ts} < last processed {ent.last_event_created_at}. Ignoring."
            )
            return

    ent.status = "past_due"
    ent.last_invoice_id = invoice_id
    ent.last_invoice_status = "payment_failed"
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

    # Update valid_until and current_period_start
    if current_period_end_ts:
        new_valid = datetime.datetime.fromtimestamp(current_period_end_ts, tz=datetime.timezone.utc)
        cur_valid = to_utc(ent.valid_until)
        if not ent.has_authoritative_period or cur_valid is None or new_valid >= cur_valid:
            ent.valid_until = new_valid
            ent.has_authoritative_period = 1

    current_period_start_ts = sub.get("current_period_start")
    if current_period_start_ts and (not ent.current_period_start or ent.has_authoritative_period == 0):
        ent.current_period_start = datetime.datetime.fromtimestamp(current_period_start_ts, tz=datetime.timezone.utc)

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
