"""Check entitlement semantics, not merely row counts. Local synthetic events only."""
import os,sys,asyncio,uuid,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
os.chdir(OUT);os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(OUT/('billing-'+uuid.uuid4().hex+'.sqlite')).as_posix()
os.environ['STRIPE_SECRET_KEY']='sk_test_audit';os.environ['STRIPE_WEBHOOK_SECRET']='whsec_audit'
sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy import select
from app.db.session import init_db,async_session_maker,engine
from app.db.models import Entitlement
from app.services.billing_service import process_stripe_event
from app.core.config import settings
async def main():
 await init_db();result={}
 async with async_session_maker() as db:
  obj={'id':'cs_synthetic_async','mode':'payment','amount_total':8900,'currency':'eur','payment_status':'paid','payment_intent':'pi_synthetic','customer_details':{'email':'async-proof@example.com'}}
  async def deliver(kind,data):
   await process_stripe_event(db,{'id':'evt_'+uuid.uuid4().hex,'type':kind,'data':{'object':data}})
  await deliver('checkout.session.async_payment_succeeded',obj)
  async def rows():
   return [{'status':e.status,'plan':e.plan_code} for e in (await db.execute(select(Entitlement).where(Entitlement.source_id==obj['id']))).scalars().all()]
  result['async_without_expanded_line_items']=await rows()
  await deliver('checkout.session.completed',{**obj,'line_items':{'data':[{'price':{'id':settings.STRIPE_PRICE_LIFETIME}}]}})
  result['same_purchase_after_known_price_arrives']=await rows()
  await db.rollback()
 await engine.dispose();(OUT/'fulfillment-results.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
asyncio.run(main())
