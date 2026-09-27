import datetime
import hashlib
import uuid

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.endpoints.entitlements import get_my_entitlements
from app.api.endpoints.kanzlei_invites import RedeemRequest, redeem_invitation
from app.api.endpoints.social_auth import LinkRequest, link_social_identity
from app.db.models import KanzleiInvite, PendingSocialLink, SocialIdentity, Tenant
from app.db.session import async_session_maker
from app.main import app
from app.services.email_service import EmailDeliveryService
from app.services.quota_service import check_and_reserve_quota, commit_quota


@pytest.mark.asyncio
async def test_invited_firm_gets_20_files_and_30_days_after_first_success():
    tenant_id = str(uuid.uuid4())
    email = f"kanzlei-{tenant_id}@example.test"
    code = "test-invite-" + uuid.uuid4().hex
    async with async_session_maker() as db:
        db.add(Tenant(id=tenant_id, email=email))
        db.add(KanzleiInvite(
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            email=email,
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=60),
        ))
        await db.commit()

        result = await redeem_invitation(RedeemRequest(invite_code=code), {"tenant_id": tenant_id}, db)
        await db.commit()
        assert result["plan"] == "kanzlei_trial"
        ent = await get_my_entitlements({"tenant_id": tenant_id, "sub": email}, db)
        assert ent["quota_limit"] == 20
        assert ent["remaining_units"] == 20
        assert ent["valid_until"] is None
        assert ent["capabilities"]["multi_upload"] is True

        failed = await check_and_reserve_quota(db, tenant_id, 1, str(uuid.uuid4()))
        await commit_quota(db, failed, 0)
        ent = await get_my_entitlements({"tenant_id": tenant_id, "sub": email}, db)
        assert ent["remaining_units"] == 20
        assert ent["valid_until"] is None

        first = await check_and_reserve_quota(db, tenant_id, 12, str(uuid.uuid4()))
        await commit_quota(db, first, 12)
        ent = await get_my_entitlements({"tenant_id": tenant_id, "sub": email}, db)
        assert ent["remaining_units"] == 8
        assert ent["valid_until"] is not None
        start = datetime.datetime.fromisoformat(ent["valid_until"]) - datetime.timedelta(days=30)
        assert abs((datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - start).total_seconds()) < 60

        second = await check_and_reserve_quota(db, tenant_id, 8, str(uuid.uuid4()))
        await commit_quota(db, second, 8)
        ent = await get_my_entitlements({"tenant_id": tenant_id, "sub": email}, db)
        assert ent["remaining_units"] == 0

        with pytest.raises(HTTPException) as limit:
            await check_and_reserve_quota(db, tenant_id, 1, str(uuid.uuid4()))
        assert limit.value.status_code == 429

        with pytest.raises(HTTPException) as replay:
            await redeem_invitation(RedeemRequest(invite_code=code), {"tenant_id": tenant_id}, db)
        assert replay.value.status_code == 404


@pytest.mark.asyncio
async def test_invitation_is_bound_to_verified_email():
    invited_id = str(uuid.uuid4())
    wrong_id = str(uuid.uuid4())
    code = "test-invite-" + uuid.uuid4().hex
    async with async_session_maker() as db:
        db.add_all([
            Tenant(id=invited_id, email=f"invited-{invited_id}@example.test"),
            Tenant(id=wrong_id, email=f"other-{wrong_id}@example.test"),
            KanzleiInvite(
                code_hash=hashlib.sha256(code.encode()).hexdigest(),
                email=f"invited-{invited_id}@example.test",
                expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
            ),
        ])
        await db.commit()
        with pytest.raises(HTTPException) as mismatch:
            await redeem_invitation(RedeemRequest(invite_code=code), {"tenant_id": wrong_id}, db)
        assert mismatch.value.status_code == 403
        result = await redeem_invitation(RedeemRequest(invite_code=code), {"tenant_id": invited_id}, db)
        assert result["plan"] == "kanzlei_trial"


@pytest.mark.asyncio
async def test_social_identity_requires_matching_email_before_link():
    tenant_id = str(uuid.uuid4())
    email = f"linked-{tenant_id}@example.test"
    pending_token = "social-link-" + uuid.uuid4().hex
    async with async_session_maker() as db:
        db.add(Tenant(id=tenant_id, email=email))
        db.add(PendingSocialLink(
            token_hash=hashlib.sha256(pending_token.encode()).hexdigest(),
            provider="facebook",
            subject="test-subject-" + uuid.uuid4().hex,
            email=email,
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10),
        ))
        await db.commit()
        with pytest.raises(HTTPException) as mismatch:
            await link_social_identity(LinkRequest(pending_token=pending_token), {"tenant_id": str(uuid.uuid4())}, db)
        assert mismatch.value.status_code == 403
        linked = await link_social_identity(LinkRequest(pending_token=pending_token), {"tenant_id": tenant_id}, db)
        await db.commit()
        assert linked["linked"] is True
        identities = (await db.execute(select(SocialIdentity).where(SocialIdentity.tenant_id == tenant_id))).scalars().all()
        assert len(identities) == 1


@pytest.mark.asyncio
async def test_http_email_code_then_invitation_redemption():
    email = f"http-{uuid.uuid4()}@example.com"
    code = "test-invite-" + uuid.uuid4().hex
    async with async_session_maker() as db:
        db.add(KanzleiInvite(
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            email=email,
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
        ))
        await db.commit()

    EmailDeliveryService.clear_test_inbox()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.statement2muster.com") as client:
        requested = await client.post("/api/v1/auth/request-code", json={"email": email})
        assert requested.status_code == 200
        otp = EmailDeliveryService.get_test_inbox()[-1]["code"]
        signed_in = await client.post("/api/v1/auth/token", json={"email": email, "code": otp})
        assert signed_in.status_code == 200
        token = signed_in.json()["access_token"]
        redeemed = await client.post(
            "/api/v1/kanzlei/redeem",
            json={"invite_code": code},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert redeemed.status_code == 200
        entitlements = await client.get("/api/v1/me/entitlements", headers={"Authorization": f"Bearer {token}"})
        assert entitlements.status_code == 200
        assert entitlements.json()["plan"] == "kanzlei_trial"
