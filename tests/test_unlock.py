"""Settings-immutability + unlock TTL tests."""
from __future__ import annotations

import json
import time

import unlock


def test_no_unlock_marker_initially(isolated_state):
    assert not unlock.is_unlocked()


def test_unlock_creates_marker(isolated_state):
    expire = unlock.unlock(ttl_seconds=10)
    assert unlock.is_unlocked()
    assert unlock.unlock_path().exists()
    # Expiry should be roughly now + 10
    assert abs(expire - (int(time.time()) + 10)) <= 1


def test_lock_removes_marker(isolated_state):
    unlock.unlock()
    assert unlock.is_unlocked()
    assert unlock.lock()
    assert not unlock.is_unlocked()


def test_lock_idempotent(isolated_state):
    """Calling lock when no marker exists is a no-op (returns False)."""
    assert not unlock.lock()


def test_expired_marker_is_not_unlocked(isolated_state):
    """A marker whose timestamp is in the past must not count as unlocked."""
    p = unlock.unlock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(int(time.time()) - 100))
    assert not unlock.is_unlocked()


def test_corrupt_marker_is_not_unlocked(isolated_state):
    """Garbage in the marker file fails closed (treated as locked)."""
    p = unlock.unlock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not a number")
    assert not unlock.is_unlocked()


def test_can_write_settings_when_immutability_off(isolated_state):
    """Default presets don't set settings.immutable, so writes are always allowed."""
    # No settings.json -> defaults; solo-dev (no immutable flag)
    assert unlock.can_write_settings()


def test_can_write_settings_blocked_when_immutable_and_locked(isolated_state):
    """Under zerotrust (immutable=true), writes are blocked without unlock."""
    settings_file = isolated_state / "settings.json"
    settings_file.write_text(json.dumps({"preset": "zerotrust"}))
    assert not unlock.can_write_settings()


def test_can_write_settings_allowed_when_immutable_and_unlocked(isolated_state):
    """Under zerotrust, an active unlock marker permits writes."""
    settings_file = isolated_state / "settings.json"
    settings_file.write_text(json.dumps({"preset": "zerotrust"}))
    unlock.unlock(ttl_seconds=60)
    assert unlock.can_write_settings()


def test_unlock_extends_existing(isolated_state):
    """Calling unlock again resets/extends the TTL."""
    unlock.unlock(ttl_seconds=5)
    first_expire = int(unlock.unlock_path().read_text().strip())
    time.sleep(0.05)
    unlock.unlock(ttl_seconds=60)
    second_expire = int(unlock.unlock_path().read_text().strip())
    assert second_expire >= first_expire
