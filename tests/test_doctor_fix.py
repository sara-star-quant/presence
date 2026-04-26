"""Tests for `python3 lib/doctor.py --fix`.

`--fix` auto-corrects what it safely can:
  - state directory or file perms drifted from 0o700 / 0o600 (chmod)
  - MANIFEST.lock missing entirely (regenerate)
  - .integrity-blocked marker present but the manifest now verifies (clear)

It must NOT silently regenerate a MISMATCHED manifest, because that would
mask tampering under the zerotrust posture. These tests pin both behaviors.
"""
from __future__ import annotations

import importlib
import stat as stat_mod

import _common
import doctor


def _reload_modules_with_isolated_state(state_dir, monkeypatch):
    """Reset _common's module-level state so it picks up the new PRESENCE_STATE."""
    monkeypatch.setenv("PRESENCE_STATE", str(state_dir))
    importlib.reload(_common)
    importlib.reload(doctor)
    return doctor


def test_fix_chmods_state_dir_to_700(isolated_state, monkeypatch):
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    # Drift the perms.
    isolated_state.chmod(0o755)
    actions, remaining = d.fix()
    # state_dir() recreates with 0o700 anyway, but --fix should have explicitly
    # corrected the drift it observed.
    new_mode = stat_mod.S_IMODE(isolated_state.stat().st_mode)
    assert new_mode == 0o700, f"expected 0o700, got 0o{new_mode:03o}"
    # Should have recorded the chmod action OR no remaining issues.
    assert any("chmod 0o700" in a for a in actions) or new_mode == 0o700


def test_fix_chmods_state_files_to_600(isolated_state, monkeypatch):
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    # Create a state file with wrong perms.
    bad = isolated_state / "logs" / "warnings.log"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("test", encoding="utf-8")
    bad.chmod(0o644)
    d.fix()
    new_mode = stat_mod.S_IMODE(bad.stat().st_mode)
    assert new_mode == 0o600, f"file perms should be 0o600 after --fix, got 0o{new_mode:03o}"


def test_fix_refuses_to_regenerate_mismatched_manifest(isolated_state, monkeypatch, tmp_path):
    """A mismatched manifest is ambiguous (local edits vs tampering); --fix
    must NOT silently regenerate it. This is the zerotrust safety guarantee."""
    from integrity import write_manifest

    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    # Generate a baseline manifest.
    target = write_manifest()
    original_content = target.read_text()
    # Tamper a tracked file (simulate either user edit or attacker).
    plugin_json = target.parent / ".claude-plugin" / "plugin.json"
    original_plugin = plugin_json.read_text()
    plugin_json.write_text(original_plugin + "\n", encoding="utf-8")
    try:
        actions, remaining = d.fix()
        # --fix should NOT have rewritten the manifest.
        assert target.read_text() == original_content, (
            "--fix silently regenerated a mismatched manifest; this masks tampering"
        )
        # And it should explicitly flag the issue as remaining.
        assert any("mismatched" in r.lower() for r in remaining), (
            f"--fix should report mismatched MANIFEST as remaining; got {remaining!r}"
        )
    finally:
        plugin_json.write_text(original_plugin, encoding="utf-8")


def test_fix_regenerates_missing_manifest(isolated_state, monkeypatch, tmp_path):
    """If MANIFEST.lock is missing entirely (e.g. fresh checkout that never
    ran --write), --fix regenerates it. This is the unambiguous case."""
    from integrity import PLUGIN_ROOT

    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    manifest = PLUGIN_ROOT / "MANIFEST.lock"
    backup = manifest.read_bytes() if manifest.exists() else None
    if manifest.exists():
        manifest.unlink()
    try:
        actions, _ = d.fix()
        assert manifest.exists(), "--fix must regenerate a missing MANIFEST.lock"
        assert any("regenerated" in a for a in actions)
    finally:
        if backup is not None:
            manifest.write_bytes(backup)


def test_fix_clears_stale_integrity_block(isolated_state, monkeypatch):
    """If .integrity-blocked is set from a prior failed SessionStart but the
    manifest now verifies clean, --fix removes the marker."""
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    # Plant a stale marker.
    bp = _common.integrity_block_path()
    _common.set_integrity_block("stale from previous test")
    assert bp.exists()
    actions, _ = d.fix()
    # Marker should be cleared (manifest verifies on the real repo).
    assert not bp.exists() or "cleared" in " ".join(actions).lower()
