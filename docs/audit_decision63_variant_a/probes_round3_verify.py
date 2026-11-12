"""Round-3 verification runner for Decision 63 probes without altering Codex's baseline probe_results.json."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AUDIT_DIR))
import probes  # noqa: E402


if __name__ == "__main__":
    if "--chain-child" in sys.argv:
        probes.chain_child()
    else:
        with tempfile.TemporaryDirectory(prefix="s2m-audit63-r3-") as directory:
            db = Path(directory) / "audit_r3.db"
            os.environ["SQLITE_DB_PATH"] = str(db)
            os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + db.as_posix()
            results = asyncio.run(probes.endpoint_probes())
            proc = subprocess.Popen(
                [sys.executable, "-E", str(AUDIT_DIR / "probes.py"), "--chain-child"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate(timeout=6)
            results["chain_12_segments"] = {
                "timed_out": False,
                "exit": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
            results["scope"] = "Round-3 verification of Decision 63 fixes using Codex's exact audit63/probes.py functions; synthetic data; temporary SQLite"
            out_file = AUDIT_DIR / "probe_results_round3.json"
            out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(results, indent=2, ensure_ascii=True))
