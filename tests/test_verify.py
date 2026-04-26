"""Confidence-gate logic: claim parsing + command classification."""
import pytest
from verify import classify_command, has_unhedged_success_claim


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Fixed the bug.", True),
        ("It works now.", True),
        ("Done. Passing all tests.", True),
        ("Probably works.", False),
        ("I think this is done.", False),
        ("This should fix it.", False),
        ("Untested but should work.", False),
        ("Made the change. Needs testing.", False),
        ("", False),
        ("Refactored the auth flow.", False),
    ],
)
def test_has_unhedged_success_claim(text, expected):
    assert has_unhedged_success_claim(text) is expected


@pytest.mark.parametrize(
    "cmd, exit_code, expected",
    [
        ("pytest tests/", 0, "test_pass"),
        ("pytest tests/", 1, "test_fail"),
        ("npm test", 0, "test_pass"),
        ("npm run build", 0, "build_pass"),
        ("npm run build", 2, "build_fail"),
        ("cargo test", 0, "test_pass"),
        ("tsc --noEmit", 0, "build_pass"),
        ("ls -la", 0, None),
        ("git status", 0, None),
        ("npx jest", 0, "test_pass"),
        # Unparseable exit code -> refuse to classify (safe default)
        ("pytest", "weird", None),
        ("pytest", None, None),
    ],
)
def test_classify_command(cmd, exit_code, expected):
    assert classify_command(cmd, exit_code) == expected


def test_classify_empty_command():
    assert classify_command("", 0) is None
    assert classify_command(None, 0) is None
