"""PostToolUse(Edit|Write|MultiEdit) hook: log file edits to the event stream."""
from __future__ import annotations

import os

from _common import hook_input, integrity_blocked, repo_root, safe_main, settings
from events import append_event
from verify import edit_scope


def main() -> None:
    if integrity_blocked():
        return  # SessionStart fail-closed marker is set; stay inert
    inp = hook_input()
    cfg = settings()
    cwd = inp.get("cwd") or os.getcwd()

    if not (cfg.get("events") or {}).get("enabled", True):
        return

    tool_name = inp.get("tool_name") or ""
    tool_input = inp.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""

    # scope: only an edit to code inside the project makes the work need a test run
    append_event({"kind": "edit", "tool": tool_name, "path": str(path), "scope": edit_scope(str(path), str(repo_root(cwd)))}, cwd=cwd)


if __name__ == "__main__":
    safe_main(main)
