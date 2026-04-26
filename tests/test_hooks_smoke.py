"""Smoke tests for all hook bash wrappers.

Catches wiring regressions: PYTHONPATH not set, python3 not found, JSON output
malformed. Each hook is run via its bash wrapper with realistic stdin JSON for
its event type, and we assert the wrapper exits 0 and stdout (if any) parses as
valid JSON with the expected hookSpecificOutput shape.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_ROOT / "hooks" / "scripts"


@pytest.fixture
def hook_env(tmp_path, fake_repo):
    state = tmp_path / "presence-state"
    state.mkdir()
    env = {
        **os.environ,
        "PRESENCE_STATE": str(state),
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""),
    }
    return env, state, fake_repo


def _run(script_name: str, payload: dict, env: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPTS_DIR / script_name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )


# --- per-hook smoke tests ---------------------------------------------------

def test_session_start_runs(hook_env):
    env, _state, fake_repo = hook_env
    r = _run("session-start.sh", {"cwd": str(fake_repo), "session_id": "smoke"}, env)
    assert r.returncode == 0, f"crashed: {r.stderr}"
    if r.stdout.strip():
        obj = json.loads(r.stdout)
        assert obj["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_user_prompt_submit_runs(hook_env):
    env, _state, fake_repo = hook_env
    r = _run("user-prompt-submit.sh", {"cwd": str(fake_repo), "prompt": "hi"}, env)
    assert r.returncode == 0, f"crashed: {r.stderr}"
    if r.stdout.strip():
        obj = json.loads(r.stdout)
        assert obj["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_post_tool_edit_runs(hook_env):
    env, state, fake_repo = hook_env
    r = _run(
        "post-tool-edit.sh",
        {"cwd": str(fake_repo), "tool_name": "Edit", "tool_input": {"file_path": "x.py"}},
        env,
    )
    assert r.returncode == 0, f"crashed: {r.stderr}"
    # Edit hook is silent (just logs to events). Assert event was queued.
    events_dirs = list((state / "events").iterdir())
    assert events_dirs, "events directory should have one project subdir"
    pending = events_dirs[0] / "pending.jsonl"
    assert pending.exists()
    line = json.loads(pending.read_text().splitlines()[0])
    assert line["kind"] == "edit"
    assert line["path"] == "x.py"


def test_post_tool_bash_runs(hook_env):
    env, _state, fake_repo = hook_env
    r = _run(
        "post-tool-bash.sh",
        {
            "cwd": str(fake_repo),
            "tool_input": {"command": "ls"},
            "tool_response": {"exit_code": 0},
        },
        env,
    )
    assert r.returncode == 0, f"crashed: {r.stderr}"


def test_pre_tool_bash_runs(hook_env):
    env, _state, fake_repo = hook_env
    r = _run(
        "pre-tool-bash.sh",
        {
            "cwd": str(fake_repo),
            "tool_input": {"command": "ls"},
        },
        env,
    )
    assert r.returncode == 0, f"crashed: {r.stderr}"
    # In default preset, commit_gate=off -> no decision emitted on `ls`
    if r.stdout.strip():
        obj = json.loads(r.stdout)
        assert obj["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_stop_runs_with_no_transcript(hook_env):
    env, _state, fake_repo = hook_env
    # No transcript_path -> hook should silently exit 0
    r = _run("stop.sh", {"cwd": str(fake_repo)}, env)
    assert r.returncode == 0, f"crashed: {r.stderr}"
    assert not r.stdout.strip(), f"expected silent exit, got: {r.stdout}"


def test_python_version_check_cached_across_hook_fires(hook_env):
    """The wrapper's _common.sh writes a marker (.python_version_ok) on first
    fire so subsequent fires skip the per-invocation `python3 -c '...'` probe.
    This is the v0.3.0 cold-hook latency fix; if the marker stops being written
    we silently regress by ~20 ms on every hook.
    """
    env, state, fake_repo = hook_env
    marker = state / ".python_version_ok"
    assert not marker.exists(), "fresh state must not have marker yet"
    r = _run("user-prompt-submit.sh", {"cwd": str(fake_repo), "prompt": "x"}, env)
    assert r.returncode == 0
    assert marker.exists(), "first hook fire must write the python-version cache marker"
    contents = marker.read_text(encoding="utf-8").strip()
    assert ":" in contents, "marker format must be <python_bin>:<mtime>"
    bin_path, _mtime = contents.split(":", 1)
    assert bin_path.endswith("python3") or "python" in bin_path
    # Second fire should still work (marker reused, version probe skipped).
    r2 = _run("user-prompt-submit.sh", {"cwd": str(fake_repo), "prompt": "y"}, env)
    assert r2.returncode == 0
    # Marker contents unchanged after a cache hit.
    assert marker.read_text(encoding="utf-8").strip() == contents


def test_python_version_marker_invalidates_when_python_changes(hook_env):
    """If the cached marker references a different python binary or mtime, the
    wrapper re-runs the version probe and rewrites the marker. Simulates a
    python upgrade between hook fires.
    """
    env, state, fake_repo = hook_env
    marker = state / ".python_version_ok"
    # Pre-seed a stale marker pointing at a fake binary.
    marker.write_text("/nonexistent/python3:0\n", encoding="utf-8")
    r = _run("user-prompt-submit.sh", {"cwd": str(fake_repo), "prompt": "z"}, env)
    assert r.returncode == 0
    # Marker should have been rewritten with the real python binary.
    contents = marker.read_text(encoding="utf-8").strip()
    assert "/nonexistent/python3" not in contents
    assert ":" in contents


def test_python_missing_warning_format(tmp_path, fake_repo):
    """When python3 isn't on PATH, the SessionStart wrapper must emit a one-time
    advisory JSON object that Claude Code can parse. Other wrappers just exit 0.
    Verifies the JSON shape."""
    state = tmp_path / "presence-state"
    state.mkdir()
    # Restrict PATH to /usr/bin and /bin (where bash lives) but no python3.
    # macOS/Linux both have these; python3 is typically in /usr/local/bin or
    # /opt/homebrew/bin or a versioned hostedtoolcache path that we exclude.
    env = {
        "PATH": "/usr/bin:/bin",
        "PRESENCE_STATE": str(state),
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        "HOME": str(tmp_path),
    }
    # If the system happens to have python3 in /usr/bin (some macOS / most Linux),
    # this test would not exercise the missing-python branch. Skip in that case.
    import shutil
    if shutil.which("python3", path=env["PATH"]):
        pytest.skip("system has python3 on a minimal PATH; cannot exercise the missing-python wrapper branch here")
    r = _run("session-start.sh", {"cwd": str(fake_repo)}, env)
    assert r.returncode == 0
    # First call should emit the warning
    obj = json.loads(r.stdout)
    assert obj["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "python3" in obj["hookSpecificOutput"]["additionalContext"]
    # Marker file should now exist
    marker = state / ".python3_warning_shown"
    assert marker.exists()
    # Second call should be silent (one-shot warning)
    r2 = _run("session-start.sh", {"cwd": str(fake_repo)}, env)
    assert r2.returncode == 0
    assert not r2.stdout.strip(), f"expected silence on second call, got: {r2.stdout}"
