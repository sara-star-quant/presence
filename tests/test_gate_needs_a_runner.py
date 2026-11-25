"""Where no runner the gate recognises exists, a claim cannot be verified, so the gate stays quiet and says why."""
from __future__ import annotations

import json
import subprocess

import pytest

BLOCK = {"preset": "solo-dev", "overrides": {"confidence.stop_action": "block", "confidence.commit_gate": "block"}}
WARN = {"preset": "solo-dev", "overrides": {"confidence.stop_action": "warn"}}


def _no_runner(repo):
    subprocess.run(["git", "rm", "-q", "pytest.ini"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "no tests here"], cwd=repo, check=True)


def _edit(repo):
    import events
    from _common import now_ts
    events.append_event({"kind": "edit", "ts": now_ts() - 10}, cwd=str(repo))


def _confidence(state):
    f = state / "telemetry" / "confidence.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []


def _stop(run, repo, settings):
    run("hook_stop", {"cwd": str(repo), "session_id": "s1", "last_assistant_message": "Done, it works now."}, settings=settings)


def test_where_a_runner_exists_an_unverified_claim_still_blocks(hook_runner, capsys):
    run, state, repo = hook_runner
    _edit(repo)
    _stop(run, repo, BLOCK)
    assert '"decision":"block"' in capsys.readouterr().out


def test_where_no_runner_exists_the_claim_is_left_alone_and_recorded_as_not_judged(hook_runner, capsys):
    run, state, repo = hook_runner
    _no_runner(repo)
    _edit(repo)
    _stop(run, repo, BLOCK)
    assert capsys.readouterr().out.strip() == ""
    rows = _confidence(state)
    assert len(rows) == 1 and rows[0]["verified"] is None and rows[0]["reason"] == "no_runner"


def test_where_no_runner_exists_warn_mode_leaves_no_notice(hook_runner, capsys):
    run, state, repo = hook_runner
    _no_runner(repo)
    _edit(repo)
    _stop(run, repo, WARN)
    assert list(state.rglob("notice.json")) == []


def test_a_runner_that_appears_later_makes_the_gate_work_again(hook_runner, capsys):
    run, state, repo = hook_runner
    _no_runner(repo)
    _edit(repo)
    _stop(run, repo, BLOCK)
    assert capsys.readouterr().out.strip() == ""
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8")
    _stop(run, repo, BLOCK)
    assert '"decision":"block"' in capsys.readouterr().out


def _commit(run, repo, settings):
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": "git commit -m x"}}, settings=settings)


def test_the_commit_gate_blocks_where_a_runner_exists(hook_runner, capsys):
    run, state, repo = hook_runner
    _edit(repo)
    _commit(run, repo, BLOCK)
    assert "permissionDecision" in capsys.readouterr().out


def test_the_commit_gate_does_not_block_every_commit_where_none_exists(hook_runner, capsys):
    run, state, repo = hook_runner
    _no_runner(repo)
    _edit(repo)
    _commit(run, repo, BLOCK)
    assert capsys.readouterr().out.strip() == ""


@pytest.mark.parametrize("preset", ["enterprise-strict", "zerotrust"])
def test_the_strict_presets_follow_the_same_rule(hook_runner, capsys, preset):
    run, state, repo = hook_runner
    _no_runner(repo)
    _edit(repo)
    _commit(run, repo, {"preset": preset})
    assert capsys.readouterr().out.strip() == ""
