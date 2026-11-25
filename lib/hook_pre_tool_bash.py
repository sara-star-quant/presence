"""PreToolUse(Bash) hook: confidence gate on git commit / git push.

Modes (from preset.confidence.commit_gate):
- "off"   : never intervene
- "warn"  : emit additionalContext warning, do not block (does not interrupt the user)
- "ask"   : ask user via permissionDecision=ask (interrupts every time; reserve for strict)
- "block" : deny via permissionDecision=deny
"""
from __future__ import annotations

import os

from _common import emit, emit_context, hook_input, integrity_blocked, now_ts, safe_main, settings
from cmdparse import is_git_commit, is_git_push
from testinfra import can_be_verified
from verify import run_guards_target, scan_recent
from worktree import view as tree_view


def _evidence_after_edit(cwd, session_id: str | None = None) -> tuple[bool, int]:
    """Return (evidence_present, last_edit_ts).

    evidence_present is True iff a passing test/build was logged AFTER the most
    recent edit (by event order), or there are no recorded edits in the window. Single
    peek_events scan via scan_recent (was two scans: last_edit, last_pass).
    """
    # Wide window: PreToolUse fires opportunistically, so include the longer
    # 1800 s scan_recent default rather than the 600 s test-evidence default.
    view = tree_view(cwd, session_id) if session_id else None
    recent = scan_recent(cwd, window_seconds=1800, tree_view=view)
    return recent["verified_since_edit"], recent["last_edit_ts"]


def main() -> None:
    if integrity_blocked():
        return  # SessionStart fail-closed marker is set; stay inert
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

    sid = inp.get("session_id")
    evidence_present, last_edit_ts = _evidence_after_edit(cwd, str(sid) if sid else None)
    if evidence_present:
        return
    if not can_be_verified(cwd):
        return  # no runner the gate recognises lives here: evidence is impossible, so asking for it would only block
    if run_guards_target(cmd, lambda clause: is_git_commit(clause) or is_git_push(clause)):
        return  # test && git commit: the commit only runs if the test passed

    msg = (
        "presence: about to commit/push without verification.\n"
        "No passing test or build was logged AFTER the most recent edit in this session.\n"
        "Either run the test suite first, or hedge your success claims."
    )
    if last_edit_ts:
        age = now_ts() - last_edit_ts
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
