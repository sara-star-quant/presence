"""UserPromptSubmit hook: drain pending events into the next turn's context."""
from __future__ import annotations

import os

from _common import emit_context, hook_input, integrity_blocked, safe_main, settings
from events import drain_events, summarize_events
from notice import take_notice
from worktree import ensure_base


def main() -> None:
    if integrity_blocked():
        return  # SessionStart fail-closed marker is set; stay inert
    inp = hook_input()
    cfg = settings()
    cwd = inp.get("cwd") or os.getcwd()

    # Baseline for "did code change this session", read from the working copy. Once per session.
    if inp.get("session_id") and (cfg.get("confidence") or {}).get("enabled", True):
        ensure_base(cwd, str(inp["session_id"]))

    parts: list[str] = []
    # stop_action "warn": the line an unverified claim left behind, told to the agent once (lib/notice.py).
    if (cfg.get("confidence") or {}).get("enabled", True):
        notice = take_notice(cwd, inp.get("session_id"))
        if notice:
            parts.append(notice)

    if (cfg.get("events") or {}).get("enabled", True):
        digest = summarize_events(drain_events(cwd))
        if digest:
            parts.append("=== presence: events since last turn ===\n" + digest)

    if parts:
        emit_context("UserPromptSubmit", "\n\n".join(parts))


if __name__ == "__main__":
    safe_main(main)
