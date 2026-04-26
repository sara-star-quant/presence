"""Preset management: distinguish missing vs corrupt vs OK."""
import json

from presets import (
    DEFAULT_PRESET,
    active_preset_name,
    get_preset,
    list_presets,
    use_preset,
)


def test_builtin_solo_dev_present(isolated_state):
    res = get_preset("solo-dev")
    assert res.ok
    assert res.source == "builtin"
    assert isinstance(res.data, dict)


def test_missing_preset(isolated_state):
    res = get_preset("does-not-exist")
    assert not res.ok
    assert "not found" in (res.error or "")


def test_corrupt_user_preset(isolated_state):
    user_dir = isolated_state / "presets"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "broken.json").write_text("{not valid json", encoding="utf-8")
    res = get_preset("broken")
    assert not res.ok
    assert "parse error" in (res.error or "")


def test_use_preset_persists_choice(isolated_state):
    res = use_preset("team-oss")
    assert res.ok
    assert active_preset_name() == "team-oss"


def test_use_corrupt_preset_refuses(isolated_state):
    user_dir = isolated_state / "presets"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "broken.json").write_text("{nope", encoding="utf-8")
    res = use_preset("broken")
    assert not res.ok
    assert active_preset_name() == DEFAULT_PRESET  # not silently switched


def test_user_preset_overrides_builtin(isolated_state):
    user_dir = isolated_state / "presets"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "solo-dev.json").write_text(json.dumps({"custom": True}), encoding="utf-8")
    res = get_preset("solo-dev")
    assert res.ok and res.source == "user"
    assert res.data["custom"] is True


def test_list_includes_builtins(isolated_state):
    presets = list_presets()
    for name in ("solo-dev", "team-oss", "enterprise-strict", "zerotrust"):
        assert name in presets
