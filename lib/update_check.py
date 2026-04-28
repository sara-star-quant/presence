"""Opt-in network freshness check.

First (and currently only) network-egress feature in lib/. Off by default in
every preset; forced off under zerotrust regardless of user override. Cache
TTL 24 h; fail-open on every error path so a broken network never blocks
SessionStart or /presence-doctor.

Surfaces:
  - SessionStart background gather (lib/hook_session_start.gather_update_check_refresh)
    pre-warms the cache once per 24 h. Hard-bounded by asyncio.wait_for.
  - /presence-doctor reads the cache and renders one line. Never makes a
    network call on its own.
  - /presence-doctor --refresh forces a synchronous fetch (bypasses TTL).
    Used by maintainers to verify a freshly-tagged release is visible.

Design pinned by docs/roadmap.md "Version observability and freshness" item 4.
Two roadmap deviations: 5 s timeout (not 30 s) since SessionStart is on the
interactive critical path, and we kept ISO8601 checked_at as specified.
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from _common import atomic_write, state_dir

GITHUB_RELEASES_URL = "https://api.github.com/repos/sara-star-quant/presence/releases/latest"
TTL_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 5
USER_AGENT = "presence-update-check"


def cache_path() -> Path:
    return state_dir() / ".update_check_cache.json"


def is_enabled(cfg: dict) -> bool:
    """True iff update_check.enabled is set AND network egress is allowed.

    Two-layer gate:
      1. `network.egress_allowed: false` (the zerotrust posture, currently set
         only in presets/zerotrust.json) hard-disables every network feature.
         update_check is the first reader of this flag; future network
         features should read it the same way.
      2. `update_check.enabled: true` is the per-feature opt-in.

    Defense-in-depth: presets/zerotrust.json sets *both* network.egress_allowed
    and update_check.enabled; this function would short-circuit on either alone.
    """
    if (cfg.get("network") or {}).get("egress_allowed", True) is False:
        return False
    return bool((cfg.get("update_check") or {}).get("enabled", False))


def read_cache() -> dict | None:
    """Parsed cache dict or None on missing/corrupt. Forward-compatible:
    callers must `.get(field, default)` for every field so future schema
    additions don't crash old code reading new caches (or vice versa).
    """
    p = cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _parse_checked_at(s: str | None) -> float | None:
    """Parse ISO8601 checked_at to a unix timestamp, or None if unparseable.
    Fail-open: corrupt timestamps are treated as "no cache" rather than
    "infinitely old"."""
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def status(cfg: dict, current_tag: str) -> dict:
    """Read-only view for /presence-doctor. Never makes a network call.

    Returns one of:
      {"state": "disabled"}
      {"state": "zerotrust"}
      {"state": "no_cache"}                                          (enabled but never refreshed)
      {"state": "fresh", "latest_tag": ..., "current_tag": ..., "age_seconds": ...}
      {"state": "stale", "latest_tag": ..., "current_tag": ..., "age_seconds": ...}
    """
    if (cfg.get("network") or {}).get("egress_allowed", True) is False:
        return {"state": "zerotrust"}
    if not (cfg.get("update_check") or {}).get("enabled", False):
        return {"state": "disabled"}

    cache = read_cache()
    if not cache:
        return {"state": "no_cache"}

    checked_at = _parse_checked_at(cache.get("checked_at"))
    latest_tag = cache.get("latest_tag")
    if checked_at is None or not isinstance(latest_tag, str):
        return {"state": "no_cache"}

    age = max(0, time.time() - checked_at)
    state = "fresh" if age < TTL_SECONDS else "stale"
    return {
        "state": state,
        "latest_tag": latest_tag,
        "current_tag": current_tag,
        "age_seconds": int(age),
    }


def _fetch_latest_tag() -> str:
    """One HTTPS GET to GITHUB_RELEASES_URL. Returns tag_name. Raises on any
    error so the caller (maybe_refresh, force_refresh) can choose its own
    fail-open shape. Easy to monkeypatch in tests.
    """
    req = urllib.request.Request(  # noqa: S310 — fixed https URL, not user input
        GITHUB_RELEASES_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
        body = resp.read()
    payload = json.loads(body)
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise ValueError("GitHub releases response missing tag_name")
    return tag


def _write_cache(latest_tag: str) -> None:
    """ISO8601 UTC checked_at + latest_tag. atomic_write 0o600."""
    payload = {
        "checked_at": datetime.now(UTC).isoformat(),
        "latest_tag": latest_tag,
    }
    atomic_write(cache_path(), json.dumps(payload, ensure_ascii=False) + "\n")


async def maybe_refresh(cfg: dict) -> None:
    """SessionStart gate. If enabled and cache is stale, fire one HTTPS GET
    on a worker thread (urlopen is sync) and write the cache. Fail-open: any
    exception is swallowed.

    The actual fetch is wrapped in asyncio.to_thread so an unresponsive
    socket cannot stall the event loop. The hook layer adds a second
    asyncio.wait_for as a watchdog.
    """
    if not is_enabled(cfg):
        return
    cache = read_cache()
    if cache:
        checked_at = _parse_checked_at(cache.get("checked_at"))
        if checked_at is not None and time.time() - checked_at < TTL_SECONDS:
            return
    try:
        tag = await asyncio.to_thread(_fetch_latest_tag)
        await asyncio.to_thread(_write_cache, tag)
    except Exception:  # noqa: BLE001 — fail-open is the contract
        return


def force_refresh() -> tuple[bool, str]:
    """Synchronous; ignores TTL. Used by /presence-doctor --refresh.
    Returns (ok, message). Never raises.
    """
    try:
        tag = _fetch_latest_tag()
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code} from GitHub: {e.reason}")
    except urllib.error.URLError as e:
        return (False, f"network error: {e.reason}")
    except (TimeoutError, OSError) as e:
        return (False, f"network error: {e}")
    except (ValueError, json.JSONDecodeError) as e:
        return (False, f"unexpected GitHub response: {e}")
    try:
        _write_cache(tag)
    except OSError as e:
        return (False, f"latest tag {tag} fetched but cache write failed: {e}")
    return (True, f"latest tag: {tag}")
