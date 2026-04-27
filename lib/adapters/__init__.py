"""Host-AI-tool adapter seam.

v0.4.0 ships only the Claude Code adapter (the project's primary host).
Future versions add adapters for other AI coding tools:
  v0.4.1 - MCP server entry (any MCP-aware client)
  v0.4.2 - Cursor, Gemini, Codex, claude-code (Anthropic), clawbot,
           plus a generic-fallback adapter for any other host.

Selected by the ``PRESENCE_HOST`` environment variable; defaults to
``claude``. The full list of recognized values lives in this file's
get_adapter() so the supported set is discoverable by ``grep``.
"""
import os

from .base import Adapter
from .claude import ClaudeAdapter


def get_adapter() -> Adapter:
    # ``host`` is normalized to lowercase. Unknown hosts fall through to
    # ClaudeAdapter (default) rather than raising; presence's "never break a
    # hook" stance applies even to misconfiguration.
    host = os.environ.get("PRESENCE_HOST", "claude").lower()
    # The recognized list will grow in v0.4.2; for now only "claude" is wired.
    if host == "claude":
        return ClaudeAdapter()
    return ClaudeAdapter()


__all__ = ["Adapter", "ClaudeAdapter", "get_adapter"]
