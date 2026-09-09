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

def decode_access_token(token: str) -> Dict[str, Any]:
    """Validates RS256 Bearer JWT against public key."""
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
