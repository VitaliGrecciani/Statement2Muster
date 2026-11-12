"""Independent Decision 61 review probes. Synthetic data, temporary SQLite only."""
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
sys.path.insert(0, str(ROOT / 'backend'))


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
        db.add(Tenant(id='audit62', email='audit62@example.invalid'))
        await db.commit()
    token = create_access_token(user_id='audit62@example.invalid', tenant_id='audit62')
    headers = {'Authorization': f'Bearer {token}'}
    async def units():
        async with async_session_maker() as db:
            return (await db.execute(select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
                UsageReservation.tenant_id == 'audit62', UsageReservation.status == 'COMMITTED'))).scalar()

    results = {'scope': 'local ASGI / synthetic fixtures / temporary SQLite; no live deployment'}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        before = await units()
        r = await c.post('/api/v1/convert?format=json', headers=headers,
            files={'files': ('synthetic.pdf', build_synthetic_erste_bank_6page_pdf(make_valid_at_iban()), 'application/pdf')})
        op = r.json()['operation_id']
        exp = await c.get(f'/api/v1/operations/{op}/export?format=bmd_bankauszug', headers=headers)
        results['ui_json_without_valuta'] = {'convert_http': r.status_code,
            'export_eligible': r.json()['export_eligible'], 'export_http': exp.status_code,
            'committed_delta': await units() - before}

        calls = 0
        original = parser_supervisor.parse_file
        async def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return await original(*args, **kwargs)
        parser_supervisor.parse_file = counted
        payload = b'Datum;Text;Betrag\n05.09.2026;Synthetic office;50,00\n'
        h = {**headers, 'X-Idempotency-Key': 'audit62-replay'}
        first = await c.post('/api/v1/convert?format=json', headers=h,
            files={'files': ('audit.csv', payload, 'text/csv')})
        op1 = first.json()['operation_id']
        canonical_operation_cache.delete(op1)
        replay = await c.post('/api/v1/convert?format=json', headers=h,
            files={'files': ('audit.csv', payload, 'text/csv')})
        dead = await c.get(f'/api/v1/operations/{replay.json()["operation_id"]}/export?format=bmd_bankauszug', headers=headers)
        results['operation_evicted_only'] = {'replay_http': replay.status_code,
            'same_operation_id': replay.json()['operation_id'] == op1, 'export_http': dead.status_code,
            'parser_calls': calls}
        canonical_operation_cache.clear()
        _idempotent_result_cache.clear()
        retry = await c.post('/api/v1/convert?format=json', headers=h,
            files={'files': ('audit.csv', payload, 'text/csv')})
        results['both_caches_evicted'] = {'http': retry.status_code, 'parser_calls': calls,
            'new_operation_id': retry.json().get('operation_id') != op1}
        op2 = retry.json()['operation_id']
        ex = await c.get(f'/api/v1/operations/{op2}/export?format=bmd_bankauszug', headers=headers)
        results['export_headers'] = {'http': ex.status_code, 'cache_control': ex.headers.get('cache-control')}
        unsafe = await c.get(f'/api/v1/operations/{op2}/export', headers=headers,
            params={'format': 'bmd', 'default_bank_account': '1200";"EXTRA'})
        rows = list(csv.reader(io.StringIO(unsafe.content.decode('cp1252')), delimiter=';'))
        results['export_account_validation'] = {'http': unsafe.status_code, 'header_columns': len(rows[0]),
            'row_columns': len(rows[1])}
        parser_supervisor.parse_file = original

    class NoColumnPage:
        def extract_words(self):
            return []
    p = ErsteBankAustriaParser()
    raw, errors = p._extract_page_transactions(page=NoColumnPage(), page_text=(
        'Buchungstext Valuta/Value Beträge/Amounts in EUR\n'
        'Good 01.09.2026 10,00-\n'
        'Bad 02.09.2026 12,3X-\n'), page_num=1, seg_num=29,
        account_holder='Synthetic', account_iban='', currency='EUR', filename='synthetic.pdf',
        use_valuta_as_booking_date=True)
    results['malformed_amount_text_fallback'] = {'transactions': len(raw), 'errors': errors,
        'description': raw[0]['Buchungstext'], 'amount_cents': raw[0]['_amount_cents']}

    def tx(cents, day):
        return CanonicalTransaction(tenant_id='audit62', account_id='synthetic-account',
            booking_date=dt.date(2026, 9, day), amount_cents=cents)
    a, b = tx(100, 1), tx(200, 1)
    segments = [dict(opening_cents=0, closing_cents=100, txs=[a], file='a', order=0),
                dict(opening_cents=100, closing_cents=300, txs=[b], file='b', order=1)]
    def reconciliation(segs, txs):
        return build_statement_result('r', 'audit62', txs, {'default_synthetic-account': segs},
            len(segs), len(segs)).overall_reconciliation
    rev = [dict(segments[1], order=0), dict(segments[0], order=1)]
    z = [tx(100, 1), tx(-100, 2)]
    zero = dict(opening_cents=0, closing_cents=0, txs=z, file='duplicate', order=0)
    results['multifile_chain'] = {'same_day_forward': reconciliation(segments, [a,b]),
        'same_day_reversed': reconciliation(rev, [a,b]),
        'duplicated_zero_net_statement': reconciliation([zero,dict(zero,order=1)], z+z)}

    # Reuse only DOM stubs from the supplied Node test; execute independent assertions/measurements.
    harness = (ROOT/'backend/test_bmd_bankauszug_erste.py').read_text(encoding='utf-8').split('node_script = r"""',1)[1].split('// 1. Test encode',1)[0]
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
    node = subprocess.run(['node','-e',js], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if node.returncode:
        raise RuntimeError(node.stderr)
    jr = json.loads(node.stdout.strip().splitlines()[-1])
    drows = list(csv.reader(io.StringIO(jr.pop('datev')), delimiter=';'))
    brows = list(csv.reader(io.StringIO(jr.pop('bmd')), delimiter=';'))
    results['local_export'] = {'datev_header_fields': len(drows[0]), 'datev_header_currency_col22': drows[0][21],
        'datev_header_col17': drows[0][16], 'datev_contra_account':drows[2][7],
        'bmd_header': brows[0], 'bmd_contra_account': brows[1][3]}
    results.update(jr)
    await engine.dispose()
    return results


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='s2m-audit62-', ignore_cleanup_errors=True) as tmp:
        os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + (Path(tmp)/'audit.db').as_posix()
        os.environ['SQLITE_DB_PATH'] = (Path(tmp)/'audit.db').as_posix()
        results = asyncio.run(run())
        target = Path(__file__).with_name('probe_results.json')
        target.write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(results, ensure_ascii=False, indent=2))
