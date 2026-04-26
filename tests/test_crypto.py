"""Crypto round-trip tests. Use random in-process keys to avoid touching the real keychain."""
from __future__ import annotations

import secrets

import crypto
import pytest


@pytest.fixture
def key():
    return secrets.token_bytes(crypto.KEY_BYTES)


def test_round_trip_basic(key):
    plaintext = b"hello world"
    encrypted = crypto.encrypt_line(plaintext, key)
    assert crypto.is_encrypted_line(encrypted)
    decrypted = crypto.decrypt_line(encrypted, key)
    assert decrypted == plaintext


def test_round_trip_unicode(key):
    plaintext = "Я с тобой 🦀 日本語".encode()
    encrypted = crypto.encrypt_line(plaintext, key)
    assert crypto.decrypt_line(encrypted, key) == plaintext


def test_each_call_uses_fresh_nonce(key):
    """Two encryptions of the same plaintext must produce different ciphertexts."""
    pt = b"identical input"
    a = crypto.encrypt_line(pt, key)
    b = crypto.encrypt_line(pt, key)
    assert a != b


def test_wrong_key_returns_none(key):
    encrypted = crypto.encrypt_line(b"secret", key)
    other_key = secrets.token_bytes(crypto.KEY_BYTES)
    assert crypto.decrypt_line(encrypted, other_key) is None


def test_corrupt_ciphertext_returns_none(key):
    encrypted = crypto.encrypt_line(b"data", key)
    # Flip a character in the middle of the ciphertext field
    corrupted = encrypted.replace('"c":"', '"c":"X')
    assert crypto.decrypt_line(corrupted, key) is None


def test_plain_line_returns_none_on_decrypt(key):
    """A plain JSON line must not crash decrypt_line; it just returns None."""
    assert crypto.decrypt_line('{"foo":"bar"}', key) is None


def test_is_encrypted_line():
    assert crypto.is_encrypted_line('{"_e":"aes-gcm-v1","n":"x","c":"y"}')
    assert not crypto.is_encrypted_line('{"foo":"bar"}')
    assert not crypto.is_encrypted_line("")
    assert not crypto.is_encrypted_line("not json at all")


def test_invalid_json_returns_none(key):
    assert crypto.decrypt_line("not even json", key) is None


def test_keychain_backend_detection_does_not_raise():
    """Whatever platform we're on, keychain_backend() returns a string or None without raising."""
    backend = crypto.keychain_backend()
    assert backend in ("macos", "linux", None)


def test_is_available_consistent_with_backend():
    """is_available() should be True iff cryptography lib is importable AND a backend exists."""
    # cryptography is a dev-dep for tests, so it's importable.
    has_backend = crypto.keychain_backend() is not None
    assert crypto.is_available() == has_backend
