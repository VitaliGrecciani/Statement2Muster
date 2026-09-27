import datetime
from typing import Dict, Any, List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from app.db.session import get_db
from app.db.models import Entitlement, UsageReservation, Tenant
from app.core.security import get_current_tenant
from app.services.quota_service import get_or_create_trial_entitlement

router = APIRouter(prefix="/api/v1/me", tags=["entitlements"])

@router.get("/entitlements")
async def get_my_entitlements(
    tenant_payload: Dict[str, Any] = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns active plans, quota balance, and capabilities for the authenticated tenant (ADR-001).
    """
    tenant_id = tenant_payload.get("tenant_id")
    
    # Fetch active entitlement
    ent = await get_or_create_trial_entitlement(db, tenant_id)
    plan = ent.plan_code.lower()

    used_units = 0
    quota_limit = None
    remaining_units = None

    if plan == "trial":
        quota_limit = 3
        sum_query = select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.status == "COMMITTED"
            )
        )
        used_units = (await db.execute(sum_query)).scalar()
        remaining_units = max(0, quota_limit - used_units)

    elif plan == "kanzlei_trial":
        quota_limit = 20
        invite_start = ent.created_at.replace(tzinfo=None) if ent.created_at.tzinfo else ent.created_at
        sum_query = select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.status == "COMMITTED",
                UsageReservation.created_at >= invite_start
            )
        )
        used_units = (await db.execute(sum_query)).scalar()
        remaining_units = max(0, quota_limit - used_units)

    elif plan == "starter":
        quota_limit = 20
        if ent.current_period_start:
            period_start = ent.current_period_start.replace(tzinfo=datetime.timezone.utc) if ent.current_period_start.tzinfo is None else ent.current_period_start
        elif ent.valid_until:
            exp = ent.valid_until.replace(tzinfo=datetime.timezone.utc) if ent.valid_until.tzinfo is None else ent.valid_until
            period_start = exp - datetime.timedelta(days=30)
        else:
            period_start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)

        period_start_val = period_start.replace(tzinfo=None) if period_start.tzinfo else period_start
        sum_query = select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.status == "COMMITTED",
                UsageReservation.created_at >= period_start_val
            )
        )
        used_units = (await db.execute(sum_query)).scalar()
        remaining_units = max(0, quota_limit - used_units)

    elif plan in ("pro", "lifetime", "kanzlei_trial"):
        quota_limit = "unlimited"
        remaining_units = "unlimited"

    capabilities = {
        "multi_upload": plan in ("pro", "lifetime", "kanzlei_trial"),
        "anti_mix_guard": plan in ("pro", "lifetime", "kanzlei_trial"),
        "priority_support": plan in ("pro", "lifetime", "kanzlei_trial"),
        "batch_dedup": plan in ("pro", "lifetime", "kanzlei_trial")
    }

    return {
        "tenant_id": tenant_id,
        "email": tenant_payload.get("sub"),
        "plan": plan,
        "status": ent.status,
        "source_type": ent.source_type,
        "quota_limit": quota_limit,
        "used_units": used_units,
        "remaining_units": remaining_units,
        "capabilities": capabilities,
        "valid_until": ent.valid_until.isoformat() if ent.valid_until else None,
        "paid_through": ent.paid_through.isoformat() if ent.paid_through else None,
        "is_provisional": bool(ent.has_authoritative_period == 0 and ent.source_type == "subscription"),
        "provisional_deadline": ent.provisional_deadline.isoformat() if ent.provisional_deadline else None
    }
