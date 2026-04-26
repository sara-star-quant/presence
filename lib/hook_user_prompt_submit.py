"""UserPromptSubmit hook: drain pending events into the next turn's context."""
from __future__ import annotations

import os

from _common import emit_context, hook_input, safe_main, settings
from events import drain_events, summarize_events


def main() -> None:
    inp = hook_input()
    cfg = settings()
    cwd = inp.get("cwd") or os.getcwd()

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
