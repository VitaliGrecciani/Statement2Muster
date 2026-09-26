"""Run the backend regression on fresh SQLite; rely on repository fixtures."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).with_name("pytest_fresh_database_results.txt")

with tempfile.TemporaryDirectory(prefix="s2m-gpt-followup-regression-") as directory:
    env = os.environ.copy()
    database = (Path(directory) / "audit.sqlite").as_posix()
    env["DATABASE_URL"] = "sqlite+aiosqlite:///" + database
    env["ENVIRONMENT"] = "test"
    code = (
        "import pytest; raise SystemExit(pytest.main(['-q']))"
    )
    result = subprocess.run(
        [sys.executable, "-E", "-c", code], cwd=ROOT / "backend",
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = result.stdout + result.stderr
    OUTPUT.write_text(output, encoding="utf-8")
    print(output[-12000:])
    print("EXIT_CODE:", result.returncode)
    raise SystemExit(result.returncode)
