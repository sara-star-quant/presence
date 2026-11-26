"""Model text is redacted before it is written, under every preset: the project model is the one store whose
content Claude chooses, so a pasted token must not reach disk."""
from __future__ import annotations

import json

import pytest

AWS = "AKIA" + "IOSFODNN7EXAMPLE"
GH = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789AB"


@pytest.fixture
def model(isolated_state, fake_repo):
    import importlib

    import _common
    import model as m

    def load(settings=None):
        if settings is not None:
            (isolated_state / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        importlib.reload(_common)
        return importlib.reload(m)
    load.repo = fake_repo
    return load


@pytest.mark.parametrize(
    ("note", "secret"),
    [
        (f"deploy key is {AWS} for staging", AWS),
        (f"token {GH} was used by the importer", GH),
        ("config sets " + "SECRET_" + "KEY=abc123def456 in the env file", "abc123def456"),
        ("db at https://app:" + "Sup3rS3cret@db.example/x", "Sup3rS3cret"),
        ("run it with --pass" + "word hunter2hunter2 --verbose", "hunter2hunter2"),
    ],
)
def test_a_secret_in_an_observation_never_reaches_the_file(model, note, secret):
    m = model()
    m.append_observation(note, model.repo)
    text = m.model_path(model.repo).read_text(encoding="utf-8")
    assert secret not in text and "[REDACTED:" in text


def test_ordinary_notes_are_written_as_they_are(model):
    m = model()
    note = "The parser lives in lib/cmdparse.py. Run pytest -q before committing; the gate reads the tree."
    m.append_observation(note, model.repo)
    assert note in m.model_path(model.repo).read_text(encoding="utf-8")


def test_the_entry_keeps_its_heading_and_the_header_survives(model):
    m = model()
    m.append_observation("note with " + AWS, model.repo)
    text = m.model_path(model.repo).read_text(encoding="utf-8")
    assert text.startswith("# Project model") and "\n## 20" in text


def test_zerotrust_uses_the_aggressive_level(model, monkeypatch):
    import crypto
    key = b"k" * 32  # zerotrust encrypts the model, so give it a key; the check is on the text after decryption
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(crypto, "get_or_create_key", lambda: key)
    monkeypatch.setattr(crypto, "_backend_ops", lambda: ((lambda: key), None, None))
    m = model({"preset": "zerotrust"})
    blob = "a" * 64
    m.append_observation(f"checksum {blob} noted", model.repo)
    assert "checksum" in m.read_model(model.repo) and blob not in m.read_model(model.repo)


def test_the_standard_level_leaves_a_long_hex_word_alone(model):
    m = model({"preset": "solo-dev"})
    blob = "a" * 64
    m.append_observation(f"checksum {blob} noted", model.repo)
    assert blob in m.model_path(model.repo).read_text(encoding="utf-8")


def test_redaction_can_be_switched_off_by_the_preset(model):
    m = model({"preset": "solo-dev", "overrides": {"redact.enabled": False}})
    m.append_observation("key " + AWS, model.repo)
    assert AWS in m.model_path(model.repo).read_text(encoding="utf-8")


def test_the_preset_s_redaction_profiles_apply_to_the_model_too(model):
    iban = "DE89" + "370400440532013000"
    m = model({"preset": "solo-dev", "overrides": {"redact.profiles": ["pii-eu"]}})
    m.append_observation(f"pay {iban} now", model.repo)
    assert iban not in m.model_path(model.repo).read_text(encoding="utf-8")
    m2 = model({"preset": "solo-dev"})
    m2.append_observation(f"again {iban}", model.repo)
    assert iban in m2.model_path(model.repo).read_text(encoding="utf-8")  # no profile, no pattern


def test_the_loaded_model_never_shows_the_secret_either(model):
    m = model()
    m.append_observation("x " + GH, model.repo)
    assert GH not in m.read_model(model.repo)
