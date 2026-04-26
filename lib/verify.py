"""Calibrated-confidence checker: parse success claims; check evidence."""
from __future__ import annotations

import re

from _common import now_ts
from events import peek_events

SUCCESS_CLAIMS = [
    re.compile(r"\b(?:fixed|resolved|done|works?|working|complete|completed|all set)\b", re.IGNORECASE),
    re.compile(r"\b(?:passes|passing) (?:all )?tests?\b", re.IGNORECASE),
    re.compile(r"\bready to (?:ship|merge|deploy|land)\b", re.IGNORECASE),
    # NOTE: "should X" is intentionally NOT a SUCCESS_CLAIM. "should" is itself a hedge.
]

HEDGES = [
    re.compile(r"\b(?:probably|likely|possibly|may|might|i think|i believe)\b", re.IGNORECASE),
    re.compile(r"\b(?:untested|not (?:yet )?tested|haven['']t (?:run|tested|verified))\b", re.IGNORECASE),
    re.compile(r"\bneeds? (?:verification|testing|review|to be (?:tested|verified))\b", re.IGNORECASE),
    re.compile(r"\bcan't (?:test|verify|run)\b", re.IGNORECASE),
]


def has_unhedged_success_claim(text: str) -> bool:
    if not text:
        return False
    if not any(p.search(text) for p in SUCCESS_CLAIMS):
        return False
    return not any(p.search(text) for p in HEDGES)


def scan_recent(cwd=None, since_ts: int | None = None, window_seconds: int = 1800) -> dict:
    """Single peek_events pass returning the recency facts callers need.

    Replaces N independent `for ev in peek_events(cwd)` loops with one. The
    Stop hook and PreToolUse(Bash) hook each used to call peek_events twice
    per fire (once for last-edit, once for last-pass) which doubled the cold
    JSONL parse cost.
    """
    if since_ts is None:
        since_ts = now_ts() - window_seconds
    last_edit = 0
    last_pass = 0
    for ev in peek_events(cwd):
        ts = ev.get("ts", 0)
        if ts < since_ts:
            continue
        kind = ev.get("kind")
        if kind == "edit":
            last_edit = max(last_edit, ts)
        elif kind in ("test_pass", "build_pass"):
            last_pass = max(last_pass, ts)
    return {
        "last_edit_ts": last_edit,
        "last_pass_ts": last_pass,
        "has_recent_edit": last_edit > 0,
        "has_recent_test_evidence": last_pass > 0,
    }


def has_recent_test_evidence(cwd=None, since_ts: int | None = None, window_seconds: int = 600) -> bool:
    """True iff a passing test/build event was logged since ``since_ts`` (default last 10 min)."""
    return scan_recent(cwd, since_ts=since_ts, window_seconds=window_seconds)["has_recent_test_evidence"]


def has_recent_edit(cwd=None, since_ts: int | None = None, window_seconds: int = 1800) -> bool:
    return scan_recent(cwd, since_ts=since_ts, window_seconds=window_seconds)["has_recent_edit"]


# Test/build classifiers: proper word boundaries, no cargo-culted "\n"/"$" tokens
_TEST_PATTERNS = [
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\bjest\b", re.IGNORECASE),
    re.compile(r"\bvitest\b", re.IGNORECASE),
    re.compile(r"\bgo\s+test\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+test\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+(?:run\s+)?test\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+t\b", re.IGNORECASE),
    re.compile(r"\byarn\s+(?:run\s+)?test\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(?:run\s+)?test\b", re.IGNORECASE),
    re.compile(r"\bbun\s+test\b", re.IGNORECASE),
    re.compile(r"\brspec\b", re.IGNORECASE),
    re.compile(r"\bmocha\b", re.IGNORECASE),
    re.compile(r"\bphpunit\b", re.IGNORECASE),
    re.compile(r"\bmix\s+test\b", re.IGNORECASE),
    re.compile(r"\brake\s+test\b", re.IGNORECASE),
    re.compile(r"\bginkgo\b", re.IGNORECASE),
    re.compile(r"\bnpx\s+(?:jest|vitest|mocha)\b", re.IGNORECASE),
]
_BUILD_PATTERNS = [
    re.compile(r"\bnpm\s+run\s+build\b", re.IGNORECASE),
    re.compile(r"\byarn\s+build\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(?:run\s+)?build\b", re.IGNORECASE),
    re.compile(r"\bbun\s+(?:run\s+)?build\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+build\b", re.IGNORECASE),
    re.compile(r"\bgo\s+build\b", re.IGNORECASE),
    re.compile(r"\bmake\s+build\b", re.IGNORECASE),
    re.compile(r"\btsc\b", re.IGNORECASE),
    re.compile(r"\b(?:next|vite|webpack)\s+build\b", re.IGNORECASE),
]


def classify_command(cmd: str | None, exit_code) -> str | None:
    """Return ``test_pass``/``test_fail``/``build_pass``/``build_fail`` or ``None``.

    If ``exit_code`` is missing/unparseable, returns ``None`` and refuses to classify
    (so a failed test cannot be silently logged as a pass).
    """
    if not cmd:
        return None
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        return None
    is_test = any(p.search(cmd) for p in _TEST_PATTERNS)
    is_build = any(p.search(cmd) for p in _BUILD_PATTERNS)
    if not (is_test or is_build):
        return None
    kind = "test" if is_test else "build"
    return f"{kind}_{'pass' if code == 0 else 'fail'}"
