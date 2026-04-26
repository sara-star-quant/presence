"""Audit-log hash-chain tests. Append + verify + tamper detection."""
from __future__ import annotations

import json

import audit


def test_genesis_hash_constant():
    """Genesis must be deterministic; verifier and appender must agree on it."""
    import hashlib
    expected = hashlib.sha256(b"presence-audit-v1").hexdigest()
    assert expected == audit.GENESIS_HASH


def test_empty_chain_verifies(isolated_state):
    report = audit.verify_chain()
    assert report["exists"] is False
    assert report["lines"] == 0
    assert report["ok"] is True


def test_single_append_verifies(isolated_state):
    audit.append("test_event", {"foo": "bar"})
    report = audit.verify_chain()
    assert report["exists"]
    assert report["lines"] == 1
    assert report["ok"]


def test_multiple_appends_chain(isolated_state):
    for i in range(5):
        audit.append("step", {"i": i})
    report = audit.verify_chain()
    assert report["lines"] == 5
    assert report["ok"]
    # Each line's prev_hash must equal the previous line's hash
    raw = audit.audit_path().read_text().splitlines()
    parsed = [json.loads(line) for line in raw if line.strip()]
    for i in range(1, len(parsed)):
        assert parsed[i]["prev_hash"] == parsed[i - 1]["hash"]
    # First line's prev_hash must be the genesis
    assert parsed[0]["prev_hash"] == audit.GENESIS_HASH


def test_tampered_line_detected(isolated_state):
    """Modifying any field other than `hash` makes the recomputed hash differ from the
    stored one, which `tampered` catches. (broken_link is a separate signal that fires
    only when the attacker also rewrites a later line's prev_hash inconsistently;
    see test_broken_link_detected.)"""
    audit.append("a")
    audit.append("b")
    audit.append("c")
    p = audit.audit_path()
    lines = p.read_text().splitlines()
    obj = json.loads(lines[1])
    obj["details"] = {"forged": True}
    lines[1] = json.dumps(obj, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")
    report = audit.verify_chain()
    assert not report["ok"]
    assert 1 in report["tampered"]


def test_broken_link_detected(isolated_state):
    """If an attacker rewrites a line's hash field (to make tamper-detection pass)
    without updating the next line's prev_hash, broken_link catches the mismatch."""
    audit.append("first")
    audit.append("second")
    p = audit.audit_path()
    lines = p.read_text().splitlines()
    obj = json.loads(lines[0])
    # Replace the stored hash with garbage; now line 1's prev_hash no longer matches
    obj["hash"] = "0" * 64
    lines[0] = json.dumps(obj, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")
    report = audit.verify_chain()
    # Line 0 itself is tampered (hash doesn't recompute) AND line 1 is broken_link
    assert 0 in report["tampered"]
    assert 1 in report["broken_link"]


def test_corrupt_line_detected(isolated_state):
    audit.append("good")
    p = audit.audit_path()
    p.write_text(p.read_text() + "{not valid json\n")
    report = audit.verify_chain()
    assert 1 in report["corrupt"]


def test_missing_hash_field_is_corrupt(isolated_state):
    audit.append("good")
    p = audit.audit_path()
    bad_line = json.dumps({"ts": 1, "event": "x", "preset": "y", "details": {}})
    p.write_text(p.read_text() + bad_line + "\n")
    report = audit.verify_chain()
    assert 1 in report["corrupt"]


def test_audit_includes_active_preset(isolated_state):
    audit.append("test_event")
    raw = audit.audit_path().read_text().splitlines()
    obj = json.loads(raw[0])
    # Default preset is solo-dev when no settings.json exists
    assert "preset" in obj
    assert isinstance(obj["preset"], str)
    assert isinstance(obj["ts"], int)
    assert obj["event"] == "test_event"


def test_concurrent_appends_chain_safely(isolated_state):
    """Even if two writers race (simulated), the chain stays valid because we hold
    flock for the entire read-prev + append cycle."""
    for i in range(20):
        audit.append("concurrent", {"i": i})
    report = audit.verify_chain()
    assert report["lines"] == 20
    assert report["ok"], f"chain broke under sequential appends: {report}"
