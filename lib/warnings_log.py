"""Warnings channel: visible debug signal that doesn't break Claude Code.

Two failure modes presence must distinguish:
  - "fatal bug in a hook" -> caught by safe_main, written to errors.log, error counter bumped
  - "expected-but-degraded condition" (corrupt JSONL, slow git, missing python on PATH,
    settings file unparseable) -> written here as a structured warning, warning counter
    bumped, surfaced once at next SessionStart and resettable via /presence-doctor.

Module name is ``warnings_log`` not ``warnings`` to avoid clobbering the stdlib name.
"""
from __future__ import annotations

import json
import time

# Imported here, not re-exported; keep direct dependence on _common to a minimum
# so we never get import cycles even when _common itself imports us.
from _common import _bump_counter, _rotate_if_large, logs_dir

WARNINGS_PATH = lambda: logs_dir() / "warnings.log"  # noqa: E731  intentional call-site


def warn(category: str, message: str, fix: str | None = None, **details) -> None:
    """Log a structured warning. Best-effort; never raises.

    ``fix`` is an optional one-line recovery hint surfaced inline by
    /presence-doctor (added in v0.3.4). Backward compatible: callers that omit
    ``fix`` get the same behavior as before.
    """
    line = {
        "ts": int(time.time()),
        "category": category,
        "message": message,
    }
    if fix:
        line["fix"] = fix
    if details:
        line["details"] = details
    try:
        path = WARNINGS_PATH()
        _rotate_if_large(path, max_bytes=512_000)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        _bump_counter("warning")
    except OSError:
        # Last-ditch: stderr. If even that fails, swallow; never break a hook.
        try:
            import sys
            sys.stderr.write(f"presence warn: [{category}] {message}\n")
        except OSError:
            pass


def read_warnings(limit: int = 50) -> list[dict]:
    """Return the most recent warnings, newest last."""
    path = WARNINGS_PATH()
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    out.append(json.loads(s))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out[-limit:]


def warn_once(category: str, message: str, fix: str | None = None, **details) -> None:
    """Emit a warning only the first time per category since last reset.

    Useful for one-shot conditions like 'python3 missing' or 'git not installed' that
    we don't want to log on every hook invocation. See ``warn`` for the ``fix``
    kwarg semantics.
    """
    marker = logs_dir() / f".warned-{category}"
    if marker.exists():
        return
    warn(category, message, fix=fix, **details)
    try:
        marker.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass


def clear_warnings_state() -> None:
    """Reset both the warnings log and any one-shot markers."""
    p = WARNINGS_PATH()
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass
    try:
        for marker in logs_dir().glob(".warned-*"):
            marker.unlink()
    except OSError:
        pass


__all__ = ["warn", "warn_once", "read_warnings", "clear_warnings_state"]
