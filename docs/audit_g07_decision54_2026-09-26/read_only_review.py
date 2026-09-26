"""Read-only G07 artifact/source/HTTPS checks. No credentials, POSTs or SSH."""
import ast
import datetime
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ART = ROOT / "docs/gpt_action_acceptance"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(name):
    return json.loads((ART / name).read_text(encoding="utf-8-sig"))


result = {"scope": "Independent read-only artifact, Git blob and public HTTPS review; no live conversions or Builder execution", "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "head": git("rev-parse", "HEAD").decode().strip()}
repo = load("repo_source_manifest.json")
container = load("container_source_manifest.json")
comparison = load("source_comparison.json")
result["source"] = {"hash_normalization": "CRLF to LF", "repo_count": len(repo), "container_count": len(container), "manifest_equal": repo == container, "commits": {}}
for commit in (comparison["build_commit"], comparison["audit_head_commit"], result["head"]):
    paths = git("ls-tree", "-r", "--name-only", commit, "backend/app").decode().splitlines()
    blobs = {p.removeprefix("backend/app/"): sha(git("show", f"{commit}:{p}").replace(b"\r\n", b"\n")) for p in paths if p.endswith(".py")}
    result["source"]["commits"][commit] = {"python_files": len(blobs), "matches": sum(repo.get(p) == h for p, h in blobs.items()), "missing": sorted(set(blobs) - set(repo)), "extra": sorted(set(repo) - set(blobs)), "mismatches": [p for p, h in blobs.items() if p in repo and repo[p] != h]}
result["backend_unchanged_since_decision53"] = git("diff", "8533cd3", "HEAD", "--", "backend").decode() == ""

inspect = load("docker_inspect_1015_sanitized.json")
if isinstance(inspect, list):
    inspect = inspect[0]
env = dict(v.split("=", 1) for v in inspect.get("Config", {}).get("Env", []) if "=" in v)
hc = inspect.get("HostConfig", {})
result["inspect"] = {"container_id": inspect.get("Id"), "image_id": inspect.get("Image"), "image_name": inspect.get("Config", {}).get("Image"), "state": inspect.get("State", {}).get("Status"), "health": inspect.get("State", {}).get("Health", {}).get("Status"), "jwt_expiry_minutes": env.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES"), "max_file_size_bytes": env.get("MAX_FILE_SIZE_BYTES"), "version": env.get("VERSION"), "user": inspect.get("Config", {}).get("User"), "memory": hc.get("Memory"), "nano_cpus": hc.get("NanoCpus"), "read_only_rootfs": hc.get("ReadonlyRootfs"), "health_interval_ns": inspect.get("Config", {}).get("Healthcheck", {}).get("Interval")}
result["inspect_matches_comparison"] = inspect.get("Id") == comparison["container_id"] and inspect.get("Image") == comparison["image_id"]

runner = ROOT / "scratch/verify_g07_live.py"
result["runner"] = {"exists": runner.exists(), "tracked": bool(git("ls-files", "--", "scratch/verify_g07_live.py").strip())}
if runner.exists():
    raw = runner.read_bytes()
    tree = ast.parse(raw.decode("utf-8-sig"))
    result["runner"]["sha256"] = sha(raw)
    result["runner"]["imports"] = sorted({n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})
    result["runner"]["functions"] = [{"name": n.name, "line": n.lineno} for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    result["runner"]["calls"] = [{"function": ast.unparse(n.func), "line": n.lineno} for n in ast.walk(tree) if isinstance(n, ast.Call) and any(x in ast.unparse(n.func).lower() for x in ("request", "get", "post", "ssh", "token", "subprocess", "assert"))]
    result["runner"]["assert_count"] = sum(isinstance(n, ast.Assert) for n in ast.walk(tree))

result["artifact_files"] = sorted(p.name for p in ART.iterdir() if p.is_file())
result["https"] = {}
for path in ("/healthz", "/openapi.json"):
    url = "https://api.statement2muster.com" + path
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Statement2Muster-read-only-audit/54"}), timeout=20) as response:
            body = response.read()
            data = json.loads(body)
            item = {"http": response.status, "url": response.url, "tls": "Default certificate and hostname verification enabled", "body_sha256": sha(body)}
            if path == "/healthz":
                item["body"] = data
            else:
                item["openapi_version"] = data.get("openapi")
                item["info"] = data.get("info")
                item["gpt_paths"] = [p for p in data.get("paths", {}) if "/gpt/" in p]
                (OUT / "public_openapi.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            result["https"][path] = item
    except Exception as exc:
        result["https"][path] = {"error": type(exc).__name__, "detail": str(exc)}

(OUT / "review_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=True, indent=2))
