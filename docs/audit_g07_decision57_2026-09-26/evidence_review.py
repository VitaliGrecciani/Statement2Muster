"""Read-only review of seq1 artifacts and its synthetic public download."""
import ast
import csv
import datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ART = ROOT / "docs/gpt_action_acceptance"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def sha(data):
    return hashlib.sha256(data).hexdigest()


trace = json.loads((ART / "BUILDER_E2E_TRACE.json").read_text(encoding="utf-8-sig"))
seq = trace["sequence_execution"]
a = seq["1_tenant_a_convert_success"]
replay = seq["2_tenant_a_idempotent_replay"]
b = seq["3_tenant_b_quota_exhausted_isolation"]
raw = (ART / "downloaded_statement_seq1.csv").read_bytes()
rows = list(csv.reader(io.StringIO(raw.decode("windows-1252"), newline=""), delimiter=";"))
tx = a["request_payload"]["transactions"][0]
row = rows[2]
rem = raw.replace(b"\r\n", b"")
checks = {"amount": Decimal(row[0].replace(",", ".")) == abs(Decimal(str(tx["amount"]))), "sh": row[1] == "H", "currency": row[2] == tx["currency"], "account": row[6] == a["request_payload"]["default_bank_account"], "date": row[9] == datetime.datetime.strptime(tx["booking_date"], "%d.%m.%Y").strftime("%d%m"), "reference": row[10] == tx["reference"], "description": row[13] == tx["description"]}
result = {"scope": "Independent local artifact review and public GETs only; no JWT issuance, production changes or conversions", "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "head": git("rev-parse", "HEAD").decode().strip(), "backend_and_compose_unchanged_since_56": not git("diff", "9d2b774", "HEAD", "--", "backend", "docker-compose.prod.yml"), "csv": {"size": len(raw), "sha256": sha(raw), "matches_reported": sha(raw) == a["downloaded_csv_sha256"], "crlf_only": b"\r\n" in raw and b"\r" not in rem and b"\n" not in rem, "windows1252_roundtrip": raw.decode("windows-1252").encode("windows-1252") == raw, "posting_count": len(rows) - 2, "header_timestamp": rows[0][5], "field_checks": checks}, "reported_ledger_final": [ast.literal_eval(r) for r in trace["sqlite_ledger_state_final"]], "reported_download_id_equal": a["download_id"] == replay["download_id"], "scenario_fields": {name: sorted(value) for name, value in seq.items()}, "request_capture_present": {"initial": "request_payload" in a, "replay": "request_payload" in replay, "tenant_b": "request_payload" in b}, "successful_response_capture_present": {"initial": any(k in a for k in ("response_body", "response_json", "response_sha256")), "replay": any(k in replay for k in ("response_body", "response_json", "response_sha256"))}, "error_body": b["error_body"], "public_get": {}}
result["payloads_equal"] = a["request_payload"] == replay.get("request_payload") == b.get("request_payload")
result["request_ids_equal"] = all(s.get("request_payload", {}).get("request_id") == trace["stable_request_id"] for s in (a, replay, b))
result["response_equality"] = {"initial_sha256": a.get("response_sha256"), "replay_sha256": replay.get("response_sha256"), "sha256_equal": bool(a.get("response_sha256")) and a.get("response_sha256") == replay.get("response_sha256"), "scope": "Comparison of reported engineer measurements; successful wire bodies not independently recaptured"}
error_raw = json.dumps(b["error_body"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
result["error_body_check"] = {"compact_utf8_size": len(error_raw), "sha256": sha(error_raw), "hash_matches_reported": sha(error_raw) == b.get("response_sha256"), "reported_response_bytes": b.get("response_bytes"), "size_matches_reported": len(error_raw) == b.get("response_bytes")}
result["reported_token_fixture"] = a["auth_mode"]
for name, url in (("schema", trace["schema_imported_url"]), ("synthetic_download", a["download_url"])):
    assert url.startswith("https://api.statement2muster.com/")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            body = response.read()
            item = {"http": response.status, "sha256": sha(body), "size": len(body), "tls": "Default certificate and hostname verification enabled"}
            if name == "synthetic_download":
                item["matches_saved_csv"] = body == raw
                item["content_type"] = response.headers.get("Content-Type")
                item["zero_retention"] = response.headers.get("X-Zero-Retention")
            else:
                item["matches_reported_schema"] = sha(body) == trace["schema_sha256"]
            result["public_get"][name] = item
    except urllib.error.HTTPError as exc:
        result["public_get"][name] = {"http": exc.code, "detail": "Read-only GET returned an HTTP error; no conclusion about earlier availability"}
    except Exception as exc:
        result["public_get"][name] = {"error": type(exc).__name__, "detail": str(exc)}
assert result["csv"]["matches_reported"] and result["csv"]["crlf_only"] and all(checks.values())
assert result["reported_download_id_equal"] and result["backend_and_compose_unchanged_since_56"]
assert result["payloads_equal"] and result["request_ids_equal"] and result["response_equality"]["sha256_equal"]
assert result["error_body_check"]["hash_matches_reported"]
(OUT / "evidence_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=True, indent=2))
