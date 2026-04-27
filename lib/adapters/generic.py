"""GenericAdapter: plain-text stdout for unknown / debug hosts.

Useful when running presence outside of Claude Code (e.g., manually firing
a hook for testing) or when no specific host adapter applies. Mimics the
shape of a Claude Code hook block but in human-readable text.
"""
from __future__ import annotations

import sys

from .base import Adapter


class GenericAdapter(Adapter):
    def emit_context(self, event_name: str, text: str) -> None:
        if not text:
            return
        sys.stdout.write(f"\n[presence: {event_name}]\n{text}\n")
        sys.stdout.flush()
