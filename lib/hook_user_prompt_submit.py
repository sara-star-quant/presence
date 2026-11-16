"""UserPromptSubmit hook: drain pending events into the next turn's context."""
from __future__ import annotations

import os

from _common import emit_context, hook_input, integrity_blocked, safe_main, settings
from events import drain_events, summarize_events
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

    if not (cfg.get("events") or {}).get("enabled", True):
        return

    events = drain_events(cwd)
    digest = summarize_events(events)
    if digest:
        emit_context(
            "UserPromptSubmit",
            "=== presence: events since last turn ===\n" + digest,
        )


if __name__ == "__main__":
    safe_main(main)
