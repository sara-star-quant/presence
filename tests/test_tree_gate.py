"""The gate decides by the working copy's tree, so edits no hook reported still count."""
from __future__ import annotations

import json

SID = "sess-1"
SETTINGS = {"preset": "solo-dev", "overrides": {"confidence.commit_gate": "block"}}


def _rows(state):
    f = state / "telemetry" / "confidence.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines()] if f.exists() else []


def _begin(run, repo):
    run("hook_user_prompt_submit", {"cwd": str(repo), "session_id": SID}, settings=SETTINGS)


def _claim(run, repo):
    run("hook_stop", {"cwd": str(repo), "session_id": SID, "last_assistant_message": "Done, it works now."}, settings=SETTINGS)


def _pass(run, repo):
    run("hook_post_tool_bash", {"cwd": str(repo), "session_id": SID, "tool_input": {"command": "pytest -q"},
                               "tool_response": {"exit_code": 0}}, settings=SETTINGS)


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)  # no tool hook fires: a shell, an MCP tool or a checkout would look the same


def test_an_edit_no_hook_saw_still_trips_the_gate_until_tests_pass_on_that_tree(hook_runner):
    run, state, repo = hook_runner
    _begin(run, repo)
    _write(repo, "lib/a.py", "x = 1\n")
    _claim(run, repo)
    assert [(r["verified"], r["basis"]) for r in _rows(state)] == [(False, "tree")]
    _pass(run, repo)
    _claim(run, repo)
    assert [r["verified"] for r in _rows(state)] == [False, True]
    _write(repo, "lib/a.py", "x = 2\n")  # changed again after the pass
    _claim(run, repo)
    assert [r["verified"] for r in _rows(state)] == [False, True, False]


def test_a_docs_only_change_made_outside_the_edit_tools_is_not_asked_to_verify(hook_runner):
    run, state, repo = hook_runner
    _begin(run, repo)
    _write(repo, "README.md", "hello\n")
    _claim(run, repo)
    assert _rows(state) == []


def test_changes_the_owner_had_before_the_session_are_not_the_agents(hook_runner):
    run, state, repo = hook_runner
    _write(repo, "lib/a.py", "x = 1\n")  # uncommitted work already there when the session starts
    _begin(run, repo)
    _claim(run, repo)
    assert _rows(state) == []


def test_the_commit_gate_blocks_an_unverified_tree_and_allows_a_tested_one(hook_runner, capsys):
    run, state, repo = hook_runner
    _begin(run, repo)
    _write(repo, "lib/a.py", "x = 1\n")
    payload = {"cwd": str(repo), "session_id": SID, "tool_input": {"command": "git commit -am x"}}
    run("hook_pre_tool_bash", payload, settings=SETTINGS)
    assert "deny" in capsys.readouterr().out
    _pass(run, repo)
    run("hook_pre_tool_bash", payload, settings=SETTINGS)
    assert capsys.readouterr().out.strip() == ""


def test_without_a_session_id_the_gate_falls_back_to_watching_edit_events(hook_runner):
    run, state, repo = hook_runner
    run("hook_post_tool_edit", {"cwd": str(repo), "tool_name": "Edit", "tool_input": {"file_path": str(repo / "lib" / "a.py")}},
        settings=SETTINGS)
    run("hook_stop", {"cwd": str(repo), "last_assistant_message": "Done, it works now."}, settings=SETTINGS)
    assert [(r["verified"], r["basis"]) for r in _rows(state)] == [(False, "events")]
