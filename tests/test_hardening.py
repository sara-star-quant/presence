"""Zero-Trust hardening: extra-file integrity failure, perm reverification,
guarded daemon-fallback dispatch, and audit-logged integrity failures."""

import asyncio
import importlib
import json
import stat

import pytest


def _write_manifest(root, files):
    (root / "MANIFEST.lock").write_text(
        json.dumps({"_format": 1, "files": files}, indent=2, sort_keys=True)
    )


def test_extra_file_fails_integrity(tmp_path):
    """An undeclared lib/*.py (the import-shadowing shape) must fail the gate."""
    import integrity

    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.py").write_text("x = 1\n")
    _write_manifest(tmp_path, integrity.compute_manifest(tmp_path))

    # Clean tree verifies.
    assert integrity.integrity_ok(tmp_path) is True
    missing, mismatched, extra = integrity.verify_manifest(tmp_path)
    assert not missing and not mismatched and not extra

    # Drop an undeclared file under a tracked glob.
    (tmp_path / "lib" / "_evil.py").write_text("import os\n")
    missing, mismatched, extra = integrity.verify_manifest(tmp_path)
    assert extra == ["lib/_evil.py"]
    assert not missing and not mismatched
    # Regression proof: this returned True before the hardening change.
    assert integrity.integrity_ok(tmp_path) is False


def test_integrity_gate_blocks_on_extra(isolated_state, monkeypatch):
    """fail_closed_integrity_check surfaces extra files and writes an audit line."""
    import audit
    import hook_session_start
    import integrity

    importlib.reload(integrity)
    importlib.reload(audit)
    importlib.reload(hook_session_start)

    monkeypatch.setattr(integrity, "verify_manifest", lambda root=None: ([], [], ["lib/_evil.py"]))
    cfg = {"integrity": {"fail_closed": True}, "__active_preset__": "zerotrust"}

    msg = asyncio.run(hook_session_start.fail_closed_integrity_check(cfg))
    assert msg is not None
    assert "FAILED" in msg
    assert "Extra: 1" in msg

    # The tamper event is recorded in the audit chain, and the chain still verifies.
    rep = audit.verify_chain()
    assert rep["exists"] and rep["lines"] >= 1 and rep["ok"]
    lines = (audit.audit_path()).read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(ln)["event"] == "integrity_fail" for ln in lines)


def test_integrity_gate_passes_clean(isolated_state, monkeypatch):
    import hook_session_start
    import integrity

    importlib.reload(integrity)
    importlib.reload(hook_session_start)

    monkeypatch.setattr(integrity, "verify_manifest", lambda root=None: ([], [], []))
    cfg = {"integrity": {"fail_closed": True}, "__active_preset__": "zerotrust"}
    assert asyncio.run(hook_session_start.fail_closed_integrity_check(cfg)) is None


def test_reverify_state_perms_retightens(isolated_state):
    """A loosened nested state file/dir is re-tightened to owner-only."""
    import _common

    importlib.reload(_common)
    sd = _common.state_dir()
    sub = sd / "telemetry"
    sub.mkdir()
    leaked = sub / "data.jsonl"
    leaked.write_text("{}\n")
    leaked.chmod(0o644)
    sub.chmod(0o755)

    _common.reverify_state_perms()

    assert stat.S_IMODE(leaked.stat().st_mode) == 0o600
    assert stat.S_IMODE(sub.stat().st_mode) == 0o700


def test_run_hook_fallback_is_guarded(isolated_state, monkeypatch):
    """A raising hook main on the daemon-fallback path exits 0, not a traceback."""
    import _common
    import cli

    importlib.reload(_common)
    importlib.reload(cli)

    mod = importlib.import_module("hook_post_tool_edit")
    importlib.reload(mod)

    def boom():
        raise RuntimeError("simulated hook failure")

    monkeypatch.setattr(mod, "main", boom)

    with pytest.raises(SystemExit) as ei:
        cli.run_hook("post-tool-edit")
    assert ei.value.code == 0
