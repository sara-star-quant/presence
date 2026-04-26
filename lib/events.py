"""Event log: a per-repo bounded queue. Drains TRUNCATE; they don't just advance a cursor.

Previous version used a cursor and never deleted drained data, so ``pending.jsonl``
grew unboundedly. Now: drain holds an exclusive lock, reads everything, returns the
new events, and rewrites the file with only the post-drain tail (which is empty
unless new appends raced in during the read; those are preserved).

Race semantics:
- A writer holding ``flock`` while appending always sees its write either fully
  before or fully after the drainer's snapshot.
- The drain rewrites only what it itself read; appends that arrived after the
  snapshot stay in the file.
- Two parallel drainers contend on the file lock; one runs first, the other sees
  the rewritten (empty-or-near-empty) file.
"""
from __future__ import annotations

import json
from pathlib import Path

from _common import _flock, append_jsonl, events_dir, now_ts


def event_path(cwd=None) -> Path:
    return events_dir(cwd) / "pending.jsonl"


# Hard cap: even with no drain, never let the file exceed this many bytes.
# When breached we drop the oldest half and warn.
MAX_EVENT_BYTES = 2_000_000


def append_event(ev: dict, cwd=None) -> None:
    ev = dict(ev)
    ev.setdefault("ts", now_ts())
    p = event_path(cwd)
    append_jsonl(p, ev)
    try:
        if p.stat().st_size > MAX_EVENT_BYTES:
            _emergency_truncate(p)
    except OSError:
        pass


def drain_events(cwd=None) -> list[dict]:
    """Return all queued events; truncate the file under exclusive lock.

    On any I/O error returns ``[]`` and leaves the file untouched.
    """
    p = event_path(cwd)
    if not p.exists():
        return []
    try:
        with open(p, "r+", encoding="utf-8", errors="replace") as f:
            unlock = _flock(f.fileno(), exclusive=True)
            try:
                f.seek(0)
                raw = f.read()
                drained, kept = _parse_drain(raw)
                # Rewrite only what we read; preserve any appends that raced past us
                # (cannot happen while we hold the lock, but defensive against future
                # changes that switch to advisory non-locking writes).
                f.seek(0)
                f.truncate()
                if kept:
                    f.write(kept)
            finally:
                unlock()
    except OSError:
        return []
    return drained


def _parse_drain(raw: str) -> tuple[list[dict], str]:
    """Return (parsed events, kept-as-string-tail). Tail is currently always empty
    because we drain everything we read; see module docstring for rationale.
    """
    events: list[dict] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            events.append(json.loads(s))
        except json.JSONDecodeError:
            # Corrupt line: drop it (warn separately via read_jsonl path elsewhere).
            continue
    return events, ""


def peek_events(cwd=None) -> list[dict]:
    """Read events without draining (used by verify.* and the doctor)."""
    p = event_path(cwd)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
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
    return out


def summarize_events(events: list[dict], max_lines: int = 20) -> str:
    """Group + collapse events into a short text digest. '' if nothing useful."""
    if not events:
        return ""
    # Sort by ts so file-order surprises don't leak through
    events = sorted(events, key=lambda e: e.get("ts", 0))
    edits = [e for e in events if e.get("kind") == "edit"]
    bashes = [e for e in events if e.get("kind") == "bash"]
    typed = [e for e in events if e.get("kind", "").startswith(("test_", "build_"))]
    failed_bash = [e for e in bashes if e.get("exit", 0) not in (0, "0")]

    lines: list[str] = []
    if edits:
        files = sorted({e.get("path", "?") for e in edits})
        shown = files[:8]
        suffix = f" (+{len(files) - 8} more)" if len(files) > 8 else ""
        lines.append(f"Edits: {len(edits)} across {', '.join(shown)}{suffix}")
    for t in typed[-5:]:
        lines.append(f"  {t.get('kind')}: {(t.get('cmd') or '')[:80]}")
    if failed_bash:
        lines.append(f"Failed commands: {len(failed_bash)}")
        for fb in failed_bash[-3:]:
            lines.append(f"  exit {fb.get('exit')}: {(fb.get('cmd') or '')[:80]}")
    return "\n".join(lines[:max_lines])


def _emergency_truncate(p: Path) -> None:
    """If the queue blows past MAX_EVENT_BYTES without a drainer ever arriving,
    drop the oldest half so we cap memory.
    """
    from warnings_log import warn

    keep: list[str] = []
    try:
        with open(p, "r+", encoding="utf-8", errors="replace") as f:
            unlock = _flock(f.fileno(), exclusive=True)
            try:
                f.seek(0)
                lines = f.readlines()
                keep = lines[len(lines) // 2 :]
                f.seek(0)
                f.truncate()
                f.writelines(keep)
            finally:
                unlock()
        warn(
            "events_overflow",
            "pending.jsonl exceeded max bytes; dropped oldest half",
            path=str(p),
            kept=len(keep),
        )
    except OSError as exc:
        warn("events_overflow_failed", f"could not truncate {p}: {exc}")
