"""Read-only product audit using synthetic inputs and an isolated in-memory DB.

Run from the repo root with backend/.venv/Scripts/python.exe -E <this file>.
No production API, email, Stripe, or user database is accessed.
"""
import asyncio
import base64
import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENVIRONMENT"] = "development"

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
import yaml
from app.main import app
from app.core.config import settings
from app.db.models import Tenant, Entitlement, UsageReservation
from app.db.session import async_session_maker, get_db, init_db, engine
from app.api.endpoints.gpt_action import (
    gpt_download_cache, gpt_free_tier_tracker, verify_license,
)


async def isolated_db():
    async with async_session_maker() as db:
        yield db


def payload(session="audit", **overrides):
    data = {
        "session_id": session,
        "transactions": [{"booking_date": "2026-03-10", "amount": -10,
                          "description": "Synthetic audit transaction"}],
    }
    data.update(overrides)
    return data


async def main():
    await init_db()
    app.dependency_overrides[get_db] = isolated_db
    settings.ENVIRONMENT = "production"  # Demonstrate demo bypass has no env gate.
    results = {"git_head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "local ASGI app; synthetic data; isolated SQLite in memory"}

    results["keys_accepted_with_production_setting"] = {}
    for key in ["s2m_test_pro_key", "PRO-DEMO-2026", "cs_live_audit_nonexistent",
                "sub_audit_nonexistent", "s2m_live_audit_nonexistent"]:
        valid, plan, _ = await verify_license(None, key, None)
        results["keys_accepted_with_production_setting"][key] = {"valid": valid, "plan": plan}

    class BrokenDB:
        async def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("Synthetic unavailable license DB")

    valid, plan, _ = await verify_license(BrokenDB(), "sub_audit_nonexistent", None)
    results["db_failure_injected"] = {"valid": valid, "plan": plan}

    now = datetime.datetime.now(datetime.timezone.utc)
    async with async_session_maker() as db:
        db.add(Tenant(id="audit-owner", email="paid.owner@example.invalid"))
        db.add(Entitlement(id="audit-starter", tenant_id="audit-owner", plan_code="starter",
            status="active", source_type="subscription", source_id="sub_audit_starter",
            valid_until=now + datetime.timedelta(days=30),
            current_period_start=now - datetime.timedelta(days=1)))
        db.add(Entitlement(id="audit-canceled", tenant_id="audit-owner", plan_code="pro",
            status="canceled", source_type="subscription", source_id="sub_audit_canceled"))
        db.add(UsageReservation(reservation_id="audit-used", tenant_id="audit-owner",
            idempotency_key="audit-used", units=20, status="COMMITTED"))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://audit.invalid") as client:
        response = await client.post("/v1/gpt/convert", json=payload(email="paid.owner@example.invalid"))
        data = response.json()
        async with async_session_maker() as db:
            used = (await db.execute(select(func.sum(UsageReservation.units)).where(
                UsageReservation.tenant_id == "audit-owner"))).scalar()
        results["unauthenticated_email_of_exhausted_starter"] = {
            "http": response.status_code, "status": data.get("status"),
            "free_tier_status": data.get("free_tier_status"), "ledger_units_after": used,
        }
        response = await client.post("/v1/gpt/check-license", json={"license_key": "sub_audit_canceled"})
        results["canceled_subscription_id"] = response.json()

        gpt_free_tier_tracker.clear()
        statuses = []
        for session in ["audit-reset"] * 4 + ["audit-new-session"]:
            response = await client.post("/v1/gpt/convert", json=payload(session))
            statuses.append(response.json()["status"])
        results["session_rotation_statuses"] = statuses

        response = await client.post("/v1/gpt/convert", json=payload("audit-invalid-date",
            transactions=[{"booking_date": "not-a-date", "amount": -10, "description": "Synthetic"}]))
        results["invalid_date"] = {"http": response.status_code,
            "date_from": response.json().get("summary", {}).get("date_from"),
            "server_today": datetime.date.today().isoformat()}

        response = await client.post("/v1/gpt/convert", json=payload("audit-years", transactions=[
            {"booking_date": "2025-01-02", "amount": 1, "description": "Synthetic"},
            {"booking_date": "2026-01-02", "amount": 2, "description": "Synthetic"}]))
        data = response.json()
        rows = base64.b64decode(data["file_base64"]).decode("windows-1252").splitlines()
        results["datev_mixed_years"] = {"http": response.status_code,
            "header_year": rows[0].split(";")[12], "booking_dates": [r.split(";")[9] for r in rows[2:]]}

        response = await client.post("/v1/gpt/convert", json=payload("audit-currencies", transactions=[
            {"booking_date": "2026-01-02", "amount": 10, "currency": "EUR", "description": "Synthetic"},
            {"booking_date": "2026-01-02", "amount": 20, "currency": "USD", "description": "Synthetic"}]))
        results["mixed_currency_summary"] = {"http": response.status_code, "summary": response.json()["summary"]}

        response = await client.post("/v1/gpt/convert", json=payload("audit-1500-rows", transactions=[
            {"booking_date": "2026-01-02", "amount": 1, "description": "Synthetic"}] * 1500))
        results["action_response_1500_rows"] = {"http": response.status_code,
            "json_characters": len(response.text), "transactions": response.json()["summary"]["transaction_count"],
            "native_openai_file_response": "openaiFileResponse" in response.json()}

        old_limit = settings.MAX_ROWS_PER_FILE
        settings.MAX_ROWS_PER_FILE = 2
        response = await client.post("/v1/gpt/convert", json=payload("audit-row-limit", transactions=[
            {"booking_date": "2026-01-02", "amount": 1, "description": "Synthetic"}] * 3))
        results["configured_row_budget"] = {"configured_limit": 2, "submitted_rows": 3,
            "http": response.status_code, "status": response.json().get("status")}
        settings.MAX_ROWS_PER_FILE = old_limit

        old_size = settings.MAX_FILE_SIZE_BYTES
        settings.MAX_FILE_SIZE_BYTES = 32
        raw = "Buchungstag;Betrag;Waehrung;Verwendungszweck\n10.03.2026;-10,00;EUR;Synthetic audit\n"
        response = await client.post("/v1/gpt/convert", json=payload("audit-raw-limit",
            transactions=None, raw_content=raw))
        results["raw_input_budget"] = {"configured_bytes": 32, "submitted_bytes": len(raw.encode()),
            "http": response.status_code, "status": response.json().get("status"),
            "detail": response.json().get("detail")}
        settings.MAX_FILE_SIZE_BYTES = old_size

        # Real child-process parsing gives concurrent requests an actual await boundary.
        gpt_free_tier_tracker.clear()
        gpt_free_tier_tracker.set("used_sess_audit-concurrent", 2)
        responses = await asyncio.gather(*[client.post("/v1/gpt/convert", json=payload(
            "audit-concurrent", transactions=None, raw_content=raw)) for _ in range(2)])
        results["concurrent_free_quota"] = {"used_before": 2,
            "statuses": [r.json().get("status") for r in responses],
            "http": [r.status_code for r in responses],
            "used_after": gpt_free_tier_tracker.get("used_sess_audit-concurrent")}

    spec_yaml = yaml.safe_load((ROOT / "docs/chatgpt/openapi.yaml").read_text(encoding="utf-8"))
    spec_json = json.loads((ROOT / "docs/chatgpt/openapi.json").read_text(encoding="utf-8"))
    results["schema"] = {"yaml_json_equal": spec_yaml == spec_json,
        "openapi": spec_yaml.get("openapi"),
        "operation_description_lengths": {f"{method.upper()} {path}": len(op.get("description", ""))
            for path, methods in spec_yaml["paths"].items() for method, op in methods.items()},
        "file_response_declared": "openaiFileResponse" in json.dumps(spec_yaml)}
    out = Path(__file__).with_name("probe_results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    app.dependency_overrides.clear()
    gpt_download_cache.clear()
    gpt_free_tier_tracker.clear()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
