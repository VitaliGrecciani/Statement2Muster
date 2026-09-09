"""Synthetic only; no real email, Stripe network or production database."""
import os, sys, asyncio, uuid, json, datetime, time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
os.chdir(OUT)
os.environ.pop('SQLITE_DB_PATH',None)
os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(OUT/('final-'+uuid.uuid4().hex+'.sqlite')).as_posix()
os.environ['EMAIL_BACKEND']='memory'
os.environ['EMAIL_OUTBOX_PATH']=str(OUT/'final-synthetic-outbox.jsonl')
os.environ['STRIPE_SECRET_KEY']='sk_test_synthetic'
sys.path.insert(0,str(ROOT/'backend'))
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.core.cache import BoundedMemoryCache
from app.core.config import settings
from app.services.email_service import email_service
from app.services.billing_service import process_stripe_event
from app.db.session import init_db, async_session_maker, engine
from app.db.models import Entitlement
R={}
async def main():
 await init_db()
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic.invalid') as c:
  email='final-proof@example.com'
  r=await c.post('/api/v1/auth/request-code',json={'email':email})
  code=email_service.get_test_inbox()[-1]['code']
  t=await c.post('/api/v1/auth/token',json={'email':email,'code':code})
  h={'Authorization':'Bearer '+t.json()['access_token']}
  async def convert():
   return (await c.post('/api/v1/convert?format=json',headers={**h,'X-Idempotency-Key':uuid.uuid4().hex},files={'files':('synthetic.csv',b'Datum;Text;Betrag\n01.01.2025;Synthetic;10,00\n','text/csv')})).status_code
  before=await convert()
  logout=await c.post('/api/v1/auth/logout',headers=h)
  R['logout']={'request_code':r.status_code,'token':t.status_code,'before':before,'logout':logout.status_code,'same_token_after':await convert()}
 R['memory_backend_writes_disk']=Path(settings.EMAIL_OUTBOX_PATH).exists()
 old=settings.EMAIL_OUTBOX_PATH;settings.EMAIL_OUTBOX_PATH=str(OUT)
 settings.EMAIL_BACKEND='file'
 R['file_delivery_success_when_path_is_directory']=await email_service.send_verification_email('synthetic@example.com','123456',datetime.datetime.now(datetime.timezone.utc))
 settings.EMAIL_OUTBOX_PATH=old
 cache=BoundedMemoryCache(ttl_seconds=1,max_bytes=1024,max_entries=2)
 with patch('app.core.cache.time.time',return_value=100):cache.set('financial',b'SYNTHETIC BANK DATA')
 with patch('app.core.cache.time.time',return_value=102):
  R['cache']={'expired_object_retained_before_any_access':len(cache._entries)==1,'expired_value_served':cache.get('financial') is not None}
 async with async_session_maker() as db:
  obj={'id':'cs_final','mode':'subscription','subscription':'sub_final','amount_total':490,'currency':'eur','payment_status':'paid','customer_details':{'email':'billing-proof@example.com'}}
  async def send(kind,data):await process_stripe_event(db,{'id':'evt_'+uuid.uuid4().hex,'type':kind,'data':{'object':data}})
  with patch('stripe.checkout.Session.list_line_items') as spy:
   await send('checkout.session.completed',obj)
   R['stripe_test_key_line_items_api_calls']=spy.call_count
  ent=(await db.execute(select(Entitlement).where(Entitlement.source_id=='sub_final'))).scalars().one()
  R['quarantine_before_invoice']={'status':ent.status,'plan':ent.plan_code}
  await send('invoice.paid',{'subscription':'sub_final'})
  R['quarantine_after_invoice']={'status':ent.status,'plan':ent.plan_code}
  await db.rollback()
  await engine.dispose()
 (OUT/'final-results.json').write_text(json.dumps(R,indent=2),encoding='utf8');print(json.dumps(R,indent=2))

if __name__ == '__main__':
    asyncio.run(main())
