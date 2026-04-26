"""Settings immutability via a TTL'd unlock marker.

Under the zerotrust preset (or any preset that sets ``settings.immutable: true``),
writes to ``settings.json`` and ``presets/`` are refused unless an unlock marker
exists at ``~/.claude/presence/.unlocked`` and has not yet expired.

The marker file contains a single integer: the unix timestamp at which the unlock
expires. Default TTL is 60 seconds. Re-running ``/presence-unlock`` extends.

This is a tamper-resistance signal, not a hard barrier (the user has filesystem
access; they can always rm the marker). It exists to make accidental settings
changes during a sensitive session require an explicit conscious step.
"""
from __future__ import annotations

import time
from pathlib import Path

from _common import atomic_write, state_dir
from _common import settings as load_settings

DEFAULT_TTL_SECONDS = 60


def unlock_path() -> Path:
    return state_dir() / ".unlocked"


def is_immutable(cfg: dict | None = None) -> bool:
    """True iff the active preset declares settings.immutable=true."""
    cfg = cfg if cfg is not None else load_settings()
    return bool((cfg.get("settings") or {}).get("immutable"))


def is_unlocked() -> bool:
    """True iff a non-expired unlock marker is present."""
    p = unlock_path()
    if not p.exists():
        return False
    try:
        expire_at = int(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return time.time() < expire_at


def can_write_settings(cfg: dict | None = None) -> bool:
    """True iff the active preset allows settings writes right now.

    - If immutability is off (default presets): always True.
    - If immutability is on (zerotrust): True only when an unlock marker is active.
    """
    if not is_immutable(cfg):
        return True
    return is_unlocked()


def unlock(ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
    """Create or extend the unlock marker. Returns the unix timestamp of expiry."""
    expire_at = int(time.time()) + max(1, int(ttl_seconds))
    atomic_write(unlock_path(), str(expire_at) + "\n")
    return expire_at


def lock() -> bool:
    """Remove the unlock marker. Returns True if a marker was removed."""
    p = unlock_path()
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


__all__ = [
    "is_immutable", "is_unlocked", "can_write_settings",
    "unlock", "lock", "unlock_path", "DEFAULT_TTL_SECONDS",
]
