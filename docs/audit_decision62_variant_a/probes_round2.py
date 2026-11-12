"""Post-fix Decision 62 Round-2 verification probes. Synthetic data, temporary SQLite only."""
import asyncio
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


async def run():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select, func
    from app.db.session import init_db, async_session_maker, engine
    from app.db.models import Tenant, UsageReservation
    from app.core.security import create_access_token
    from app.main import app, canonical_operation_cache, _idempotent_result_cache, parser_supervisor
    from app.parsers.erste_parser import ErsteBankAustriaParser
    from app.schemas.canonical import CanonicalTransaction
    from app.services.reconciliation_service import build_statement_result
    from test_bmd_bankauszug_erste import build_synthetic_erste_bank_6page_pdf, make_valid_at_iban

    await init_db()
    async with async_session_maker() as db:
        db.add(Tenant(id="audit62r2", email="audit62r2@example.invalid"))
        await db.commit()
    token = create_access_token(user_id="audit62r2@example.invalid", tenant_id="audit62r2")
    headers = {"Authorization": f"Bearer {token}"}

    async def units():
        async with async_session_maker() as db:
            return (
                await db.execute(
                    select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
                        UsageReservation.tenant_id == "audit62r2", UsageReservation.status == "COMMITTED"
                    )
                )
            ).scalar()

    results = {"scope": "Decision 62 Round-2 verification; local ASGI / synthetic fixtures / temporary SQLite"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 1. R62-1: bare format=json without Valuta (preview only: operation_id=None, 0 quota committed)
        before = await units()
        pdf_bytes = build_synthetic_erste_bank_6page_pdf(make_valid_at_iban())
        r = await c.post(
            "/api/v1/convert?format=json",
            headers=headers,
            files={"files": ("synthetic.pdf", pdf_bytes, "application/pdf")},
        )
        r_body = r.json()
        # 2. R62-1: format=json&target_format=bmd_bankauszug without Valuta -> 422 with result, 0 quota committed
        r_targeted = await c.post(
            "/api/v1/convert?format=json&target_format=bmd_bankauszug",
            headers=headers,
            files={"files": ("synthetic.pdf", pdf_bytes, "application/pdf")},
        )
        results["ui_json_without_valuta"] = {
            "bare_convert_http": r.status_code,
            "bare_operation_id": r_body.get("operation_id"),
            "bare_export_eligible": r_body.get("export_eligible"),
            "targeted_422_http": r_targeted.status_code,
            "targeted_has_result_preview": "result" in r_targeted.json(),
            "committed_delta": await units() - before,
        }

        # 3. R62-2 + R62-7 + R62-8: Eviction / replay / no-store / account code validation
        calls = 0
        original = parser_supervisor.parse_file

        async def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return await original(*args, **kwargs)

        parser_supervisor.parse_file = counted
        try:
            payload = b"Datum;Text;Betrag\n05.09.2026;Synthetic office;50,00\n"
            h = {**headers, "X-Idempotency-Key": "audit62r2-replay"}
            first = await c.post(
                "/api/v1/convert?format=json&target_format=datev",
                headers=h,
                files={"files": ("audit.csv", payload, "text/csv")},
            )
            op1 = first.json()["operation_id"]
            canonical_operation_cache.delete(op1)
            replay = await c.post(
                "/api/v1/convert?format=json&target_format=datev",
                headers=h,
                files={"files": ("audit.csv", payload, "text/csv")},
            )
            dead = await c.get(f"/api/v1/operations/{op1}/export?format=bmd_bankauszug", headers=headers)
            results["operation_evicted_only"] = {
                "replay_http": replay.status_code,
                "export_http": dead.status_code,
                "parser_calls": calls,
            }

            canonical_operation_cache.clear()
            _idempotent_result_cache.clear()
            retry = await c.post(
                "/api/v1/convert?format=json&target_format=datev",
                headers=h,
                files={"files": ("audit.csv", payload, "text/csv")},
            )
            results["both_caches_evicted"] = {
                "http": retry.status_code,
                "parser_calls": calls,
                "cache_control": retry.headers.get("cache-control"),
            }

            fresh_conv = await c.post(
                "/api/v1/convert?format=json&target_format=datev",
                headers={**headers, "X-Idempotency-Key": "audit62r2-export"},
                files={"files": ("audit.csv", payload, "text/csv")},
            )
            op2 = fresh_conv.json()["operation_id"]
            ex = await c.get(f"/api/v1/operations/{op2}/export?format=bmd_bankauszug", headers=headers)
            results["export_headers"] = {
                "http": ex.status_code,
                "cache_control": ex.headers.get("cache-control"),
            }
            unsafe = await c.get(
                f"/api/v1/operations/{op2}/export",
                headers=headers,
                params={"format": "bmd", "default_bank_account": '1200";"EXTRA'},
            )
            results["export_account_validation"] = {
                "http": unsafe.status_code,
                "detail": unsafe.json().get("detail") if unsafe.status_code != 200 else None,
            }
        finally:
            parser_supervisor.parse_file = original

    # 4. R62-4: Text-fallback malformed amount protection
    class NoColumnPage:
        def extract_words(self):
            return []

    p = ErsteBankAustriaParser()
    raw, errors = p._extract_page_transactions(
        page=NoColumnPage(),
        page_text=(
            "Buchungstext Valuta/Value Beträge/Amounts in EUR\n"
            "Good 01.09.2026 10,00-\n"
            "Bad 02.09.2026 12,3X-\n"
        ),
        page_num=1,
        seg_num=29,
        account_holder="Synthetic",
        account_iban="",
        currency="EUR",
        filename="synthetic.pdf",
        use_valuta_as_booking_date=True,
    )
    results["malformed_amount_text_fallback"] = {
        "transactions": len(raw),
        "errors": errors,
        "description": raw[0]["Buchungstext"],
        "amount_cents": raw[0]["_amount_cents"],
    }

    # 5. R62-5: Order-independent chaining & duplicate zero-net statement
    def tx(cents, day):
        return CanonicalTransaction(
            tenant_id="audit62r2",
            account_id="synthetic-account",
            booking_date=dt.date(2026, 9, day),
            amount_cents=cents,
        )

    a, b = tx(100, 1), tx(200, 1)
    segments = [
        dict(opening_cents=0, closing_cents=100, txs=[a], file="a", order=0),
        dict(opening_cents=100, closing_cents=300, txs=[b], file="b", order=1),
    ]

    def reconciliation(segs, txs):
        return build_statement_result(
            "r", "audit62r2", txs, {"default_synthetic-account": segs}, len(segs), len(segs)
        ).overall_reconciliation

    rev = [dict(segments[1], order=0), dict(segments[0], order=1)]
    z = [tx(100, 1), tx(-100, 2)]
    zero = dict(opening_cents=0, closing_cents=0, txs=z, file="duplicate", order=0)
    results["multifile_chain"] = {
        "same_day_forward": reconciliation(segments, [a, b]),
        "same_day_reversed": reconciliation(rev, [a, b]),
        "duplicated_zero_net_statement": reconciliation([zero, dict(zero, order=1)], z + z),
    }

    # 6. R62-3, R62-5, R62-6: Client-side DATEV/BMD quoting/EUR, discontinuous chain, late export race
    harness = (
        (ROOT / "backend/test_bmd_bankauszug_erste.py")
        .read_text(encoding="utf-8")
        .split('node_script = r"""', 1)[1]
        .split("// 1. Test encode", 1)[0]
    )
    js = harness + r'''
const tx = {booking_date:'2026-09-01',amount_cents:-100,currency:'EUR',description:'Office',reference:'R',contra_account:'4930',account_id:'A',validation_status:'VALID'};
const res = {transactions:[tx],overall_reconciliation:'UNVERIFIED'};
const datev = sandbox.buildCanonicalResultExport(res, 'datev').csvText;
const bmd = sandbox.buildCanonicalResultExport(res, 'bmd').csvText;
const page=(num,open,close,date,amt)=>['Erste Bank Kontoauszug Digitales Banking',`KONTOAUSZUG Nr. ${num}/2026`,'IBAN: AT611904300234573201',`Alter Kontostand ${open}`,'Buchungstext Valuta/Value Beträge/Amounts in EUR',`Test ${date} ${amt}`,`Neuer Kontostand/New Balance ${close}`].join('\n');
const pages=[page('029','100,00','90,00','01.09.2026','10,00-'),page('030','200,00','180,00','02.09.2026','20,00-')];
sandbox.extractTextFromPdf=async idx=>({text:pages[idx],pageTexts:[pages[idx]],lowTextPages:[]});
sandbox.displayCanonicalPreview=noop;
sandbox.updateReconciliationBadge=noop;
sandbox.renderSafeguards=noop;
let observed;
sandbox.applyClientSideExportToPreview=(result,fmt)=>{observed={aggregate:result.overall_reconciliation,export_blocks:sandbox.computeClientExportBlocks(result,fmt)}};
vm.runInContext('valutaAsBookingCheckbox.checked=true; currentSelectedFormat="bmd_bankauszug";',sandbox);
(async()=>{
await sandbox.processClientSideFiles([{name:'a.pdf',arrayBuffer:async()=>0},{name:'b.pdf',arrayBuffer:async()=>1}]);
sandbox.chrome.storage.local.get=async()=>({authToken:'synthetic-token'});
let completeBody;
const deferredBody=new Promise(resolve=>{completeBody=resolve});
sandbox.fetch=async()=>({ok:true,headers:{get:()=>null},arrayBuffer:()=>deferredBody});
vm.runInContext('currentExportSource="backend";currentOperationId="synthetic-old-op";',sandbox);
const pending=sandbox.switchPreviewFormat('bmd_bankauszug');
await Promise.resolve();await Promise.resolve();await Promise.resolve();
sandbox.clearFile();
sandbox.syncFormatSelection('datev');
completeBody(new TextEncoder().encode('Transaction Booking Date;old-result').buffer);
await pending;
const race=vm.runInContext('({selected:currentSelectedFormat,filename:currentCsvFilename,downloadEnabled:!btnDownloadCsv.disabled,text:currentCsvText})',sandbox);
console.log(JSON.stringify({datev,bmd,offline_discontinuous_chain:observed,late_export_after_reset:race}));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    node = subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if node.returncode:
        raise RuntimeError(node.stderr)
    jr = json.loads(node.stdout.strip().splitlines()[-1])
    datev_csv = jr.pop("datev")
    bmd_csv = jr.pop("bmd")
    drows = list(csv.reader(io.StringIO(datev_csv), delimiter=";"))
    brows = list(csv.reader(io.StringIO(bmd_csv), delimiter=";"))
    results["local_export"] = {
        "datev_raw_row1": datev_csv.splitlines()[0],
        "datev_header_fields": len(drows[0]),
        "datev_header_currency_col22": drows[0][21],
        "datev_header_col17": drows[0][16],
        "datev_contra_account": drows[2][7],
        "bmd_header": brows[0],
        "bmd_contra_account": brows[1][3],
    }
    results.update(jr)
    await engine.dispose()
    return results


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="s2m-audit62-r2-", ignore_cleanup_errors=True) as tmp:
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + (Path(tmp) / "audit.db").as_posix()
        os.environ["SQLITE_DB_PATH"] = (Path(tmp) / "audit.db").as_posix()
        results = asyncio.run(run())
        target = Path(__file__).with_name("probe_results_round2.json")
        target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
