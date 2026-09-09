"""Local synthetic audit witnesses. No real Stripe calls, PDFs or project database."""
import os, sys, asyncio, json, uuid, csv, io, hashlib, zipfile, importlib.metadata
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + (OUT / ('probe-' + uuid.uuid4().hex + '.sqlite')).as_posix()
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_audit_synthetic'
os.environ['STRIPE_WEBHOOK_SECRET'] = 'whsec_audit_synthetic'
sys.path.insert(0, str(ROOT / 'backend'))
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from app.main import app
from app.db.session import init_db, async_session_maker, engine
from app.db.models import Tenant, Entitlement, UsageReservation, AuthChallenge
from app.services.quota_service import check_and_reserve_quota, get_or_create_trial_entitlement
from app.services.billing_service import process_stripe_event
from app.parsers.csv_parser import StructuredCsvParser
from app.exporters.muster_csv import export_to_muster_csv
from app.exporters.datev import export_to_datev_csv
from app.core.config import settings

results = {}
CSV = b'Datum;Text;Betrag\n01.01.2025;Synthetic;10,00\n'
async def main():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://audit.invalid') as c:
        r = await c.post('/api/v1/auth/token', json={'email':'audit@example.com'})
        r2 = await c.post('/api/v1/auth/token', json={'email':'audit@example.com','code':'WRONG'})
        results['identity_without_verification'] = {
            'no_code': r.status_code,
            'wrong_code': r2.status_code,
            'bypassed': r.status_code == 200 or r2.status_code == 200
        }
        
        # Proper OTP challenge/response authentication
        await c.post('/api/v1/auth/request-code', json={'email':'audit@example.com'})
        async with async_session_maker() as db:
            ch = (await db.execute(select(AuthChallenge).where(AuthChallenge.email=='audit@example.com').order_by(AuthChallenge.id.desc()))).scalars().first()
            valid_code = ch.code
        r_auth = await c.post('/api/v1/auth/token', json={'email':'audit@example.com', 'code': valid_code})
        tid = r_auth.json()['tenant_id']
        headers = {'Authorization': 'Bearer ' + r_auth.json()['access_token'], 'X-Idempotency-Key': 'same-key'}

        results['jwks_status'] = (await c.get('/api/v1/auth/jwks.json')).status_code
        statuses = []
        for n in range(5):
            rr = await c.post('/api/v1/convert?format=json', headers=headers, files={'files':('synthetic.csv', CSV.replace(b'Synthetic', f'Changed{n}'.encode()), 'text/csv')})
            statuses.append(rr.status_code)
        async with async_session_maker() as db:
            units = (await db.execute(select(func.sum(UsageReservation.units)).where(UsageReservation.tenant_id==tid))).scalar()
        results['changed_body_replay'] = {'statuses': statuses, 'charged_units': units, 'replay_attack_blocked': statuses == [200, 409, 409, 409, 409]}
        
        headers_new = {'Authorization': 'Bearer ' + r_auth.json()['access_token'], 'X-Idempotency-Key': 'part-key'}
        partial = await c.post('/api/v1/convert?format=json', headers=headers_new, files=[('files',('good.csv', CSV, 'text/csv')), ('files',('bad.csv', b'unsupported', 'text/csv'))])
        results['partial_success'] = {'status': partial.status_code, 'successful_files': partial.json().get('successful_files'), 'unparsed_lines': partial.json().get('unparsed_lines')}
        
        old = settings.MAX_BATCH_SIZE_BYTES
        settings.MAX_BATCH_SIZE_BYTES = 100
        boundary = 'AuditBoundary'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="synthetic.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode() + CSV + f'\r\n--{boundary}--\r\n'.encode())
        async def chunks():
            yield body[:80]
            yield body[80:]
        headers_chunk = {'Authorization': 'Bearer ' + r_auth.json()['access_token'], 'X-Idempotency-Key': 'chunk-key', 'Content-Type': f'multipart/form-data; boundary={boundary}'}
        rr = await c.post('/api/v1/convert?format=json', headers=headers_chunk, content=chunks())
        results['actual_body_budget'] = {'configured_bytes': 100, 'sent_bytes': len(body), 'status': rr.status_code}
        settings.MAX_BATCH_SIZE_BYTES = old
        
        old = settings.MAX_FILE_SIZE_BYTES; settings.MAX_FILE_SIZE_BYTES = 10
        headers_file = {'Authorization': 'Bearer ' + r_auth.json()['access_token'], 'X-Idempotency-Key': 'file-key'}
        rr = await c.post('/api/v1/convert?format=json', headers=headers_file, files={'files':('synthetic.csv', CSV, 'text/csv')})
        results['per_file_budget'] = {'configured_bytes': 10, 'file_bytes': len(CSV), 'status': rr.status_code}
        settings.MAX_FILE_SIZE_BYTES = old
    async with async_session_maker() as db:
        t = Tenant(email='reserved@example.com'); db.add(t); await db.flush()
        res1_ok = False
        res2_blocked = False
        try:
            await check_and_reserve_quota(db, t.id, 3, 'one', request_hash='hash1')
            res1_ok = True
        except Exception:
            pass
        try:
            await check_and_reserve_quota(db, t.id, 3, 'two', request_hash='hash2')
        except Exception:
            res2_blocked = True
        results['pending_quota'] = {'trial_allowance': 3, 'first_reservation_ok': res1_ok, 'second_reservation_blocked': res2_blocked}
        await db.rollback()
    async with async_session_maker() as db:
        obj = {'id':'cs_synthetic','mode':'payment','amount_total':1,'currency':'usd','payment_status':'unpaid','payment_intent':'pi_synthetic','customer':'cus_synthetic','customer_details':{'email':'billing@example.com'}}
        for i in range(2):
            try:
                await process_stripe_event(db, {'id':f'evt_synthetic_{i}','type':'checkout.session.completed','data':{'object':obj}})
            except Exception:
                pass
        ents = (await db.execute(select(Entitlement).where(Entitlement.source_id=='cs_synthetic'))).scalars().all()
        results['billing_unpaid_unknown_purchase_and_refund'] = {'unpaid_rejected_entitlements_count': len(ents)}
        
        # Valid Lifetime checkout session
        valid_obj = {'id': 'cs_valid_pro', 'mode': 'payment', 'amount_total': 14900, 'currency': 'eur', 'payment_status': 'paid', 'payment_intent': 'pi_valid_pro', 'customer': 'cus_pro', 'customer_details': {'email': 'pro@example.com'}}
        t_pro = Tenant(email='pro@example.com'); db.add(t_pro); await db.flush()
        await process_stripe_event(db, {'id': 'evt_valid_pro', 'type': 'checkout.session.completed', 'data': {'object': valid_obj}})
        results['trial_then_paid_selected_plan'] = (await get_or_create_trial_entitlement(db, t_pro.id)).plan_code
        
        # Refund matching
        await process_stripe_event(db, {'id': 'evt_refund', 'type': 'charge.refunded', 'data': {'object': {'payment_intent': 'pi_valid_pro'}}})
        ent_refunded = (await db.execute(select(Entitlement).where(Entitlement.source_id == 'cs_valid_pro'))).scalars().first()
        results['refund_status'] = ent_refunded.status if ent_refunded else 'not_found'
        await db.rollback()
    p=StructuredCsvParser()
    fixtures={
        'invalid_amount':'Datum;Text;Betrag\n01.01.2025;Synthetic;garbage\n',
        'dropped_date':'Datum;Text;Betrag\n31.02.2025;Lost;10\n01.03.2025;Kept;20\n',
        'currency_alias':'Datum;Text;Betrag;Waehrung\n01.01.2025;Synthetic;10;USD\n',
        'account_mixing':'Datum;Text;Betrag;IBAN\n01.01.2025;One;10;SYNTHETIC_A\n02.01.2025;Two;20;SYNTHETIC_B\n',
        'debit_suffix':'Datum;Text;Betrag;Saldo\n01.01.2025;Synthetic;10,00 S;100,00\n',
        'reference_delimiter':'Datum;Text;Betrag;Referenz\n01.01.2025;=1+1;10;"REF;BROKEN"\n',
    }
    for name,value in fixtures.items():
        txs,summary=p.parse_to_canonical(value.encode(),'synthetic.csv','synthetic')
        results[name]={'transactions':[{'date':str(t.booking_date),'cents':t.amount_cents,'currency':t.currency,'account':t.account_id,'validation':t.validation_status} for t in txs]}
        if name=='debit_suffix':
            from app.services.reconciliation_service import reconcile_account
            results[name]['reconciliation']=reconcile_account(summary.account_id,summary.bank_name,txs,summary.opening_balance_cents,summary.closing_balance_cents).reconciliation_status
        if name=='reference_delimiter':
            output=export_to_muster_csv(txs).decode('cp1252')
            results[name]['csv_column_counts']=[len(r) for r in csv.reader(io.StringIO(output),delimiter=';')]
            results[name]['formula_preserved']=';=1+1;' in output
            datev=export_to_datev_csv(txs).decode('cp1252')
            (OUT/'synthetic-datev.csv').write_bytes(datev.encode('cp1252'))
            results['datev_previous_year']={'transaction_year':2025,'header':datev.splitlines()[0],'positive_bank_movement_indicator':txs[0].soll_haben_kennzeichen}
    results['versions']={n:importlib.metadata.version(n) for n in ['python-multipart','fastapi','starlette','stripe','pytest','SQLAlchemy']}
    results['release_hashes']={}
    for path in ['dist/statement2muster-chrome-v1.0.2.zip','dist/statement2muster-firefox-v1.0.2.zip','backend/Dockerfile','backend/requirements.txt']:
        results['release_hashes'][path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest().upper()
    results['zip_source_comparison']={}
    for flavor,folder in [('chrome','extension'),('firefox','extension_firefox_build')]:
        with zipfile.ZipFile(ROOT/f'dist/statement2muster-{flavor}-v1.0.2.zip') as z:
            mismatches=[]
            for name in z.namelist():
                if name.endswith('/'):continue
                path=ROOT/folder/name.replace('\\','/')
                if not path.exists() or path.read_bytes()!=z.read(name):mismatches.append(name)
            results['zip_source_comparison'][flavor]={'entries':len(z.namelist()),'mismatches':mismatches}
    await engine.dispose()
    (OUT/'probe-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True,indent=2))
asyncio.run(main())
