"""Synthetic Decision 52 cache isolation and real-parser replay probes."""
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
    async with async_session_maker() as db:
        for name in ["owner", "other", "file", "eviction"]:
            tenant = "audit-" + name
            db.add(Tenant(id=tenant, email=name + "@example.invalid"))
            db.add(Entitlement(tenant_id=tenant, plan_code="starter", status="active",
                source_type="subscription", source_id="sub_" + tenant,
                current_period_start=now - datetime.timedelta(days=1),
                valid_until=now + datetime.timedelta(days=30)))
        db.add(UsageReservation(tenant_id="audit-other", idempotency_key="other-spend",
                               units=20, status="COMMITTED"))
        await db.commit()
    headers = {name: {"Authorization": "Bearer " + create_access_token(
        user_id=name + "@example.invalid", tenant_id="audit-" + name)}
        for name in ["owner", "other", "file", "eviction"]}
    out = {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"],
        cwd=base.ROOT, text=True).strip(), "scope": "local ASGI; synthetic data; temporary SQLite"}
    async with AsyncClient(transport=ASGITransport(app=base.app), base_url="https://audit.invalid") as client:
        body = base.payload("shared-session", request_id="shared-client-operation")
        owner = await client.post("/v1/gpt/convert", json=body, headers=headers["owner"])
        other = await client.post("/v1/gpt/convert", json=body, headers=headers["other"])
        gpt.gpt_free_tier_tracker.set("used_sess_shared-session", 3)
        anonymous = await client.post("/v1/gpt/convert", json=body)
        download = await client.get(owner.json()["download_url"])
        control_body = dict(body, request_id="different-client-operation")
        other_control = await client.post("/v1/gpt/convert", json=control_body, headers=headers["other"])
        anon_control = await client.post("/v1/gpt/convert", json=control_body)
        async with async_session_maker() as db:
            rows = (await db.execute(select(UsageReservation).where(
                UsageReservation.tenant_id == "audit-other"))).scalars().all()
            other_rows = [{"units": row.units, "status": row.status,
                           "key": row.idempotency_key} for row in rows]
        out["cross_identity_operation_cache"] = {
            "owner": base.brief(owner), "other_tenant": base.brief(other),
            "anonymous": base.brief(anonymous),
            "other_received_exact_owner_response": other.content == owner.content,
            "anonymous_received_exact_owner_response": anonymous.content == owner.content,
            "download_id_shared": len({r.json().get("download_id") for r in [owner, other, anonymous]}) == 1,
            "download_http": download.status_code,
            "other_tenant_new_id_control": base.brief(other_control),
            "anonymous_new_id_control": base.brief(anon_control), "other_tenant_ledger": other_rows}

        # Count actual parser invocation; wrapper forwards to the real supervisor.
        csv = b"Buchungstag;Betrag;Waehrung;Verwendungszweck\n10.03.2026;-10,00;EUR;Synthetic\n"
        file_body = base.payload("file-session", request_id="file-operation", transactions=None,
            file_base64=base64.b64encode(csv).decode("ascii"), filename="statement.csv")
        real_parse = gpt.parser_supervisor.parse_file
        count = 0
        async def count_parse(*args, **kwargs):
            nonlocal count
            count += 1
            return await real_parse(*args, **kwargs)
        gpt.parser_supervisor.parse_file = count_parse
        try:
            first = await client.post("/v1/gpt/convert", json=file_body, headers=headers["file"])
            second = await client.post("/v1/gpt/convert", json=file_body, headers=headers["file"])
            gpt.gpt_download_cache.clear()
            third = await client.post("/v1/gpt/convert", json=file_body, headers=headers["file"])
        finally:
            gpt.parser_supervisor.parse_file = real_parse
        out["file_replay_parser_execution"] = {"instrumentation": "wrapper counts calls to real supervisor; clear simulates cache eviction",
            "responses": [base.brief(r) for r in [first, second, third]], "real_parser_calls": count,
            "first_and_second_response_identical": first.content == second.content}

        # Simulate eviction of file entry while operation entry is still in the same LRU cache.
        big = base.payload("eviction-session", request_id="eviction-operation", transactions=[
            {"booking_date": "2026-03-10", "amount": -10, "description": "Synthetic"}] * 150)
        before = await client.post("/v1/gpt/convert", json=big, headers=headers["eviction"])
        gpt.gpt_download_cache.delete(before.json()["download_id"])
        after = await client.post("/v1/gpt/convert", json=big, headers=headers["eviction"])
        download_url = after.json().get("download_url")
        link = await client.get(download_url) if download_url else None
        out["file_entry_evicted_operation_entry_present"] = {
            "injection": "delete file entry only, modeling independent LRU eviction",
            "initial": base.brief(before), "replay": base.brief(after),
            "inline_base64": after.json().get("file_base64") is not None,
            "operation_response_identical": before.content == after.content,
            "download_http": link.status_code if link else None}
    Path(__file__).with_name("cache_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    await engine.dispose()
    base.audit_tmp.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
