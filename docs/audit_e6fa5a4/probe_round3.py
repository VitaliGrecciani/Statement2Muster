"""Independent local synthetic probes. Never reads the application's working DB."""
import os, sys, asyncio, uuid, json, hashlib, zipfile, datetime, importlib.metadata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(OUT/('probe-'+uuid.uuid4().hex+'.sqlite')).as_posix()
os.environ['STRIPE_SECRET_KEY']='sk_test_synthetic_audit'
os.environ['STRIPE_WEBHOOK_SECRET']='whsec_synthetic_audit'
sys.path.insert(0,str(ROOT/'backend'))
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from app.main import app, registry
from app.db.session import init_db, async_session_maker, engine
from app.db.models import Tenant, Entitlement, AuthChallenge, UsageReservation
from app.core.security import create_access_token
from app.core.config import settings
from app.services.quota_service import check_and_reserve_quota
from app.services.billing_service import process_stripe_event
R={}; GOOD=b'Datum;Text;Betrag\n01.01.2025;Synthetic;10,00\n'
async def main():
 await init_db()
 async with async_session_maker() as db:
  t=Tenant(email='round3@example.com');db.add(t);await db.flush();tid=t.id
  db.add(Entitlement(tenant_id=tid,plan_code='pro',status='active',source_type='subscription',source_id='sub_round3'))
  await db.commit()
 h={'Authorization':'Bearer '+create_access_token('round3@example.com',tid)}
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic.invalid') as c:
  R['no_code']=(await c.post('/api/v1/auth/token',json={'email':'round3@example.com'})).status_code
  R['wrong_code']=(await c.post('/api/v1/auth/token',json={'email':'round3@example.com','code':'000000'})).status_code
  R['jwks']=(await c.get('/api/v1/auth/jwks.json')).status_code
  req=await c.post('/api/v1/auth/request-code',json={'email':'round3@example.com'})
  async with async_session_maker() as db:
   ch=(await db.execute(select(AuthChallenge).where(AuthChallenge.email=='round3@example.com',AuthChallenge.used==0))).scalars().first()
   code=ch.code
  statuses=[]
  for _ in range(30):
   statuses.append((await c.post('/api/v1/auth/token',json={'email':'round3@example.com','code':'000000'})).status_code)
  valid=await c.post('/api/v1/auth/token',json={'email':'round3@example.com','code':code})
  R['otp_attempt_budget']={'request_status':req.status_code,'wrong_attempts':len(statuses),'statuses':sorted(set(statuses)),'valid_after_attempts':valid.status_code,'code_source':'test-only direct DB read; no email delivery'}
  replay_h={**h,'X-Idempotency-Key':'repeat'};calls=0;original=registry.parse_file
  def count_parse(*a,**kw):
   nonlocal calls
   calls+=1
   return original(*a,**kw)
  registry.parse_file=count_parse
  try:
   statuses=[]
   ids=[]
   for _ in range(4):
    r=await c.post('/api/v1/convert?format=json',headers=replay_h,files={'files':('same.csv',GOOD,'text/csv')})
    statuses.append(r.status_code);ids.append(r.json()['transactions'][0]['transaction_id'])
   R['identical_replay']={'statuses':statuses,'parser_calls':calls,'distinct_transaction_ids':len(set(ids))}
   R['changed_body']=(await c.post('/api/v1/convert?format=json',headers=replay_h,files={'files':('same.csv',GOOD+b'02.01.2025;Changed;2\n','text/csv')})).status_code
  finally:registry.parse_file=original
  cases={
   'error_amount': [('bad.csv',b'Datum;Text;Betrag\n01.01.2025;Synthetic;garbage\n')],
   'missing_amount':[('missing.csv',b'Datum;Text;Betrag\n01.01.2025;Synthetic;\n')],
   'invalid_date':[('date.csv',b'Datum;Text;Betrag\n31.02.2025;Synthetic;10\n')],
   'invalid_and_valid_dates':[('dates.csv',b'Datum;Text;Betrag\n31.02.2025;Invalid;10\n01.03.2025;Valid;20\n')],
   'ignored_extension':[('good.csv',GOOD),('unsupported.xml',b'<synthetic/>')],
   'mixed_accounts':[('mixed.csv',b'Datum;Text;Betrag;IBAN\n01.01.2025;A;10;SYNTHETIC_A\n02.01.2025;B;20;SYNTHETIC_B\n')],
   'mixed_years':[('years.csv',b'Datum;Text;Betrag\n31.12.2025;A;10\n01.01.2026;B;20\n')],
   'mixed_currencies':[('curr.csv',b'Datum;Text;Betrag;Currency;Saldo\n01.01.2025;A;10;EUR;100\n02.01.2025;B;20;USD;120\n')],
  }
  for name,fs in cases.items():
   files=[('files',(f,b,'text/csv')) for f,b in fs]
   rj=await c.post('/api/v1/convert?format=json',headers=h,files=files)
   fmt='datev' if name=='mixed_years' else 'muster_csv'
   re=await c.post('/api/v1/convert?format='+fmt,headers=h,files=files)
   data=rj.json()
   R[name]={'json_status':rj.status_code,'validation':[x['validation_status'] for x in data.get('transactions',[])],'reconciliation':data.get('overall_reconciliation'),'successful_files':data.get('successful_files'),'account_count':len(data.get('accounts',{})),'export_status':re.status_code,'export_excerpt':re.content.decode('cp1252')[:700]}
  old=settings.MAX_ROWS_PER_FILE;settings.MAX_ROWS_PER_FILE=1
  try:
   rr=await c.post('/api/v1/convert?format=json',headers=h,files={'files':('rows.csv',GOOD+b'02.01.2025;Second;20\n','text/csv')})
   R['row_budget']={'limit':1,'rows':len(rr.json().get('transactions',[])),'status':rr.status_code}
  finally:settings.MAX_ROWS_PER_FILE=old
  old=settings.MAX_BATCH_SIZE_BYTES;settings.MAX_BATCH_SIZE_BYTES=100
  try:
   body=b'--b\r\nContent-Disposition: form-data; name="files"; filename="synthetic.csv"\r\n\r\n'+GOOD+b'\r\n--b--\r\n'
   async def chunks():yield body[:60];yield body[60:]
   R['chunked_status']=(await c.post('/api/v1/convert?format=json',headers={**h,'Content-Type':'multipart/form-data; boundary=b'},content=chunks())).status_code
  finally:settings.MAX_BATCH_SIZE_BYTES=old
  old=settings.MAX_FILE_SIZE_BYTES;settings.MAX_FILE_SIZE_BYTES=10
  try:R['per_file_status']=(await c.post('/api/v1/convert?format=json',headers=h,files={'files':('a.csv',GOOD,'text/csv')})).status_code
  finally:settings.MAX_FILE_SIZE_BYTES=old
 # Real distinct sessions, synchronize after BOTH quota SUM reads; don't alter returned data.
 async with async_session_maker() as db:
  t=Tenant(email='concurrent@example.com');db.add(t);await db.flush();ctid=t.id
  db.add(Entitlement(tenant_id=ctid,plan_code='trial',status='active',source_type='trial'))
  await db.commit()
 barrier=asyncio.Event();arrived=0
 async def reserve(n):
  nonlocal arrived
  async with async_session_maker() as db:
   original_execute=db.execute
   async def synchronized_execute(stmt,*a,**kw):
    nonlocal arrived
    result=await original_execute(stmt,*a,**kw)
    if 'sum(usage_reservations.units)' in str(stmt):
     arrived+=1
     if arrived==2:barrier.set()
     await asyncio.wait_for(barrier.wait(),5)
    return result
   db.execute=synchronized_execute
   try:
    r=await check_and_reserve_quota(db,ctid,3,'concurrent-'+str(n),request_hash=str(n));await db.commit();return r.status
   except Exception as e:await db.rollback();return type(e).__name__+':'+str(e)
 R['concurrent_sessions']=await asyncio.gather(reserve(1),reserve(2))
 async with async_session_maker() as db:
  R['concurrent_reserved_units']=(await db.execute(select(func.sum(UsageReservation.units)).where(UsageReservation.tenant_id==ctid))).scalar()
  async def event(kind,obj):return await process_stripe_event(db,{'id':'evt_'+uuid.uuid4().hex,'type':kind,'data':{'object':obj}})
  await event('customer.subscription.deleted',{'id':'sub_round3'})
  await event('invoice.paid',{'subscription':'sub_round3'})
  ent=(await db.execute(select(Entitlement).where(Entitlement.source_id=='sub_round3'))).scalars().first()
  R['cancel_then_late_invoice']=ent.status
  base={'id':'cs_unknown_price','mode':'payment','amount_total':8900,'payment_status':'paid','currency':'eur','payment_intent':'pi_synth','customer_details':{'email':'unknown@example.com'},'line_items':{'data':[{'price':{'id':'price_unrelated'}}]}}
  await event('checkout.session.completed',base)
  e=(await db.execute(select(Entitlement).where(Entitlement.source_id==base['id']))).scalars().first()
  R['unknown_price_exact_amount']=None if not e else e.plan_code
  await event('checkout.session.completed',{**base,'id':'cs_async','payment_status':'unpaid'})
  await event('checkout.session.async_payment_succeeded',{**base,'id':'cs_async'})
  R['async_success_entitlements']=(await db.execute(select(func.count(Entitlement.id)).where(Entitlement.source_id=='cs_async'))).scalar()
  await event('charge.refunded',{'id':'ch_synth','payment_intent':'pi_synth'})
  R['normal_lifetime_refund']=e.status
  await db.rollback()
 R['versions']={n:importlib.metadata.version(n) for n in ['fastapi','starlette','pytest','python-multipart','SQLAlchemy']}
 R['hashes']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest().upper() for p in ['dist/statement2muster-chrome-v1.0.2.zip','dist/statement2muster-firefox-v1.0.2.zip','backend/Dockerfile','backend/requirements.txt']}
 R['zip_mismatches']={}
 for flavor,folder in [('chrome','extension'),('firefox','extension_firefox_build')]:
  with zipfile.ZipFile(ROOT/f'dist/statement2muster-{flavor}-v1.0.2.zip') as z:
   R['zip_mismatches'][flavor]=[n for n in z.namelist() if not n.endswith('/') and (not (ROOT/folder/n).exists() or (ROOT/folder/n).read_bytes()!=z.read(n))]
 await engine.dispose()
 (OUT/'results.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(R,ensure_ascii=True,indent=2))
asyncio.run(main())
