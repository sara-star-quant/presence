"""Host-AI-tool adapter seam.

Selected by the ``PRESENCE_HOST`` environment variable; defaults to
``claude``. Recognized values:

  ``claude``     -> ClaudeAdapter: emits Claude Code's hookSpecificOutput
                    JSON shape. Default; matches v0.3.x and v0.4.0 behavior.
  ``agents-md``  -> AgentsMdAdapter: refresh a delimited section of
                    ``<repo_root>/AGENTS.md`` (or ``$PRESENCE_AGENTS_MD_FILENAME``)
                    on SessionStart. AGENTS.md is the cross-tool open
                    standard read by Codex, Cursor, Gemini CLI, Windsurf,
                    GitHub Copilot, and others. v0.4.2+.
  ``generic``    -> GenericAdapter: plain-text stdout. Useful for debugging
                    presence outside Claude Code.

Unknown hosts fall through to ClaudeAdapter (the safest default for hooks
running inside Claude Code).
"""
import os

from .agents_md import AgentsMdAdapter
from .base import Adapter
from .claude import ClaudeAdapter
from .generic import GenericAdapter

_REGISTRY: dict[str, type[Adapter]] = {
    "claude": ClaudeAdapter,
    "agents-md": AgentsMdAdapter,
    "agents_md": AgentsMdAdapter,   # tolerate underscore form
    "agents":    AgentsMdAdapter,   # short alias
    "generic":   GenericAdapter,
}


def get_adapter() -> Adapter:
    host = os.environ.get("PRESENCE_HOST", "claude").lower().strip()
    cls = _REGISTRY.get(host, ClaudeAdapter)
    return cls()


__all__ = [
    "Adapter",
    "AgentsMdAdapter",
    "ClaudeAdapter",
    "GenericAdapter",
    "get_adapter",
]
