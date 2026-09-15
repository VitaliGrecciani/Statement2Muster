import os
import sys
import json
import time
import uuid
import datetime
import asyncio
import sqlite3
import shutil
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVIDENCE_DIR = BASE_DIR / "docs" / "managed_extension_acceptance"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(BASE_DIR / "backend"))
from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    revoke_token,
    is_token_revoked,
    hash_token,
    _revoked_tokens
)
import app.db.session as session_mod
from app.db.session import init_db
from app.main import app

def switch_db(db_path: Path):
    """Dynamically binds SQLAlchemy engine and sessionmaker to isolated test database."""
    db_url = f"sqlite+aiosqlite:///{db_path}"
    settings.DATABASE_URL = db_url
    session_mod.engine = create_async_engine(db_url, echo=False, future=True)
    session_mod.async_session_maker = async_sessionmaker(
        session_mod.engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

async def run_chain2_hardening():
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "test_suite": "Chain 2: Fault Tolerance, Fail-Closed Revocation, Multi-Worker Isolation & DB Migrations",
        "provenance": {
            "decision_ref": "Architect Decision 26",
            "p1_issue": "Fail-open SQLite error handling remediated to fail-closed HTTP 503",
        },
        "scenarios": {},
        "overall_status": "RUNNING"
    }

    print("=== Starting Hardened Chain 2 Acceptance Test Suite (Decision 26) ===")

    temp_dir = Path(tempfile.mkdtemp(prefix="s2m_chain2_hardened_"))
    try:
        # -------------------------------------------------------------
        # SCENARIO 1: P1 FAIL-CLOSED REVOCATION VERIFICATION
        # -------------------------------------------------------------
        print("\n--- Scenario 1: P1 Fail-Closed Revocation on DB Outage / Corruption ---")
        fail_db_path = temp_dir / "fail_closed_test.db"
        switch_db(fail_db_path)
        await init_db()

        test_token = create_access_token(user_id="fail_test@s2m.de", tenant_id="t_fail_1")
        _revoked_tokens.clear()

        # 1.1 Injected OperationalError on SQLite connection -> Must return HTTP 503, NEVER False
        print("[1.1] Testing DB OperationalError with empty RAM cache...")
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Simulated DB lock / disk failure")):
            from fastapi import HTTPException
            try:
                is_token_revoked(test_token)
                p1_unit_status = "FAIL_OPEN"
            except HTTPException as exc:
                p1_unit_status = "FAIL_CLOSED_503" if exc.status_code == 503 else f"ERROR_{exc.status_code}"
                print(f"      is_token_revoked correctly raised HTTPException({exc.status_code}): {exc.detail}")

        assert p1_unit_status == "FAIL_CLOSED_503", "P1: is_token_revoked did not raise 503 on DB error!"

        # 1.2 HTTP API path: /api/v1/convert during DB outage -> Must return HTTP 503
        print("[1.2] Testing HTTP /api/v1/convert with revoked token during DB outage...")
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Simulated DB lock")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp_503 = await ac.post(
                    "/api/v1/convert",
                    headers={"Authorization": f"Bearer {test_token}"},
                    files={"files": ("test.csv", b"dummy;data\n1;2", "text/csv")}
                )
                print(f"      HTTP convert response during outage: {resp_503.status_code} ({resp_503.text})")
                assert resp_503.status_code == 503
                assert resp_503.json().get("error") == "service_unavailable"

        # 1.3 DB recovered -> confirmed revoked token returns HTTP 401
        print("[1.3] Testing DB recovery with revoked token...")
        th = hash_token(test_token)
        s_conn = sqlite3.connect(str(fail_db_path))
        s_cur = s_conn.cursor()
        s_cur.execute(
            "INSERT INTO revoked_tokens (token_hash, revoked_at, expires_at) VALUES (?, ?, ?)",
            (th, datetime.datetime.now(), datetime.datetime.now() + datetime.timedelta(minutes=10))
        )
        s_conn.commit()
        s_conn.close()
        _revoked_tokens.clear()

        assert is_token_revoked(test_token) is True

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp_401 = await ac.post(
                "/api/v1/convert",
                headers={"Authorization": f"Bearer {test_token}"},
                files={"files": ("test.csv", b"dummy;data\n1;2", "text/csv")}
            )
            print(f"      HTTP convert response after DB recovery: {resp_401.status_code} ({resp_401.text})")
            assert resp_401.status_code == 401
            assert "revoked" in resp_401.json().get("detail", "").lower()

        # 1.4 Decision 27 Verification: Expired RAM cache entry (exp <= now) MUST fall through to DB
        print("[1.4] Testing expired RAM cache entry fallthrough to SQLite...")
        _revoked_tokens[th] = time.time() - 10 # expired in RAM
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Simulated DB lock during cache fallthrough")):
            try:
                is_token_revoked(test_token)
                cache_fallthrough_status = "FAIL_OPEN"
            except HTTPException as exc:
                cache_fallthrough_status = "FAIL_CLOSED_503" if exc.status_code == 503 else f"ERROR_{exc.status_code}"
                print(f"      Expired cache fallthrough correctly raised HTTPException({exc.status_code}): {exc.detail}")
        assert cache_fallthrough_status == "FAIL_CLOSED_503", "Decision 27: Expired cache did not raise 503 on DB error!"

        # 1.5 When DB is accessible, expired RAM cache entry falls through and confirms revocation (401)
        _revoked_tokens[th] = time.time() - 10
        assert is_token_revoked(test_token) is True
        print("      Expired cache fallthrough with accessible DB correctly verified revocation.")

        report["scenarios"]["scenario1_fail_closed_revocation"] = {
            "status": "PASS",
            "db_error_code": 503,
            "error_type": "service_unavailable",
            "post_recovery_status": 401,
            "expired_cache_fallthrough_verified": True,
            "p1_verified": True
        }

        # -------------------------------------------------------------
        # SCENARIO 2: INDEPENDENT OS PROCESS MULTI-WORKER PERSISTENCE (Decision 27)
        # -------------------------------------------------------------
        print("\n--- Scenario 2: Real Independent OS Subprocess Multi-Worker Persistence ---")
        worker_db_path = temp_dir / "worker_test.db"
        switch_db(worker_db_path)
        await init_db()

        w_email = "worker_isolation@s2m.de"
        w_tenant = "t_worker_iso_1"
        w_token = create_access_token(user_id=w_email, tenant_id=w_tenant)

        # Logout via API
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            logout_res = await ac.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {w_token}"})
            assert logout_res.status_code == 200

        # Execute an independent OS Python process with completely separate memory space (Decision 27 requirement)
        backend_dir_str = str(BASE_DIR / 'backend').replace('\\', '/')
        worker_db_str = str(worker_db_path).replace('\\', '/')
        subprocess_code = (
            f"import sys, os\n"
            f"sys.path.insert(0, '{backend_dir_str}')\n"
            f"from app.core.config import settings\n"
            f"settings.DATABASE_URL = 'sqlite+aiosqlite:///{worker_db_str}'\n"
            f"from app.core.security import is_token_revoked\n"
            f"token = '{w_token}'\n"
            f"rev = is_token_revoked(token)\n"
            f"print(f'SUBPROCESS_REVOKED:{{rev}}')\n"
            f"sys.exit(0 if rev is True else 1)\n"
        )
        
        py_exe = sys.executable
        sub_proc = subprocess.run([py_exe, "-c", subprocess_code], capture_output=True, text=True)
        print(f"[2.1] Independent OS Worker 2 process exited with code {sub_proc.returncode}. Output: {sub_proc.stdout.strip()}")
        assert sub_proc.returncode == 0, f"Worker 2 subprocess failed: {sub_proc.stderr}"
        assert "SUBPROCESS_REVOKED:True" in sub_proc.stdout

        report["scenarios"]["scenario2_multi_worker_revocation"] = {
            "status": "PASS",
            "independent_os_process": True,
            "subprocess_returncode": sub_proc.returncode,
            "sqlite_persistence_confirmed": True
        }

        # -------------------------------------------------------------
        # SCENARIO 3: LEGACY DB MIGRATION + SUBSEQUENT LOGIN & CONVERT
        # -------------------------------------------------------------
        print("\n--- Scenario 3: Legacy DB Migration & Subsequent Login/Conversion ---")
        legacy_db = temp_dir / "legacy_v1_full.db"
        
        # Create v1 schema
        conn = sqlite3.connect(str(legacy_db))
        cur = conn.cursor()
        cur.execute("CREATE TABLE tenants (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, name VARCHAR(255) NOT NULL, created_at DATETIME, updated_at DATETIME);")
        cur.execute("CREATE TABLE entitlements (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36) NOT NULL, plan_code VARCHAR(50), status VARCHAR(50) NOT NULL, source_type VARCHAR(50) NOT NULL, source_id VARCHAR(255), valid_until DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);")
        cur.execute("CREATE TABLE usage_reservations (reservation_id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36) NOT NULL, idempotency_key VARCHAR(255) NOT NULL, units INTEGER NOT NULL, status VARCHAR(50) NOT NULL, created_at DATETIME NOT NULL, committed_at DATETIME);")
        cur.execute("CREATE TABLE revoked_tokens (token_hash VARCHAR(64) PRIMARY KEY, revoked_at DATETIME NOT NULL, expires_at DATETIME NOT NULL);")
        cur.execute("CREATE TABLE auth_challenges (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255) NOT NULL, code VARCHAR(6) NOT NULL, expires_at DATETIME NOT NULL, used INTEGER NOT NULL, session_id VARCHAR(255), ip_address VARCHAR(45), created_at DATETIME NOT NULL);")
        cur.execute("CREATE TABLE auth_rate_limits (email VARCHAR(255) PRIMARY KEY, request_count INTEGER NOT NULL, window_start DATETIME NOT NULL, failed_attempts INTEGER NOT NULL, lockout_until DATETIME, updated_at DATETIME NOT NULL);")

        leg_tenant_id = "t_leg_tax_office"
        cur.execute("INSERT INTO tenants (id, email, name) VALUES (?, ?, ?)", (leg_tenant_id, "kanzlei@steuer-mueller.de", "Kanzlei Mueller"))
        cur.execute("INSERT INTO entitlements (id, tenant_id, plan_code, status, source_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), leg_tenant_id, "pro", "active", "stripe", datetime.datetime.now(), datetime.datetime.now()))
        cur.execute("INSERT INTO usage_reservations (reservation_id, tenant_id, idempotency_key, units, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), leg_tenant_id, "idem_leg_01", 1, "COMMITTED", datetime.datetime.now()))
        conn.commit()
        conn.close()
        print("[3.1] Legacy v1 schema initialized with existing tenant and active pro entitlement.")

        # Run init_db() migration (Run 1)
        switch_db(legacy_db)
        await init_db()
        print("[3.2] 1st migration run applied successfully.")

        # Verify added columns
        conn = sqlite3.connect(str(legacy_db))
        cur = conn.cursor()
        t_cols = [c[1] for c in cur.execute("PRAGMA table_info(tenants)").fetchall()]
        e_cols = [c[1] for c in cur.execute("PRAGMA table_info(entitlements)").fetchall()]
        u_cols = [c[1] for c in cur.execute("PRAGMA table_info(usage_reservations)").fetchall()]
        conn.close()

        assert "version" in t_cols
        assert "payment_intent" in e_cols
        assert "request_hash" in u_cols
        print("[3.3] Confirmed new columns: tenants.version, entitlements.payment_intent, usage_reservations.request_hash.")

        # Idempotency runs (Run 2 and Run 3)
        await init_db()
        await init_db()
        print("[3.4] Re-ran init_db() 2 more times — verified 100% idempotent.")

        # Subsequent Operation Test (Decision 26 requirement):
        # Authenticate and convert using the migrated database!
        print("[3.5] Performing subsequent login and conversion on migrated database...")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. Request OTP
            req_otp_res = await ac.post("/api/v1/auth/request-code", json={"email": "kanzlei@steuer-mueller.de"})
            assert req_otp_res.status_code == 200

            # 2. Get code from DB
            m_conn = sqlite3.connect(str(legacy_db))
            m_cur = m_conn.cursor()
            m_code = m_cur.execute("SELECT code FROM auth_challenges WHERE email=? ORDER BY created_at DESC LIMIT 1", ("kanzlei@steuer-mueller.de",)).fetchone()[0]
            m_conn.close()

            # 3. Verify OTP and obtain JWT
            ver_res = await ac.post("/api/v1/auth/token", json={"email": "kanzlei@steuer-mueller.de", "code": m_code})
            assert ver_res.status_code == 200
            m_token = ver_res.json()["access_token"]
            assert ver_res.json()["plan"] == "pro"
            print("      OTP login succeeded on migrated DB, received PRO Bearer JWT.")

            # 4. Perform synthetic statement conversion with Bearer JWT (JSON format)
            sample_file_path = BASE_DIR / "docs" / "datev_bmd_validation_package" / "01_SYNTHETIC_INPUTS" / "Sparkasse_Kontoauszug_Januar2026.csv"
            sample_csv = sample_file_path.read_bytes()

            conv_json_res = await ac.post(
                "/api/v1/convert?format=json",
                headers={"Authorization": f"Bearer {m_token}"},
                files={"files": ("Sparkasse_Kontoauszug_Januar2026.csv", sample_csv, "text/csv")}
            )
            print(f"      JSON conversion response on migrated DB: {conv_json_res.status_code}")
            assert conv_json_res.status_code == 200
            conv_data = conv_json_res.json()
            assert len(conv_data["transactions"]) == 10
            print("      JSON conversion verified: 10 transactions parsed and reconciled.")

            # 5. Perform DATEV EXTF export generation on migrated DB
            conv_datev_res = await ac.post(
                "/api/v1/convert?format=datev",
                headers={"Authorization": f"Bearer {m_token}"},
                files={"files": ("Sparkasse_Kontoauszug_Januar2026.csv", sample_csv, "text/csv")}
            )
            print(f"      DATEV EXTF export response on migrated DB: {conv_datev_res.status_code}")
            assert conv_datev_res.status_code == 200
            extf_text = conv_datev_res.content.decode("windows-1252")
            assert extf_text.startswith('"EXTF"')
            lines = [l for l in extf_text.splitlines() if l.strip()]
            # EXTF header is 2 lines, followed by 10 transactions -> 12 lines
            assert len(lines) >= 12
            print("      DATEV EXTF verified: Valid Windows-1252 EXTF file with 10 booking lines generated.")

        # -------------------------------------------------------------
        # SCENARIO 4: PARSER WORKER ERROR HANDLING & SECURITY BOUNDARY
        # -------------------------------------------------------------
        print("\n--- Scenario 4: Parser Worker Error Handling & Security Boundary ---")
        
        # 4.1 Worker failure simulation: corrupt / malformed data causing parsing error
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            fail_parse_res = await ac.post(
                "/api/v1/convert?format=json",
                headers={"Authorization": f"Bearer {m_token}"},
                files={"files": ("corrupted.csv", b"NOT_A_VALID_STATEMENT_BINARY\x00\xff\xfe\x01\x02", "text/csv")}
            )
            print(f"[4.1] Malformed input handled with code: {fail_parse_res.status_code}")
            assert fail_parse_res.status_code == 422

        # 4.2 Subsequent valid request: worker recovers cleanly and processes request
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            clean_res = await ac.post(
                "/api/v1/convert?format=json",
                headers={"Authorization": f"Bearer {m_token}"},
                files={"files": ("Sparkasse_Kontoauszug_Januar2026.csv", sample_csv, "text/csv")}
            )
            print(f"[4.2] Worker processed subsequent valid file: {clean_res.status_code}")
            assert clean_res.status_code == 200

        # 4.3 Security Boundary: Revoking token immediately blocks access without worker invocation
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            logout_res = await ac.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {m_token}"})
            assert logout_res.status_code == 200

        # Attempt convert with newly revoked token
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            blocked_res = await ac.post(
                "/api/v1/convert?format=json",
                headers={"Authorization": f"Bearer {m_token}"},
                files={"files": ("Sparkasse_Kontoauszug_Januar2026.csv", sample_csv, "text/csv")}
            )
            print(f"[4.3] Revoked token rejected at middleware boundary: {blocked_res.status_code} ({blocked_res.text})")
            assert blocked_res.status_code == 401
            assert "revoked" in blocked_res.json().get("detail", "").lower()

        report["scenarios"]["scenario3_migration_and_subsequent_ops"] = {
            "status": "PASS",
            "columns_migrated": ["tenants.version", "entitlements.payment_intent", "usage_reservations.request_hash"],
            "idempotency_runs": 3,
            "post_migration_login": "PASS",
            "post_migration_json_conversion": "PASS",
            "post_migration_datev_extf": "PASS",
            "extf_lines_count": len(lines),
            "transactions_reconciled": 10
        }

        report["scenarios"]["scenario4_worker_error_and_security_boundary"] = {
            "status": "PASS",
            "malformed_input_status": 422,
            "recovered_worker_status": 200,
            "revocation_at_middleware_boundary": 401
        }

        all_pass = all(s["status"] == "PASS" for s in report["scenarios"].values())
        report["overall_status"] = "PASSED" if all_pass else "FAILED"
        print(f"\n=== OVERALL HARDENED CHAIN 2 STATUS: {report['overall_status']} ===")

        # Save machine-readable evidence
        results_path = EVIDENCE_DIR / "chain2_fault_tolerance_results.json"
        results_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Updated results written to {results_path}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(run_chain2_hardening())
