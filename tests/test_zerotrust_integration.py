"""End-to-end Zero-Trust integration tests.

Avoids touching the real OS keychain by monkey-patching crypto._backend_ops with
in-memory get/set/delete functions. This lets us exercise the encryption + read
paths from append_jsonl/read_jsonl without leaving a key in the user's keychain.
"""
from __future__ import annotations

import json

import _common
import crypto
import pytest


@pytest.fixture
def in_memory_keychain(monkeypatch):
    """Replace the per-platform keychain ops with in-memory equivalents."""
    store = {"key": None}

    def get():
        return store["key"]

    def set_(k):
        store["key"] = k
        return True

    def delete():
        store["key"] = None
        return True

    monkeypatch.setattr(crypto, "_backend_ops", lambda: (get, set_, delete))
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(crypto, "keychain_backend", lambda: "in-memory")

    # Reset _common's encryption state cache so it re-resolves
    monkeypatch.setattr(_common, "_ENCRYPTION_STATE_CACHE", None)

    return store


def _activate_zerotrust(state_dir):
    """Write a settings.json that activates zerotrust (which enables encryption)."""
    (state_dir / "settings.json").write_text(json.dumps({"preset": "zerotrust"}))


def test_append_under_zerotrust_writes_encrypted_lines(isolated_state, in_memory_keychain):
    _activate_zerotrust(isolated_state)
    # Need to unlock first because zerotrust has settings.immutable=true and we already
    # wrote settings.json directly above (bypassing the unlock check for setup).
    from unlock import unlock
    unlock(ttl_seconds=60)

    target = isolated_state / "test.jsonl"
    _common.append_jsonl(target, {"hello": "world"})

    raw = target.read_text().strip()
    assert crypto.is_encrypted_line(raw), f"expected encrypted line, got: {raw[:80]}"


def test_read_decrypts_and_returns_plain_dict(isolated_state, in_memory_keychain):
    _activate_zerotrust(isolated_state)
    from unlock import unlock
    unlock(ttl_seconds=60)

    target = isolated_state / "test.jsonl"
    _common.append_jsonl(target, {"id": 1, "msg": "first"})
    _common.append_jsonl(target, {"id": 2, "msg": "second"})

    rows = _common.read_jsonl(target)
    assert len(rows) == 2
    assert rows[0] == {"id": 1, "msg": "first"}
    assert rows[1] == {"id": 2, "msg": "second"}


def test_mixed_file_handled_per_line(isolated_state, in_memory_keychain):
    """A file with both encrypted and plain lines must read correctly: encrypted lines
    decrypt, plain lines parse directly."""
    _activate_zerotrust(isolated_state)
    from unlock import unlock
    unlock(ttl_seconds=60)

    target = isolated_state / "mixed.jsonl"
    _common.append_jsonl(target, {"kind": "encrypted"})
    # Append a plain line manually
    with open(target, "a") as f:
        f.write(json.dumps({"kind": "plain"}) + "\n")

    rows = _common.read_jsonl(target)
    assert len(rows) == 2
    assert {r["kind"] for r in rows} == {"encrypted", "plain"}


def test_solodev_preset_writes_plain(isolated_state, in_memory_keychain, monkeypatch):
    """Default preset (solo-dev) does NOT request encryption, so writes stay plain."""
    # No settings.json => defaults to solo-dev
    monkeypatch.setattr(_common, "_ENCRYPTION_STATE_CACHE", None)
    target = isolated_state / "plain.jsonl"
    _common.append_jsonl(target, {"foo": "bar"})
    raw = target.read_text().strip()
    assert raw == '{"foo":"bar"}', f"expected plain line, got: {raw[:80]}"


def test_integrity_block_lifecycle(isolated_state):
    """SessionStart can set/clear a block; integrity_blocked() reflects it."""
    assert not _common.integrity_blocked()
    _common.set_integrity_block("test reason")
    assert _common.integrity_blocked()
    _common.clear_integrity_block()
    assert not _common.integrity_blocked()


def test_integrity_block_persists_across_module_calls(isolated_state):
    """The block marker is on disk, so any process checking sees it. Simulates
    SessionStart writing and another hook reading."""
    _common.set_integrity_block("session 12345")
    # New "process" perspective: just call the function fresh
    assert _common.integrity_block_path().exists()
    assert _common.integrity_blocked()
