"""Synthetic actual process path and admission deadline; guarded for Windows spawn."""
import os,sys,uuid,asyncio,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))

async def main():
 os.chdir(OUT);os.environ.pop('SQLITE_DB_PATH',None)
 os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(OUT/('isolated-'+uuid.uuid4().hex+'.sqlite')).as_posix()
 os.environ['EMAIL_BACKEND']='memory';os.environ['STRIPE_SECRET_KEY']='sk_test_mock'
 os.environ['MAX_ROWS_PER_FILE']='1'
 from app.main import app
 from app.core.config import settings
 from app.core.security import create_access_token
 from app.db.session import init_db,async_session_maker,engine
 from app.db.models import Tenant,Entitlement
 from app.services.parser_process_supervisor import ParserProcessSupervisor,parser_supervisor
 from httpx import AsyncClient,ASGITransport
 R={'default_process_isolation':settings.PARSER_PROCESS_ISOLATION}
 settings.PARSER_PROCESS_ISOLATION=True
 await init_db()
 async with async_session_maker() as db:
  t=Tenant(email='isolation@example.com');db.add(t);await db.flush();tid=t.id
  db.add(Entitlement(tenant_id=tid,plan_code='pro',status='active',source_type='subscription',source_id='sub_isolation'));await db.commit()
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic.invalid') as c:
  h={'Authorization':'Bearer '+create_access_token('isolation@example.com',tid)}
  for name,body in [('one_row',b'Datum;Text;Betrag\n01.01.2025;A;1\n'),('over_row_limit',b'Datum;Text;Betrag\n01.01.2025;A;1\n02.01.2025;B;2\n')]:
   r=await c.post('/api/v1/convert?format=json',headers={**h,'X-Idempotency-Key':uuid.uuid4().hex},files={'files':('synthetic.csv',body,'text/csv')})
   R[name]={'http':r.status_code,'detail':r.json().get('detail')}
 settings.PARSER_TIMEOUT_SECONDS=0.02
 for _ in range(parser_supervisor.max_concurrency):await parser_supervisor.semaphore.acquire()
 try:
  async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic.invalid') as c:
   try:
    r=await c.post('/api/v1/convert?format=json',headers={**h,'X-Idempotency-Key':uuid.uuid4().hex},files={'files':('synthetic.csv',b'Datum;Text;Betrag\n01.01.2025;A;1\n','text/csv')})
    R['route_admission']={'http':r.status_code}
   except BaseException as e:
    R['route_admission']={'escaped_exception':type(e).__name__,'message':str(e)}
 finally:
  for _ in range(parser_supervisor.max_concurrency):parser_supervisor.semaphore.release()
 R['config_wiring']={'settings_concurrency':settings.PARSER_WORKER_CONCURRENCY,'actual_concurrency':parser_supervisor.max_concurrency,'settings_queue_depth':settings.PARSER_MAX_QUEUE_DEPTH,'actual_queue_depth':parser_supervisor.max_queue_depth}
 sup=ParserProcessSupervisor(max_concurrency=1,default_timeout=0.01)
 await sup.semaphore.acquire()
 task=asyncio.create_task(sup.parse_file(b'SYNTHETIC','x.csv','t',timeout=0.01))
 await asyncio.sleep(0.08)
 R['admission']={'timeout_seconds':0.01,'still_pending_after_80ms':not task.done()}
 task.cancel()
 try:await task
 except asyncio.CancelledError:pass
 sup.semaphore.release()
 import multiprocessing
 from fastapi import HTTPException
 try:
  await sup.parse_file(b'Datum;Text;Betrag\n01.01.2025;A;1\n','synthetic.csv','t',timeout=0.001)
  R['real_supervisor_timeout']={'http':200}
 except HTTPException as e:
  R['real_supervisor_timeout']={'http':e.status_code,'live_children_after_response':[p.pid for p in multiprocessing.active_children() if p.is_alive()]}
 await engine.dispose();(OUT/'isolated-route-results.json').write_text(json.dumps(R,indent=2));print(json.dumps(R,indent=2))

if __name__=='__main__':asyncio.run(main())
