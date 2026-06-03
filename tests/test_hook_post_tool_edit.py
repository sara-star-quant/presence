"""Branch tests for hook_post_tool_edit: the PostToolUse(Edit|Write|MultiEdit) hook."""
from __future__ import annotations

import json


def _edit_events(state, repo):
    """Return the edit events the hook recorded for `repo`."""
    out = []
    for p in (state / "events").rglob("pending.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ev = json.loads(line)
                if ev.get("kind") == "edit":
                    out.append(ev)
    return out


def test_edit_recorded_with_tool_and_path(hook_runner):
    run, state, repo = hook_runner
    run("hook_post_tool_edit", {
        "cwd": str(repo),
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x/y.py"},
    })
    events = _edit_events(state, repo)
    assert len(events) == 1
    assert events[0]["tool"] == "Edit"
    assert events[0]["path"] == "/x/y.py"


def test_edit_path_fallback_to_path_key(hook_runner):
    """tool_input may carry `path` instead of `file_path`."""
    run, state, repo = hook_runner
    run("hook_post_tool_edit", {
        "cwd": str(repo),
        "tool_name": "Write",
        "tool_input": {"path": "/a/b.txt"},
    })
    events = _edit_events(state, repo)
    assert len(events) == 1
    assert events[0]["path"] == "/a/b.txt"


def test_edit_skipped_when_events_disabled(hook_runner):
    run, state, repo = hook_runner
    run(
        "hook_post_tool_edit",
        {"cwd": str(repo), "tool_name": "Edit", "tool_input": {"file_path": "/x/y.py"}},
        settings={"preset": "solo-dev", "overrides": {"events.enabled": False}},
    )
    assert _edit_events(state, repo) == []
