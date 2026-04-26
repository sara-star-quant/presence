"""Living project model: a per-repo markdown file appended by Claude across sessions."""
from __future__ import annotations

import time
from pathlib import Path

from _common import _flock, atomic_write, project_dir

MODEL_HEADER = """# Project model: maintained by presence

This file is appended by Claude Code via the `presence` plugin. It captures Claude's
understanding of this codebase across sessions. Compressed periodically by the
model-curator agent. Do not commit to your repo unless you want a team-shared view.

"""


def model_path(cwd=None) -> Path:
    return project_dir(cwd) / "model.md"


def read_model(cwd=None, max_chars: int | None = None) -> str:
    p = model_path(cwd)
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if max_chars and len(text) > max_chars:
        # Keep header + most-recent tail
        header_end = text.find("\n\n")
        head = text[: header_end + 2] if header_end > 0 else ""
        budget = max(0, max_chars - len(head) - 100)
        tail = text[-budget:] if budget else ""
        return head + "\n\n[...older entries elided; run /presence-doctor to compress...]\n\n" + tail
    return text


def append_observation(text: str, cwd=None) -> None:
    p = model_path(cwd)
    if not p.exists():
        atomic_write(p, MODEL_HEADER)
    timestamp = time.strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp}\n\n{text.strip()}\n"
    with open(p, "a", encoding="utf-8") as f:
        unlock = _flock(f.fileno(), exclusive=True)
        try:
            f.write(entry)
        finally:
            unlock()


def model_size(cwd=None) -> int:
    p = model_path(cwd)
    return p.stat().st_size if p.exists() else 0
