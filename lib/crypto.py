"""AES-GCM encryption for state files at rest. Optional dep: ``cryptography``.

Used by the zerotrust preset to encrypt JSONL state. Per-line encryption with fresh
random 12-byte nonces; the 32-byte data key is stored in the OS keychain (macOS via
``security``, Linux via ``secret-tool``). On any failure (missing dep, missing
keychain tool, key not retrievable), the storage layer silently falls back to plain
text and ``warnings_log.warn`` records the degradation so ``/presence-doctor``
surfaces it.

Encrypted line format (JSON, one per file line, ASCII only):

    {"_e":"aes-gcm-v1","n":"<b64 nonce>","c":"<b64 ciphertext+tag>"}

Files are NOT renamed when encrypted. The reader detects per-line whether each line
is encrypted or plain and routes accordingly. Mixed files (after a preset switch
that didn't migrate) read fine.
"""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
from base64 import b64decode, b64encode

KEYCHAIN_SERVICE = "presence"
KEYCHAIN_ACCOUNT = "presence-data-key"
NONCE_BYTES = 12
KEY_BYTES = 32
FORMAT_MARKER = "aes-gcm-v1"


def _crypto_lib():
    """Return the AESGCM class if cryptography is importable; None otherwise."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError:
        return None


def _has_executable(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


def keychain_backend() -> str | None:
    """Which keychain backend is available on this platform; None if none."""
    if sys.platform == "darwin" and _has_executable("security"):
        return "macos"
    if sys.platform.startswith("linux") and _has_executable("secret-tool"):
        return "linux"
    return None


def is_available() -> bool:
    """True iff cryptography is importable AND a keychain backend is present."""
    return _crypto_lib() is not None and keychain_backend() is not None


# ---------------------------------------------------------------------------
# Keychain ops (per-platform)
# ---------------------------------------------------------------------------

def _macos_get_key() -> bytes | None:
    try:
        result = subprocess.run(  # noqa: PLW1510  we check returncode ourselves
            ["security", "find-generic-password",
             "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        return bytes.fromhex(result.stdout.strip())
    except ValueError:
        return None


def _macos_set_key(key: bytes) -> bool:
    # Delete any existing entry first; security add-generic-password is not idempotent
    subprocess.run(  # noqa: PLW1510  best-effort cleanup; ignore returncode
        ["security", "delete-generic-password",
         "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE],
        capture_output=True, timeout=5,
    )
    try:
        result = subprocess.run(  # noqa: PLW1510  we check returncode ourselves
            ["security", "add-generic-password",
             "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE,
             "-w", key.hex(),
             "-D", "presence-data-key",
             "-j", "presence: AES-GCM data key for at-rest encryption"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return result.returncode == 0


def _macos_delete_key() -> bool:
    try:
        subprocess.run(  # noqa: PLW1510  best-effort cleanup; ignore returncode
            ["security", "delete-generic-password",
             "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE],
            capture_output=True, timeout=5,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _linux_get_key() -> bytes | None:
    try:
        result = subprocess.run(  # noqa: PLW1510  we check returncode ourselves
            ["secret-tool", "lookup",
             "service", KEYCHAIN_SERVICE, "account", KEYCHAIN_ACCOUNT],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        return bytes.fromhex(result.stdout.strip())
    except ValueError:
        return None


def _linux_set_key(key: bytes) -> bool:
    try:
        result = subprocess.run(  # noqa: PLW1510  we check returncode ourselves
            ["secret-tool", "store", "--label=presence data key",
             "service", KEYCHAIN_SERVICE, "account", KEYCHAIN_ACCOUNT],
            input=key.hex(), capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return result.returncode == 0


def _linux_delete_key() -> bool:
    try:
        subprocess.run(  # noqa: PLW1510  best-effort cleanup; ignore returncode
            ["secret-tool", "clear",
             "service", KEYCHAIN_SERVICE, "account", KEYCHAIN_ACCOUNT],
            capture_output=True, timeout=5,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _backend_ops():
    backend = keychain_backend()
    if backend == "macos":
        return _macos_get_key, _macos_set_key, _macos_delete_key
    if backend == "linux":
        return _linux_get_key, _linux_set_key, _linux_delete_key
    return None, None, None


# ---------------------------------------------------------------------------
# Public key ops
# ---------------------------------------------------------------------------

def get_or_create_key() -> bytes | None:
    """Get the data key, creating a new random one if none exists. None on failure."""
    if not is_available():
        return None
    get, set_, _del = _backend_ops()
    existing = get()
    if existing and len(existing) == KEY_BYTES:
        return existing
    new_key = secrets.token_bytes(KEY_BYTES)
    if not set_(new_key):
        return None
    return new_key


def rotate_key() -> bytes | None:
    """Force-rotate the data key. Existing ciphertext becomes unreadable; caller is
    responsible for re-encrypting (or wiping) any existing state files."""
    if not is_available():
        return None
    _get, set_, _del = _backend_ops()
    new_key = secrets.token_bytes(KEY_BYTES)
    if not set_(new_key):
        return None
    return new_key


def delete_key() -> bool:
    """Remove the data key from the keychain. Returns True on success or no-op."""
    _get, _set, del_ = _backend_ops()
    if del_ is None:
        return False
    return del_()


# ---------------------------------------------------------------------------
# Per-line encrypt / decrypt
# ---------------------------------------------------------------------------

def encrypt_line(plaintext: bytes, key: bytes) -> str:
    """Encrypt a single record. Returns the JSON line (no trailing newline)."""
    AESGCM = _crypto_lib()
    if AESGCM is None:
        raise RuntimeError("cryptography library not available")
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return json.dumps({
        "_e": FORMAT_MARKER,
        "n": b64encode(nonce).decode("ascii"),
        "c": b64encode(ciphertext).decode("ascii"),
    }, separators=(",", ":"))


def decrypt_line(line: str, key: bytes) -> bytes | None:
    """Decrypt a single encrypted line. Returns None on any failure (corrupt,
    wrong format, wrong key, etc.). Never raises."""
    AESGCM = _crypto_lib()
    if AESGCM is None:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or obj.get("_e") != FORMAT_MARKER:
        return None
    try:
        nonce = b64decode(obj["n"])
        ciphertext = b64decode(obj["c"])
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception:  # noqa: BLE001  never raise from a decrypt path
        return None


def is_encrypted_line(line: str) -> bool:
    """Cheap check: does this line look like our encrypted format?"""
    s = line.strip()
    if not s.startswith('{"_e":"'):
        return False
    return FORMAT_MARKER in s[:60]


__all__ = [
    "is_available", "keychain_backend",
    "get_or_create_key", "rotate_key", "delete_key",
    "encrypt_line", "decrypt_line", "is_encrypted_line",
    "KEY_BYTES", "NONCE_BYTES", "FORMAT_MARKER",
]
