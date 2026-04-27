import json
import sys

from .base import Adapter


class ClaudeAdapter(Adapter):
    """Native Claude Code JSON stdout format."""

    def emit_context(self, event_name: str, text: str) -> None:
        if not text:
            return

        payload = {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": text,
            }
        }

        try:
            import orjson
            sys.stdout.buffer.write(orjson.dumps(payload))
        except ImportError:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.stdout.flush()
