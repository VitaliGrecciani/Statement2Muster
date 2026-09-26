"""Read-only review of Decision 55 follow-up evidence; no POST, keys or SSH."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ART = ROOT / "docs/gpt_action_acceptance"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def sha(data):
    return hashlib.sha256(data).hexdigest()


raw = (ART / "BUILDER_E2E_TRACE.json").read_bytes()
trace = json.loads(raw)
scenarios = trace["scenarios_executed"]
a = scenarios["2_authenticated_tenant_a"]
b = scenarios["3_authenticated_tenant_b_quota_isolation"]
ledger = [ast.literal_eval(row) for row in trace["sqlite_ledger_state"]]
result = {"scope": "Independent local evidence review and public schema GET only", "head": git("rev-parse", "HEAD").decode().strip(), "trace_sha256": sha(raw), "backend_and_runtime_config_unchanged": not git("diff", "b4e1d43", "HEAD", "--", "backend", "docker-compose.prod.yml"), "tenant_a": {"reported_request_id": a["request_id"], "reported_event": a["nginx_log"], "selected_ledger": ast.literal_eval(a["ledger_entry"]), "all_ledger_entries": [r for r in ledger if r[0] == a["tenant_id"]], "reported_summary": a["financial_summary"]}, "tenant_b": {"reported_request_id": b["request_id"], "http": b["http_status"], "reported_new_reservations": b["new_reservations_created"]}, "scenario_fields": {name: sorted(value) for name, value in scenarios.items()}, "replay_capture_present": any("response_sha256" in value or "response_body" in value or "download_id" in value or "request_payload" in value for value in scenarios.values()), "visual_artifact_hashes": {p: sha((ROOT / p).read_bytes()) for p in trace["visual_artifacts"]}}
result["earlier_replay_screenshots_unchanged"] = all(git("show", "b4e1d43:" + p) == (ROOT / p).read_bytes() for p in trace["visual_artifacts"] if not p.endswith("chatgpt_builder_tenant_b_quota_429.png"))
with urllib.request.urlopen("https://api.statement2muster.com/gpt-openapi.json", timeout=20) as response:
    data = response.read()
    result["public_schema"] = {"http": response.status, "sha256": sha(data), "matches_claimed": sha(data) == trace["schema_sha256"], "tls": "Default hostname and certificate verification enabled"}
assert result["backend_and_runtime_config_unchanged"] and result["public_schema"]["matches_claimed"]
assert len(result["tenant_a"]["all_ledger_entries"]) == 2
(OUT / "evidence_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=True, indent=2))
