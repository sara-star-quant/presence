"""Passphrase-sealed snapshots: zerotrust state moving between machines.

Two machines are simulated by swapping the key held in an in-memory keychain
between snapshot and restore. Failure paths dominate on purpose: a snapshot that
silently drops data or half-restores is worse than no snapshot.
"""
from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path

import _common
import audit
import crypto
import pytest
import snapshot

KEY_A = bytes(range(32))
KEY_B = bytes(range(32, 64))
PW = "correct horse battery"
HEADER_LEN = 8 + 1 + 16 + 12


@pytest.fixture
def keychain(monkeypatch, isolated_state):
    """In-memory keychain plus fast scrypt; returns the store so tests can swap keys."""
    store = {"key": KEY_A}
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (
        lambda: store["key"],
        lambda k: store.update(key=k) or True,
        lambda: store.update(key=None) or True,
    ))
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(_common, "_WRITE_STATE_CACHE", None)
    monkeypatch.setattr(_common, "_READ_KEY_CACHE", _common._UNSET)
    monkeypatch.setattr(_common, "_SETTINGS_CACHE", None)
    monkeypatch.setattr(snapshot, "_SCRYPT_LOG2", 14)
    importlib.reload(audit)
    return store


def _enc(key: bytes, obj: dict) -> str:
    return crypto.encrypt_line(json.dumps(obj).encode(), key)


def _seed(sd: Path, key: bytes = KEY_A) -> None:
    (sd / "projects" / "abc123def456").mkdir(parents=True, exist_ok=True)
    (sd / "projects" / "abc123def456" / "model.md").write_text("# model\n")
    (sd / "telemetry").mkdir(exist_ok=True)
    (sd / "telemetry" / "claims.jsonl").write_text(
        _enc(key, {"n": 1}) + "\n" + _enc(key, {"n": 2}) + "\n"
    )
    (sd / "settings.json").write_text(json.dumps({"preset": "zerotrust"}))


def _tree_hash(sd: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(sd.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(sd).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _decrypt_file(path: Path, key: bytes) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        plain = crypto.decrypt_line(line, key)
        assert plain is not None, f"line not decryptable with the expected key: {line[:40]}"
        out.append(json.loads(plain))
    return out


def test_roundtrip_reencrypts_under_destination_key(keychain, isolated_state, tmp_path):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    assert out.read_bytes().startswith(snapshot.SEAL_MAGIC)
    assert b"claims" not in out.read_bytes() and b"# model" not in out.read_bytes()

    keychain["key"] = KEY_B  # the destination machine
    snapshot.restore(out, overwrite=True, passphrase=PW)

    claims = isolated_state / "telemetry" / "claims.jsonl"
    assert _decrypt_file(claims, KEY_B) == [{"n": 1}, {"n": 2}]
    assert all(crypto.decrypt_line(ln, KEY_A) is None for ln in claims.read_text().splitlines())
    assert (isolated_state / "projects" / "abc123def456" / "model.md").read_text() == "# model\n"


def test_mixed_plain_and_encrypted_lines_roundtrip(keychain, isolated_state, tmp_path):
    (isolated_state / "events").mkdir()
    f = isolated_state / "events" / "pending.jsonl"
    f.write_text('{"plain":1}\n' + _enc(KEY_A, {"enc": 2}) + "\n")
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    keychain["key"] = KEY_B
    snapshot.restore(out, overwrite=True, passphrase=PW)
    got = [
        json.loads(plain) if (plain := crypto.decrypt_line(ln, KEY_B)) else json.loads(ln)
        for ln in f.read_text().splitlines()
    ]
    assert got == [{"plain": 1}, {"enc": 2}]


def test_sealed_snapshot_of_plain_state_restores_plain(keychain, isolated_state, tmp_path):
    (isolated_state / "events").mkdir()
    (isolated_state / "events" / "pending.jsonl").write_text('{"a":1}\n')
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    snapshot.restore(out, overwrite=True, passphrase=PW)
    assert (isolated_state / "events" / "pending.jsonl").read_text() == '{"a":1}\n'


def test_wrong_passphrase_leaves_state_untouched(keychain, isolated_state, tmp_path):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    before = _tree_hash(isolated_state)
    wrong = "not the passphrase"
    with pytest.raises(snapshot.SnapshotError, match="passphrase"):
        snapshot.restore(out, overwrite=True, passphrase=wrong)
    assert _tree_hash(isolated_state) == before


@pytest.mark.parametrize("where", ["header_salt", "middle", "tag"])
def test_tampered_ciphertext_rejected(keychain, isolated_state, tmp_path, where):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    blob = bytearray(out.read_bytes())
    idx = {"header_salt": 12, "middle": (HEADER_LEN + len(blob)) // 2, "tag": len(blob) - 1}[where]
    blob[idx] ^= 0x01
    out.write_bytes(bytes(blob))
    before = _tree_hash(isolated_state)
    with pytest.raises(snapshot.SnapshotError):
        snapshot.restore(out, overwrite=True, passphrase=PW)
    assert _tree_hash(isolated_state) == before


@pytest.mark.parametrize("cost", [0, 13, 19, 255])
def test_hostile_scrypt_cost_rejected_before_derivation(keychain, isolated_state, tmp_path, monkeypatch, cost):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    blob = bytearray(out.read_bytes())
    blob[8] = cost
    out.write_bytes(bytes(blob))
    monkeypatch.setattr(hashlib, "scrypt", lambda *a, **k: pytest.fail("derived a key for hostile params"))
    with pytest.raises(snapshot.SnapshotError, match="cost"):
        snapshot.restore(out, overwrite=True, passphrase=PW)


@pytest.mark.parametrize("cut", [0, 5, 8, HEADER_LEN, HEADER_LEN + 1, HEADER_LEN + 15])
def test_truncated_file_rejected(keychain, isolated_state, tmp_path, cut):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    out.write_bytes(out.read_bytes()[:cut])
    with pytest.raises(snapshot.SnapshotError):
        snapshot.restore(out, overwrite=True, passphrase=PW)


def test_sealed_restore_requires_a_passphrase(keychain, isolated_state, tmp_path):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    with pytest.raises(snapshot.SnapshotError, match="passphrase"):
        snapshot.restore(out, overwrite=True)


@pytest.mark.parametrize("bad", ["", "short", "       "])
def test_weak_or_empty_passphrase_rejected_at_seal_time(keychain, isolated_state, tmp_path, bad):
    _seed(isolated_state)
    out = tmp_path / "s.snap"
    with pytest.raises(snapshot.SnapshotError, match="passphrase"):
        snapshot.snapshot(out, passphrase=bad)
    assert not out.exists()


def test_undecryptable_line_aborts_and_names_the_file(keychain, isolated_state, tmp_path):
    _seed(isolated_state)
    with open(isolated_state / "telemetry" / "claims.jsonl", "a") as f:
        f.write(_enc(KEY_B, {"orphan": 1}) + "\n")  # source key for this line is lost
    out = tmp_path / "s.snap"
    with pytest.raises(snapshot.SnapshotError, match=r"telemetry/claims\.jsonl"):
        snapshot.snapshot(out, passphrase=PW)
    assert not out.exists() and not list(tmp_path.glob("*.tmp*"))


def test_snapshot_without_source_key_aborts_when_encrypted_lines_exist(keychain, isolated_state, tmp_path):
    _seed(isolated_state)
    keychain["key"] = None
    out = tmp_path / "s.snap"
    with pytest.raises(snapshot.SnapshotError, match="key"):
        snapshot.snapshot(out, passphrase=PW)
    assert not out.exists()


def test_missing_cryptography_gives_actionable_error(keychain, isolated_state, tmp_path, monkeypatch):
    _seed(isolated_state)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    with pytest.raises(snapshot.SnapshotError, match="pip install"):
        snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)


def test_no_destination_key_refuses_before_touching_state(keychain, isolated_state, tmp_path, monkeypatch):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    before = _tree_hash(isolated_state)
    # Destination keychain has no key and refuses to store a new one.
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (lambda: None, lambda k: False, lambda: True))
    with pytest.raises(snapshot.SnapshotError, match="key"):
        snapshot.restore(out, overwrite=True, passphrase=PW)
    assert _tree_hash(isolated_state) == before


def test_restore_rolls_back_when_the_swap_fails_midway(keychain, isolated_state, tmp_path, monkeypatch):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    (isolated_state / "extra.txt").write_text("pre-existing")
    before = _tree_hash(isolated_state)
    real = os.replace
    placed = {"n": 0}

    def flaky(src, dst):
        if ".presence-restore-" in str(src) and "/new/" in str(src):
            placed["n"] += 1
            if placed["n"] == 2:  # fail on the second file placed into the state dir
                raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(snapshot.SnapshotError, match="rolled back"):
        snapshot.restore(out, overwrite=True, passphrase=PW)
    monkeypatch.setattr(os, "replace", real)
    assert _tree_hash(isolated_state) == before
    assert not [p for p in isolated_state.parent.iterdir() if p.name.startswith(".presence-restore-")]


def test_restore_refuses_non_regular_members(keychain, isolated_state, tmp_path):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tf:
        meta = json.dumps({"format": 1}).encode()
        ti = tarfile.TarInfo("_snapshot_meta.json")
        ti.size = len(meta)
        tf.addfile(ti, io.BytesIO(meta))
        link = tarfile.TarInfo("evil")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    p = tmp_path / "evil.tar.gz"
    p.write_bytes(raw.getvalue())
    with pytest.raises(snapshot.SnapshotError, match="unsafe"):
        snapshot.restore(p, overwrite=True)


def test_sealed_ops_append_audit_events_without_secrets(keychain, isolated_state, tmp_path):
    _seed(isolated_state)
    out = snapshot.snapshot(tmp_path / "s.snap", passphrase=PW)
    snapshot.restore(out, overwrite=True, passphrase=PW)
    lines = audit.audit_path().read_text().splitlines()
    events = [json.loads(ln) for ln in lines]
    assert [e["event"] for e in events if e["event"].startswith("snapshot_")] == [
        "snapshot_exported", "snapshot_restored",
    ]
    blob = "\n".join(lines)
    assert PW not in blob and KEY_A.hex() not in blob
    assert audit.verify_chain()["ok"]


def test_plain_snapshot_still_refuses_zerotrust_without_a_passphrase(keychain, isolated_state, tmp_path):
    _seed(isolated_state)
    with pytest.raises(snapshot.SnapshotError, match="passphrase"):
        snapshot.snapshot(tmp_path / "plain.tar.gz")


def test_cli_passphrase_comes_from_env_never_argv(keychain, isolated_state, tmp_path, monkeypatch, capsys):
    _seed(isolated_state)
    out = tmp_path / "s.snap"
    monkeypatch.setenv("SNAP_PW", PW)
    monkeypatch.setattr(sys, "argv", ["snapshot", "snapshot", str(out), "--passphrase-env", "SNAP_PW"])
    assert snapshot._cli() == 0
    monkeypatch.setattr(sys, "argv", ["snapshot", "restore", str(out), "--overwrite", "--passphrase-env", "SNAP_PW"])
    assert snapshot._cli() == 0
    monkeypatch.delenv("SNAP_PW")
    monkeypatch.setattr(sys, "argv", ["snapshot", "restore", str(out), "--overwrite", "--passphrase-env", "SNAP_PW"])
    assert snapshot._cli() == 1 and "SNAP_PW" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["snapshot", "snapshot", str(out), "--passphrase", "x"])
    with pytest.raises(SystemExit):
        snapshot._cli()


def test_cli_prompt_mode_confirms_passphrase_on_snapshot(keychain, isolated_state, tmp_path, monkeypatch, capsys):
    import getpass

    _seed(isolated_state)
    out = tmp_path / "s.snap"
    answers = iter([PW, "different"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr(sys, "argv", ["snapshot", "snapshot", str(out), "--passphrase-prompt"])
    assert snapshot._cli() == 1 and "match" in capsys.readouterr().err
    assert not out.exists()


def test_install_sh_forwards_passphrase_flags(tmp_path):
    import subprocess

    install_sh = Path(__file__).resolve().parent.parent / "install.sh"
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "projects" / "abc").mkdir(parents=True)
    (src / "projects" / "abc" / "model.md").write_text("# hello\n")
    dst.mkdir()
    out = tmp_path / "s.snap"
    # install.sh picks python3 from PATH; make it the interpreter that has cryptography.
    path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
    base = {**os.environ, "PATH": path, "CLAUDE_HOME": str(tmp_path / "home"), "SNAP_PW": PW}

    def run(state, *args):
        return subprocess.run(
            ["bash", str(install_sh), *args],
            capture_output=True, text=True, check=False, env={**base, "PRESENCE_STATE": str(state)},
        )

    r = run(src, "--snapshot", str(out), "--passphrase-env", "SNAP_PW")
    assert r.returncode == 0, r.stderr
    assert out.read_bytes().startswith(snapshot.SEAL_MAGIC)
    r = run(dst, "--restore", str(out), "--overwrite", "--passphrase-env", "SNAP_PW")
    assert r.returncode == 0, r.stderr
    assert (dst / "projects" / "abc" / "model.md").read_text() == "# hello\n"
    r = run(dst, "--restore", str(out), "--overwrite")
    assert r.returncode != 0 and "passphrase" in r.stderr
