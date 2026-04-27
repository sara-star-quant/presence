"""Commit SHA parsing and revert detection."""
import pytest
from telemetry import parse_commit_sha_from_stdout


@pytest.mark.parametrize(
    "stdout, expected",
    [
        ("[main a1b2c3d4] fix the thing\n 1 file changed", "a1b2c3d4"),
        ("[feature/foo abc1234] msg", "abc1234"),
        ("[main (root-commit) deadbee] init", "deadbee"),
        ("nothing here", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_commit_sha_from_stdout(stdout, expected):
    assert parse_commit_sha_from_stdout(stdout) == expected


def test_record_and_read_claim(isolated_state, fake_repo):
    from _common import read_jsonl
    from telemetry import claims_path, record_commit_claim
    record_commit_claim(str(fake_repo), "abc1234567890123", "fix the thing", intent="git commit -m fix")
    rows = read_jsonl(claims_path())
    assert len(rows) == 1
    assert rows[0]["sha"].startswith("abc")


def test_secret_in_commit_message_redacted(isolated_state, fake_repo):
    from _common import read_jsonl
    from telemetry import claims_path, record_commit_claim
    record_commit_claim(
        str(fake_repo), "abc1234567890", "set TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789AB", intent=None,
    )
    rows = read_jsonl(claims_path())
    assert "ghp_" not in rows[0]["message"]


def test_redact_profiles_threaded_to_commit_claim(isolated_state, fake_repo, monkeypatch):
    """Settings-configured redact.profiles must reach redact_command in record_commit_claim."""
    import importlib
    import json as _json

    # Plant a settings.json that opts into pii-eu via overrides.
    (isolated_state / "settings.json").write_text(
        _json.dumps({"preset": "solo-dev", "overrides": {"redact": {"profiles": ["pii-eu"]}}}),
        encoding="utf-8",
    )
    # Reload _common so the settings cache picks up the new file.
    import _common
    importlib.reload(_common)
    import telemetry
    importlib.reload(telemetry)

    telemetry.record_commit_claim(
        str(fake_repo), "abc1234567890",
        "transferred to GB82WEST12345698765432 today", intent=None,
    )
    rows = _common.read_jsonl(telemetry.claims_path())
    assert "GB82WEST12345698765432" not in rows[0]["message"]
    assert "[REDACTED:iban]" in rows[0]["message"]


def test_redact_profiles_helper_reads_settings(isolated_state, monkeypatch):
    import importlib
    import json as _json
    (isolated_state / "settings.json").write_text(
        _json.dumps({"preset": "solo-dev", "overrides": {"redact": {"profiles": ["pii-eu", "pci-dss"]}}}),
        encoding="utf-8",
    )
    import _common
    importlib.reload(_common)
    import telemetry
    importlib.reload(telemetry)
    assert telemetry._redact_profiles() == ["pii-eu", "pci-dss"]


def test_redact_profiles_helper_default_empty(isolated_state):
    import telemetry
    # No settings.json planted -> defaults -> empty list.
    assert telemetry._redact_profiles() == []
