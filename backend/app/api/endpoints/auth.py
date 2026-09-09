import uuid
import secrets
import datetime
from typing import Optional
import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, case
from app.db.session import get_db
from app.db.models import Tenant, AuthChallenge, RevokedToken, AuthRateLimit
from app.core.security import create_access_token, _PUB_KEY, get_jwks, revoke_token, hash_token
from app.core.config import settings
from app.services.quota_service import get_or_create_trial_entitlement

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class RequestCodeRequest(BaseModel):
    email: EmailStr

class TokenRequest(BaseModel):
    email: EmailStr
    code: Optional[str] = None # One-time code from launchWebAuthFlow / request-code
    session_id: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 600 # 10 minutes
    tenant_id: str
    plan: str

from app.services.email_service import email_service

async def _get_or_create_rate_limit(db: AsyncSession, email: str, now: datetime.datetime) -> AuthRateLimit:
    """Safely gets or inserts rate limit record across concurrent sessions (C04)."""
    rl = (await db.execute(select(AuthRateLimit).where(AuthRateLimit.email == email))).scalars().first()
    if not rl:
        try:
            async with db.begin_nested():
                db.add(AuthRateLimit(
                    email=email,
                    failed_attempts=0,
                    request_count=0,
                    window_start=now,
                    updated_at=now
                ))
                await db.flush()
        except Exception:
            pass
        rl = (await db.execute(select(AuthRateLimit).where(AuthRateLimit.email == email))).scalars().first()
    return rl

@router.post("/request-code")
async def request_code(req: RequestCodeRequest, db: AsyncSession = Depends(get_db)):
    """
    Issues a single-use 6-digit OTP code with 10-minute TTL for email identity proof (A01).
    Enforces persistent request-rate budget (max 3/10m) and lockout via AuthRateLimit (C04).
    Truthful delivery status via EmailDeliveryService (C03).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. Persistent rate limit & lockout record (C04)
    rl = await _get_or_create_rate_limit(db, req.email, now)

    # 2. Check active lockout
    if rl and rl.lockout_until:
        lockout_dt = rl.lockout_until if rl.lockout_until.tzinfo else rl.lockout_until.replace(tzinfo=datetime.timezone.utc)
        if now < lockout_dt:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed verification attempts. Please wait until the lockout period expires."
            )
        else:
            await db.execute(
                update(AuthRateLimit)
                .where(AuthRateLimit.email == req.email)
                .values(lockout_until=None, failed_attempts=0, updated_at=now)
            )
            await db.commit()

    # 3. Rate-limit request-code calls (max 3 requests per 10 minutes - C04)
    w_start = rl.window_start if (rl and rl.window_start and rl.window_start.tzinfo) else (rl.window_start.replace(tzinfo=datetime.timezone.utc) if (rl and rl.window_start) else None)
    if not w_start or (now - w_start) > datetime.timedelta(minutes=10):
        await db.execute(
            update(AuthRateLimit)
            .where(AuthRateLimit.email == req.email)
            .values(window_start=now, request_count=1, updated_at=now)
        )
        await db.commit()
    else:
        if rl.request_count >= 3:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many verification code requests. Please wait a few minutes before requesting another code."
            )
        await db.execute(
            update(AuthRateLimit)
            .where(AuthRateLimit.email == req.email)
            .values(request_count=AuthRateLimit.request_count + 1, updated_at=now)
        )
        await db.commit()
        curr_rl = (await db.execute(select(AuthRateLimit).where(AuthRateLimit.email == req.email))).scalars().first()
        if curr_rl and curr_rl.request_count > 3:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many verification code requests. Please wait a few minutes before requesting another code."
            )

    code = f"{secrets.randbelow(900000) + 100000}"
    expires = now + datetime.timedelta(minutes=10)
    
    # Invalidate previous unused codes for this email
    await db.execute(
        update(AuthChallenge)
        .where(AuthChallenge.email == req.email, AuthChallenge.used == 0)
        .values(used=1)
    )
    
    challenge = AuthChallenge(
        id=str(uuid.uuid4()),
        email=req.email,
        code=code,
        expires_at=expires,
        used=0
    )
    db.add(challenge)
    await db.commit()

    # 3. Truthful delivery via EmailDeliveryService
    sent = await email_service.send_verification_email(req.email, code, expires)
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to deliver verification code email. Please verify email address or try again."
        )
    
    return {
        "message": "Verification code sent to email.",
        "email": req.email,
        "expires_in": 600,
        "status": "pending"
    }

@router.post("/token", response_model=TokenResponse)
async def exchange_token(req: TokenRequest, db: AsyncSession = Depends(get_db)):
    """
    Exchanges verified identity / code from launchWebAuthFlow into a short-lived
    10-minute RS256 Bearer JWT (ADR-001).
    Enforces proof-of-identity: token cannot be issued by email alone (A01).
    Enforces attempt budget: 5 failed attempts locks out the email for 15 minutes (429 Too Many Requests).
    Lockout is persistent across request-code invocations (B01 / C04).
    """
    if not req.code:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verification code required. Please call /api/v1/auth/request-code first."
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    
    rl = await _get_or_create_rate_limit(db, req.email, now)

    # Check active lockout
    if rl and rl.lockout_until:
        lockout_dt = rl.lockout_until if rl.lockout_until.tzinfo else rl.lockout_until.replace(tzinfo=datetime.timezone.utc)
        if now < lockout_dt:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed verification attempts. Account is temporarily locked out."
            )
        else:
            # Lockout expired, reset
            await db.execute(
                update(AuthRateLimit)
                .where(AuthRateLimit.email == req.email)
                .values(lockout_until=None, failed_attempts=0, updated_at=now)
            )
            await db.commit()

    c_query = select(AuthChallenge).where(
        AuthChallenge.email == req.email,
        AuthChallenge.code == req.code,
        AuthChallenge.used == 0,
        AuthChallenge.expires_at > now
    )
    challenge = (await db.execute(c_query)).scalars().first()
    if not challenge:
        # Atomic increment of failed_attempts and conditional lockout under concurrency (C04)
        lockout_time = now + datetime.timedelta(minutes=15)
        stmt = (
            update(AuthRateLimit)
            .where(AuthRateLimit.email == req.email)
            .values(
                failed_attempts=AuthRateLimit.failed_attempts + 1,
                lockout_until=case(
                    (AuthRateLimit.failed_attempts + 1 >= 5, lockout_time),
                    else_=AuthRateLimit.lockout_until
                ),
                updated_at=now
            )
        )
        await db.execute(stmt)
        await db.commit()

        # Read updated state to return 429 if locked out, else 401
        updated_rl = (await db.execute(select(AuthRateLimit).where(AuthRateLimit.email == req.email))).scalars().first()
        if updated_rl and updated_rl.failed_attempts >= 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed verification attempts. Account is temporarily locked out."
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code."
        )

    # Atomic consume condition (prevents concurrent replay of the same challenge)
    upd_res = await db.execute(
        update(AuthChallenge)
        .where(AuthChallenge.id == challenge.id, AuthChallenge.used == 0)
        .values(used=1)
    )
    if upd_res.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verification code has already been consumed."
        )

    # Success: clear failed attempts atomically
    await db.execute(
        update(AuthRateLimit)
        .where(AuthRateLimit.email == req.email)
        .values(failed_attempts=0, lockout_until=None, updated_at=now)
    )
    await db.commit()

    query = select(Tenant).where(Tenant.email == req.email)
    res = await db.execute(query)
    tenant = res.scalars().first()
    
    if not tenant:
        tenant = Tenant(id=str(uuid.uuid4()), email=req.email, name=req.email.split("@")[0])
        db.add(tenant)
        await db.flush()

    # Ensure entitlement exists and select the highest priority plan (Lifetime > Pro > Starter > Trial)
    ent = await get_or_create_trial_entitlement(db, tenant.id)

    token = create_access_token(
        user_id=tenant.email,
        tenant_id=tenant.id,
        session_id=req.session_id
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        tenant_id=tenant.id,
        plan=ent.plan_code
    )

@router.get("/jwks.json")
async def get_jwks_endpoint():
    """Exposes standard RFC 7517 JSON Web Key Set (JWKS) for asymmetric signature verification."""
    return get_jwks()

@router.get("/public-key")
async def get_public_key():
    """Exposes RS256 Public Key PEM for client-side or third-party token validation."""
    return {"algorithm": "RS256", "public_key": _PUB_KEY.decode()}

@router.post("/logout")
async def logout_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Client logout, token revocation, and session termination (B01 / C02)."""
    auth_header = request.headers.get("authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            th = hash_token(token)
            now = datetime.datetime.now(datetime.timezone.utc)
            exp_dt = now + datetime.timedelta(minutes=10)
            try:
                payload = jwt.decode(
                    token,
                    _PUB_KEY,
                    algorithms=[settings.JWT_ALGORITHM],
                    audience="statement2muster-api",
                    issuer="statement2muster.com",
                    options={"verify_exp": False}
                )
                if "exp" in payload:
                    exp_dt = datetime.datetime.fromtimestamp(payload["exp"], tz=datetime.timezone.utc)
            except Exception:
                pass

            revoke_token(token, exp_dt.timestamp())
            revoked_rec = RevokedToken(
                token_hash=th,
                expires_at=exp_dt.replace(tzinfo=None)
            )
            await db.merge(revoked_rec)
            await db.flush()
        except Exception:
            revoke_token(token)

    return {"message": "Session logged out successfully.", "status": "logged_out"}

