"""Synthetic independent follow-ups; isolated cwd/DB; no real mail/Stripe network."""
import os,sys,asyncio,uuid,json,datetime,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
os.chdir(OUT)
os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(OUT/('followup-'+uuid.uuid4().hex+'.sqlite')).as_posix()
os.environ['STRIPE_SECRET_KEY']='sk_test_audit';os.environ['STRIPE_WEBHOOK_SECRET']='whsec_audit'
sys.path.insert(0,str(ROOT/'backend'))
from httpx import AsyncClient,ASGITransport
from sqlalchemy import select,func
from app.main import app,registry,_idempotent_result_cache
from app.db.session import init_db,async_session_maker,engine
from app.db.models import Tenant,Entitlement
from app.services.billing_service import process_stripe_event
from app.services.quota_service import get_or_create_trial_entitlement
from app.core.security import create_access_token
R={};GOOD=b'Datum;Text;Betrag\n01.01.2025;Synthetic;10,00\n';YEARS=b'Datum;Text;Betrag\n31.12.2025;A;10\n01.01.2026;B;20\n'
async def main():
 await init_db()
 async with async_session_maker() as db:
  t=Tenant(email='followup@example.com');db.add(t);await db.flush();tid=t.id
  db.add(Entitlement(tenant_id=tid,plan_code='pro',status='active',source_type='subscription',source_id='sub_followup'));await db.commit()
 h={'Authorization':'Bearer '+create_access_token('followup@example.com',tid)}
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic.invalid') as c:
  email='otp-followup@example.com'
  await c.post('/api/v1/auth/request-code',json={'email':email})
  codes=[]
  for i in range(6):codes.append((await c.post('/api/v1/auth/token',json={'email':email,'code':'000000'})).status_code)
  new=(await c.post('/api/v1/auth/request-code',json={'email':email})).status_code
  after=(await c.post('/api/v1/auth/token',json={'email':email,'code':'000000'})).status_code
  R['lockout_reset']={'attempt_statuses':codes,'new_code_request':new,'wrong_attempt_after_new_code':after,'outbox_on_disk':(OUT/'docs/audit_2026-09-09_round3/email_outbox.jsonl').exists()}
  for fmt in ['datev','unexpected','']:
   r=await c.post('/api/v1/convert?format='+fmt,headers=h,files={'files':('years.csv',YEARS,'text/csv')})
   R['format_'+(fmt or 'empty')]={'status':r.status_code,'is_datev':r.content.startswith(b'"EXTF"')}
  key={**h,'X-Idempotency-Key':'profile-key'}
  r1=await c.post('/api/v1/convert?format=datev&default_bank_account=1200',headers=key,files={'files':('a.csv',GOOD,'text/csv')})
  r2=await c.post('/api/v1/convert?format=datev&default_bank_account=1800',headers=key,files={'files':('a.csv',GOOD,'text/csv')})
  R['changed_account_cached_response']={'first':r1.status_code,'second':r2.status_code,'same_response':r1.content==r2.content,'requested_1800_but_contains_1200':b'"1200"' in r2.content}
  original=registry.parse_file;calls=0
  def count(*a,**kw):
   nonlocal calls
   calls+=1;return original(*a,**kw)
  registry.parse_file=count
  try:
   await c.post('/api/v1/convert?format=json',headers={**h,'X-Idempotency-Key':'evicted'},files={'files':('a.csv',GOOD,'text/csv')})
   retained=sum(len(str(v[0])) for v in _idempotent_result_cache.values())
   _idempotent_result_cache.clear() # Simulate eviction/new worker; request and DB unchanged.
   again=await c.post('/api/v1/convert?format=json',headers={**h,'X-Idempotency-Key':'evicted'},files={'files':('a.csv',GOOD,'text/csv')})
   R['cache_miss_existing_reservation']={'status':again.status_code,'parser_calls':calls,'cache_content_chars_before_eviction':retained}
  finally:registry.parse_file=original
  # Feed real exporter results to independent UI fixtures, rather than a now-blocked response.
  for fmt in ['datev','bmd','muster_csv']:
   payload=b'Datum;Text;Betrag;Referenz\n01.01.2025;"SHOP;Branch";10,00;"REF;SECOND"\n'
   r=await c.post('/api/v1/convert?format='+fmt,headers=h,files={'files':('quoted.csv',payload,'text/csv')})
   (OUT/('fixture-'+fmt+'.csv')).write_bytes(r.content)
   R['fixture_'+fmt]=r.status_code
 async with async_session_maker() as db:
  obj={'id':'cs_unknown','mode':'payment','amount_total':8900,'payment_status':'paid','currency':'eur','payment_intent':'pi_unknown','customer_details':{'email':'unknown-round4@example.com'},'line_items':{'data':[{'price':{'id':'price_unrelated'}}]}}
  async def event(kind,obj):await process_stripe_event(db,{'id':'evt_'+uuid.uuid4().hex,'type':kind,'data':{'object':obj}})
  await event('checkout.session.completed',obj)
  ents=(await db.execute(select(Entitlement).where(Entitlement.source_id=='cs_unknown'))).scalars().all()
  R['unknown_price_actual_rows']=[{'plan':e.plan_code,'status':e.status} for e in ents]
  try:
   ent=await get_or_create_trial_entitlement(db,ents[0].tenant_id)
   R['effective_unknown_plan']=ent.plan_code
  except Exception as e:R['effective_unknown_plan_error']=type(e).__name__+': '+str(e)
  obj2={k:v for k,v in obj.items() if k!='line_items'};obj2.update(id='cs_no_line_items',payment_intent='pi_no_lines',customer_details={'email':'no-lines@example.com'})
  await event('checkout.session.completed',obj2)
  ent=(await db.execute(select(Entitlement).where(Entitlement.source_id=='cs_no_line_items'))).scalars().first()
  R['no_price_still_grants']=ent.plan_code
  await event('customer.subscription.deleted',{'id':'sub_followup'})
  await event('customer.subscription.updated',{'id':'sub_followup','status':'active'})
  ent=(await db.execute(select(Entitlement).where(Entitlement.source_id=='sub_followup'))).scalars().first()
  R['cancel_then_stale_updated']=ent.status
  await db.rollback()
 await engine.dispose()
 (OUT/'followup-results.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(R,ensure_ascii=True,indent=2))
asyncio.run(main())
