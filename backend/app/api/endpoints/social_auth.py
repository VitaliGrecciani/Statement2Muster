"""Browser OAuth login. First use of a social identity requires email OTP binding."""
import datetime
import hashlib
import json
import secrets
import uuid
from typing import Any

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, get_current_tenant
from app.db.models import PendingSocialLink, SocialIdentity, Tenant
from app.db.session import get_db
from app.services.quota_service import get_or_create_trial_entitlement

router = APIRouter(prefix="/api/v1/auth/oauth", tags=["auth"])
oauth = OAuth()

if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

if settings.LINKEDIN_CLIENT_ID and settings.LINKEDIN_CLIENT_SECRET:
    oauth.register(
        name="linkedin",
        client_id=settings.LINKEDIN_CLIENT_ID,
        client_secret=settings.LINKEDIN_CLIENT_SECRET,
        server_metadata_url="https://www.linkedin.com/oauth/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email"},
    )

if settings.FACEBOOK_CLIENT_ID and settings.FACEBOOK_CLIENT_SECRET:
    oauth.register(
        name="facebook",
        client_id=settings.FACEBOOK_CLIENT_ID,
        client_secret=settings.FACEBOOK_CLIENT_SECRET,
        authorize_url="https://www.facebook.com/v23.0/dialog/oauth",
        access_token_url="https://graph.facebook.com/v23.0/oauth/access_token",
        client_kwargs={"scope": "email"},
    )


def _popup_result(payload: dict[str, Any]) -> HTMLResponse:
    """Deliver the result to the requesting page without placing tokens in URLs."""
    safe_json = json.dumps({"type": "statement2muster:oauth", **payload}).replace("<", "\\u003c")
    target_origin = settings.PUBLIC_WEB_ORIGIN.rstrip("/")
    html = (
        "<!doctype html><html lang='de'><meta charset='utf-8'>"
        "<title>Statement2Muster Anmeldung</title>"
        "<body><p>Sie können dieses Fenster schließen.</p><script>"
        f"if(window.opener) window.opener.postMessage({safe_json}, {json.dumps(target_origin)});"
        "window.close();</script></body></html>"
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/{provider}/start")
async def oauth_start(provider: str, request: Request):
    client = oauth.create_client(provider) if provider in {"google", "linkedin", "facebook"} else None
    if client is None:
        raise HTTPException(status_code=503, detail="Dieser Anmeldeanbieter ist noch nicht eingerichtet.")
    callback_url = f"{settings.PUBLIC_API_ORIGIN.rstrip('/')}/api/v1/auth/oauth/{provider}/callback"
    return await client.authorize_redirect(request, callback_url)


@router.get("/{provider}/callback")
async def oauth_callback(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    client = oauth.create_client(provider) if provider in {"google", "linkedin", "facebook"} else None
    if client is None:
        return _popup_result({"error": "Dieser Anmeldeanbieter ist noch nicht eingerichtet."})
    if request.query_params.get("error"):
        return _popup_result({"error": "Die Anmeldung wurde abgebrochen oder abgelehnt."})

    try:
        # Authlib checks the signed session state, exchanges the code and validates OIDC ID tokens.
        token = await client.authorize_access_token(request)
        if provider == "facebook":
            profile_response = await client.get("https://graph.facebook.com/me?fields=id,email", token=token)
            profile_response.raise_for_status()
            profile = profile_response.json()
            subject = profile.get("id")
        else:
            profile = token.get("userinfo") or {}
            subject = profile.get("sub")
        email = (profile.get("email") or "").strip().lower()
        if not subject:
            raise ValueError("Provider did not supply an account identifier")
    except Exception:
        return _popup_result({"error": "Die Anmeldung beim Anbieter konnte nicht bestätigt werden."})

    identity = (await db.execute(select(SocialIdentity).where(
        SocialIdentity.provider == provider,
        SocialIdentity.subject == subject,
    ))).scalars().first()

    if identity:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == identity.tenant_id))).scalars().first()
        if tenant is None:
            return _popup_result({"error": "Die verknüpfte Anmeldung ist nicht mehr verfügbar."})
        await get_or_create_trial_entitlement(db, tenant.id)
        access_token = create_access_token(user_id=tenant.email, tenant_id=tenant.id)
        return _popup_result({"access_token": access_token})

    if not email:
        return _popup_result({"error": "Der Anbieter hat keine E-Mail-Adresse übermittelt. Bitte melden Sie sich per E-Mail an."})

    # The provider's email is confirmed by our own OTP before an identity is linked.
    link_token = secrets.token_urlsafe(32)
    pending = PendingSocialLink(
        token_hash=hashlib.sha256(link_token.encode()).hexdigest(),
        provider=provider,
        subject=subject,
        email=email,
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10),
    )
    db.add(pending)
    await db.flush()
    return _popup_result({"pending_token": link_token, "email": email})


class LinkRequest(BaseModel):
    pending_token: str


@router.post("/link")
async def link_social_identity(
    req: LinkRequest,
    tenant_payload: dict[str, Any] = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    token_hash = hashlib.sha256(req.pending_token.encode()).hexdigest()
    pending = (await db.execute(select(PendingSocialLink).where(PendingSocialLink.token_hash == token_hash))).scalars().first()
    now = datetime.datetime.now(datetime.timezone.utc)
    if pending is None:
        raise HTTPException(status_code=404, detail="Verknüpfung nicht gefunden.")
    expires = pending.expires_at.replace(tzinfo=datetime.timezone.utc) if pending.expires_at.tzinfo is None else pending.expires_at
    if expires <= now:
        await db.delete(pending)
        raise HTTPException(status_code=410, detail="Verknüpfung abgelaufen.")
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_payload["tenant_id"]))).scalars().first()
    if tenant is None or tenant.email.strip().lower() != pending.email:
        raise HTTPException(status_code=403, detail="Bitte bestätigen Sie dieselbe E-Mail-Adresse.")
    existing = (await db.execute(select(SocialIdentity).where(
        SocialIdentity.provider == pending.provider,
        SocialIdentity.subject == pending.subject,
    ))).scalars().first()
    if existing and existing.tenant_id != tenant.id:
        raise HTTPException(status_code=409, detail="Dieses Profil ist bereits mit einem anderen Konto verbunden.")
    if existing is None:
        db.add(SocialIdentity(provider=pending.provider, subject=pending.subject, tenant_id=tenant.id))
    await db.delete(pending)
    await db.flush()
    return {"linked": True, "provider": pending.provider}

