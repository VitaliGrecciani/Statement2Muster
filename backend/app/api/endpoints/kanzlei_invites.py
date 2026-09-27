"""Redeem a single-use Kanzlei trial invitation after email OTP login."""
import datetime
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_tenant
from app.db.models import Entitlement, KanzleiInvite, Tenant
from app.db.session import get_db
from app.services.quota_service import get_or_create_trial_entitlement

router = APIRouter(prefix="/api/v1/kanzlei", tags=["kanzlei"])


class RedeemRequest(BaseModel):
    invite_code: str


@router.post("/redeem")
async def redeem_invitation(
    req: RedeemRequest,
    tenant_payload: dict[str, Any] = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    code = req.invite_code.strip()
    if len(code) < 24 or len(code) > 256:
        raise HTTPException(status_code=400, detail="Ungültiger Einladungscode.")
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    invitation = (await db.execute(select(KanzleiInvite).where(KanzleiInvite.code_hash == code_hash))).scalars().first()
    now = datetime.datetime.now(datetime.timezone.utc)
    if invitation is None or invitation.redeemed_at is not None:
        raise HTTPException(status_code=404, detail="Einladung nicht gefunden oder bereits verwendet.")
    expiration = invitation.expires_at.replace(tzinfo=datetime.timezone.utc) if invitation.expires_at.tzinfo is None else invitation.expires_at
    if expiration <= now:
        raise HTTPException(status_code=410, detail="Diese Einladung ist abgelaufen.")

    tenant_id = tenant_payload["tenant_id"]
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if tenant is None or tenant.email.strip().lower() != invitation.email.strip().lower():
        raise HTTPException(status_code=403, detail="Bitte melden Sie sich mit der eingeladenen E-Mail-Adresse an.")

    previous_invite = (await db.execute(select(Entitlement).where(
        Entitlement.tenant_id == tenant_id,
        Entitlement.source_type == "invite",
    ))).scalars().first()
    if previous_invite is not None:
        raise HTTPException(status_code=409, detail="Für dieses Konto wurde bereits ein Kanzleitest aktiviert.")

    current = await get_or_create_trial_entitlement(db, tenant_id)
    if current.plan_code.lower() in ("starter", "pro", "lifetime"):
        raise HTTPException(status_code=409, detail="Dieses Konto hat bereits einen bezahlten Tarif.")

    consumed = await db.execute(
        update(KanzleiInvite)
        .where(KanzleiInvite.id == invitation.id, KanzleiInvite.redeemed_at.is_(None))
        .values(redeemed_at=now.replace(tzinfo=None), tenant_id=tenant_id)
    )
    if consumed.rowcount != 1:
        raise HTTPException(status_code=409, detail="Die Einladung wurde bereits verwendet.")

    db.add(Entitlement(
        tenant_id=tenant_id,
        plan_code="kanzlei_trial",
        status="active",
        source_type="invite",
        source_id=invitation.id,
    ))
    await db.flush()
    return {"plan": "kanzlei_trial", "quota_limit": 20, "starts_with_first_success": True}

