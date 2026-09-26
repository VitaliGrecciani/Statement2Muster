"""Additional synthetic raw/file admission checks; count real supervisor calls."""
import asyncio
import base64
import datetime
import json
from pathlib import Path
import subprocess

import baseline_probes as base
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.api.endpoints import gpt_action as gpt
from app.core.security import create_access_token
from app.db.models import Tenant, Entitlement, UsageReservation
from app.db.session import init_db, async_session_maker, engine


async def main():
    await init_db()
    now = datetime.datetime.now(datetime.timezone.utc)
    raw = "Buchungstag;Betrag;Waehrung;Verwendungszweck\n10.03.2026;-10,00;EUR;Synthetic\n"
    body = base.payload("shared-raw-session", transactions=None, raw_content=raw, request_id="raw-operation")
    busy_body = dict(body, request_id="busy-operation")
    async with async_session_maker() as db:
        for name in ["full", "busy", "a", "b"]:
            db.add(Tenant(id="admission-" + name, email=name + "@example.invalid"))
            db.add(Entitlement(tenant_id="admission-" + name, plan_code="starter", status="active",
                source_type="subscription", source_id="sub_admission_" + name,
                current_period_start=now - datetime.timedelta(days=1),
                valid_until=now + datetime.timedelta(days=30)))
        db.add(UsageReservation(tenant_id="admission-full", idempotency_key="earlier-spend",
                               status="COMMITTED", units=20))
        db.add(UsageReservation(tenant_id="admission-busy", idempotency_key="gpt_busy-operation",
            request_hash=gpt.compute_payload_hash(gpt.GptConvertRequest(**busy_body)),
            status="RESERVED", units=1))
        await db.commit()
    headers = {name: {"Authorization": "Bearer " + create_access_token(
        user_id=name + "@example.invalid", tenant_id="admission-" + name)}
        for name in ["full", "busy", "a", "b"]}
    calls = 0
    actual_parse = gpt.parser_supervisor.parse_file
    async def count_parse(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await actual_parse(*args, **kwargs)
    gpt.parser_supervisor.parse_file = count_parse
    out = {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"],
        cwd=base.ROOT, text=True).strip(), "scope": "synthetic local ASGI; temporary SQLite"}
    try:
        async with AsyncClient(transport=ASGITransport(app=base.app), base_url="https://audit.invalid") as client:
            file_body = dict(body, raw_content=None, file_base64=base64.b64encode(raw.encode()).decode("ascii"))
            for name, tenant, payload, expected in [
                ("exhausted_raw", "full", body, 429),
                ("exhausted_file", "full", file_body, 429),
                ("in_progress_raw", "busy", busy_body, 409)]:
                start = calls
                response = await client.post("/v1/gpt/convert", json=payload, headers=headers[tenant])
                out[name] = {"response": base.brief(response), "parser_calls": calls - start}
                assert response.status_code == expected and calls == start
            a = await client.post("/v1/gpt/convert", json=body, headers=headers["a"])
            assert a.status_code == 200 and calls == 1
            start = calls
            changed = dict(body, raw_content=raw.replace("-10,00", "-20,00"))
            conflict = await client.post("/v1/gpt/convert", json=changed, headers=headers["a"])
            out["changed_raw_replay"] = {"response": base.brief(conflict), "parser_calls": calls - start}
            assert conflict.status_code == 409 and calls == start
            b = await client.post("/v1/gpt/convert", json=body, headers=headers["b"])
            assert b.status_code == 200 and calls == 2
            async with async_session_maker() as db:
                rows = (await db.execute(select(UsageReservation).where(
                    UsageReservation.tenant_id.in_(["admission-a", "admission-b"])))).scalars().all()
                ledger = [{"tenant": row.tenant_id, "status": row.status, "units": row.units} for row in rows]
            out["two_allowed_tenants_same_id_and_payload"] = {
                "codes": [a.status_code, b.status_code], "distinct_download_ids":
                    a.json()["download_id"] != b.json()["download_id"], "parser_calls": calls, "ledger": ledger}
            assert a.json()["download_id"] != b.json()["download_id"] and len(ledger) == 2
    finally:
        gpt.parser_supervisor.parse_file = actual_parse
    out["all_checks_passed"] = True
    Path(__file__).with_name("admission_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    await engine.dispose()
    base.audit_tmp.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
