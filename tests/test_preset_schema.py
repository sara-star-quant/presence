"""Preset schema validation: shipped presets are clean; typos and bad types warn."""

import importlib
import json


def _reload():
    import _common
    import warnings_log

    importlib.reload(_common)
    importlib.reload(warnings_log)
    return _common, warnings_log


def test_shipped_presets_validate_clean(isolated_state):
    _common, warnings_log = _reload()
    warnings_log.clear_warnings_state()
    for name in ("solo-dev", "team-oss", "enterprise-strict", "zerotrust"):
        assert _common._load_preset(name) is not None
    cats = [w["category"] for w in warnings_log.read_warnings(limit=200)]
    assert "preset_unknown_key" not in cats
    assert "preset_bad_type" not in cats


def test_unknown_key_warns(isolated_state):
    _common, warnings_log = _reload()
    warnings_log.clear_warnings_state()
    (isolated_state / "presets").mkdir()
    # A typo'd section (telematry) is never read, so it silently does nothing.
    (isolated_state / "presets" / "bad.json").write_text(
        json.dumps({"telematry": {"enabled": True}})
    )
    assert _common._load_preset("bad") is not None
    cats = [w["category"] for w in warnings_log.read_warnings(limit=100)]
    assert "preset_unknown_key" in cats


def test_bad_type_warns(isolated_state):
    _common, warnings_log = _reload()
    warnings_log.clear_warnings_state()
    (isolated_state / "presets").mkdir()
    (isolated_state / "presets" / "bad.json").write_text(
        json.dumps({"confidence": {"commit_gate": "nope"}})  # not in the enum
    )
    _common._load_preset("bad")
    cats = [w["category"] for w in warnings_log.read_warnings(limit=100)]
    assert "preset_bad_type" in cats


def test_schema_file_is_loadable_json():
    import _common

    importlib.reload(_common)
    schema = _common._preset_schema()
    assert isinstance(schema, dict) and "model" in schema and "integrity" in schema
