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


# --- a commit that only runs after a test passed in the same command -------------------------------

import pytest  # noqa: E402


def _gate(hook_runner, capsys, cmd, gate="block"):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)  # an edit and no recorded pass: the plain commit is unverified
    run("hook_pre_tool_bash", {"cwd": str(repo), "tool_input": {"command": cmd}}, settings=_settings(gate))
    return capsys.readouterr().out


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest && git commit -m x",
        "pytest -q && git commit -am x",
        "cd repo && pytest -q && git commit -am x",
        "make build && git commit -m x",
        "pytest && git push",
        "pytest && git commit -m x && git push",
        "uv run pytest && git commit -m x",
        "x=1; pytest && git commit -m x",
        "pytest && git add -A && git commit -m x",
        "pytest && cd repo && git commit -m x",
        "pytest && git status && git commit -m x",
        "pytest && pytest -q && git commit -m x",
    ],
)
def test_a_commit_chained_after_a_passing_test_is_not_gated(hook_runner, capsys, cmd):
    """With && the commit only runs when the test exited 0, so asking for evidence first is a false alarm."""
    assert _gate(hook_runner, capsys, cmd) == ""


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest; git commit -m x",  # a semicolon commits whatever the test said
        "pytest || git commit -m x",
        "git commit -m x && pytest",  # the commit comes first
        "pytest | tee out && git commit -m x",  # a pipe hides the test's status
        "echo pytest && git commit -m x",  # not in command position
        "pytest --collect-only && git commit -m x",  # nothing ran
        "false || pytest && git commit -m x",  # the test may be skipped
        "pytest & git commit -m x",
        "git commit -m x && git push",
        "pytest && sed -i s/a/b/ f.py && git commit -m x",  # an edit between the test and the commit
        "pytest && ./fix.sh && git commit -m x",
        "pytest && make fmt && git commit -m x",
        "pytest && git stash pop && git commit -m x",
    ],
)
def test_a_commit_the_test_does_not_guard_is_still_gated(hook_runner, capsys, cmd):
    assert "permissionDecision" in _gate(hook_runner, capsys, cmd)


def test_the_warn_mode_is_quiet_for_a_guarded_commit(hook_runner, capsys):
    assert _gate(hook_runner, capsys, "pytest && git commit -m x", gate="warn") == ""


@pytest.mark.parametrize("cmd", ["echo a && " * 3000 + "git commit -m x", "git commit -m x && " * 1500 + "pytest", "pytest && " + "git add . && " * 2000 + "git commit -m x"])
def test_a_long_chain_is_judged_quickly(hook_runner, capsys, cmd):
    import time
    start = time.monotonic()
    _gate(hook_runner, capsys, cmd)
    assert time.monotonic() - start < 3.0
