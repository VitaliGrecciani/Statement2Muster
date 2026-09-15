import datetime
import uuid
from typing import Optional, Dict, Any
import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

security_bearer = HTTPBearer(auto_error=False)

import base64
from cryptography.hazmat.primitives import serialization

# Cache generated keys for session lifetime
_PRIV_KEY, _PUB_KEY = settings.get_jwt_keys()

def get_jwks() -> Dict[str, Any]:
    """Generates standard RFC 7517 JWKS representation of the active RS256 public key."""
    pub_key_obj = serialization.load_pem_public_key(_PUB_KEY)
    numbers = pub_key_obj.public_numbers()
    e_bytes = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, byteorder="big")
    n_bytes = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, byteorder="big")
    e_b64 = base64.urlsafe_b64encode(e_bytes).rstrip(b"=").decode("ascii")
    n_b64 = base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii")
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": settings.JWT_ALGORITHM,
                "kid": "s2m-auth-key-1",
                "n": n_b64,
                "e": e_b64,
            }
        ]
    }

def create_access_token(
    user_id: str,
    tenant_id: str,
    session_id: Optional[str] = None,
    expires_delta: Optional[datetime.timedelta] = None
) -> str:
    """Issues an asymmetric RS256 Bearer JWT with 10-minute expiry (ADR-001)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + datetime.timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        
    payload = {
        "iss": "statement2muster.com",
        "aud": "statement2muster-api",
        "sub": user_id,
        "tenant_id": tenant_id,
        "sid": session_id or str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp())
    }
    
    encoded_jwt = jwt.encode(payload, _PRIV_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

import hashlib
import time
import os

# Thread-safe in-memory cache of revoked token hashes: hash -> expiration epoch
_revoked_tokens: Dict[str, float] = {}

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def revoke_token(token: str, expires_at: Optional[float] = None) -> None:
    """Revokes an active Bearer token until its expiration (C02)."""
    th = hash_token(token)
    if expires_at is None:
        try:
            payload = jwt.decode(
                token,
                _PUB_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                audience="statement2muster-api",
                issuer="statement2muster.com",
                options={"verify_exp": False}
            )
            expires_at = float(payload.get("exp", time.time() + 600))
        except Exception:
            expires_at = time.time() + 600
    _revoked_tokens[th] = expires_at

def is_token_revoked(token: str) -> bool:
    """Checks whether token has been revoked in-memory or database.
    
    Fail-closed (Decisions 26 & 27):
    - If RAM cache entry is valid and unexpired: return True.
    - If RAM cache entry has expired: pop it and continue to authoritative SQLite registry check.
    - If SQLite registry is unreachable, corrupt, or missing: raise HTTP 503 Service Unavailable.
    - If SQLite registry contains active unexpired revocation: cache it until actual token expiry and return True.
    - If SQLite registry confirms token is not revoked: return False.
    """
    th = hash_token(token)
    now = time.time()
    exp = _revoked_tokens.get(th)
    if exp is not None:
        if exp > now:
            return True
        else:
            _revoked_tokens.pop(th, None)
            # Do NOT return False: cache expired, fall through to authoritative SQLite check!

    # Authoritative SQLite registry check
    db_url = settings.DATABASE_URL
    if "sqlite" in db_url:
        path = db_url.split(":///")[-1]
        if not path or not os.path.exists(path):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Revocation registry unavailable. Operation rejected for security."
            )
        import sqlite3
        try:
            conn = sqlite3.connect(path, timeout=1.0)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT expires_at FROM revoked_tokens WHERE token_hash = ?", (th,))
                row = cursor.fetchone()
                if row:
                    db_exp_val = row[0]
                    db_exp_epoch = None
                    if isinstance(db_exp_val, (int, float)):
                        db_exp_epoch = float(db_exp_val)
                    elif isinstance(db_exp_val, str):
                        try:
                            dt = datetime.datetime.fromisoformat(db_exp_val.replace(" ", "T"))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=datetime.timezone.utc)
                            db_exp_epoch = dt.timestamp()
                        except Exception:
                            db_exp_epoch = now + 600
                    elif isinstance(db_exp_val, datetime.datetime):
                        if db_exp_val.tzinfo is None:
                            dt = db_exp_val.replace(tzinfo=datetime.timezone.utc)
                        else:
                            dt = db_exp_val
                        db_exp_epoch = dt.timestamp()
                    else:
                        db_exp_epoch = now + 600

                    if db_exp_epoch and db_exp_epoch > now:
                        _revoked_tokens[th] = db_exp_epoch
                    return True
                return False
            finally:
                conn.close()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Revocation registry unavailable. Operation rejected for security."
            ) from exc
    return False

def decode_access_token(token: str) -> Dict[str, Any]:
    """Validates RS256 Bearer JWT against public key and revocation list (C02)."""
    if is_token_revoked(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please re-authenticate."
        )
    try:
        payload = jwt.decode(
            token,
            _PUB_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience="statement2muster-api",
            issuer="statement2muster.com"
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired. Please re-authenticate."
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}"
        )

async def get_current_tenant(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer)
) -> Dict[str, Any]:
    """Dependency extracting tenant identity from Bearer token."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token."
        )
    return decode_access_token(credentials.credentials)
