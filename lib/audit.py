"""Tamper-evident audit log with per-line hash chain.

Each appended line includes the hash of the previous line. Tampering with any past
line invalidates every subsequent hash, which ``verify_chain`` detects and reports.

Format (one JSON object per file line, ASCII only):

    {"ts": <int>, "event": "<kind>", "preset": "<name>", "details": {...},
     "prev_hash": "<hex64>", "hash": "<hex64>"}

Hash is ``sha256(prev_hash || canonical_json(line_without_hash))``. ``canonical_json``
is JSON with ``sort_keys=True`` and ``separators=(",", ":")`` so that the recomputed
hash matches regardless of which writer produced the line.

The genesis hash for the very first line is ``sha256(b"presence-audit-v1")`` so the
chain anchors to a known constant rather than the empty string (helps the verifier
distinguish "this is line 0" from "prev_hash got truncated to empty").
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from _common import _flock, append_jsonl, now_ts, state_dir

from presets import active_preset_name

GENESIS_HASH = hashlib.sha256(b"presence-audit-v1").hexdigest()


def audit_path() -> Path:
    return state_dir() / "audit.jsonl"


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _last_hash(path: Path) -> str:
    """Return the hash field of the last line, or GENESIS_HASH if file is empty/missing."""
    if not path.exists():
        return GENESIS_HASH
    last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s:
                    last = s
    except OSError:
        return GENESIS_HASH
    if not last:
        return GENESIS_HASH
    try:
        obj = json.loads(last)
        h = obj.get("hash")
        return h if isinstance(h, str) and len(h) == 64 else GENESIS_HASH
    except json.JSONDecodeError:
        return GENESIS_HASH


def append(event: str, details: dict | None = None) -> None:
    """Append a tamper-evident audit line. Best-effort; never raises."""
    path = audit_path()
    record = {
        "ts": now_ts(),
        "event": event,
        "preset": active_preset_name(),
        "details": details or {},
    }
    # Hold the audit lock for the entire read-prev + compute-hash + append cycle so
    # concurrent appenders chain off the same prev_hash.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            unlock = _flock(f.fileno(), exclusive=True)
            try:
                prev = _last_hash(path)
                record["prev_hash"] = prev
                # Hash everything except the hash field itself
                line_hash = hashlib.sha256(prev.encode("ascii") + _canonical(record)).hexdigest()
                record["hash"] = line_hash
                f.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
            finally:
                unlock()
    except OSError:
        # If the audit log cannot be written, fall back to a regular warning so the
        # operator at least sees that audit was attempted and failed.
        try:
            from warnings_log import warn
            warn("audit_write_failed", f"could not append audit line for event={event}")
        except Exception:  # noqa: BLE001, S110  if even the warn channel is broken, just swallow
            pass


def verify_chain() -> dict:
    """Walk the audit log; return a report dict.

    {
      "exists": bool,
      "lines": int,                # total parsed lines
      "tampered": [int],           # 0-based line indices whose hash didn't recompute
      "broken_link": [int],        # lines whose prev_hash didn't match the previous line's hash
      "corrupt": [int],            # lines that didn't parse as JSON or lacked required fields
      "ok": bool,                  # True iff tampered + broken_link + corrupt all empty
    }
    """
    path = audit_path()
    report = {
        "exists": path.exists(),
        "lines": 0,
        "tampered": [],
        "broken_link": [],
        "corrupt": [],
        "ok": True,
    }
    if not path.exists():
        return report
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        report["ok"] = False
        return report

    expected_prev = GENESIS_HASH
    for idx, raw in enumerate(raw_lines):
        s = raw.strip()
        if not s:
            continue
        report["lines"] += 1
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            report["corrupt"].append(idx)
            continue
        stored_hash = obj.get("hash")
        stored_prev = obj.get("prev_hash")
        if not (isinstance(stored_hash, str) and isinstance(stored_prev, str)):
            report["corrupt"].append(idx)
            continue
        # Recompute the hash from the rest of the record
        without_hash = {k: v for k, v in obj.items() if k != "hash"}
        recomputed = hashlib.sha256(stored_prev.encode("ascii") + _canonical(without_hash)).hexdigest()
        if recomputed != stored_hash:
            report["tampered"].append(idx)
        if stored_prev != expected_prev:
            report["broken_link"].append(idx)
        expected_prev = stored_hash

    report["ok"] = not (report["tampered"] or report["broken_link"] or report["corrupt"])
    return report


__all__ = ["append", "verify_chain", "audit_path", "GENESIS_HASH"]


# Suppress the unused import warning for append_jsonl, which we kept around in case
# a future refactor wants to switch from manual locking to the shared helper.
_ = append_jsonl
