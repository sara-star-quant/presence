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
from verify import scan_recent


def _evidence_after_edit(cwd) -> tuple[bool, int]:
    """Return (evidence_present, last_edit_ts).

    evidence_present is True iff a passing test/build was logged AFTER the most
    recent edit, or there are no recorded edits in the window. Single
    peek_events scan via scan_recent (was two scans: last_edit, last_pass).
    """
    # Wide window: PreToolUse fires opportunistically, so include the longer
    # 1800 s scan_recent default rather than the 600 s test-evidence default.
    recent = scan_recent(cwd, window_seconds=1800)
    edit_ts = recent["last_edit_ts"]
    if edit_ts == 0:
        return True, 0
    return recent["last_pass_ts"] > edit_ts, edit_ts


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

    evidence_present, last_edit_ts = _evidence_after_edit(cwd)
    if evidence_present:
        return

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
