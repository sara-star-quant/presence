"""Coverage for the load-bearing, previously under-tested modules:
cli dispatch, the UserPromptSubmit hook, telemetry recording/scan, and the
integrity CLI. Targets issue #39 (climb toward the 80% Silver gate)."""

import importlib
import json
import sys

import pytest

# --------------------------------------------------------------------------
# cli.py dispatch
# --------------------------------------------------------------------------

def test_cli_dispatches_hook(monkeypatch):
    import cli

    importlib.reload(cli)
    seen = {}
    monkeypatch.setattr(cli, "run_hook", lambda name: seen.setdefault("hook", name))
    monkeypatch.setattr(sys, "argv", ["cli.py", "hook", "stop"])
    cli.main()
    assert seen["hook"] == "stop"


def test_cli_dispatches_mcp(monkeypatch):
    import cli

    importlib.reload(cli)
    seen = {}
    monkeypatch.setattr(cli, "run_mcp", lambda: seen.setdefault("mcp", True))
    monkeypatch.setattr(sys, "argv", ["cli.py", "mcp"])
    cli.main()
    assert seen["mcp"] is True


def test_run_hook_unknown_exits_1():
    import cli

    with pytest.raises(SystemExit) as ei:
        cli.run_hook("does-not-exist")
    assert ei.value.code == 1


def test_run_mcp_invokes_server(monkeypatch):
    import types

    import cli

    fake = types.ModuleType("mcp_server")
    fake.main = lambda: None
    monkeypatch.setitem(sys.modules, "mcp_server", fake)
    cli.run_mcp()  # imports the fake module and calls main(); must not raise


# --------------------------------------------------------------------------
# hook_user_prompt_submit.py
# --------------------------------------------------------------------------

def test_user_prompt_submit_inert_when_integrity_blocked(hook_runner, capsys):
    run, state, repo = hook_runner
    import _common

    importlib.reload(_common)
    _common.set_integrity_block("blocked for test")
    run("hook_user_prompt_submit", {"cwd": str(repo)})
    assert capsys.readouterr().out == ""


def test_user_prompt_submit_no_events_no_output(hook_runner, capsys):
    run, state, repo = hook_runner
    run("hook_user_prompt_submit", {"cwd": str(repo)})
    # No pending events -> nothing emitted.
    assert capsys.readouterr().out == ""


def test_user_prompt_submit_disabled(hook_runner, capsys):
    run, state, repo = hook_runner
    run("hook_user_prompt_submit", {"cwd": str(repo)}, settings={"events": {"enabled": False}})
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------
# telemetry.py
# --------------------------------------------------------------------------

def _reload_telemetry():
    import _common

    importlib.reload(_common)
    import telemetry

    importlib.reload(telemetry)
    return telemetry


def test_parse_commit_sha_from_stdout():
    t = _reload_telemetry()
    assert t.parse_commit_sha_from_stdout(None) is None
    assert t.parse_commit_sha_from_stdout("nothing here") is None
    sha = t.parse_commit_sha_from_stdout("[main (root-commit) a1b2c3d] msg")
    assert sha == "a1b2c3d"


def test_record_commit_claim_roundtrip(isolated_state, fake_repo):
    t = _reload_telemetry()
    t.record_commit_claim(str(fake_repo), "deadbeef", "add a thing", intent="ship it")
    rows = [json.loads(ln) for ln in t.claims_path().read_text().splitlines() if ln.strip()]
    assert rows and rows[-1]["kind"] == "commit"
    assert rows[-1]["sha"] == "deadbeef"
    assert rows[-1]["message"] == "add a thing"


def test_record_outcome_and_confidence(isolated_state, fake_repo):
    t = _reload_telemetry()
    t.record_outcome("merged", "deadbeef", pr=7)
    t.record_confidence("tests pass", True, evidence="ci")
    outcomes = [json.loads(ln) for ln in t.outcomes_path().read_text().splitlines() if ln.strip()]
    conf = [json.loads(ln) for ln in t.confidence_path().read_text().splitlines() if ln.strip()]
    assert outcomes[-1]["kind"] == "merged" and outcomes[-1]["pr"] == 7
    assert conf[-1]["claim"] == "tests pass" and conf[-1]["verified"] is True


def test_get_head_commit_real_repo(isolated_state, fake_repo):
    t = _reload_telemetry()
    head = t.get_head_commit(str(fake_repo))
    assert head and len(head["sha"]) == 40 and isinstance(head["ct"], int)


def test_scan_for_revert_finds_revert(isolated_state, fake_repo):
    import subprocess

    t = _reload_telemetry()
    # Make a commit, record it as a claim, then add a revert that names its short sha.
    (fake_repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-m", "feature", "-q"], cwd=fake_repo, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=fake_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    t.record_commit_claim(str(fake_repo), sha, "feature")
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", f"Revert {sha[:7]} bad", "-q"],
        cwd=fake_repo, check=True,
    )
    findings = t.scan_for_revert(str(fake_repo), 1)
    assert any(f["tracked"] == sha for f in findings)


def test_async_scan_for_revert_finds_revert(isolated_state, fake_repo):
    """The async revert path must find the same revert the sync path does."""
    import asyncio
    import subprocess

    t = _reload_telemetry()
    (fake_repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-m", "feature", "-q"], cwd=fake_repo, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=fake_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    t.record_commit_claim(str(fake_repo), sha, "feature")
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", f"Revert {sha[:7]} bad", "-q"],
        cwd=fake_repo, check=True,
    )
    findings = asyncio.run(t.async_scan_for_revert(str(fake_repo), 1))
    assert any(f["tracked"] == sha for f in findings)


def test_async_scan_for_revert_empty_without_since(isolated_state, fake_repo):
    """since_ts=0 short-circuits to [] without touching git."""
    import asyncio

    t = _reload_telemetry()
    assert asyncio.run(t.async_scan_for_revert(str(fake_repo), 0)) == []


def test_async_scan_for_revert_empty_without_tracked_claims(isolated_state, fake_repo):
    """No recorded commit claims -> nothing to match reverts against."""
    import asyncio

    t = _reload_telemetry()
    assert asyncio.run(t.async_scan_for_revert(str(fake_repo), 1)) == []


# --------------------------------------------------------------------------
# crypto.py key management (backend mocked; no real keychain touched)
# --------------------------------------------------------------------------

def test_get_or_create_key_returns_existing(monkeypatch):
    import crypto

    importlib.reload(crypto)
    existing = b"\x01" * crypto.KEY_BYTES
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (lambda: existing, lambda k: True, lambda: True))
    assert crypto.get_or_create_key() == existing


def test_get_or_create_key_creates_when_absent(monkeypatch):
    import crypto

    importlib.reload(crypto)
    stored = {}
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(
        crypto, "_backend_ops",
        lambda: (lambda: None, lambda k: stored.update(key=k) or True, lambda: True),
    )
    key = crypto.get_or_create_key()
    assert key is not None and len(key) == crypto.KEY_BYTES
    assert stored["key"] == key


def test_get_or_create_key_none_when_unavailable(monkeypatch):
    import crypto

    importlib.reload(crypto)
    monkeypatch.setattr(crypto, "is_available", lambda: False)
    assert crypto.get_or_create_key() is None


def test_get_or_create_key_none_when_store_fails(monkeypatch):
    import crypto

    importlib.reload(crypto)
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (lambda: None, lambda k: False, lambda: True))
    assert crypto.get_or_create_key() is None


def test_rotate_key_stores_new(monkeypatch):
    import crypto

    importlib.reload(crypto)
    stored = {}
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(
        crypto, "_backend_ops",
        lambda: (lambda: b"\x02" * crypto.KEY_BYTES, lambda k: stored.update(key=k) or True, lambda: True),
    )
    new = crypto.rotate_key()
    assert new is not None and stored["key"] == new and len(new) == crypto.KEY_BYTES


def test_delete_key(monkeypatch):
    import crypto

    importlib.reload(crypto)
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (lambda: None, lambda k: True, lambda: True))
    assert crypto.delete_key() is True
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (None, None, None))
    assert crypto.delete_key() is False


# --------------------------------------------------------------------------
# integrity.py CLI
# --------------------------------------------------------------------------

def test_integrity_cli_write_verify_audit(tmp_path, monkeypatch, capsys):
    import integrity

    importlib.reload(integrity)
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.py").write_text("x = 1\n")

    monkeypatch.setattr(sys, "argv", ["integrity.py", "--write", "--root", str(tmp_path)])
    assert integrity._cli() == 0

    monkeypatch.setattr(sys, "argv", ["integrity.py", "--verify", "--root", str(tmp_path)])
    assert integrity._cli() == 0

    # Modify a tracked file -> verify must fail.
    (tmp_path / "lib" / "a.py").write_text("x = 2\n")
    monkeypatch.setattr(sys, "argv", ["integrity.py", "--verify", "--root", str(tmp_path)])
    assert integrity._cli() == 1

    # Audit-verify with no audit log present -> exits 0 (nothing to verify).
    monkeypatch.setattr(sys, "argv", ["integrity.py", "--audit-verify"])
    assert integrity._cli() == 0


# --------------------------------------------------------------------------
# Zero-Trust storage round-trip: append_jsonl encrypts on disk under a preset
# that requests encryption, and read_jsonl transparently decrypts it back.
# Keychain is mocked; no real `security`/`secret-tool` is touched.
# --------------------------------------------------------------------------

def test_encrypted_storage_round_trip(isolated_state, monkeypatch):
    import _common
    import crypto

    importlib.reload(crypto)
    importlib.reload(_common)

    key = b"\x07" * crypto.KEY_BYTES
    # Preset wants events encrypted; provide a deterministic key without a keychain.
    monkeypatch.setattr(_common, "settings", lambda strict=False: {"events": {"encrypted": True}})
    monkeypatch.setattr(crypto, "is_available", lambda: True)
    monkeypatch.setattr(crypto, "get_or_create_key", lambda: key)
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (lambda: key, lambda k: True, lambda: True))
    # Reset the per-process caches so the monkeypatched state takes effect.
    _common._WRITE_STATE_CACHE = None
    _common._READ_KEY_CACHE = _common._UNSET

    path = isolated_state / "events.jsonl"
    record = {"kind": "test", "secret": "AKIAIOSFODNN7EXAMPLE", "n": 1}
    _common.append_jsonl(path, record)

    # On-disk line must be ciphertext, not the plaintext record.
    raw = path.read_text().strip()
    assert crypto.is_encrypted_line(raw)
    assert "AKIAIOSFODNN7EXAMPLE" not in raw

    # read_jsonl transparently decrypts back to the original object.
    rows = _common.read_jsonl(path)
    assert rows == [record]


def test_encrypted_read_skips_unrecoverable_line(isolated_state, monkeypatch):
    """An encrypted-looking line with no available key is skipped, not crashed on."""
    import _common
    import crypto

    importlib.reload(crypto)
    importlib.reload(_common)

    # Write one genuinely-encrypted line with a key, then make the key unavailable.
    key = b"\x09" * crypto.KEY_BYTES
    enc = crypto.encrypt_line(b'{"kind":"x"}', key)
    path = isolated_state / "events.jsonl"
    path.write_text(enc + "\n")

    monkeypatch.setattr(_common, "settings", lambda strict=False: {})
    monkeypatch.setattr(crypto, "_backend_ops", lambda: (lambda: None, lambda k: True, lambda: True))
    _common._WRITE_STATE_CACHE = None
    _common._READ_KEY_CACHE = _common._UNSET

    assert _common.read_jsonl(path) == []
