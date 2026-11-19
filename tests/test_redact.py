"""Redaction patterns. Standard catches well-known shapes; aggressive adds blob/upper-assign.

Note on test fixtures: the patterns below construct tokens at runtime from harmless
fragments rather than embedding the literal token shape in source. This avoids
GitHub's secret-scanner false-positiving on documented test data (Google API keys,
Stripe keys, GitHub PATs, etc.) while still exercising the redactor's regex.
"""
import pytest
from redact import REDACTION, redact_command, redact_text

# Construct fixture tokens at runtime so the literal patterns never appear in source.
# Each value still matches the corresponding regex in lib/redact.py.
_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
_GH_PAT = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789AB"
_SLACK = "xoxb" + "-12345-67890-abcdefghijklmnopqrstuvwx"
_GOOGLE = "AIza" + "SyA0123456789abcdefghijklmnopqrstuv"
_STRIPE = "sk_" + "live_" + "0123456789abcdefghijklmnopqr"
_BEARER = "Bearer " + "abc123def456ghi789jkl"


@pytest.mark.parametrize(
    "raw, kind",
    [
        (_AWS, "aws-access-key"),
        (_GH_PAT, "github-pat"),
        (_SLACK, "slack-token"),
        (_GOOGLE, "google-api-key"),
        (_STRIPE, "stripe-live"),
        (_BEARER, "bearer"),
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
    # Same runtime-construction trick: don't embed a literal JWT in source.
    jwt = "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NSJ9." + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
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


# --- shapes a command line carries that no token prefix gives away -----------------------------
# Values are runtime-joined so the literal assignments never sit in source for a secret scanner.

@pytest.mark.parametrize(
    "raw, secret",
    [
        ("export " + "SECRET_" + "KEY=abc123def456", "abc123def456"),
        ("DJANGO_" + "SECRET_" + "KEY=abc123def456 ./manage.py", "abc123def456"),
        ("DB_" + "PASS=hunter2hunter2 psql", "hunter2hunter2"),
        ("PASS" + "PHRASE=correcthorse", "correcthorse"),
        ("CLIENT_" + "SECRET=zzz999yyy", "zzz999yyy"),
        ("curl --to" + "ken abcdef123456 https://x.example", "abcdef123456"),
        ("tool --pass" + "word hunter2hunter2 --verbose", "hunter2hunter2"),
        ("deploy --api-" + "key k9k9k9k9 now", "k9k9k9k9"),
        ("run --sec" + "ret s3cr3tvalue", "s3cr3tvalue"),
        ("git clone https://user:" + "pw12345@host.example/r.git", "pw12345"),
        ("psql postgres://app:" + "Sup3rS3cret@db.example:5432/x", "Sup3rS3cret"),
        ("mysql -u root -p" + "hunter2hunter2 db", "hunter2hunter2"),
        ("ssh" + "pass -p hunter2hunter2 ssh h", "hunter2hunter2"),
    ],
)
def test_secrets_in_command_shapes_are_redacted(raw, secret):
    out = redact_command(raw)
    assert secret not in out, out


@pytest.mark.parametrize(
    "raw",
    [
        "mkdir -p /tmp/x",
        "mkdir -pv /tmp/x",
        "ls -pl",
        "ls -p",
        "git -p log",
        "BYPASS_CACHE=1 make",
        "compass=north",
        "passenger=3",
        "tool --token-count 5",
        "tool --password-file /etc/pw",
        "tool --secret-name prod",
        "git clone https://github.com/a/b.git",
        "scp user@host:path .",
        "mysql -u root db",
        "tool --api-key",
        "tool --password --verbose",
    ],
)
def test_ordinary_commands_are_left_alone(raw):
    assert redact_command(raw) == raw


def test_the_flag_and_the_scheme_stay_readable():
    out = redact_command("deploy --pass" + "word hunter2hunter2 --verbose")
    assert "--password" in out and "--verbose" in out
    url = redact_command("git clone https://user:" + "pw12345@host.example/r.git")
    assert url.startswith("git clone https://user:") and url.endswith("@host.example/r.git")


@pytest.mark.parametrize(
    "hostile",
    ["mysql " * 40_000, "a-" * 100_000, "--password " * 20_000, "x://" * 50_000, "http://u:" * 30_000, "sshpass -p " * 20_000],
)
def test_the_new_patterns_stay_fast_on_hostile_text(hostile):
    import time
    start = time.monotonic()
    redact_command(hostile)
    assert time.monotonic() - start < 1.0
