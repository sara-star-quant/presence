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
