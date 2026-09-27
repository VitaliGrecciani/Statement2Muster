import datetime
from typing import Optional
from sqlalchemy import select, func, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.db.models import Entitlement, UsageReservation, Tenant
from app.core.config import settings

PLAN_PRIORITY = {"lifetime": 1, "pro": 2, "starter": 3, "kanzlei_trial": 4, "trial": 5}

async def get_or_create_trial_entitlement(db: AsyncSession, tenant_id: str) -> Entitlement:
    """Ensures each tenant has an initial trial or active entitlement, prioritizing paid plans."""
    now = datetime.datetime.now(datetime.timezone.utc)
    query = select(Entitlement).where(
        and_(Entitlement.tenant_id == tenant_id, Entitlement.status == "active")
    )
    result = await db.execute(query)
    all_ents = result.scalars().all()
    if all_ents:
        # Filter valid entitlements by valid_until and sort by plan priority (Lifetime > PRO > Starter > Trial)
        valid_ents = []
        for e in all_ents:
            if not e.plan_code or e.plan_code.lower() not in PLAN_PRIORITY:
                continue
            if e.valid_until is not None:
                exp = e.valid_until if e.valid_until.tzinfo else e.valid_until.replace(tzinfo=datetime.timezone.utc)
                if exp <= now:
                    continue
            valid_ents.append(e)
        if valid_ents:
            valid_ents.sort(key=lambda e: PLAN_PRIORITY.get(e.plan_code.lower(), 99))
            return valid_ents[0]
    
    # Auto-create Free Trial entitlement (3 files allowance)
    trial_ent = Entitlement(
        tenant_id=tenant_id,
        plan_code="trial",
        status="active",
        source_type="trial",
        source_id="trial_default"
    )
    db.add(trial_ent)
    await db.flush()
    return trial_ent

async def check_and_reserve_quota(
    db: AsyncSession,
    tenant_id: str,
    file_count: int,
    idempotency_key: str,
    request_hash: Optional[str] = None
) -> UsageReservation:
    """
    Two-phase commit quota reservation (ADR-001):
    1. Idempotency check on (tenant_id, idempotency_key). Replay with different body -> 409 Conflict.
    2. Enforce limits: Trial (3 files), Starter (20 files/month), PRO/Lifetime (Fair Use concurrency).
       Accounts for both COMMITTED units and active pending RESERVED units.
    3. Atomically create RESERVED ledger row before parsing.
    """
    if file_count <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File count must be greater than 0"
        )
    if file_count > settings.MAX_FILES_PER_BATCH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch size {file_count} exceeds maximum allowed of {settings.MAX_FILES_PER_BATCH} files"
        )

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    pending_cutoff = now_utc - datetime.timedelta(minutes=5)
    pending_cutoff_val = pending_cutoff.replace(tzinfo=None) if pending_cutoff.tzinfo else pending_cutoff

    # 1. Idempotency check
    query = select(UsageReservation).where(
        and_(
            UsageReservation.tenant_id == tenant_id,
            UsageReservation.idempotency_key == idempotency_key
        )
    )
    res = await db.execute(query)
    existing_res = res.scalars().first()
    if existing_res:
        # If the idempotency key was reused with a DIFFERENT request payload -> 409 Conflict
        if request_hash and existing_res.request_hash and existing_res.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key reused with different request payload"
            )

        # State machine handling (Architect F02 / Decision 51):
        if existing_res.status == "COMMITTED":
            # Existing COMMITTED reservation returned for replay handling by caller
            return existing_res

        if existing_res.status == "RESERVED":
            res_created = existing_res.created_at
            if res_created and res_created.tzinfo is None:
                res_created = res_created.replace(tzinfo=datetime.timezone.utc)
            if res_created and res_created >= pending_cutoff:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An operation with this idempotency key is currently in progress. Please retry shortly."
                )
            # Expired in-flight reservation: fall through to re-evaluate quota and re-reserve

        # For RELEASED (or expired RESERVED):
        # Do NOT bypass quota! Fall through to Step 2 to evaluate quota before allowing retry.

    # 2. Entitlement evaluation
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_res.scalars().first()
    if not tenant:
        tenant = Tenant(id=tenant_id, email=f"{tenant_id}@autogen.invalid", version=0)
        db.add(tenant)
        await db.flush()
    current_version = tenant.version

    ent = await get_or_create_trial_entitlement(db, tenant_id)
    plan = ent.plan_code.lower()

    if plan == "trial":
        # Sum both COMMITTED units and active unexpired RESERVED units to prevent concurrency bypass
        sum_query = select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                or_(
                    UsageReservation.status == "COMMITTED",
                    and_(UsageReservation.status == "RESERVED", UsageReservation.created_at >= pending_cutoff)
                )
            )
        )
        total_used = (await db.execute(sum_query)).scalar()
        if total_used >= 3:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Free Trial limit reached (3 files). Please upgrade to Starter, Business PRO or Lifetime."
            )
        if total_used + file_count > 3:
            remaining = 3 - total_used
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Batch exceeds remaining Free Trial allowance ({remaining} file(s) left)."
            )

    elif plan == "kanzlei_trial":
        # Count only work performed after this invitation was redeemed.
        invite_start = ent.created_at.replace(tzinfo=None) if ent.created_at.tzinfo else ent.created_at
        sum_query = select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.created_at >= invite_start,
                or_(
                    UsageReservation.status == "COMMITTED",
                    and_(UsageReservation.status == "RESERVED", UsageReservation.created_at >= pending_cutoff_val)
                )
            )
        )
        used = (await db.execute(sum_query)).scalar()
        if used + file_count > 20:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Kanzleitest: {max(0, 20 - used)} Auszug/Auszüge verbleiben."
            )

    elif plan == "starter":
        # 20 files per billing period:
        # Align with current subscription billing cycle (Section 3)
        if ent.current_period_start:
            period_start = ent.current_period_start.replace(tzinfo=datetime.timezone.utc) if ent.current_period_start.tzinfo is None else ent.current_period_start
        elif ent.valid_until:
            exp = ent.valid_until if ent.valid_until.tzinfo else ent.valid_until.replace(tzinfo=datetime.timezone.utc)
            period_start = exp - datetime.timedelta(days=30)
        else:
            period_start = now_utc - datetime.timedelta(days=30)

        period_start_val = period_start.replace(tzinfo=None) if period_start.tzinfo else period_start
        pending_cutoff_val = pending_cutoff.replace(tzinfo=None) if pending_cutoff.tzinfo else pending_cutoff

        sum_query = select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                or_(
                    UsageReservation.status == "COMMITTED",
                    and_(UsageReservation.status == "RESERVED", UsageReservation.created_at >= pending_cutoff_val)
                ),
                UsageReservation.created_at >= period_start_val
            )
        )
        used = (await db.execute(sum_query)).scalar()
        if used >= 20:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Starter plan monthly quota of 20 statements reached. Upgrade to Business PRO for unlimited conversions."
            )
        if used + file_count > 20:
            remaining = 20 - used
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Batch of {file_count} files exceeds your remaining monthly quota ({remaining} left)."
            )

    elif plan in ("pro", "lifetime"):
        # Fair use: Max 1 active in-flight conversion job per tenant (ADR-001)
        active_query = select(func.count(UsageReservation.reservation_id)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.status == "RESERVED",
                UsageReservation.created_at >= pending_cutoff
            )
        )
        active_jobs = (await db.execute(active_query)).scalar()
        if active_jobs >= 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Concurrency limit: Another conversion job is currently active for this tenant."
            )

    # 3. Optimistic Concurrency Control (OCC) lock on Tenant
    res_upd = await db.execute(
        update(Tenant)
        .where(and_(Tenant.id == tenant_id, Tenant.version == current_version))
        .values(version=current_version + 1)
    )
    if res_upd.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent quota reservation conflict. Please retry."
        )

    # 4. Create or re-activate RESERVED record
    if existing_res:
        existing_res.status = "RESERVED"
        existing_res.units = file_count
        existing_res.request_hash = request_hash
        existing_res.created_at = now_utc.replace(tzinfo=None)
        await db.flush()
        return existing_res

    reservation = UsageReservation(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        units=file_count,
        status="RESERVED"
    )
    db.add(reservation)
    await db.flush()
    return reservation

async def commit_quota(db: AsyncSession, reservation: UsageReservation, successful_count: int):
    """Marks quota reservation as successfully committed."""
    if successful_count > 0:
        now = datetime.datetime.now(datetime.timezone.utc)
        reservation.units = successful_count
        reservation.status = "COMMITTED"
        reservation.committed_at = now
        # Start the 30-day window only after the first successful file.
        entitlement = await get_or_create_trial_entitlement(db, reservation.tenant_id)
        if entitlement.plan_code.lower() == "kanzlei_trial" and entitlement.current_period_start is None:
            entitlement.current_period_start = now.replace(tzinfo=None)
            entitlement.valid_until = (now + datetime.timedelta(days=30)).replace(tzinfo=None)
    else:
        reservation.status = "RELEASED"
    try:
        await db.commit()
    except Exception:
        await db.flush()

async def release_quota(db: AsyncSession, reservation: UsageReservation):
    """Releases reservation back to available quota pool on error. Never mutates COMMITTED records."""
    if reservation.status != "RESERVED":
        return
    reservation.status = "RELEASED"
    try:
        await db.commit()
    except Exception:
        await db.flush()
