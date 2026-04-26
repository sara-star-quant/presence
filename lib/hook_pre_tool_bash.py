"""PreToolUse(Bash) hook: confidence gate on git commit / git push.

Modes (from preset.confidence.commit_gate):
- "off"   : never intervene
- "warn"  : emit additionalContext warning, do not block (does not interrupt the user)
- "ask"   : ask user via permissionDecision=ask (interrupts every time; reserve for strict)
- "block" : deny via permissionDecision=deny
"""
from __future__ import annotations

import os

from _common import emit, emit_context, hook_input, now_ts, safe_main, settings
from cmdparse import is_git_commit, is_git_push
from events import peek_events


def _last_edit_ts(cwd) -> int:
    """Most recent edit timestamp from the event queue; 0 if none."""
    last = 0
    for ev in peek_events(cwd):
        if ev.get("kind") == "edit":
            ts = ev.get("ts", 0)
            last = max(last, ts)
    return last


def _last_pass_ts(cwd) -> int:
    last = 0
    for ev in peek_events(cwd):
        if ev.get("kind") in ("test_pass", "build_pass"):
            ts = ev.get("ts", 0)
            last = max(last, ts)
    return last


def _evidence_after_edit(cwd) -> bool:
    """True iff a passing test/build was logged AFTER the most recent edit."""
    edit_ts = _last_edit_ts(cwd)
    if edit_ts == 0:
        return True  # no recorded edits -> no claim to verify
    return _last_pass_ts(cwd) > edit_ts


def main() -> None:
    inp = hook_input()
    cfg = settings()
    cwd = inp.get("cwd") or os.getcwd()

    tool_input = inp.get("tool_input") or {}
    cmd = tool_input.get("command") or ""

    gate = ((cfg.get("confidence") or {}).get("commit_gate")) or "off"
    if gate == "off":
        return
    if not (is_git_commit(cmd) or is_git_push(cmd)):
        return

    if _evidence_after_edit(cwd):
        return

    msg = (
        "presence: about to commit/push without verification.\n"
        "No passing test or build was logged AFTER the most recent edit in this session.\n"
        "Either run the test suite first, or hedge your success claims."
    )
    age = now_ts() - _last_edit_ts(cwd)
    if age:
        msg += f"\n(Most recent edit was {age}s ago.)"

    if gate == "warn":
        # Advisory only; never interrupt. Just inject context for Claude/the user to see
        emit_context("PreToolUse", msg)
        return
    if gate == "ask":
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": msg,
            }
        })
        return
    if gate == "block":
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": msg,
            }
        })
        return


if __name__ == "__main__":
    safe_main(main)
