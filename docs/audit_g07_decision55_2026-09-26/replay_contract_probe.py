"""Local synthetic ASGI replay contract check; isolated DB and ephemeral keys."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
temp = tempfile.TemporaryDirectory(prefix="s2m-g07-r55-local-")
os.chdir(temp.name)  # Do not load the workspace .env.
os.environ.update(DATABASE_URL="sqlite+aiosqlite:///" + (Path(temp.name) / "probe.db").as_posix(), ENVIRONMENT="development", EMAIL_BACKEND="memory", JWT_PRIVATE_KEY_PEM="", JWT_PUBLIC_KEY_PEM="", JWT_ACCESS_TOKEN_EXPIRE_MINUTES="10")
os.environ.pop("SQLITE_DB_PATH", None)

from httpx import ASGITransport, AsyncClient
from app.main import app
from app.db.session import engine, init_db
from app.api.endpoints import gpt_action as gpt


async def main():
    await init_db()
    gpt.gpt_download_cache.clear()
    gpt.gpt_free_tier_tracker.clear()
    original = gpt.export_to_datev_csv
    calls = 0

    def counted_export(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    gpt.export_to_datev_csv = counted_export
    results = {"scope": "Local synthetic ASGI, temporary SQLite, no production keys or network", "instrumentation": "Counter wrapper calls the real DATEV exporter", "cases": {}}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://audit.invalid") as client:
            for has_request_id in (False, True):
                body = json.loads((ROOT / "docs/gpt_action_acceptance/synthetic_source_input.json").read_text(encoding="utf-8"))
                body["session_id"] = "local-explicit-id" if has_request_id else "local-no-operation-id"
                if has_request_id:
                    body["request_id"] = "local-stable-operation"
                else:
                    body.pop("request_id", None)
                start = calls
                a = await client.post("/v1/gpt/convert", json=body)
                b = await client.post("/v1/gpt/convert", json=body)
                assert a.status_code == b.status_code == 200
                result = {"codes": [a.status_code, b.status_code], "exporter_calls": calls - start, "byte_identical": a.content == b.content, "same_download_id": a.json()["download_id"] == b.json()["download_id"], "demo_used": [a.json()["free_tier_status"]["conversions_used"], b.json()["free_tier_status"]["conversions_used"]]}
                if has_request_id:
                    assert result["byte_identical"] and result["same_download_id"] and result["exporter_calls"] == 1 and result["demo_used"] == [1, 1]
                else:
                    assert not result["byte_identical"] and not result["same_download_id"] and result["exporter_calls"] == 2 and result["demo_used"] == [1, 2]
                results["cases"]["with_request_id" if has_request_id else "without_request_id"] = result
    finally:
        gpt.export_to_datev_csv = original
        await engine.dispose()
    (OUT / "replay_contract_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        os.chdir(ROOT)
        temp.cleanup()
