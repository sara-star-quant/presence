"""Plugin integrity: write/load/verify the SHA-256 manifest."""

import integrity


def test_compute_manifest_includes_known_files():
    m = integrity.compute_manifest()
    # Should include at least the plugin manifest and one hook script
    assert ".claude-plugin/plugin.json" in m
    assert any(p.startswith("hooks/scripts/") for p in m)


def test_write_and_load_roundtrip(tmp_path, monkeypatch):
    # Use the real plugin root for compute, write into a temp root
    real_manifest = integrity.compute_manifest()
    p = tmp_path / "MANIFEST.lock"
    import json

    p.write_text(json.dumps({"_format": 1, "files": real_manifest}, indent=2, sort_keys=True))
    # Point load at tmp dir but compute against real plugin root for verify
    loaded = integrity.load_manifest(tmp_path)
    assert loaded == real_manifest


def test_verify_clean(tmp_path):
    # Verifying against the real plugin's own MANIFEST.lock-not-yet-written
    # If MANIFEST.lock doesn't exist at PLUGIN_ROOT, verify_manifest returns ([], [], [])
    missing, mismatched, _extra = integrity.verify_manifest()
    if (integrity.PLUGIN_ROOT / "MANIFEST.lock").exists():
        assert not missing
        assert not mismatched


def test_integrity_ok_with_no_manifest():
    # No MANIFEST.lock present is treated as "nothing to verify"; caller chooses policy.
    # The function returns True (vacuously OK); caller in zerotrust mode should not call it
    # if missing manifest must be a hard fail.
    if not (integrity.PLUGIN_ROOT / "MANIFEST.lock").exists():
        assert integrity.integrity_ok() is True
