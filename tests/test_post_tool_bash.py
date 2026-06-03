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


def test_redact_profiles_threaded_to_bash_event(hook_env):
    """settings.redact.profiles must reach redact_command in the bash hook event log."""
    env, state, fake_repo = hook_env
    # Plant settings opting into pii-eu
    (state / "settings.json").write_text(
        json.dumps({"preset": "solo-dev", "overrides": {"redact": {"profiles": ["pii-eu"]}}}),
        encoding="utf-8",
    )
    payload = {
        "cwd": str(fake_repo),
        "tool_input": {"command": "echo IBAN GB82WEST12345698765432"},
        "tool_response": {"exit_code": 0, "stdout": ""},
    }
    result = _run_hook(payload, env)
    assert result.returncode == 0, f"hook crashed: {result.stderr}"

    # Find the events file and check the bash event payload was redacted.
    events_root = state / "events"
    bash_lines: list[str] = []
    for p in events_root.rglob("pending.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("kind") == "bash":
                bash_lines.append(ev.get("cmd") or "")
    assert bash_lines, f"expected a bash event under {events_root}; found: {list(events_root.rglob('*'))}"
    joined = " ".join(bash_lines)
    assert "GB82WEST12345698765432" not in joined
    assert "[REDACTED:iban]" in joined


# --- in-process branch coverage (hook_runner) --------------------------------

def _claims(state):
    f = state / "telemetry" / "claims.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def _events_of_kind(state, kind):
    out = []
    for p in (state / "events").rglob("pending.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("kind") == kind:
                out.append(json.loads(line))
    return out


def test_git_push_records_push_claim(hook_runner):
    run, state, repo = hook_runner
    run("hook_post_tool_bash", {
        "cwd": str(repo),
        "tool_input": {"command": "git push origin main"},
        "tool_response": {"exit_code": 0},
    })
    claims = _claims(state)
    assert len(claims) == 1 and claims[0]["kind"] == "push"


def test_gh_pr_create_records_push_claim(hook_runner):
    run, state, repo = hook_runner
    run("hook_post_tool_bash", {
        "cwd": str(repo),
        "tool_input": {"command": "gh pr create --fill"},
        "tool_response": {"exit_code": 0},
    })
    claims = _claims(state)
    assert len(claims) == 1 and claims[0]["kind"] == "push"


def test_passing_test_command_classified(hook_runner):
    run, state, repo = hook_runner
    run("hook_post_tool_bash", {
        "cwd": str(repo),
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"exit_code": 0},
    })
    assert _events_of_kind(state, "test_pass")
    assert _claims(state) == []  # a test run is not a commit/push claim


def test_nonzero_exit_records_nothing(hook_runner):
    run, state, repo = hook_runner
    run("hook_post_tool_bash", {
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m x"},
        "tool_response": {"exit_code": 1},
    })
    assert _claims(state) == []


def test_resolve_commit_cwd():
    import os

    from hook_post_tool_bash import _resolve_commit_cwd
    assert _resolve_commit_cwd("/repo", "git -C /abs/dir commit -m x") == "/abs/dir"
    assert _resolve_commit_cwd("/repo", "git -C sub commit -m x") == os.path.join("/repo", "sub")
    assert _resolve_commit_cwd("/repo", "cd sub && git commit -m x") == os.path.join("/repo", "sub")
    assert _resolve_commit_cwd("/repo", "git commit -m x") == "/repo"
