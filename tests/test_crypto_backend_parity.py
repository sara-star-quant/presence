"""The Rust extension and the Python fallback share one keychain entry.

Only key storage lives in Rust; the AES-GCM line format is Python-only. A key
written by one backend must still be read by the other, so the service name,
account name, attribute names and hex encoding have to agree. These tests read
ext/src/crypto.rs as text, so they run without building the extension.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import crypto  # noqa: E402

RUST = (ROOT / "ext" / "src" / "crypto.rs").read_text()


def test_rust_declares_service_and_account_per_platform():
    found = re.findall(r'const (?:SERVICE|ACCOUNT): &str', RUST)
    assert len(found) == 4  # macos + linux, two constants each


def test_every_rust_declaration_agrees_not_just_the_last():
    services = set(re.findall(r'const SERVICE: &str = "([^"]+)";', RUST))
    accounts = set(re.findall(r'const ACCOUNT: &str = "([^"]+)";', RUST))
    assert services == {crypto.KEYCHAIN_SERVICE}
    assert accounts == {crypto.KEYCHAIN_ACCOUNT}


def test_linux_attribute_names_match_secret_tool_lookup():
    # Python looks the key up with `secret-tool lookup service X account Y`.
    assert 'props.insert("service", SERVICE);' in RUST
    assert 'props.insert("account", ACCOUNT);' in RUST


def test_both_backends_store_the_key_as_hex_text():
    assert "hex::encode(key)" in RUST and "hex::decode" in RUST
    key = bytes(range(crypto.KEY_BYTES))
    assert bytes.fromhex(key.hex()) == key
    assert len(key.hex()) == crypto.KEY_BYTES * 2


def test_rust_does_not_implement_line_encryption():
    # If this fails, the format now lives in two places and needs a real
    # cross-implementation round-trip test before anything else changes.
    assert "aes_gcm" not in RUST.lower() and "aesgcm" not in RUST.lower()
