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

    elif plan == "starter":
        quota_limit = 20
        period_start = datetime.datetime.utcnow() - datetime.timedelta(days=30)
        sum_query = select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
            and_(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.status == "COMMITTED",
                UsageReservation.created_at >= period_start
            )
        )
        used_units = (await db.execute(sum_query)).scalar()
        remaining_units = max(0, quota_limit - used_units)

    elif plan in ("pro", "lifetime"):
        quota_limit = "unlimited"
        remaining_units = "unlimited"

    capabilities = {
        "multi_upload": plan in ("pro", "lifetime"),
        "anti_mix_guard": plan in ("pro", "lifetime"),
        "priority_support": plan in ("pro", "lifetime"),
        "batch_dedup": plan in ("pro", "lifetime")
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
        "valid_until": ent.valid_until.isoformat() if ent.valid_until else None
    }
