"""Independent G07 follow-up: local artifacts and public GETs only."""
import ast
import csv
import datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ART = ROOT / "docs/gpt_action_acceptance"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def read(name):
    return json.loads((ART / name).read_text(encoding="utf-8-sig"))


results = {"scope": "Independent Git/artifact/file review and public HTTPS GETs; no production modifications, token issuance, conversions or restart", "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "head": git("rev-parse", "HEAD").decode().strip()}
repo = read("repo_source_manifest.json")
container = read("container_source_manifest.json")
comparison = read("source_comparison.json")
results["source"] = {"normalization": "CRLF to LF", "manifest_equal": repo == container, "commits": {}}
for commit in (comparison["build_commit"], comparison["audit_head_commit"], results["head"]):
    paths = git("ls-tree", "-r", "--name-only", commit, "backend/app").decode().splitlines()
    blobs = {p.removeprefix("backend/app/"): sha(git("show", f"{commit}:{p}").replace(b"\r\n", b"\n")) for p in paths if p.endswith(".py")}
    results["source"]["commits"][commit] = {"files": len(blobs), "matches": sum(repo.get(p) == h for p, h in blobs.items()), "missing": sorted(set(blobs) - set(repo)), "extra": sorted(set(repo) - set(blobs)), "mismatches": [p for p, h in blobs.items() if p in repo and repo[p] != h]}
results["backend_unchanged_since_54"] = not git("diff", "8050769", "HEAD", "--", "backend")

inspect = read("docker_inspect_1015_sanitized.json")
if isinstance(inspect, list):
    inspect = inspect[0]
env = dict(s.split("=", 1) for s in inspect.get("Config", {}).get("Env", []) if "=" in s)
results["inspect"] = {"container_id": inspect.get("Id"), "image_id": inspect.get("Image"), "image_name": inspect.get("Config", {}).get("Image"), "jwt_expiry_minutes": env.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES"), "max_file_size_bytes": env.get("MAX_FILE_SIZE_BYTES"), "health_interval_ns": inspect.get("Config", {}).get("Healthcheck", {}).get("Interval"), "health": inspect.get("State", {}).get("Health", {}).get("Status")}
live = read("g07_live_acceptance_results.json")
results["container_binding"] = inspect["Id"] == comparison["container_id"] == live["container_id"] and inspect["Image"] == comparison["image_id"] == live["image_id"]
results["reported_jwt_test"] = live["tests"]["jwt_expiration_policy_r54_3"]
results["reported_eviction_test"] = live["tests"]["file_eviction_and_410_replay_r54_2"]

source = read("synthetic_source_input.json")
raw = (ART / "downloaded_statement_sample.csv").read_bytes()
text = raw.decode("windows-1252")
rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
audit = []
for entry, row in zip(source["transactions"], rows[2:]):
    amount = Decimal(str(entry["amount"]))
    date = datetime.date.fromisoformat(entry["booking_date"])
    checks = {"amount": Decimal(row[0].replace(",", ".")) == abs(amount), "sh": row[1] == ("S" if amount >= 0 else "H"), "currency": row[2] == entry["currency"], "bank_account": row[6] == source["default_bank_account"], "booking_date": row[9] == date.strftime("%d%m"), "reference": row[10] == entry["reference"], "description": row[13] == entry["description"]}
    audit.append({"checks": checks, "pass": all(checks.values())})
remainder = raw.replace(b"\r\n", b"")
results["csv"] = {"sha256": sha(raw), "matches_reported_sha256": sha(raw) == live["tests"]["csv_download_and_field_audit_r54_2"]["file_sha256"], "bytes": len(raw), "header": rows[0][:5], "crlf_only": b"\r\n" in raw and b"\r" not in remainder and b"\n" not in remainder, "windows1252_roundtrip": text.encode("windows-1252") == raw, "contains_non_ascii_windows1252": b"\xfc" in raw, "posting_count": len(rows) - 2, "input_count": len(source["transactions"]), "rows": audit, "net": str(sum(Decimal(str(e["amount"])) for e in source["transactions"]))}

ledger = [s.split("|") for s in live["tests"]["ledger_verification"]]
results["reported_ledger"] = {"rows": len(ledger), "all_committed": all(r[3] == "COMMITTED" for r in ledger), "tenant_units": {tenant: sum(int(r[2]) for r in ledger if r[0] == tenant) for tenant in sorted({r[0] for r in ledger})}}
runner = ROOT / "tests/acceptance/run_g07_live_acceptance.py"
tree = ast.parse(runner.read_text(encoding="utf-8-sig"))
results["runner"] = {"tracked": bool(git("ls-files", "--", runner.relative_to(ROOT).as_posix())), "sha256": sha(runner.read_bytes()), "assertions": sum(isinstance(n, ast.Assert) for n in ast.walk(tree)), "eviction_method": "docker restart in runner, not natural TTL expiry", "expired_token_method": "create_access_token(expires_delta=timedelta(seconds=-30)); no natural 600-second wait", "private_key_export_removed": "JWT_PRIVATE_KEY_PEM" not in runner.read_text(encoding="utf-8-sig")}

builder = read("BUILDER_E2E_TRACE.json")
results["builder"] = {"gpt_id": builder["gpt_id"], "auth_mode": builder["auth_mode"], "schema_sha256": builder["schema_sha256"], "successful_attempt_keys": sorted(builder["self_corrected_attempt_200"]), "replay_attempt_keys": sorted(builder["replay_attempt_200"]), "successful_request_saved": "request" in builder["self_corrected_attempt_200"], "successful_response_saved": "response" in builder["self_corrected_attempt_200"], "replay_request_saved": "request" in builder["replay_attempt_200"], "replay_response_saved": "response" in builder["replay_attempt_200"], "screenshot_hashes": {p: sha((ROOT / p).read_bytes()) for p in builder["screenshots"]}}

results["https"] = {}
for path in ("/healthz", "/openapi.json", "/gpt-openapi.json"):
    try:
        with urllib.request.urlopen("https://api.statement2muster.com" + path, timeout=20) as response:
            data = response.read()
            obj = json.loads(data)
            item = {"http": response.status, "tls": "Default certificate and hostname verification enabled", "body_sha256": sha(data)}
            if path == "/healthz":
                item["body"] = obj
            else:
                item["info"] = obj.get("info")
                item["operation_ids"] = {p: {m: spec.get("operationId") for m, spec in methods.items() if m in ("get", "post")} for p, methods in obj.get("paths", {}).items() if "/gpt/" in p}
                if path == "/gpt-openapi.json":
                    item["matches_builder_import_sha256"] = sha(data) == builder["schema_sha256"]
            results["https"][path] = item
    except Exception as exc:
        results["https"][path] = {"error": type(exc).__name__, "detail": str(exc)}

assert results["source"]["manifest_equal"] and results["container_binding"]
assert all(c["matches"] == 33 and not c["missing"] and not c["extra"] and not c["mismatches"] for c in results["source"]["commits"].values())
assert results["csv"]["crlf_only"] and results["csv"]["matches_reported_sha256"] and results["csv"]["windows1252_roundtrip"]
assert len(audit) == len(source["transactions"]) == len(rows) - 2 == 2 and all(r["pass"] for r in audit)
assert env["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] == "10" and env["MAX_FILE_SIZE_BYTES"] == "10485760"
assert results["runner"]["tracked"] and results["runner"]["private_key_export_removed"]
(OUT / "review_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=True, indent=2))
