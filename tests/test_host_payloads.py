"""presence's real hooks against payloads captured from the real Claude Code.

tests/fixtures/host/<version>/ holds what the host actually sent (see
tests/fixtures/capture_host_payloads.py). Every other hook test builds its own
payloads, so it can only agree with our idea of the contract. These cannot: they
caught that a successful Bash command carries no exit code and that failures arrive
as a separate PostToolUseFailure event.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / "tests" / "fixtures" / "host"
VERSIONS = sorted(p.name for p in HOST.iterdir() if p.is_dir())
SCRIPTS = {
    "session_start": "session-start.sh",
    "user_prompt_submit": "user-prompt-submit.sh",
    "pre_tool_bash": "pre-tool-bash.sh",
    "post_tool_bash": "post-tool-bash.sh",
    "post_tool_bash_failure": "post-tool-bash.sh",
    "post_tool_edit": "post-tool-edit.sh",
    "stop": "stop.sh",
}


def _payloads(version: str):
    return sorted((HOST / version).glob("*.json"))


def _kind(path: Path) -> str:
    return path.name.split(".")[0]


@pytest.fixture
def run(tmp_path):
    """Run a captured payload through its real hook script; return (result, state dir)."""
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    for cmd in (["init", "-q"], ["remote", "add", "origin", "https://example.invalid/presence-fixture.git"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    env = {**os.environ, "PRESENCE_STATE": str(state), "CLAUDE_PLUGIN_ROOT": str(ROOT),
           "PRESENCE_NO_DAEMON": "1", "PYTHONPATH": str(ROOT / "lib"),
           "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]}

    def _run(path: Path):
        payload = json.loads(path.read_text())
        payload["cwd"] = str(repo)
        r = subprocess.run(["bash", str(ROOT / "hooks" / "scripts" / SCRIPTS[_kind(path)])],
                           input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30, check=False)
        return r, state

    return _run


def _events(state: Path) -> list[dict]:
    out = []
    for f in sorted(state.glob("events/*/*.jsonl")):
        out += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out


def _warnings(state: Path) -> str:
    f = state / "logs" / "warnings.log"
    return f.read_text() if f.exists() else ""


def _one(version: str, name: str) -> Path:
    return HOST / version / name


def test_fixtures_exist():
    assert VERSIONS, "no host payloads captured; run tests/fixtures/capture_host_payloads.py"


@pytest.mark.parametrize("version", VERSIONS)
def test_payloads_carry_the_fields_presence_reads(version):
    for path in _payloads(version):
        d = json.loads(path.read_text())
        kind = _kind(path)
        assert d.get("hook_event_name") and d.get("session_id") and d.get("cwd"), path.name
        if kind in ("pre_tool_bash", "post_tool_bash", "post_tool_bash_failure"):
            assert isinstance(d["tool_input"]["command"], str), path.name
        if kind == "post_tool_bash":
            assert isinstance(d["tool_response"].get("stdout"), str), path.name
        if kind == "post_tool_bash_failure":
            assert isinstance(d["error"], str), path.name
        if kind == "post_tool_edit":
            assert d["tool_input"].get("file_path"), path.name
        if kind == "stop":
            assert d.get("transcript_path"), path.name
        if kind == "user_prompt_submit":
            assert isinstance(d.get("prompt"), str), path.name


@pytest.mark.parametrize("version", VERSIONS)
def test_every_hook_exits_clean_on_real_payloads(version, run):
    for path in _payloads(version):
        r, _ = run(path)
        assert r.returncode == 0, f"{path.name}: {r.stderr[:300]}"
        if r.stdout.strip():
            json.loads(r.stdout)  # whatever a hook prints must be valid JSON


@pytest.mark.parametrize("version", VERSIONS)
def test_a_successful_commit_is_recorded_as_a_claim(version, run):
    r, state = run(_one(version, "post_tool_bash.git-commit-allow-empty-m-probe.json"))
    assert r.returncode == 0, r.stderr
    claims = state / "telemetry" / "claims.jsonl"
    assert claims.exists() and "commit" in claims.read_text()
    assert "bash_exit_unknown" not in _warnings(state)


@pytest.mark.parametrize("version", VERSIONS)
def test_a_passing_test_run_counts_as_verification(version, run):
    r, state = run(_one(version, "post_tool_bash.python-m-pytest-version.json"))
    assert r.returncode == 0, r.stderr
    kinds = [e["kind"] for e in _events(state)]
    assert "test_pass" in kinds, kinds


@pytest.mark.parametrize("version", VERSIONS)
def test_a_failed_test_run_is_recorded_as_a_failure_not_a_pass(version, run):
    r, state = run(_one(version, "post_tool_bash_failure.python-m-pytest-no-such-test-py-.json"))
    assert r.returncode == 0, r.stderr
    events = _events(state)
    kinds = [e["kind"] for e in events]
    assert "test_fail" in kinds and "test_pass" not in kinds, kinds
    assert any(e["kind"] == "bash" and e["exit"] == 4 for e in events), events


@pytest.mark.parametrize("version", VERSIONS)
def test_a_failed_push_is_not_recorded_as_a_claim(version, run):
    r, state = run(_one(version, "post_tool_bash_failure.git-push-origin-main.json"))
    assert r.returncode == 0, r.stderr
    claims = state / "telemetry" / "claims.jsonl"
    assert not claims.exists() or "push" not in claims.read_text()
