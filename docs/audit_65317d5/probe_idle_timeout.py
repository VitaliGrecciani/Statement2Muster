"""Synthetic idle lifetime and actual route timeout witnesses. No external services."""
import os,sys,asyncio,uuid,time,threading,json
from pathlib import Path
from collections import OrderedDict
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
os.chdir(OUT);os.environ.pop('SQLITE_DB_PATH',None)
os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(OUT/('timeout-'+uuid.uuid4().hex+'.sqlite')).as_posix()
os.environ['EMAIL_BACKEND']='memory';os.environ['STRIPE_SECRET_KEY']='sk_test_mock'
sys.path.insert(0,str(ROOT/'backend'))
from app.main import app,registry
from app.core.cache import BoundedMemoryCache
from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import init_db,async_session_maker,engine
from app.db.models import Tenant,Entitlement
from httpx import AsyncClient,ASGITransport
R={}
async def main():
 cache=BoundedMemoryCache(ttl_seconds=1)
 cache.set('financial',b'SYNTHETIC DATA',ttl_seconds=0.02)
 await asyncio.sleep(0.06)
 # Call base implementation: observation must not invoke subclass purge.
 R['idle']={'raw_entries_after_ttl':OrderedDict.__len__(cache._entries),'bytes_after_ttl':cache._current_bytes}
 R['idle']['entries_after_instrumented_len']=len(cache._entries)
 await init_db()
 async with async_session_maker() as db:
  t=Tenant(email='timeout@example.com');db.add(t);await db.flush();tid=t.id
  db.add(Entitlement(tenant_id=tid,plan_code='pro',status='active',source_type='subscription',source_id='sub_timeout'));await db.commit()
 stopped=threading.Event();started=threading.Event();original=registry.parse_file
 def slow(**kwargs):
  started.set();time.sleep(0.25);stopped.set();return [],None
 registry.parse_file=slow
 settings.PARSER_TIMEOUT_SECONDS=0.03
 try:
  async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic.invalid') as c:
   r=await c.post('/api/v1/convert?format=json',headers={'Authorization':'Bearer '+create_access_token('timeout@example.com',tid),'X-Idempotency-Key':uuid.uuid4().hex},files={'files':('SYNTHETIC_PRIVATE_NAME.csv',b'Datum;Text;Betrag\n01.01.2025;Test;1\n','text/csv')})
   R['timeout']={'http':r.status_code,'worker_started':started.is_set(),'worker_still_running_when_response_received':not stopped.is_set()}
   await asyncio.sleep(0.3)
   R['timeout']['worker_completed_after_response']=stopped.is_set()
 finally:registry.parse_file=original
 await engine.dispose()
 (OUT/'idle-timeout-results.json').write_text(json.dumps(R,indent=2));print(json.dumps(R,indent=2))
asyncio.run(main())
