"""Coverage-guided, structure-aware fuzzer for snapshot restore.

Raw bytes rarely get past the gzip header or the AES-GCM tag, so most modes
build a well-formed container (tar, or a sealed tar) from fuzzed members and
then optionally damage it. Contract: restore raises only SnapshotError, never
writes outside the state dir, and always leaves the state dir a directory.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
ROOT = Path(tempfile.mkdtemp(prefix="presence-fuzz-snapshot-"))
STATE = ROOT / "state"
STATE.mkdir()
os.environ["PRESENCE_STATE"] = str(STATE)

import atheris

with atheris.instrument_imports():
    import crypto
    import snapshot

# scrypt at the real cost would make every execution take seconds.
snapshot._derive = lambda _pw, salt, log2: hashlib.sha256(salt + bytes([log2])).digest()
# restore re-encrypts record logs when the archive says they were encrypted; give it
# a fixed key so that branch runs and the fuzzer never touches a real keychain.
crypto.get_or_create_key = lambda: bytes(32)

PW = "fuzz"


def _tar(fdp) -> bytes:
    meta: dict = {"format": snapshot.SCHEMA_FORMAT if fdp.ConsumeBool() else fdp.ConsumeIntInRange(0, 3)}
    if fdp.ConsumeBool():
        meta["encrypted_files"] = [fdp.ConsumeUnicodeNoSurrogates(12) for _ in range(fdp.ConsumeIntInRange(0, 2))]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        members = [(snapshot.META_FILENAME, json.dumps(meta).encode(), tarfile.REGTYPE)]
        for _ in range(fdp.ConsumeIntInRange(0, 5)):
            name = fdp.ConsumeUnicodeNoSurrogates(24)
            kind = fdp.PickValueInList([tarfile.REGTYPE, tarfile.REGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE])
            members.append((name, fdp.ConsumeBytes(64), kind))
        for name, body, kind in members:
            if not name:
                continue
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.SYMTYPE:
                info.linkname = fdp.ConsumeUnicodeNoSurrogates(16)
            else:
                info.size = len(body) if kind == tarfile.REGTYPE else 0
            tf.addfile(info, io.BytesIO(body) if kind == tarfile.REGTYPE else None)
    return buf.getvalue()


def _blob(fdp) -> bytes:
    mode = fdp.ConsumeIntInRange(0, 3)
    if mode == 0:
        return fdp.ConsumeBytes(4096)
    if mode == 1:
        return _tar(fdp)
    if mode == 2:
        sealed = bytearray(snapshot._seal(_tar(fdp), PW))
        if fdp.ConsumeBool():  # damage one byte: the tag must catch it
            sealed[fdp.ConsumeIntInRange(0, len(sealed) - 1)] ^= fdp.ConsumeIntInRange(1, 255)
        return bytes(sealed)
    return snapshot.SEAL_MAGIC + fdp.ConsumeBytes(4096)  # hostile header: cost byte, salt, nonce


def _clean() -> None:
    for p in ROOT.iterdir():
        if p != STATE:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    if not STATE.is_dir():
        STATE.unlink()
        STATE.mkdir()
    for p in STATE.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    _clean()
    blob = _blob(fdp)
    snap = ROOT / "in.snap"
    snap.write_bytes(blob)
    try:
        snapshot.restore(snap, overwrite=True, passphrase=PW if fdp.ConsumeBool() else None)
    except snapshot.SnapshotError:
        pass
    assert STATE.is_dir(), "restore replaced the state dir"
    assert {p.name for p in ROOT.iterdir()} <= {"state", "in.snap"}, "restore wrote outside the state dir"
    real = STATE.resolve()
    for p in STATE.rglob("*"):
        assert real in p.resolve().parents, f"escaped the state dir: {p}"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
