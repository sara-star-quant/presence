"""Living project model: header init, append, max-chars truncation."""
from model import append_observation, read_model


def test_first_append_creates_header(isolated_state, fake_repo):
    append_observation("First note", str(fake_repo))
    text = read_model(str(fake_repo))
    assert "Project model" in text
    assert "First note" in text


def test_multiple_appends_accumulate(isolated_state, fake_repo):
    append_observation("alpha", str(fake_repo))
    append_observation("beta", str(fake_repo))
    text = read_model(str(fake_repo))
    assert "alpha" in text
    assert "beta" in text


def test_max_chars_truncates_with_marker(isolated_state, fake_repo):
    for i in range(50):
        append_observation(f"entry number {i} " + "x" * 200, str(fake_repo))
    text = read_model(str(fake_repo), max_chars=2000)
    assert len(text) < 2200  # max_chars + small overhead
    assert "elided" in text or "Project model" in text


def test_unicode_in_observation(isolated_state, fake_repo):
    # Intentional non-ASCII content: this test verifies that append_observation
    # round-trips Cyrillic, Japanese, and emoji through utf-8 file I/O without
    # mangling. Do not "fix" this to ASCII; that would erase what's being tested.
    append_observation("проверка 日本語 🦀", str(fake_repo))
    text = read_model(str(fake_repo))
    assert "проверка" in text
    assert "🦀" in text
