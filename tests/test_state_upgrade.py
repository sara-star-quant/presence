"""State written by earlier releases still opens under the current code.

tests/fixtures/state/<tag>/ holds a state directory produced by that release's
real hooks (see tests/fixtures/make_state_fixture.py). Each one is copied to a
scratch location, then the current SessionStart hook and doctor run against it.
Fixtures are never regenerated from newer code; add a new tag when a release
ships, do not edit old ones.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "state"
TAGS = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())
JSONL = ("telemetry/claims.jsonl", "telemetry/outcomes.jsonl", "telemetry/confidence.jsonl")


@pytest.fixture
def upgraded(tmp_path, request):
    """Copy a fixture, point a repo with the fixture's origin at it, return a runner."""
    src = FIXTURES / request.param
    state = tmp_path / "state"
    shutil.copytree(src, state)
    origin = (state / "ORIGIN").read_text().strip()
    (state / "ORIGIN").unlink()
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["remote", "add", "origin", origin],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    env = {**os.environ, "PRESENCE_STATE": str(state), "CLAUDE_PLUGIN_ROOT": str(ROOT),
           "PRESENCE_NO_DAEMON": "1", "PYTHONPATH": str(ROOT / "lib"),
           "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]}
    before = {rel: (state / rel).read_bytes() for rel in JSONL}
    return state, repo, env, before


def _session_start(repo, env):
    return subprocess.run(["bash", str(ROOT / "hooks" / "scripts" / "session-start.sh")],
                          input=json.dumps({"cwd": str(repo), "session_id": "up"}),
                          capture_output=True, text=True, env=env, timeout=30, check=False)


@pytest.mark.parametrize("upgraded", TAGS, indirect=True)
def test_session_start_loads_old_model_and_stays_quiet(upgraded):
    state, repo, env, _ = upgraded
    r = _session_start(repo, env)
    assert r.returncode == 0, r.stderr
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Parser lives in lib/parse.py" in ctx
    assert "audit" not in ctx.lower()  # fail-closed gate stayed open


@pytest.mark.parametrize("upgraded", TAGS, indirect=True)
def test_doctor_reports_old_state_healthy(upgraded):
    state, repo, env, _ = upgraded
    r = subprocess.run([sys.executable, str(ROOT / "lib" / "doctor.py"), "--json", "--cwd", str(repo)],
                       capture_output=True, text=True, env=env, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["integrity"] == "OK"
    assert d["errors_since_last_session"] == 0 and d["warnings_since_last_session"] == 0
    assert d["model_size_bytes"] > 0
    assert d["claims_bytes"] > 0 and d["outcomes_bytes"] > 0 and d["confidence_bytes"] > 0


@pytest.mark.parametrize("upgraded", TAGS, indirect=True)
def test_audit_chain_verifies_without_a_head_anchor(upgraded):
    state, repo, env, _ = upgraded
    code = "import audit, json; print(json.dumps(audit.verify_chain()))"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    report = json.loads(r.stdout)
    assert report["ok"] and report["lines"] == 2


@pytest.mark.parametrize("upgraded", TAGS, indirect=True)
def test_upgrade_does_not_rewrite_old_records(upgraded):
    state, repo, env, before = upgraded
    assert _session_start(repo, env).returncode == 0
    for rel, data in before.items():
        assert (state / rel).read_bytes().startswith(data), f"{rel} was rewritten"
    assert not (state / "logs" / "errors.log").exists() or not (state / "logs" / "errors.log").read_text().strip()


def test_fixtures_cover_the_last_five_minors():
    assert {"v0.7.1", "v0.8.1", "v0.9.2", "v0.10.0", "v0.11.0"} <= set(TAGS)
