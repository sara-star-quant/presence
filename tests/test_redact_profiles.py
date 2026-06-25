"""Tests for composable redaction profiles (v0.5.0).

Profiles ship under ``presets/redaction/`` and add jurisdiction-relevant
patterns on top of the standard secret redactor. Tests cover:

- positive: each pattern catches a realistic-but-fake fixture
- negative: nearby look-alikes (timestamps, IDs) are NOT caught
- composition: multiple profiles run together
- backward compat: redact_text without profiles= behaves unchanged
- Luhn validator: gates PAN matches; non-Luhn 16-digit strings pass through
- load failures: malformed JSON, unknown validator, bad regex - profile is
  empty/partial, redaction continues with the standard set
"""
from __future__ import annotations

import json
import re

import pytest
from redact import (
    REDACTION,
    SCHEMA_VERSION,
    _check_luhn,
    _clear_profile_cache,
    _load_profile,
    list_available_profiles,
    redact_text,
)


@pytest.fixture(autouse=True)
def _reset_profile_cache():
    _clear_profile_cache()
    yield
    _clear_profile_cache()


# ---------- pii-eu ----------

def test_pii_eu_iban_redacted():
    out = redact_text("Wire to GB82WEST12345698765432 today", profiles=["pii-eu"])
    assert "GB82WEST12345698765432" not in out
    assert REDACTION.format(kind="iban") in out


def test_pii_eu_iban_short_does_not_match():
    # A bank-account-shaped string too short for ISO 13616 BBAN must not match.
    out = redact_text("ref AB12CD3", profiles=["pii-eu"])
    assert out == "ref AB12CD3"


def test_pii_eu_bsn_requires_prefix():
    # Bare 9-digit number must not match without the BSN prefix.
    out = redact_text("count: 123456789 widgets", profiles=["pii-eu"])
    assert "123456789" in out
    # With prefix, redacted.
    out2 = redact_text("BSN: 123456789", profiles=["pii-eu"])
    assert "123456789" not in out2
    assert REDACTION.format(kind="nl-bsn") in out2


def test_pii_eu_codice_fiscale():
    out = redact_text("CF: RSSMRA85M01H501Z", profiles=["pii-eu"])
    assert "RSSMRA85M01H501Z" not in out
    assert REDACTION.format(kind="it-codice-fiscale") in out


def test_pii_eu_insee_requires_prefix():
    # Bare 13-digit number must not match.
    out = redact_text("epoch 1234567890123 ms", profiles=["pii-eu"])
    assert "1234567890123" in out
    # With prefix, redacted.
    out2 = redact_text("INSEE: 1850578006048", profiles=["pii-eu"])
    assert "1850578006048" not in out2


# ---------- pii-us ----------

def test_pii_us_ssn_with_hyphens():
    out = redact_text("SSN 123-45-6789 on file", profiles=["pii-us"])
    assert "123-45-6789" not in out
    assert REDACTION.format(kind="us-ssn") in out


def test_pii_us_ssn_without_hyphens_not_matched():
    # Hyphenless 9-digit number is intentionally NOT matched by us-ssn pattern.
    out = redact_text("ref 123456789", profiles=["pii-us"])
    assert "123456789" in out


def test_pii_us_ein_requires_prefix():
    out_no = redact_text("call 12-3456789 if needed", profiles=["pii-us"])
    assert "12-3456789" in out_no
    out_yes = redact_text("EIN 12-3456789 on the W9", profiles=["pii-us"])
    assert "12-3456789" not in out_yes


def test_pii_us_routing_requires_prefix():
    out_no = redact_text("counter at 123456789 events", profiles=["pii-us"])
    assert "123456789" in out_no
    out_yes = redact_text("routing: 021000021 amt 100", profiles=["pii-us"])
    assert "021000021" not in out_yes


# ---------- pci-dss + Luhn ----------

def test_pci_dss_luhn_valid_pan_redacted():
    # 4111-1111-1111-1111 is a well-known PCI test number (passes Luhn).
    out = redact_text("paid with 4111-1111-1111-1111 ok", profiles=["pci-dss"])
    assert "4111-1111-1111-1111" not in out
    assert REDACTION.format(kind="pan") in out


def test_pci_dss_luhn_invalid_pan_passes_through():
    # Random 16-digit number that fails Luhn must be left alone.
    fake = "1234567890123456"  # Luhn-fail
    out = redact_text(f"order id {fake} thanks", profiles=["pci-dss"])
    assert fake in out


def test_pci_dss_pan_with_spaces():
    # PCI test card with space separators (still passes Luhn after digit-only normalization).
    out = redact_text("card 4111 1111 1111 1111 entered", profiles=["pci-dss"])
    assert "4111 1111 1111 1111" not in out
    assert REDACTION.format(kind="pan") in out


def test_check_luhn_unit():
    # Known-valid PCI test numbers from the PCI DSS test card list.
    assert _check_luhn("4111111111111111")
    assert _check_luhn("5555555555554444")
    assert _check_luhn("378282246310005")  # 15-digit Amex
    # Random rejects.
    assert not _check_luhn("1234567890123456")
    assert not _check_luhn("0000")  # too short
    assert not _check_luhn("12345678901234567890")  # too long


# ---------- composition ----------

def test_composition_runs_all_profiles():
    text = "card 4111-1111-1111-1111 IBAN GB82WEST12345698765432 SSN 123-45-6789"
    out = redact_text(text, profiles=["pii-eu", "pii-us", "pci-dss"])
    assert "4111-1111-1111-1111" not in out
    assert "GB82WEST12345698765432" not in out
    assert "123-45-6789" not in out


def test_composition_order_does_not_lose_matches():
    # Same content, profiles in reversed order - should still redact all three.
    text = "card 4111-1111-1111-1111 IBAN GB82WEST12345698765432 SSN 123-45-6789"
    out = redact_text(text, profiles=["pci-dss", "pii-us", "pii-eu"])
    assert "4111-1111-1111-1111" not in out
    assert "GB82WEST12345698765432" not in out
    assert "123-45-6789" not in out


# ---------- backward compat ----------

def test_no_profiles_kwarg_matches_v04x_behavior():
    # Without profiles, the standard set still runs but profile-only patterns don't.
    text = "IBAN GB82WEST12345698765432 and AKIA" + "IOSFODNN7EXAMPLE"
    out_no_profiles = redact_text(text)
    out_explicit_none = redact_text(text, profiles=None)
    out_empty_list = redact_text(text, profiles=[])
    assert out_no_profiles == out_explicit_none == out_empty_list
    # The IBAN passes through (no profile loaded), the AWS key is redacted.
    assert "GB82WEST12345698765432" in out_no_profiles
    assert "AKIA" + "IOSFODNN7EXAMPLE" not in out_no_profiles


def test_profile_name_typo_does_not_break_redaction():
    # Unknown profile -> not_found, redaction continues with standard set.
    text = "AKIA" + "IOSFODNN7EXAMPLE"
    out = redact_text(text, profiles=["nonexistent-profile"])
    assert "AKIA" + "IOSFODNN7EXAMPLE" not in out  # standard pattern still ran
    r = _load_profile("nonexistent-profile")
    assert r.status == "not_found"
    assert r.patterns == []


# ---------- load failure modes ----------

def test_malformed_json_profile(tmp_path, monkeypatch):
    # Plant a malformed user-override profile and check that load reports parse_error.
    user_dir = tmp_path / "presets" / "redaction"
    user_dir.mkdir(parents=True)
    (user_dir / "broken.json").write_text("{ this is: not valid json", encoding="utf-8")

    import _common
    monkeypatch.setattr(_common, "state_dir", lambda: tmp_path)
    _clear_profile_cache()

    r = _load_profile("broken")
    assert r.status == "parse_error"
    assert r.patterns == []
    # Standard redaction still runs.
    out = redact_text("AKIA" + "IOSFODNN7EXAMPLE", profiles=["broken"])
    assert "AKIA" + "IOSFODNN7EXAMPLE" not in out


def test_unknown_validator_load_status(tmp_path, monkeypatch):
    user_dir = tmp_path / "presets" / "redaction"
    user_dir.mkdir(parents=True)
    profile = {
        "_schema_version": 1,
        "_description": "test",
        "_disclaimer": "test",
        "_last_reviewed": "2026-04-27",
        "patterns": [
            {"name": "x", "pattern": r"\bXYZ\d+\b", "kind": "x",
             "validator": "nonexistent-validator"},
        ],
    }
    (user_dir / "bad-val.json").write_text(json.dumps(profile), encoding="utf-8")

    import _common
    monkeypatch.setattr(_common, "state_dir", lambda: tmp_path)
    _clear_profile_cache()

    r = _load_profile("bad-val")
    assert r.status == "unknown_validator"
    # No patterns were loadable since the only one had a bad validator.
    assert r.patterns == []
    # Redaction still runs the standard set.
    out = redact_text("AKIA" + "IOSFODNN7EXAMPLE", profiles=["bad-val"])
    assert "AKIA" + "IOSFODNN7EXAMPLE" not in out


def test_bad_regex_load_status(tmp_path, monkeypatch):
    user_dir = tmp_path / "presets" / "redaction"
    user_dir.mkdir(parents=True)
    profile = {
        "_schema_version": 1,
        "_description": "test",
        "_disclaimer": "test",
        "_last_reviewed": "2026-04-27",
        "patterns": [
            {"name": "broken", "pattern": "[unclosed", "kind": "broken"},
        ],
    }
    (user_dir / "bad-regex.json").write_text(json.dumps(profile), encoding="utf-8")

    import _common
    monkeypatch.setattr(_common, "state_dir", lambda: tmp_path)
    _clear_profile_cache()

    r = _load_profile("bad-regex")
    assert r.status == "compile_error"
    assert r.patterns == []


def test_partial_load_keeps_good_patterns(tmp_path, monkeypatch):
    user_dir = tmp_path / "presets" / "redaction"
    user_dir.mkdir(parents=True)
    profile = {
        "_schema_version": 1,
        "_description": "test",
        "_disclaimer": "test",
        "_last_reviewed": "2026-04-27",
        "patterns": [
            {"name": "good", "pattern": r"\bSECRETXYZ123\b", "kind": "good"},
            {"name": "bad", "pattern": "[unclosed", "kind": "bad"},
        ],
    }
    (user_dir / "mixed.json").write_text(json.dumps(profile), encoding="utf-8")

    import _common
    monkeypatch.setattr(_common, "state_dir", lambda: tmp_path)
    _clear_profile_cache()

    r = _load_profile("mixed")
    assert r.status == "partial"
    assert len(r.patterns) == 1
    assert r.patterns[0].kind == "good"
    out = redact_text("token SECRETXYZ123 here", profiles=["mixed"])
    assert "SECRETXYZ123" not in out


def test_user_override_shadows_builtin(tmp_path, monkeypatch):
    # User-authored pii-eu.json must shadow the built-in.
    user_dir = tmp_path / "presets" / "redaction"
    user_dir.mkdir(parents=True)
    sentinel_kind = "user-override-iban-marker"
    profile = {
        "_schema_version": 1,
        "_description": "user override",
        "_disclaimer": "user override",
        "_last_reviewed": "2026-04-27",
        "patterns": [
            {"name": "marker", "pattern": r"\bMARKER123\b", "kind": sentinel_kind},
        ],
    }
    (user_dir / "pii-eu.json").write_text(json.dumps(profile), encoding="utf-8")

    import _common
    monkeypatch.setattr(_common, "state_dir", lambda: tmp_path)
    _clear_profile_cache()

    r = _load_profile("pii-eu")
    assert r.source_path is not None
    assert "presets/redaction/pii-eu.json" in str(r.source_path)
    assert str(tmp_path) in str(r.source_path)
    assert any(p.kind == sentinel_kind for p in r.patterns)


# ---------- list_available_profiles ----------

def test_list_available_profiles_includes_builtins():
    profiles = list_available_profiles()
    names = [n for n, _ in profiles]
    assert "pii-eu" in names
    assert "pii-us" in names
    assert "pci-dss" in names


# ---------- forward-compat schema ----------

def test_future_schema_version_loads_in_compat_mode(tmp_path, monkeypatch):
    user_dir = tmp_path / "presets" / "redaction"
    user_dir.mkdir(parents=True)
    profile = {
        "_schema_version": SCHEMA_VERSION + 99,
        "_description": "future",
        "_disclaimer": "future",
        "_last_reviewed": "2099-01-01",
        "_unknown_future_key": {"deeply": "nested"},
        "patterns": [
            {"name": "f", "pattern": r"\bFUTUREMARKER\b", "kind": "future-marker"},
        ],
    }
    (user_dir / "future.json").write_text(json.dumps(profile), encoding="utf-8")

    import _common
    monkeypatch.setattr(_common, "state_dir", lambda: tmp_path)
    _clear_profile_cache()

    r = _load_profile("future")
    # Patterns still load; status reports compat-mode warning via error field.
    assert r.status == "ok"
    assert r.error is not None and "compatibility mode" in r.error
    assert any(p.kind == "future-marker" for p in r.patterns)


# ---------- shipped profiles validate ----------

@pytest.mark.parametrize("name", ["pii-eu", "pii-us", "pci-dss"])
def test_shipped_profiles_load_clean(name):
    r = _load_profile(name)
    assert r.status == "ok", f"{name}: {r.error}"
    assert r.patterns, f"{name}: no patterns loaded"
    assert r.disclaimer, f"{name}: missing _disclaimer"
    assert r.last_reviewed, f"{name}: missing _last_reviewed"
    # Each pattern must have a non-empty kind and a compiled regex.
    for pp in r.patterns:
        assert pp.kind
        assert isinstance(pp.pattern, re.Pattern)


# ---------- CLI surface (python lib/redact.py ...) ----------

def test_cli_list_profiles_lists_builtins(capsys):
    import redact

    assert redact._cli(["--list-profiles"]) == 0
    out = capsys.readouterr().out
    for name in ("pci-dss", "pii-eu", "pii-us"):
        assert name in out


def test_cli_show_profile_ok(capsys):
    import redact

    assert redact._cli(["--show-profile", "pci-dss"]) == 0
    out = capsys.readouterr().out
    assert "patterns" in out and "schema_version" in out


def test_cli_show_profile_not_found_returns_2(capsys):
    import redact

    assert redact._cli(["--show-profile", "does-not-exist"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_test_profile_stdin_redacts(monkeypatch, capsys):
    import io

    import redact

    # A Luhn-valid PAN must be redacted by the pci-dss profile.
    monkeypatch.setattr("sys.stdin", io.StringIO("card 4111111111111111 here"))
    assert redact._cli(["--test-profile", "pci-dss", "--stdin"]) == 0
    out = capsys.readouterr().out
    assert "4111111111111111" not in out
    assert "[REDACTED:" in out


def test_cli_test_profile_input_file(tmp_path, capsys):
    import redact

    f = tmp_path / "in.txt"
    f.write_text("card 4111111111111111 here")
    assert redact._cli(["--test-profile", "pci-dss", "--input", str(f)]) == 0
    assert "4111111111111111" not in capsys.readouterr().out


def test_cli_test_profile_requires_input_source(capsys):
    import redact

    assert redact._cli(["--test-profile", "pci-dss"]) == 2
    assert "requires --input" in capsys.readouterr().err


def test_redact_iter_redacts_each_item():
    from redact import redact_iter

    out = redact_iter(["AKIAIOSFODNN7EXAMPLE", "nothing secret"])
    assert "AKIAIOSFODNN7EXAMPLE" not in out[0]
    assert out[1] == "nothing secret"
