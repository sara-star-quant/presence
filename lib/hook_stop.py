"""Stop hook: parse final assistant message for unhedged success claims; verify against evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path

from _common import emit, hook_input, integrity_blocked, safe_main, settings
from telemetry import record_confidence
from verify import has_recent_edit, has_recent_test_evidence, has_unhedged_success_claim
from warnings_log import warn

# Default cap on how much transcript we'll read. Most sessions are well under this;
# very long sessions still find the most recent assistant message in the tail.
# Per-preset override available via `transcript.max_bytes`.
TRANSCRIPT_TAIL_BYTES_DEFAULT = 262_144


def _transcript_max_bytes(cfg: dict) -> int:
    raw = (cfg.get("transcript") or {}).get("max_bytes", TRANSCRIPT_TAIL_BYTES_DEFAULT)
    try:
        return max(1024, int(raw))
    except (TypeError, ValueError):
        return TRANSCRIPT_TAIL_BYTES_DEFAULT


def _safe_transcript_path(transcript_path: str | None, cfg: dict) -> Path | None:
    if not transcript_path:
        return None
    p = Path(transcript_path)
    try:
        p = p.resolve(strict=True)
    except OSError:
        return None
    if not p.is_file():
        return None
    if (cfg.get("transcript") or {}).get("restrict_to_claude_projects"):
        # Zero-Trust: refuse paths outside ~/.claude/projects/
        projects = (Path.home() / ".claude" / "projects").resolve()
        try:
            p.relative_to(projects)
        except ValueError:
            warn("transcript_outside_projects", f"refusing transcript at {p} (outside ~/.claude/projects)")
            return None
    return p


def _last_assistant_text(p: Path, max_bytes: int = TRANSCRIPT_TAIL_BYTES_DEFAULT) -> str:
    """Tail-read the JSONL transcript and return the last assistant message text."""
    try:
        size = p.stat().st_size
    except OSError:
        return ""
    start = max(0, size - max_bytes)
    last = ""
    try:
        with open(p, "rb") as f:
            f.seek(start)
            chunk = f.read()
    except OSError:
        return ""
    text = chunk.decode("utf-8", errors="replace")
    # If we started mid-line, drop the partial first line
    if start > 0:
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1 :]
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            last = content
        elif isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                last = "\n".join(texts)
    return last


def main() -> None:
    if integrity_blocked():
        return  # SessionStart fail-closed marker is set; stay inert
    inp = hook_input()
    cfg = settings()
    cwd = inp.get("cwd") or os.getcwd()

    if not (cfg.get("confidence") or {}).get("enabled", True):
        return

    transcript = _safe_transcript_path(inp.get("transcript_path"), cfg)
    if transcript is None:
        return

    final = _last_assistant_text(transcript, max_bytes=_transcript_max_bytes(cfg))
    if not final:
        # Could be schema drift, or just an empty session. Track it so /presence-doctor
        # can flag persistent emptiness.
        warn("transcript_no_assistant_text", f"could not extract assistant text from {transcript}")
        return

    if not has_unhedged_success_claim(final):
        return

    if not has_recent_edit(cwd):
        return

    verified = has_recent_test_evidence(cwd)
    record_confidence("unhedged_success", verified, final_excerpt=final[:200])

    if verified:
        return

    # Strict presets force a re-prompt; default presets log silently so the next
    # SessionStart can surface the count via the warnings counter pathway.
    stop_action = (cfg.get("confidence") or {}).get("stop_action") or "silent"
    if stop_action != "block":
        # Logged to confidence.jsonl above; SessionStart's counter surfacer will mention it.
        warn("unverified_success_claim", "asserted success without test/build evidence", excerpt=final[:120])
        return

    msg = (
        "presence: calibrated-confidence gate (preset stop_action=block):\n"
        "Your final message asserts success ('fixed', 'done', 'works', etc.) but no "
        "passing test or build was logged since the most recent edit in this session.\n"
        "Either run the test/build now and confirm it passes, or hedge the claim "
        "explicitly ('untested but should work', 'needs verification', etc.) before stopping."
    )
    emit({"decision": "block", "reason": msg})


if __name__ == "__main__":
    safe_main(main)
