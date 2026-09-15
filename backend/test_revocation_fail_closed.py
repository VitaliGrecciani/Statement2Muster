import os
import sys
import time
import uuid
import sqlite3
import pytest
from unittest.mock import patch
from pathlib import Path
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    is_token_revoked,
    revoke_token,
    _revoked_tokens
)
from app.main import app

@pytest.fixture(autouse=True)
def clean_ram_cache():
    _revoked_tokens.clear()
    yield
    _revoked_tokens.clear()

def test_revocation_fail_closed_on_db_operational_error(tmp_path):
    """P1 Verification: DB error with empty RAM cache must raise 503, never False."""
    test_db = tmp_path / "test.db"
    test_db.touch()
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db}"
    
    token = create_access_token(user_id="fail_closed@test.com", tenant_id="t_1")
    _revoked_tokens.clear()

    with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Disk I/O error or lock failure")):
        with pytest.raises(HTTPException) as exc_info:
            is_token_revoked(token)
        assert exc_info.value.status_code == 503
        assert "Revocation registry unavailable" in exc_info.value.detail

def test_revocation_fail_closed_on_missing_db(tmp_path):
    """P1 Verification: Missing DB file with empty RAM cache must raise 503, never False."""
    missing_db = tmp_path / "non_existent.db"
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{missing_db}"
    
    token = create_access_token(user_id="fail_closed@test.com", tenant_id="t_1")
    _revoked_tokens.clear()

    with pytest.raises(HTTPException) as exc_info:
        is_token_revoked(token)
    assert exc_info.value.status_code == 503
    assert "Revocation registry unavailable" in exc_info.value.detail

@pytest.mark.asyncio
async def test_revocation_fail_closed_http_api_503(tmp_path):
    """P1 Verification: HTTP convert request returns 503 when revocation DB fails."""
    test_db = tmp_path / "test.db"
    test_db.touch()
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db}"

    token = create_access_token(user_id="fail_closed@test.com", tenant_id="t_1")
    _revoked_tokens.clear()

    with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("DB locked")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/convert",
                headers={"Authorization": f"Bearer {token}"},
                files={"files": ("test.csv", b"dummy;data\n1;2", "text/csv")}
            )
            assert resp.status_code == 503
            data = resp.json()
            assert data.get("error") == "service_unavailable"
            assert "Revocation registry unavailable" in data.get("detail", "")

@pytest.mark.asyncio
async def test_revocation_recovered_and_confirmed_401(tmp_path):
    """P1 Verification: After DB recovery, confirmed revoked token returns 401."""
    test_db = tmp_path / "rev_test.db"
    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE revoked_tokens (
        token_hash VARCHAR(64) PRIMARY KEY,
        revoked_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL
    );
    """)
    conn.commit()
    conn.close()

    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db}"
    token = create_access_token(user_id="revoked_user@test.com", tenant_id="t_rev")
    
    # Store token revocation directly in DB
    from app.core.security import hash_token
    import datetime
    th = hash_token(token)
    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO revoked_tokens (token_hash, revoked_at, expires_at) VALUES (?, ?, ?)",
        (th, datetime.datetime.now(), datetime.datetime.now() + datetime.timedelta(minutes=10))
    )
    conn.commit()
    conn.close()

    # Clear RAM cache
    _revoked_tokens.clear()

    # Must be detected as revoked from DB
    assert is_token_revoked(token) is True

    # Must fail HTTP convert with 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/convert",
            headers={"Authorization": f"Bearer {token}"},
            files={"files": ("test.csv", b"dummy;data\n1;2", "text/csv")}
        )
        assert resp.status_code == 401
        assert "revoked" in resp.json().get("detail", "").lower()

def test_revocation_expired_ram_cache_falls_through_to_db_operational_error_503(tmp_path):
    """Decision 27 Verification: Expired RAM cache entry MUST fall through to SQLite.
    If SQLite encounters OperationalError, it must raise 503, NEVER return False.
    """
    test_db = tmp_path / "test_exp_cache.db"
    test_db.touch()
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db}"

    token = create_access_token(user_id="cache_exp@test.com", tenant_id="t_exp")
    from app.core.security import hash_token
    th = hash_token(token)

    # Set expired cache entry: exp = 999 while now = 1000
    _revoked_tokens[th] = time.time() - 10

    with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Simulated DB lock during cache fallthrough")):
        with pytest.raises(HTTPException) as exc_info:
            is_token_revoked(token)
        assert exc_info.value.status_code == 503
        assert "Revocation registry unavailable" in exc_info.value.detail

def test_revocation_expired_ram_cache_falls_through_to_db_confirmed_revocation(tmp_path):
    """Decision 27 Verification: Expired RAM cache entry MUST fall through to SQLite and confirm revocation."""
    test_db = tmp_path / "test_exp_cache2.db"
    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE revoked_tokens (
        token_hash VARCHAR(64) PRIMARY KEY,
        revoked_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL
    );
    """)
    conn.commit()
    conn.close()

    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db}"
    token = create_access_token(user_id="cache_exp2@test.com", tenant_id="t_exp2")
    from app.core.security import hash_token
    import datetime
    th = hash_token(token)

    # Populate SQLite with valid revocation record
    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO revoked_tokens (token_hash, revoked_at, expires_at) VALUES (?, ?, ?)",
        (th, datetime.datetime.now(), datetime.datetime.now() + datetime.timedelta(minutes=10))
    )
    conn.commit()
    conn.close()

    # Set expired RAM cache entry (exp in past)
    _revoked_tokens[th] = time.time() - 5

    # Must fall through, read SQLite, and confirm revocation
    assert is_token_revoked(token) is True
    # Cache must be updated to future
    assert _revoked_tokens[th] > time.time()

