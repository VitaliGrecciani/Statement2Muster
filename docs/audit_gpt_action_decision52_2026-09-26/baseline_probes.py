"""Decision 49 follow-up: synthetic local ASGI probes; isolated temporary SQLite.

No deployed server, production keys, mail, Stripe or client data are accessed.
Run from repo root: backend/.venv/Scripts/python.exe -E <this file>.
"""
import asyncio
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
audit_tmp = tempfile.TemporaryDirectory(prefix="s2m-gpt-followup-probes-")
audit_db = Path(audit_tmp.name) / "probe.db"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + audit_db.as_posix()
os.environ["ENVIRONMENT"] = "development"

import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, revoke_token, _revoked_tokens
from app.db.session import init_db, async_session_maker, engine
from app.db.models import Tenant, Entitlement, UsageReservation
from app.api.endpoints.gpt_action import gpt_download_cache, gpt_free_tier_tracker


def payload(session, **overrides):
    result = {"session_id": session, "transactions": [
        {"booking_date": "2026-03-10", "amount": -10, "description": "Synthetic"}]}
    result.update(overrides)
    return result


def brief(response):
    try:
        body = response.json()
    except Exception:
        body = {}
    return {"http": response.status_code, "status": body.get("status"),
            "plan": body.get("free_tier_status", {}).get("plan"),
            "detail": body.get("detail")}


async def main():
    await init_db()
    now = datetime.datetime.now(datetime.timezone.utc)
    async with async_session_maker() as db:
        db.add_all([Tenant(id="audit-starter", email="starter@example.invalid"),
                    Tenant(id="audit-full", email="full@example.invalid")])
        for tenant in ["audit-starter", "audit-full"]:
            db.add(Entitlement(tenant_id=tenant, plan_code="starter", status="active",
                source_type="subscription", source_id="sub_" + tenant,
                valid_until=now + datetime.timedelta(days=30),
                current_period_start=now - datetime.timedelta(days=1)))
        db.add(UsageReservation(tenant_id="audit-full", idempotency_key="earlier-use",
                               units=20, status="COMMITTED"))
        await db.commit()

    token = create_access_token(user_id="starter@example.invalid", tenant_id="audit-starter")
    full_token = create_access_token(user_id="full@example.invalid", tenant_id="audit-full")
    headers = {"Authorization": "Bearer " + token}
    results = {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"],
        cwd=ROOT, text=True).strip(), "scope": "local ASGI; synthetic data; temporary isolated SQLite"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://audit.invalid") as client:
        results["fake_keys"] = {}
        for key in ["s2m_test_pro_key", "PRO-DEMO-2026", "cs_live_audit_nonexistent", "sub_audit_nonexistent"]:
            r = await client.post("/v1/gpt/convert", json=payload(key, license_key=key))
            results["fake_keys"][key] = brief(r)
        results["bare_email"] = brief(await client.post("/v1/gpt/convert",
            json=payload("email-only", email="starter@example.invalid")))
        results["exhausted_starter_new_request"] = brief(await client.post("/v1/gpt/convert",
            json=payload("new-full"), headers={"Authorization": "Bearer " + full_token}))

        statuses = []
        amounts = []
        for amount in [-10, -20, -30]:
            r = await client.post("/v1/gpt/convert", json=payload("same-conversation",
                transactions=[{"booking_date": "2026-03-10", "amount": amount, "description": "Synthetic"}]),
                headers=headers)
            statuses.append(brief(r))
            amounts.append(r.json().get("summary", {}).get("net_balance"))
        async with async_session_maker() as db:
            rows = (await db.execute(select(UsageReservation).where(
                UsageReservation.tenant_id == "audit-starter"))).scalars().all()
            ledger = [{"status": row.status, "units": row.units,
                       "request_hash": row.request_hash} for row in rows]
        results["different_inputs_same_session"] = {"responses": statuses,
            "returned_net_balances": amounts, "ledger": ledger}
        r = await client.post("/v1/gpt/convert", json=payload("same-conversation",
            transactions=[{"booking_date": "invalid", "amount": -10, "description": "Synthetic"}]),
            headers=headers)
        async with async_session_maker() as db:
            rows = (await db.execute(select(UsageReservation).where(
                UsageReservation.tenant_id == "audit-starter"))).scalars().all()
            ledger = [{"status": row.status, "units": row.units} for row in rows]
        results["invalid_retry_mutates_prior_committed_ledger"] = {"response": brief(r), "ledger_after": ledger}

        revoke_token(token)
        results["revoked_token_header"] = brief(await client.post("/v1/gpt/convert",
            json=payload("revoked-header"), headers=headers))
        results["revoked_token_body"] = brief(await client.post("/v1/gpt/convert",
            json=payload("revoked-body", license_key=token)))
        _revoked_tokens.clear()
        original_url = settings.DATABASE_URL
        settings.DATABASE_URL = "sqlite+aiosqlite:///" + (Path(audit_tmp.name) / "missing-registry.db").as_posix()
        try:
            results["missing_registry_header"] = brief(await client.post("/v1/gpt/convert",
                json=payload("registry-header"), headers=headers))
            results["missing_registry_body"] = brief(await client.post("/v1/gpt/convert",
                json=payload("registry-body", license_key=token)))
        finally:
            settings.DATABASE_URL = original_url

        for label, txs in [
            ("invalid_date", [{"booking_date": "invalid", "amount": 1, "description": "Synthetic"}]),
            ("mixed_years", [{"booking_date": "2025-01-02", "amount": 1, "description": "Synthetic"},
                              {"booking_date": "2026-01-02", "amount": 1, "description": "Synthetic"}]),
            ("mixed_currencies", [{"booking_date": "2026-01-02", "amount": 1, "currency": c,
                                   "description": "Synthetic"} for c in ["EUR", "USD"]])]:
            results[label] = brief(await client.post("/v1/gpt/convert", json=payload(label, transactions=txs)))

        results["ambiguous_date"] = {}
        r = await client.post("/v1/gpt/convert", json=payload("ambiguous-date",
            transactions=[{"booking_date": "03/04/2026", "amount": 1, "description": "Synthetic"}]))
        results["ambiguous_date"] = {"response": brief(r), "parsed_date": r.json().get("summary", {}).get("date_from")}

        gpt_free_tier_tracker.set("used_sess_concurrent", 2)
        raw = "Buchungstag;Betrag;Waehrung;Verwendungszweck\n10.03.2026;-10,00;EUR;Synthetic\n"
        rs = await asyncio.gather(*[client.post("/v1/gpt/convert", json=payload("concurrent",
            transactions=None, raw_content=raw)) for _ in range(2)])
        results["concurrent_demo_real_parser"] = {"responses": [brief(r) for r in rs],
                                                  "used_after": gpt_free_tier_tracker.get("used_sess_concurrent")}

        old_batch = settings.MAX_BATCH_SIZE_BYTES
        settings.MAX_BATCH_SIZE_BYTES = 64
        try:
            results["content_length_budget"] = brief(await client.post("/v1/gpt/convert",
                content=b"x" * 65, headers={"content-type": "application/json"}))
            async def chunks():
                yield b"x" * 32
                yield b"x" * 33
            results["chunked_budget"] = brief(await client.post("/v1/gpt/convert",
                content=chunks(), headers={"content-type": "application/json"}))
        finally:
            settings.MAX_BATCH_SIZE_BYTES = old_batch

        r = await client.post("/v1/gpt/convert", json=payload("1500-rows", transactions=[
            {"booking_date": "2026-01-02", "amount": 1, "description": "Synthetic"}] * 1500))
        results["normal_large_batch"] = {"response": brief(r), "json_characters": len(r.text),
            "inline_base64": r.json().get("file_base64") is not None}

        oversized_account_payload = payload("oversized-account", default_bank_account="1" * 40000,
            transactions=[{"booking_date": "2026-01-02", "amount": 1, "description": "Synthetic"}] * 3)
        r = await client.post("/v1/gpt/convert", json=oversized_account_payload)
        results["response_bound_counterexample"] = {"response": brief(r),
            "request_json_characters": len(json.dumps(oversized_account_payload)),
            "response_json_characters": len(r.text), "inline_base64": r.json().get("file_base64") is not None}

    spec_yaml = yaml.safe_load((ROOT / "docs/chatgpt/openapi.yaml").read_text(encoding="utf-8"))
    spec_json = json.loads((ROOT / "docs/chatgpt/openapi.json").read_text(encoding="utf-8"))
    results["schema"] = {"yaml_json_equal": spec_yaml == spec_json,
        "description_characters": len(spec_yaml["paths"]["/v1/gpt/convert"]["post"]["description"]),
        "paths": list(spec_yaml["paths"])}
    Path(__file__).with_name("probe_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    gpt_download_cache.clear()
    gpt_free_tier_tracker.clear()
    await engine.dispose()
    audit_tmp.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
