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
    monkeypatch.setattr(_common, "_WRITE_STATE_CACHE", None)
    monkeypatch.setattr(_common, "_READ_KEY_CACHE", _common._UNSET)
    monkeypatch.setattr(_common, "_SETTINGS_CACHE", None)

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


def test_redact_profile_pii_eu_under_zerotrust_e2e(isolated_state, in_memory_keychain, fake_repo):
    """End-to-end: zerotrust + redact.profiles=['pii-eu'] override -> commit message
    containing an EU IBAN is redacted in the encrypted-on-disk claims.jsonl, and the
    decrypted readback shows [REDACTED:iban].

    This is the regulated-workload smoke path: settings opt-in, claim recorded, file
    on disk is ciphertext, but the redaction happened before encryption so a future
    decrypt cannot recover the IBAN."""
    import importlib

    (isolated_state / "settings.json").write_text(json.dumps({
        "preset": "zerotrust",
        "overrides": {"redact": {"profiles": ["pii-eu"]}},
    }))
    from unlock import unlock
    unlock(ttl_seconds=60)

    # Reload modules so the new settings (and profile cache reset) take effect.
    importlib.reload(_common)
    import telemetry
    importlib.reload(telemetry)
    from redact import _clear_profile_cache
    _clear_profile_cache()

    telemetry.record_commit_claim(
        str(fake_repo), "abc1234567890",
        "transferred to GB82WEST12345698765432 today", intent=None,
    )

    # On-disk: must be encrypted ciphertext (zerotrust contract).
    raw = telemetry.claims_path().read_text().strip()
    assert crypto.is_encrypted_line(raw), f"expected encrypted line, got: {raw[:80]}"
    assert "GB82WEST12345698765432" not in raw, "raw IBAN must not appear in ciphertext file"

    # Decrypted readback: redaction marker present, IBAN absent.
    rows = _common.read_jsonl(telemetry.claims_path())
    assert len(rows) == 1
    assert "GB82WEST12345698765432" not in rows[0]["message"]
    assert "[REDACTED:iban]" in rows[0]["message"]


def test_no_profile_override_under_zerotrust_leaves_iban_alone(isolated_state, in_memory_keychain, fake_repo):
    """Negative control for the e2e above: without redact.profiles, the IBAN is NOT
    redacted (it's not part of the standard set). Proves the redaction in the previous
    test came from the profile, not from incidental coverage."""
    import importlib

    (isolated_state / "settings.json").write_text(json.dumps({"preset": "zerotrust"}))
    from unlock import unlock
    unlock(ttl_seconds=60)

    importlib.reload(_common)
    import telemetry
    importlib.reload(telemetry)
    from redact import _clear_profile_cache
    _clear_profile_cache()

    telemetry.record_commit_claim(
        str(fake_repo), "abc1234567890",
        "transferred to GB82WEST12345698765432 today", intent=None,
    )
    rows = _common.read_jsonl(telemetry.claims_path())
    assert len(rows) == 1
    assert "GB82WEST12345698765432" in rows[0]["message"]


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


def test_events_drain_under_zerotrust(isolated_state, in_memory_keychain):
    """append_event under zerotrust must encrypt, drain_events must decrypt
    back to the original dict, and summarize_events must classify the events.
    Regression for the events.py / encryption gap: until v0.3.1, drain_events
    used raw json.loads on encrypted envelopes and returned opaque dicts with
    no `kind`, so summarize_events silently dropped every event.
    """
    _activate_zerotrust(isolated_state)
    from unlock import unlock
    unlock(ttl_seconds=60)
    from events import append_event, drain_events, event_path, summarize_events

    append_event({"kind": "edit", "path": "src/foo.py"})
    append_event({"kind": "bash", "cmd": "pytest -q", "exit": 0})

    # Confirm the file on disk is encrypted (sanity check on the fixture).
    raw = event_path().read_text().splitlines()
    assert all(crypto.is_encrypted_line(line) for line in raw if line.strip()), (
        "events.encrypted=true must produce encrypted-on-disk lines"
    )

    events = drain_events()
    assert len(events) == 2
    kinds = {e.get("kind") for e in events}
    assert kinds == {"edit", "bash"}, f"drain returned opaque envelopes: {events}"
    digest = summarize_events(events)
    assert "src/foo.py" in digest


def test_events_peek_under_zerotrust(isolated_state, in_memory_keychain):
    """peek_events must also see the decrypted payload (verify.* and the
    doctor read events without draining)."""
    _activate_zerotrust(isolated_state)
    from unlock import unlock
    unlock(ttl_seconds=60)
    from events import append_event, peek_events

    append_event({"kind": "edit", "path": "src/bar.py"})
    rows = peek_events()
    assert len(rows) == 1
    assert rows[0].get("kind") == "edit"
    assert rows[0].get("path") == "src/bar.py"


def test_solodev_preset_writes_plain(isolated_state, in_memory_keychain, monkeypatch):
    """Default preset (solo-dev) does NOT request encryption, so writes stay plain."""
    # No settings.json => defaults to solo-dev
    monkeypatch.setattr(_common, "_WRITE_STATE_CACHE", None)
    monkeypatch.setattr(_common, "_READ_KEY_CACHE", _common._UNSET)
    monkeypatch.setattr(_common, "_SETTINGS_CACHE", None)
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
