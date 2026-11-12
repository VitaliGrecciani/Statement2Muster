"""Independent Decision 63 boundary probes. Synthetic data, temporary SQLite, no live services."""
import asyncio
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

def chain_child():
    from app.schemas.canonical import CanonicalTransaction
    from app.services.reconciliation_service import _chain_file_segments
    segments = []
    for i in range(12):
        amounts = [100, -100] if i < 11 else [100]
        txs = [CanonicalTransaction(tenant_id='audit63', account_id='synthetic',
            booking_date=dt.date(2026, 9, 1), amount_cents=a,
            description=f'Synthetic segment {i} transaction {j}') for j, a in enumerate(amounts)]
        segments.append(dict(file=f'synthetic-{i}.pdf', opening_cents=0 if i < 11 else 1000,
            closing_cents=0 if i < 11 else 1100, txs=txs))
    print('CHAIN_STARTED', flush=True)
    start = time.perf_counter()
    result = _chain_file_segments(segments)
    print(json.dumps({'seconds': time.perf_counter()-start, 'result': result}))

async def endpoint_probes():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select, func
    from app.db.session import init_db, async_session_maker, engine
    from app.db.models import Tenant, UsageReservation
    from app.core.security import create_access_token
    from app.core.cache import shared_ram_budget, estimate_size
    from app.main import app, canonical_operation_cache, _idempotent_result_cache
    await init_db()
    async with async_session_maker() as db:
        db.add(Tenant(id='audit63', email='audit63@example.invalid'))
        await db.commit()
    headers = {'Authorization': 'Bearer ' + create_access_token(user_id='audit63@example.invalid', tenant_id='audit63')}
    payload = b'Datum;Text;Betrag\n05.09.2026;Synthetic office;50,00\n'
    files = {'files': ('synthetic.csv', payload, 'text/csv')}
    async def units():
        async with async_session_maker() as db:
            return (await db.execute(select(func.coalesce(func.sum(UsageReservation.units), 0)).where(
                UsageReservation.tenant_id == 'audit63', UsageReservation.status == 'COMMITTED'))).scalar()
    results = {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        canonical_operation_cache.clear()
        _idempotent_result_cache.clear()
        original_set = canonical_operation_cache.set
        original_budget = shared_ram_budget.max_bytes
        boundary = {}
        def constrained_set(key, value, *args, **kwargs):
            # Model the boundary where a canonical entry fits, but the entry + replay reference do not.
            boundary['canonical_bytes'] = estimate_size(value)
            shared_ram_budget.max_bytes = estimate_size(value) + 1
            boundary['shared_budget_bytes'] = shared_ram_budget.max_bytes
            return original_set(key, value, *args, **kwargs)
        canonical_operation_cache.set = constrained_set
        before = await units()
        try:
            first = await client.post('/api/v1/convert?format=json&target_format=bmd_bankauszug',
                headers={**headers, 'X-Idempotency-Key': 'boundary'}, files=files)
            body = first.json()
            operation = body.get('operation_id')
            download = await client.get(f'/api/v1/operations/{operation}/export?format=bmd_bankauszug', headers=headers) if operation else None
            results['cache_pair_admission'] = {**boundary, 'convert_http': first.status_code,
                'operation_issued': bool(operation), 'canonical_present': canonical_operation_cache.get(operation) is not None,
                'export_http': download.status_code if download else None, 'committed_delta': await units()-before}
        finally:
            canonical_operation_cache.set = original_set
            shared_ram_budget.max_bytes = original_budget
            canonical_operation_cache.clear()
            _idempotent_result_cache.clear()
        h = {**headers, 'X-Idempotency-Key': 'datev-replay'}
        a = await client.post('/api/v1/convert?format=datev', headers=h, files=files)
        await asyncio.sleep(1.1)
        b = await client.post('/api/v1/convert?format=datev', headers=h, files=files)
        results['datev_replay_bytes'] = {'statuses': [a.status_code, b.status_code], 'equal': a.content == b.content,
            'sha256': [hashlib.sha256(x.content).hexdigest() for x in (a,b)],
            'first_lines': [x.content.splitlines()[0].decode('cp1252') for x in (a,b)]}
    await engine.dispose()
    return results

if __name__ == '__main__':
    if '--chain-child' in sys.argv:
        chain_child()
    else:
        with tempfile.TemporaryDirectory(prefix='s2m-audit63-') as directory:
            db = Path(directory) / 'audit.db'
            os.environ['SQLITE_DB_PATH'] = str(db)
            os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + db.as_posix()
            results = asyncio.run(endpoint_probes())
            proc = subprocess.Popen([sys.executable, '-E', __file__, '--chain-child'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                stdout, stderr = proc.communicate(timeout=6)
                results['chain_12_segments'] = {'timed_out': False, 'exit': proc.returncode, 'stdout': stdout, 'stderr': stderr}
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                results['chain_12_segments'] = {'timed_out': True, 'timeout_seconds': 6, 'stdout': stdout, 'stderr': stderr,
                    'scope': 'Real reconciliation function in isolated child; not an HTTP load test; no production traffic'}
            results['scope'] = 'Independent local ASGI boundary probes; synthetic data; temporary SQLite'
            (Path(__file__).parent / 'probe_results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
            print(json.dumps(results, indent=2, ensure_ascii=True))
