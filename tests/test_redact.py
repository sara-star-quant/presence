"""Redaction patterns. Standard catches well-known shapes; aggressive adds blob/upper-assign."""
import pytest
from redact import REDACTION, redact_command, redact_text


@pytest.mark.parametrize(
    "raw, kind",
    [
        ("AKIAIOSFODNN7EXAMPLE", "aws-access-key"),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123456789AB", "github-pat"),
        ("xoxb-12345-67890-abcdefghijklmnopqrstuvwx", "slack-token"),
        ("AIzaSyA0123456789abcdefghijklmnopqrstuv", "google-api-key"),
        ("sk_live_0123456789abcdefghijklmnopqr", "stripe-live"),
        ("Bearer abc123def456ghi789jkl", "bearer"),
    ],
)
def test_standard_known_token_shapes(raw, kind):
    out = redact_text(f"prefix {raw} suffix")
    assert REDACTION.format(kind=kind) in out
    assert raw not in out


def test_env_style_secret_assignment():
    out = redact_text("API_KEY=supersecretvalue123")
    assert "supersecretvalue123" not in out
    assert "API_KEY=" in out
    assert REDACTION.format(kind="env-secret") in out


def test_password_assignment():
    out = redact_text('PASSWORD="hunter2"')
    assert "hunter2" not in out


def test_standard_does_not_redact_random_uppercase():
    # Standard mode should NOT redact arbitrary uppercase assignments
    out = redact_text("MAX_RETRIES=5", level="standard")
    assert "MAX_RETRIES=5" in out


def test_aggressive_redacts_uppercase_assignments():
    out = redact_text("MAX_RETRIES=5", level="aggressive")
    assert "MAX_RETRIES=5" not in out


def test_aggressive_redacts_long_hex():
    h = "a" * 64  # SHA-256-shaped
    out = redact_text(f"hash: {h}", level="aggressive")
    assert h not in out
    assert REDACTION.format(kind="hex-blob") in out


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    out = redact_text(f"token={jwt}")
    assert jwt not in out


def test_empty_input():
    assert redact_text("") == ""
    assert redact_text(None) is None  # type: ignore[arg-type]


def test_redact_command_alias():
    assert redact_command("git commit -m 'TOKEN=xyzabc1234'") != "git commit -m 'TOKEN=xyzabc1234'"


def test_invalid_pattern_does_not_raise():
    # Intentional non-ASCII: we wrap a token in unicode codepoints (crab + bomb
    # emoji) to verify redact_text doesn't choke on weird inputs. Do not "fix"
    # to ASCII; that would erase what's being tested.
    weird = "🦀" + "ghp_" + "a" * 36 + "💥"
    out = redact_text(weird)
    assert "ghp_" not in out or REDACTION.format(kind="github-pat") in out
