"""Force overlapping reads in six independent synthetic DB sessions."""
import os,sys,uuid,asyncio,json,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
os.chdir(OUT);os.environ.pop('SQLITE_DB_PATH',None)
os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(OUT/('race-'+uuid.uuid4().hex+'.sqlite')).as_posix()
os.environ['EMAIL_BACKEND']='memory';sys.path.insert(0,str(ROOT/'backend'))
from app.main import app
from app.db.models import AuthRateLimit
from app.db.session import init_db,async_session_maker,engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from httpx import AsyncClient,ASGITransport
async def main():
 await init_db();email='race@example.com'
 async with async_session_maker() as db:
  db.add(AuthRateLimit(email=email,failed_attempts=0,request_count=0,window_start=datetime.datetime.now(datetime.timezone.utc)));await db.commit()
 original=AsyncSession.execute;barrier=asyncio.Barrier(6)
 async def execute(self,stmt,*a,**kw):
  if str(stmt).startswith('UPDATE auth_rate_limits SET') and 'request_count=' in str(stmt):
   await asyncio.wait_for(barrier.wait(),timeout=3)
  return await original(self,stmt,*a,**kw)
 AsyncSession.execute=execute
 try:
  async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic.invalid') as c:
   responses=await asyncio.gather(*[c.post('/api/v1/auth/request-code',json={'email':email}) for _ in range(6)])
 finally:AsyncSession.execute=original
 async with async_session_maker() as db:
  row=(await db.execute(select(AuthRateLimit).where(AuthRateLimit.email==email))).scalars().one()
  from app.services.email_service import email_service
  r={'parallel_requests':6,'statuses':[x.status_code for x in responses],'persisted_request_count':row.request_count,'delivered_memory_messages':len(email_service.get_test_inbox())}
 await engine.dispose();(OUT/'request-race-results.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
asyncio.run(main())
