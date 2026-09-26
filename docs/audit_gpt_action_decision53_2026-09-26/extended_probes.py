"""Decision 51: synthetic local probes of the remaining operation-state boundaries.

One explicit exporter-failure injection models a retryable failure. No deployed
server, provider account, production secret or real statement is accessed.
"""
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


async def ledger(tenant):
    async with async_session_maker() as db:
        rows = (await db.execute(select(UsageReservation).where(
            UsageReservation.tenant_id == tenant))).scalars().all()
        return [{"status": row.status, "units": row.units,
                 "key": row.idempotency_key, "hash": row.request_hash} for row in rows]


async def main():
    await init_db()
    now = datetime.datetime.now(datetime.timezone.utc)
    names = ["hash", "released", "replay", "limit"]
    async with async_session_maker() as db:
        for name in names:
            tenant = "audit-" + name
            db.add(Tenant(id=tenant, email=name + "@example.invalid"))
            db.add(Entitlement(tenant_id=tenant, plan_code="starter", status="active",
                source_type="subscription", source_id="sub_" + tenant,
                current_period_start=now - datetime.timedelta(days=1),
                valid_until=now + datetime.timedelta(days=30)))
        await db.commit()
    headers = {name: {"Authorization": "Bearer " + create_access_token(
        user_id=name + "@example.invalid", tenant_id="audit-" + name)} for name in names}
    out = {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"],
        cwd=base.ROOT, text=True).strip(), "scope": "synthetic local ASGI; temporary SQLite"}

    async with AsyncClient(transport=ASGITransport(app=base.app),
                           base_url="https://audit.invalid") as client:
        # Concatenation of account and bank name is not an unambiguous hash encoding.
        p1 = base.payload("hash-session", request_id="same-operation",
                          default_bank_account="1200", bank_name="a")
        p2 = base.payload("hash-session", request_id="same-operation",
                          default_bank_account="120", bank_name="0a")
        h1 = gpt.compute_payload_hash(gpt.GptConvertRequest(**p1))
        h2 = gpt.compute_payload_hash(gpt.GptConvertRequest(**p2))
        r1 = await client.post("/v1/gpt/convert", json=p1, headers=headers["hash"])
        r2 = await client.post("/v1/gpt/convert", json=p2, headers=headers["hash"])
        out["distinct_accounts_same_request_id"] = {
            "hashes_equal": h1 == h2, "account_1": "1200", "account_2": "120",
            "responses": [base.brief(r1), base.brief(r2)],
            "previews_differ": r1.json().get("preview_csv") != r2.json().get("preview_csv"),
            "second_quota": r2.json().get("free_tier_status"),
            "ledger": await ledger("audit-hash")}

        # Positive control: a changed amount does get rejected under one operation ID.
        changed = base.payload("hash-session", request_id="same-operation",
            default_bank_account="1200", bank_name="a", transactions=[
                {"booking_date": "2026-03-10", "amount": -20, "description": "Synthetic"}])
        out["changed_amount_conflict"] = base.brief(await client.post(
            "/v1/gpt/convert", json=changed, headers=headers["hash"]))

        # Ingestion selects file_base64 before raw_content, hashing does the reverse.
        mixed_responses = []
        mixed_hashes = []
        for amount in [10, 20]:
            csv = ("Buchungstag;Betrag;Waehrung;Verwendungszweck\n"
                   f"10.03.2026;-{amount},00;EUR;Synthetic\n").encode("utf-8")
            mixed = base.payload("mixed-session", request_id="mixed-input-operation",
                transactions=None, raw_content="unchanged ignored content",
                file_base64=base64.b64encode(csv).decode("ascii"), filename="statement.csv")
            mixed_hashes.append(gpt.compute_payload_hash(gpt.GptConvertRequest(**mixed)))
            response = await client.post("/v1/gpt/convert", json=mixed, headers=headers["hash"])
            mixed_responses.append({"http": response.status_code,
                "net_balance": response.json().get("summary", {}).get("net_balance")})
        mixed_rows = [row for row in await ledger("audit-hash")
                      if row["key"] == "gpt_mixed-input-operation"]
        out["file_and_raw_input_hash_mismatch"] = {"hashes_equal": mixed_hashes[0] == mixed_hashes[1],
            "responses": mixed_responses, "ledger": mixed_rows}

        # Explicit one-shot exporter fault, followed by unrelated usage and a retry.
        retry = base.payload("released-session", request_id="released-operation")
        real_export = gpt.export_to_datev_csv
        def fail_export(*args, **kwargs):
            raise RuntimeError("Synthetic audit exporter failure")
        gpt.export_to_datev_csv = fail_export
        try:
            failed = await client.post("/v1/gpt/convert", json=retry,
                                       headers=headers["released"])
        finally:
            gpt.export_to_datev_csv = real_export
        after_failure = await ledger("audit-released")
        async with async_session_maker() as db:
            db.add(UsageReservation(tenant_id="audit-released", idempotency_key="other-usage",
                                   units=20, status="COMMITTED"))
            await db.commit()
        fresh = await client.post("/v1/gpt/convert", json=base.payload(
            "released-session", request_id="fresh-operation"), headers=headers["released"])
        retried = await client.post("/v1/gpt/convert", json=retry, headers=headers["released"])
        out["released_retry_after_exhaustion"] = {
            "injection": "one exporter RuntimeError before commit; subsequently restored",
            "failed_response": base.brief(failed), "ledger_after_failure": after_failure,
            "fresh_request": base.brief(fresh), "released_retry": base.brief(retried),
            "ledger_after_retry": await ledger("audit-released")}

        # Observe actual exporter execution on a completed identical retry.
        calls = 0
        def count_export(*args, **kwargs):
            nonlocal calls
            calls += 1
            return real_export(*args, **kwargs)
        gpt.export_to_datev_csv = count_export
        try:
            identical = base.payload("replay-session", request_id="completed-operation")
            a = await client.post("/v1/gpt/convert", json=identical, headers=headers["replay"])
            b = await client.post("/v1/gpt/convert", json=identical, headers=headers["replay"])
            # Cache expiry/eviction is simulated by clearing the dedicated cache.
            gpt.gpt_download_cache.clear()
            c = await client.post("/v1/gpt/convert", json=identical, headers=headers["replay"])
        finally:
            gpt.export_to_datev_csv = real_export
        out["completed_replay_execution"] = {
            "instrumentation": "wrapper counts real exporter calls; clear simulates cache eviction",
            "responses": [base.brief(r) for r in [a, b, c]],
            "exporter_calls": calls, "distinct_download_ids": len({
                r.json().get("download_id") for r in [a, b, c]}),
            "ledger": await ledger("audit-replay")}

        # Twenty different statements in a single conversation, then the 21st.
        limit_responses = []
        for n in range(21):
            p = base.payload("one-conversation", transactions=[
                {"booking_date": "2026-03-10", "amount": -(n + 1), "description": "Synthetic"}])
            limit_responses.append(await client.post("/v1/gpt/convert", json=p,
                                                    headers=headers["limit"]))
        out["twenty_one_distinct_statements"] = {
            "codes": [r.status_code for r in limit_responses],
            "twentieth_quota": limit_responses[19].json().get("free_tier_status"),
            "last": base.brief(limit_responses[20]), "ledger_rows": len(await ledger("audit-limit"))}

        # Bounded field snippets do not bound the number of validation errors.
        invalid = base.payload("many-errors", transactions=[
            {"booking_date": "2026-03-10", "amount": "x", "description": "Synthetic"}] * 600)
        raw = json.dumps(invalid, ensure_ascii=False, separators=(",", ":"))
        bad = await client.post("/v1/gpt/convert", content=raw.encode("utf-8"),
            headers={"content-type": "application/json"})
        out["many_validation_errors"] = {"http": bad.status_code,
            "request_characters": len(raw), "response_characters": len(bad.text),
            "error_count": len(bad.json().get("detail", []))}

    Path(__file__).with_name("extended_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    await engine.dispose()
    base.audit_tmp.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
