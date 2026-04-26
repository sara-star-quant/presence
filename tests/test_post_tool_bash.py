"""Regression: PostToolUse(Bash) must log a warning (not silently drop) when exit_code is missing/unparseable."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "scripts" / "post-tool-bash.sh"


@pytest.fixture
def hook_env(tmp_path, fake_repo, monkeypatch):
    """Run the hook with PRESENCE_STATE and CLAUDE_PLUGIN_ROOT pointing where we want."""
    state = tmp_path / "presence-state"
    state.mkdir()
    env = {
        **os.environ,
        "PRESENCE_STATE": str(state),
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""),
    }
    return env, state, fake_repo


def _run_hook(payload: dict, env: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )


def test_b1_missing_exit_code_warns_and_does_not_record(hook_env):
    """B1 regression: when tool_response has no exit_code, we must NOT record the
    commit claim AND must log a warning so /presence-doctor can surface it.
    Previously, `if exit_code != 0: return` short-circuited on None, dropping the
    claim silently."""
    env, state, fake_repo = hook_env
    payload = {
        "cwd": str(fake_repo),
        "tool_input": {"command": "git commit -m 'fake commit'"},
        "tool_response": {},  # no exit_code
    }
    result = _run_hook(payload, env)
    assert result.returncode == 0, f"hook crashed: {result.stderr}"

    # No claim should have been recorded
    claims_file = state / "telemetry" / "claims.jsonl"
    assert not claims_file.exists() or claims_file.stat().st_size == 0, \
        "telemetry/claims.jsonl should be empty: missing exit_code is not a confirmed success"

    # Warning should have been logged
    warnings_file = state / "logs" / "warnings.log"
    assert warnings_file.exists(), "warnings.log should have been created"
    contents = warnings_file.read_text()
    assert "bash_exit_unknown" in contents, \
        f"expected 'bash_exit_unknown' warning, got: {contents}"


def test_b1_zero_exit_code_records_claim(hook_env):
    """Sanity: with a normal exit_code=0, the commit claim IS recorded."""
    env, state, fake_repo = hook_env
    # Make a real commit so get_head_commit has something to find
    subprocess.run(["git", "commit", "--allow-empty", "-m", "smoke"],
                   cwd=fake_repo, check=True, capture_output=True)
    payload = {
        "cwd": str(fake_repo),
        "tool_input": {"command": "git commit -m smoke"},
        "tool_response": {"exit_code": 0, "stdout": "[main abc1234] smoke\n"},
    }
    result = _run_hook(payload, env)
    assert result.returncode == 0, f"hook crashed: {result.stderr}"

    claims_file = state / "telemetry" / "claims.jsonl"
    assert claims_file.exists(), "telemetry/claims.jsonl should exist after a successful commit"
    lines = [json.loads(line) for line in claims_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["kind"] == "commit"
