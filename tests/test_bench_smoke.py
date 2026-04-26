"""Smoke tests for bench/ scripts.

Catches refactor breakage (e.g., a change to time_subprocess's return
signature must not silently leave a bench script unable to start). Each test
runs its bench at --runs=1 with a reduced fixture and asserts:
  - the script exits 0
  - the JSON blob at the end of stdout parses as valid JSON

These are slow-ish (each spawns a real bench session, which itself spawns
hooks), but cap out around 5-10 s for all four combined at n=1.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "bench"


@pytest.mark.parametrize("script,args", [
    ("cold_startup.py",            ["--runs", "1"]),
    ("session_start_populated.py", ["--runs", "1"]),
    ("install_to_working.py",      ["--runs", "1"]),
    ("aggregate_session.py",       ["--runs", "1"]),
])
def test_bench_runs_at_n_eq_1(script, args, tmp_path):
    env = {
        **os.environ,
        "PRESENCE_STATE": str(tmp_path / "presence"),
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    r = subprocess.run(
        [sys.executable, str(BENCH_DIR / script), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert r.returncode == 0, (
        f"{script} crashed:\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    # Each bench prints a one-line human summary, then a JSON blob (json.dumps
    # with indent=2). Strip the human line and parse the rest.
    lines = r.stdout.splitlines()
    blob_start = next((i for i, ln in enumerate(lines) if ln.startswith("{")), -1)
    assert blob_start != -1, f"{script} did not emit a JSON report:\n{r.stdout}"
    parsed = json.loads("\n".join(lines[blob_start:]))
    assert isinstance(parsed, dict)
    # Sanity: every report has either a 'bench' key (cold/SS/agg) or
    # 'install'+'status' keys (install_to_working).
    assert "bench" in parsed or ("install" in parsed and "status" in parsed)
