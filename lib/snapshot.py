"""State snapshot + restore for cross-machine continuity (non-zerotrust only).

Plain snapshots (a tar.gz) cover non-zerotrust state. Zerotrust state is
encrypted with a per-machine keychain key, so it travels as a sealed snapshot:
the state is decrypted in memory on the source, the whole archive is sealed
with a key derived from a user passphrase (scrypt + AES-GCM), and restore
re-encrypts the affected files under the destination machine's own key.

Sealed layout: MAGIC(8) | scrypt log2 cost(1) | salt(16) | nonce(12) | AES-GCM
ciphertext of the tar.gz, with everything before the ciphertext as AAD. Only
`*.jsonl` files other than audit.jsonl ever hold encrypted lines (model.md and
the audit chain are plain), and the sealed metadata lists which ones did.

Excluded from snapshots (per-machine cache only):
  .python_bin, .python_version_ok, .integrity-blocked, .unlock-*, logs/.warned-*

Included:
  projects/<repo_id>/{model.md,last_seen}, events/<repo_id>/pending.jsonl,
  telemetry/{claims,outcomes,confidence}.jsonl, logs/{errors,warnings}.log,
  settings.json, presets/<custom>.json, audit.jsonl, audit.head

Schema versioned via _snapshot_meta.json at the tarball root.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import io
import json
import os
import secrets
import shutil
import tarfile
import tempfile
from pathlib import Path

from _common import PLUGIN_ROOT, _try_existing_key_only, settings, state_dir

SCHEMA_FORMAT = 1
META_FILENAME = "_snapshot_meta.json"

SEAL_MAGIC = b"PRSNAP2\n"
_SCRYPT_LOG2 = 15  # write cost: 32 MiB; restore accepts _SCRYPT_LOG2_RANGE
_SCRYPT_LOG2_RANGE = (14, 18)  # caps what a hostile archive can make us allocate
_SALT_BYTES = 16
_NONCE_BYTES = 12
_MIN_PASSPHRASE = 8
_HEADER_LEN = len(SEAL_MAGIC) + 1 + _SALT_BYTES + _NONCE_BYTES
_STAGE_PREFIX = ".presence-restore-"

# Path patterns excluded from snapshots. Matched against POSIX paths relative
# to the state dir. The first three are markers that should never travel
# across machines (they describe the source host's interpreter / session
# state); the warned-* family is per-process counter state.
_EXCLUDE_PATTERNS = (
    ".python_bin",
    ".python_version_ok",
    ".integrity-blocked",
    "unlock-*",
    ".unlock-*",
    "logs/.warned-*",
)


class SnapshotError(Exception):
    """Snapshot or restore refused or failed."""


def _is_excluded(rel_posix: str) -> bool:
    """Return True iff rel_posix matches any exclusion pattern."""
    for pat in _EXCLUDE_PATTERNS:
        # Match either the full path or just the basename.
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(Path(rel_posix).name, pat):
            return True
    return False


def _zerotrust_active() -> bool:
    """True iff the current settings request encryption on any storage section.

    We check the merged preset, not just the preset name, because a user could
    pick zerotrust and then disable encryption via overrides (the schema allows
    this). What matters is whether anything currently on disk would be encrypted.
    """
    cfg = settings()
    return any(
        bool((cfg.get(section) or {}).get("encrypted"))
        for section in ("model", "telemetry", "events")
    )


def _read_version() -> str:
    p = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, json.JSONDecodeError):
        return "unknown"


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise SnapshotError(
            "sealed snapshots need the `cryptography` package: pip install --user cryptography"
        ) from exc
    return AESGCM


def _derive(passphrase: str, salt: bytes, log2: int) -> bytes:
    return hashlib.scrypt(
        passphrase.encode("utf-8"), salt=salt, n=1 << log2, r=8, p=1, maxmem=2**30, dklen=32,
    )


def _seal(payload: bytes, passphrase: str) -> bytes:
    aesgcm = _aesgcm()
    salt, nonce = secrets.token_bytes(_SALT_BYTES), secrets.token_bytes(_NONCE_BYTES)
    header = SEAL_MAGIC + bytes([_SCRYPT_LOG2]) + salt + nonce
    return header + aesgcm(_derive(passphrase, salt, _SCRYPT_LOG2)).encrypt(nonce, payload, header)


def _unseal(blob: bytes, passphrase: str) -> bytes:
    if len(blob) < _HEADER_LEN + 16:
        raise SnapshotError("sealed snapshot is truncated")
    log2 = blob[len(SEAL_MAGIC)]
    if not _SCRYPT_LOG2_RANGE[0] <= log2 <= _SCRYPT_LOG2_RANGE[1]:
        raise SnapshotError(f"sealed snapshot has an unsupported scrypt cost ({log2}); refusing to derive a key")
    aesgcm = _aesgcm()
    off = len(SEAL_MAGIC) + 1
    salt, nonce = blob[off:off + _SALT_BYTES], blob[off + _SALT_BYTES:_HEADER_LEN]
    try:
        return aesgcm(_derive(passphrase, salt, log2)).decrypt(nonce, blob[_HEADER_LEN:], blob[:_HEADER_LEN])
    except Exception as exc:  # noqa: BLE001  InvalidTag: wrong passphrase or tampered archive
        raise SnapshotError("wrong passphrase, or the snapshot is corrupted") from exc


def _is_record_log(rel: str) -> bool:
    return rel.endswith(".jsonl") and rel != "audit.jsonl"


def _decrypt_log(rel: str, data: bytes, get_key) -> tuple[bytes, bool]:
    """Decrypt every encrypted line of a JSONL file. Returns (plain bytes, had_encrypted)."""
    from crypto import decrypt_line, is_encrypted_line

    out, had = [], False
    for line in data.decode("utf-8").splitlines():
        text = line
        if is_encrypted_line(line):
            had = True
            key = get_key()
            if key is None:
                raise SnapshotError(
                    f"{rel} holds encrypted lines but this machine's keychain has no data key to read them"
                )
            plain = decrypt_line(line, key)
            if plain is None:
                raise SnapshotError(f"cannot decrypt a line in {rel}: key mismatch or corruption")
            text = plain.decode("utf-8")
        out.append(text + "\n")
    return "".join(out).encode("utf-8"), had


def _encrypt_log(data: bytes, key: bytes) -> bytes:
    from crypto import encrypt_line

    return "".join(
        encrypt_line(ln.encode("utf-8"), key) + "\n" for ln in data.decode("utf-8").splitlines()
    ).encode("utf-8")


def _audit(event: str, details: dict) -> None:
    try:
        from audit import append
        append(event, details)
    except Exception:  # noqa: BLE001, S110  the audit trail is advisory; never fail a snapshot over it
        pass


def _meta(**extra) -> dict:
    return {
        "format": SCHEMA_FORMAT,
        "presence_version": _read_version(),
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds") + "Z",
        **extra,
    }


def _add_bytes(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(dt.datetime.now().timestamp())
    info.mode = 0o600
    tf.addfile(info, io.BytesIO(data))


def _snapshot_sealed(out: Path, passphrase: str) -> Path:
    if len(passphrase.strip()) < _MIN_PASSPHRASE:
        raise SnapshotError(f"passphrase must be at least {_MIN_PASSPHRASE} characters")
    _aesgcm()  # fail early with the install hint, before reading any state
    sd = state_dir()
    if not sd.exists():
        raise SnapshotError(f"state directory does not exist: {sd}")

    keys: list[bytes | None] = []

    def get_key() -> bytes | None:
        if not keys:
            keys.append(_try_existing_key_only())
        return keys[0]

    entries: dict[str, bytes] = {}
    encrypted_files: list[str] = []
    for path in sorted(sd.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(sd).as_posix()
        if _is_excluded(rel):
            continue
        data = path.read_bytes()
        if _is_record_log(rel):
            data, had = _decrypt_log(rel, data, get_key)
            if had:
                encrypted_files.append(rel)
        entries[rel] = data

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tf:
        _add_bytes(tf, META_FILENAME, json.dumps(_meta(sealed=True, encrypted_files=encrypted_files), indent=2).encode())
        for rel, data in entries.items():
            _add_bytes(tf, rel, data)

    blob = _seal(raw.getvalue(), passphrase)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_bytes(blob)
        tmp.chmod(0o600)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    _audit("snapshot_exported", {"sealed": True, "files": len(entries)})
    return out


def snapshot(out_path: str | Path, passphrase: str | None = None) -> Path:
    """Write a snapshot of the state dir.

    With a passphrase the archive is sealed (decrypted on the way in, so it works
    for zerotrust state). Without one it is a plain tar.gz, and an active
    encryption preset is refused: a plain archive of encrypted state would be
    unreadable on any other machine.
    """
    if passphrase is not None:
        return _snapshot_sealed(Path(out_path), passphrase)
    if _zerotrust_active():
        raise SnapshotError(
            "snapshot of zerotrust state needs a passphrase: pass --passphrase-env VAR "
            "or --passphrase-prompt to seal it"
        )

    sd = state_dir()
    if not sd.exists():
        raise SnapshotError(f"state directory does not exist: {sd}")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    meta = {
        "format": SCHEMA_FORMAT,
        "presence_version": _read_version(),
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds") + "Z",
    }

    with tarfile.open(out, "w:gz") as tf:
        # Write meta first so restore can validate without scanning the whole tar.
        meta_bytes = json.dumps(meta, indent=2).encode("utf-8")
        meta_info = tarfile.TarInfo(META_FILENAME)
        meta_info.size = len(meta_bytes)
        meta_info.mtime = int(dt.datetime.now().timestamp())
        meta_info.mode = 0o600
        tf.addfile(meta_info, io.BytesIO(meta_bytes))

        # Walk state dir in sorted order so the tar is deterministic.
        for path in sorted(sd.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(sd).as_posix()
            if _is_excluded(rel):
                continue
            tf.add(path, arcname=rel, recursive=False)

    return out


def _apply(sd: Path, entries: dict[str, bytes], drop: tuple[str, ...] = ()) -> None:
    """Swap entries into the state dir, all or nothing.

    Files are staged next to the state dir, any existing file they replace is
    moved into a backup first, and a failure partway puts every original back.
    """
    stage = Path(tempfile.mkdtemp(prefix=_STAGE_PREFIX, dir=sd.parent))
    new, backup = stage / "new", stage / "backup"
    try:
        for rel, data in entries.items():
            t = new / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(data)
            t.chmod(0o600)
    except OSError as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise SnapshotError(f"could not stage the restore: {exc}") from exc

    done: list[tuple[Path, Path | None]] = []  # (target, backup) ; backup None = newly placed
    try:
        for rel in (*entries, *(d for d in drop if d not in entries)):
            target = sd / rel
            if target.exists() or target.is_symlink():
                held = backup / rel
                held.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, held)
                done.append((target, held))
        for rel in entries:
            target = sd / rel
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(new / rel, target)
            done.append((target, None))
    except OSError as exc:
        for target, held in reversed(done):
            try:
                if held is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(held, target)
            except OSError:
                pass
        shutil.rmtree(stage, ignore_errors=True)
        raise SnapshotError(f"restore failed and was rolled back: {exc}") from exc
    shutil.rmtree(stage, ignore_errors=True)


def restore(in_path: str | Path, overwrite: bool = False, passphrase: str | None = None) -> None:
    """Restore a snapshot (plain or sealed) over the state dir.

    Refuses if state already exists and overwrite=False (the safe default;
    the user must explicitly opt in to clobbering existing memory).
    Refuses on schema version mismatch, a wrong passphrase, unsafe members, or a
    destination without a usable data key when the snapshot held encrypted files.
    Everything is validated in memory before the state dir is touched, and the
    final swap rolls back on failure.
    """
    p = Path(in_path)
    if not p.exists():
        raise SnapshotError(f"snapshot not found: {p}")

    sd = state_dir()
    if any(sd.iterdir()) and not overwrite:
        raise SnapshotError(
            f"state directory is non-empty: {sd}\n"
            "pass --overwrite to clobber existing state, "
            "or remove ~/.claude/presence/ first"
        )

    raw = p.read_bytes()
    sealed = raw.startswith(SEAL_MAGIC)
    if sealed:
        if not passphrase:
            raise SnapshotError(
                "this snapshot is passphrase-sealed: pass --passphrase-env VAR or --passphrase-prompt"
            )
        raw = _unseal(raw, passphrase)
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")  # noqa: SIM115  closed by the with below; only the open is guarded
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise SnapshotError(f"not a readable snapshot archive: {exc}") from exc

    entries: dict[str, bytes] = {}
    with tf:
        # Validate meta first.
        try:
            meta_member = tf.getmember(META_FILENAME)
        except KeyError as exc:
            raise SnapshotError(f"snapshot missing {META_FILENAME}; not a presence snapshot") from exc
        meta_file = tf.extractfile(meta_member)
        if meta_file is None:
            raise SnapshotError("snapshot meta unreadable")
        try:
            meta = json.loads(meta_file.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SnapshotError(f"snapshot meta is not valid JSON: {exc}") from exc
        if meta.get("format") != SCHEMA_FORMAT:
            raise SnapshotError(
                f"snapshot format {meta.get('format')!r} != supported {SCHEMA_FORMAT!r}; "
                "this snapshot was made by a different version of presence"
            )

        for member in tf.getmembers():
            if member.name == META_FILENAME:
                continue
            if member.name.startswith("/") or ".." in Path(member.name).parts or not member.isreg():
                raise SnapshotError(f"refusing unsafe tar member: {member.name!r}")
            f = tf.extractfile(member)
            entries[member.name] = f.read() if f is not None else b""

    reencrypt = [r for r in (meta.get("encrypted_files") or []) if r in entries]
    if reencrypt:
        from crypto import get_or_create_key

        key = get_or_create_key()
        if key is None:
            raise SnapshotError(
                "this snapshot holds encrypted state but the destination has no usable data key "
                "(keychain unavailable or refused to store one); nothing was restored"
            )
        for rel in reencrypt:
            entries[rel] = _encrypt_log(entries[rel], key)

    # An archive without an audit anchor (pre-0.9) must not leave this machine's
    # old anchor behind: it would disagree with the restored log and read as truncation.
    _apply(sd, entries, drop=("audit.head",))
    if sealed:
        _audit("snapshot_restored", {"sealed": True, "files": len(entries)})


def _passphrase(args, confirm: bool) -> str | None:
    if args.passphrase_env:
        value = os.environ.get(args.passphrase_env)
        if not value:
            raise SnapshotError(f"environment variable {args.passphrase_env} is empty or unset")
        return value
    if args.passphrase_prompt:
        import getpass

        value = getpass.getpass("passphrase: ")
        if confirm and getpass.getpass("repeat passphrase: ") != value:
            raise SnapshotError("passphrases do not match")
        return value
    return None


def _cli() -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="presence: state snapshot / restore")
    sub = ap.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot", help="write a snapshot of the state dir")
    snap.add_argument("out_path")
    rest = sub.add_parser("restore", help="restore a snapshot over the state dir")
    rest.add_argument("in_path")
    rest.add_argument("--overwrite", action="store_true",
                      help="clobber existing state instead of refusing")
    for sp in (snap, rest):
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--passphrase-env", metavar="VAR",
                       help="seal/open with the passphrase in this environment variable")
        g.add_argument("--passphrase-prompt", action="store_true",
                       help="seal/open with a passphrase typed at the prompt")
    args = ap.parse_args()

    try:
        if args.cmd == "snapshot":
            out = snapshot(args.out_path, passphrase=_passphrase(args, confirm=True))
            print(f"wrote {out}")
        else:
            restore(args.in_path, overwrite=args.overwrite, passphrase=_passphrase(args, confirm=False))
            print(f"restored from {args.in_path} to {state_dir()}")
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
