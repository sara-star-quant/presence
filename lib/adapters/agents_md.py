"""AgentsMdAdapter: refresh a delimited section of AGENTS.md at SessionStart.

AGENTS.md became an open standard in 2026 (Agentic AI Foundation, Linux
Foundation directed fund) and is read by Codex, Cursor, Gemini CLI,
Windsurf, GitHub Copilot, and dozens of other AI coding tools. presence
runs as a Claude Code plugin; this adapter lets the same machine's other
AI tools see presence's accumulated project knowledge by refreshing the
project's AGENTS.md every time a Claude Code SessionStart hook fires.

Filename override: ``PRESENCE_AGENTS_MD_FILENAME`` env var. Defaults to
``AGENTS.md``. Useful values:
  - ``AGENTS.md`` (default; works for all AGENTS.md-aware tools)
  - ``GEMINI.md`` (Gemini CLI's preferred name; also works as a fallback)
  - ``.cursor/rules/presence.mdc`` (Cursor's modular rules format)

Section delimiters: ``<!-- presence:start -->`` ... ``<!-- presence:end -->``.
Presence-managed content is replaced inside these markers; everything else
in the file is left alone. Idempotent.

Event scope: this adapter ONLY acts on ``SessionStart`` events. Hooks that
fire continuously (UserPromptSubmit, PostToolUse, etc.) would write to disk
on every fire, which is unnecessary noise; SessionStart is when the model
+ telemetry digest is freshest.
"""
from __future__ import annotations

import os
from pathlib import Path

from .base import Adapter

DEFAULT_FILENAME = "AGENTS.md"
START_MARKER = "<!-- presence:start -->"
END_MARKER = "<!-- presence:end -->"


def _project_root() -> Path:
    """Return the repo root (git toplevel) or the current working directory.

    Imported from _common to reuse the existing git-aware resolution; that
    helper already handles non-git directories gracefully.
    """
    from _common import repo_root
    return repo_root()


def _target_path() -> Path:
    """Resolve the AGENTS.md target file. Honors PRESENCE_AGENTS_MD_FILENAME."""
    filename = os.environ.get("PRESENCE_AGENTS_MD_FILENAME", DEFAULT_FILENAME)
    return _project_root() / filename


def _build_section(text: str) -> str:
    """Wrap ``text`` in the presence-managed section markers."""
    return (
        f"{START_MARKER}\n"
        f"<!-- This block is managed by presence (https://github.com/sara-star-quant/presence). -->\n"
        f"<!-- It refreshes at the start of each Claude Code session. Edit outside the markers. -->\n"
        f"\n"
        f"{text.strip()}\n"
        f"\n"
        f"{END_MARKER}\n"
    )


def _replace_section(existing: str, new_section: str) -> str:
    """Replace the existing presence-managed section, or append if missing.

    Idempotent: calling twice with the same new_section produces the same
    result. User-authored content outside the markers is preserved exactly.
    """
    start = existing.find(START_MARKER)
    end = existing.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        # No existing section; append (with a blank line if the file is non-empty).
        sep = "\n" if existing and not existing.endswith("\n") else ""
        if existing.strip():
            return existing + sep + "\n" + new_section
        return new_section
    # Replace the section in place. end + len(END_MARKER) covers the closing tag;
    # also consume one trailing newline if present for clean idempotence.
    end_pos = end + len(END_MARKER)
    if end_pos < len(existing) and existing[end_pos] == "\n":
        end_pos += 1
    return existing[:start] + new_section + existing[end_pos:]


class AgentsMdAdapter(Adapter):
    """Refresh AGENTS.md (or override) on SessionStart; noop on other events.

    The text content presence assembles for SessionStart already includes
    the living model, telemetry digest, and recent events wrapped in XML
    tags. We pass that text through verbatim into the AGENTS.md section so
    AGENTS.md-aware tools see the same context Claude Code would.
    """

    def emit_context(self, event_name: str, text: str) -> None:
        if event_name != "SessionStart" or not text:
            return
        target = _target_path()
        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError:
            existing = ""
        new_section = _build_section(text)
        updated = _replace_section(existing, new_section)
        if updated == existing:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
        except OSError:
            # Never break a hook on a write failure; the user's repo may be
            # read-only, on a network mount, etc. presence's stance: hooks
            # are best-effort observers, never required to succeed.
            pass
