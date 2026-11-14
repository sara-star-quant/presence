"""presence loaded into a real Claude Code session, checked from the outside.

Opt in with PRESENCE_LIVE_HOST=1. It needs a logged-in `claude` and spends a few cents per
test (cheapest model, scratch repo, hooks from this checkout, nothing else loaded). CI cannot
run it, so run it before a release and whenever Claude Code updates:

    PRESENCE_LIVE_HOST=1 .venv/bin/python -m pytest tests/live -q

The captured-payload tests cover what the host sends in. These cover what it does with what
presence prints back: injected context, a PreToolUse deny, a Stop block.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("PRESENCE_LIVE_HOST") or shutil.which("claude") is None,
    reason="set PRESENCE_LIVE_HOST=1 with a logged-in claude on PATH",
)


@pytest.fixture
def live(tmp_path):
    state, repo = tmp_path / "state", tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    for cmd in (["init", "-q"], ["remote", "add", "origin", "https://example.invalid/presence-live.git"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    env = {**os.environ, "PRESENCE_STATE": str(state), "PRESENCE_NO_DAEMON": "1",
           "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]}

    def run(prompt: str, preset: str = "solo-dev", max_turns: int = 8) -> dict:
        (state / "settings.json").write_text(json.dumps({"preset": preset}))
        r = subprocess.run(
            ["claude", "-p", prompt, "--plugin-dir", str(ROOT), "--setting-sources", "project", "--model", "haiku",
             "--permission-mode", "acceptEdits", "--allowedTools", "Write", "Bash", "Edit",
             "--max-turns", str(max_turns), "--no-session-persistence", "--output-format", "json"],
            cwd=repo, env=env, capture_output=True, text=True, timeout=300, check=False,
        )
        assert r.returncode == 0, r.stderr[-500:]
        return json.loads(r.stdout)

    def commits() -> int:
        return int(subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo, check=True,
                                  capture_output=True, text=True).stdout)

    def jsonl(rel: str) -> str:
        files = sorted(state.glob(rel))
        return "\n".join(f.read_text() for f in files)

    def seed(observation: str) -> None:
        code = f"from model import append_observation as o; o({observation!r}, cwd={str(repo)!r})"
        subprocess.run([sys.executable, "-c", code], env={**env, "PYTHONPATH": str(ROOT / "lib")},
                       cwd=repo, check=True, capture_output=True)

    run.state, run.repo, run.commits, run.jsonl, run.seed = state, repo, commits, jsonl, seed
    return run


def test_hooks_load_and_record_a_commit_and_a_passing_test(live):
    out = live("Use the Bash tool to run these one at a time: git commit --allow-empty -m probe, then "
               "python -m pytest --version. Reply with the single word done.")
    assert live.commits() == 2, out["result"]
    assert "commit" in live.jsonl("telemetry/claims.jsonl")
    assert "test_pass" in live.jsonl("events/*/*.jsonl")


def test_session_context_reaches_the_model(live):
    live.seed("The parser lives in lib/zebra_parse.py and prefers small pure functions.")
    out = live("Do not use any tools. According to the project notes in your context, which file holds the "
               "parser? Reply with only the file name, or UNKNOWN if your context does not say.")
    assert "zebra_parse" in out["result"], out["result"]


def test_commit_gate_deny_stops_an_unverified_commit(live):
    out = live("Use the Write tool to create a.txt containing hi. Then use the Bash tool to run: "
               "git add a.txt && git commit -m add-a. If a tool call is refused, do not retry; reply REFUSED.",
               preset="enterprise-strict")
    assert live.commits() == 1, f"the gate did not stop the commit: {out['result']}"


def test_stop_gate_block_forces_another_turn(live):
    out = live("Use the Write tool to create a.txt containing hi. Then reply with exactly: Fixed, it works.",
               preset="enterprise-strict")
    assert "unhedged_success" in live.jsonl("telemetry/confidence.jsonl")
    assert out["num_turns"] >= 3, f"Stop block did not re-prompt (turns={out['num_turns']}): {out['result']}"
    assert out["subtype"] == "success", "the Stop gate must not loop the session into the turn limit"


def test_commit_gate_allows_a_commit_after_a_passing_test(live):
    out = live("Use the Write tool to create a.txt containing hi. Then use the Bash tool to run "
               "python -m pytest --version. Then use the Bash tool to run: git add a.txt && git commit -m add-a. "
               "Run exactly these commands and no others, then reply with the single word done.",
               preset="enterprise-strict")
    assert live.commits() == 2, f"verified work was blocked: {out['result']}\n{live.jsonl('events/*/*.jsonl')}"
