"""Branch tests for hook_pre_tool_bash: the commit/push confidence gate."""
from __future__ import annotations


def _seed(repo, *, edit_age=None, pass_age=None):
    """Seed edit / test_pass events at controlled ages (seconds ago), within the
    scan_recent window so the gate sees them."""
    import events
    from _common import now_ts
    t = now_ts()
    if edit_age is not None:
        events.append_event({"kind": "edit", "ts": t - edit_age}, cwd=str(repo))
    if pass_age is not None:
        events.append_event({"kind": "test_pass", "ts": t - pass_age}, cwd=str(repo))


def _settings(gate):
    return {"preset": "solo-dev", "overrides": {"confidence.commit_gate": gate}}


def test_gate_off_is_silent(hook_runner, capsys):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)  # unverified edit present, but gate is off
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": "git commit -m x"}},
        settings=_settings("off"))
    assert capsys.readouterr().out.strip() == ""


def test_non_commit_command_is_ignored(hook_runner, capsys):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": "ls -la"}},
        settings=_settings("block"))
    assert capsys.readouterr().out.strip() == ""


def test_warn_emits_context_without_blocking(hook_runner, capsys):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)  # edit, no later pass -> unverified
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": "git commit -m x"}},
        settings=_settings("warn"))
    out = capsys.readouterr().out
    assert "without verification" in out
    assert "additionalContext" in out
    assert "permissionDecision" not in out  # warn must never block


def test_ask_sets_permission_ask(hook_runner, capsys):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": "git push"}},
        settings=_settings("ask"))
    out = capsys.readouterr().out
    assert '"permissionDecision":"ask"' in out


def test_block_denies(hook_runner, capsys):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": "git commit -m x"}},
        settings=_settings("block"))
    out = capsys.readouterr().out
    assert '"permissionDecision":"deny"' in out


def test_evidence_after_edit_passes_gate(hook_runner, capsys):
    """A passing test logged AFTER the most recent edit -> no intervention."""
    run, state, repo = hook_runner
    _seed(repo, edit_age=10, pass_age=5)  # pass is newer than edit
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": "git commit -m x"}},
        settings=_settings("block"))
    assert capsys.readouterr().out.strip() == ""
