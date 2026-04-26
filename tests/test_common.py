"""Foundations: repo_id, atomic_write, settings, hook_input."""
import json

import _common
import pytest


def test_repo_id_for_git_repo(isolated_state, fake_repo):
    rid = _common.repo_id()
    assert isinstance(rid, str) and len(rid) == 12


def test_repo_id_stable(isolated_state, fake_repo):
    a = _common.repo_id()
    b = _common.repo_id()
    assert a == b


def test_repo_id_for_non_git_dir(isolated_state, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rid = _common.repo_id()
    assert isinstance(rid, str) and len(rid) == 12


def test_atomic_write_creates_file(isolated_state, tmp_path):
    p = tmp_path / "target" / "file.txt"
    _common.atomic_write(p, "hello")
    assert p.read_text() == "hello"


def test_atomic_write_overwrites(isolated_state, tmp_path):
    p = tmp_path / "f"
    _common.atomic_write(p, "a")
    _common.atomic_write(p, "b")
    assert p.read_text() == "b"


def test_settings_missing_returns_default(isolated_state):
    s = _common.settings()
    # solo-dev preset should be loaded from PLUGIN_ROOT
    assert isinstance(s, dict)


def test_settings_corrupt_warns_and_defaults(isolated_state):
    (_common.state_dir() / "settings.json").write_text("{not json", encoding="utf-8")
    s = _common.settings()
    assert isinstance(s, dict)


def test_settings_corrupt_strict_raises(isolated_state):
    (_common.state_dir() / "settings.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(_common.SettingsError):
        _common.settings(strict=True)


def test_hook_input_empty(monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert _common.hook_input() == {}


def test_hook_input_valid(monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO('{"cwd": "/tmp"}'))
    assert _common.hook_input() == {"cwd": "/tmp"}


def test_hook_input_malformed(monkeypatch, isolated_state):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    assert _common.hook_input() == {}


def test_hook_input_non_dict_returns_empty(monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("[1,2,3]"))
    assert _common.hook_input() == {}


def test_state_dir_perms(isolated_state):
    import stat
    s = _common.state_dir()
    mode = stat.S_IMODE(s.stat().st_mode)
    assert mode == 0o700


def test_dotted_settings_override(isolated_state):
    settings_file = _common.state_dir() / "settings.json"
    settings_file.write_text(
        json.dumps({"preset": "solo-dev", "overrides": {"model.max_tokens": 1234}}),
        encoding="utf-8",
    )
    s = _common.settings()
    assert s.get("model", {}).get("max_tokens") == 1234


def test_dotted_settings_override_creates_section(isolated_state):
    settings_file = _common.state_dir() / "settings.json"
    settings_file.write_text(
        json.dumps({"overrides": {"new_section.key": "value"}}),
        encoding="utf-8",
    )
    s = _common.settings()
    assert s.get("new_section", {}).get("key") == "value"


def test_counter_lifecycle(isolated_state):
    assert _common.read_counter("error") == 0
    _common._bump_counter("error")
    _common._bump_counter("error")
    assert _common.read_counter("error") == 2
    _common.reset_counter("error")
    assert _common.read_counter("error") == 0
