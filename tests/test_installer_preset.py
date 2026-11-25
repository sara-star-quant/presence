"""install.sh --preset: the preset is active before any hook can run, and an unsafe choice is refused."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def clone(tmp_path):
    """A scratch copy of the plugin, so a test can change a library file without touching the checkout."""
    c = tmp_path / "plugin"
    c.mkdir()
    for name in ("lib", "presets", ".claude-plugin", "hooks", "commands", "skills", "agents"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, c / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "presence-client"))
    shutil.copy2(ROOT / "install.sh", c / "install.sh")
    return c


def _env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("PRESENCE_PRESET", "CLAUDE_PLUGIN_ROOT")}
    env.update({"CLAUDE_HOME": str(tmp_path / "home"), "PRESENCE_STATE": str(tmp_path / "state"), **extra})
    return env


def _install(clone, tmp_path, *args, **env):
    return subprocess.run(["bash", str(clone / "install.sh"), *args], capture_output=True, text=True, check=False,
                          env=_env(tmp_path, **env), cwd=clone)


def _preset(tmp_path):
    f = tmp_path / "state" / "settings.json"
    return json.loads(f.read_text())["preset"] if f.exists() else None


def _link(tmp_path):
    return tmp_path / "home" / "plugins" / "presence"


def test_without_the_flag_nothing_is_written(clone, tmp_path):
    r = _install(clone, tmp_path)
    assert r.returncode == 0, r.stderr
    assert _preset(tmp_path) is None  # the default preset is simply the absence of a choice


@pytest.mark.parametrize("how", ["flag", "env"])
def test_a_named_preset_is_active_after_install(clone, tmp_path, how):
    r = _install(clone, tmp_path, *(("--preset", "team-oss") if how == "flag" else ()),
                 **({"PRESENCE_PRESET": "team-oss"} if how == "env" else {}))
    assert r.returncode == 0, r.stderr
    assert _preset(tmp_path) == "team-oss"
    assert "team-oss" in r.stdout and _link(tmp_path).is_symlink()


def test_the_state_the_preset_creates_is_private_to_the_user(clone, tmp_path):
    r = _install(clone, tmp_path, "--preset", "team-oss")
    assert r.returncode == 0, r.stderr
    state = tmp_path / "state"
    assert (state.stat().st_mode & 0o777) == 0o700
    assert ((state / "settings.json").stat().st_mode & 0o777) == 0o600


def test_an_unknown_preset_stops_the_install_before_the_plugin_is_registered(clone, tmp_path):
    r = _install(clone, tmp_path, "--preset", "no-such-preset")
    assert r.returncode != 0
    assert not _link(tmp_path).exists() and _preset(tmp_path) is None


@pytest.mark.parametrize("name", ["../evil", "a/b", "x y", ""])
def test_a_preset_name_that_is_not_a_plain_name_is_refused(clone, tmp_path, name):
    r = _install(clone, tmp_path, "--preset", name)
    assert r.returncode != 0 and not _link(tmp_path).exists()


def test_a_name_cannot_reach_a_preset_file_outside_the_presets_folder(clone, tmp_path):
    shutil.copy2(clone / "presets" / "team-oss.json", clone / "evil.json")
    r = _install(clone, tmp_path, "--preset", "../evil")
    assert r.returncode != 0 and _preset(tmp_path) is None and not _link(tmp_path).exists()


def _crypto(clone, available):
    (clone / "lib" / "crypto.py").write_text(
        "def is_available():\n    return " + ("True" if available else "False") + "\n"
        "def keychain_backend():\n    return None\n")


def test_zerotrust_is_refused_when_encryption_cannot_work(clone, tmp_path):
    _crypto(clone, available=False)
    r = _install(clone, tmp_path, "--preset", "zerotrust")
    assert r.returncode != 0
    assert "cryptography" in r.stderr and "plain text" in r.stderr
    assert not _link(tmp_path).exists() and _preset(tmp_path) is None


def test_zerotrust_is_activated_when_encryption_can_work(clone, tmp_path):
    _crypto(clone, available=True)
    r = _install(clone, tmp_path, "--preset", "zerotrust")
    assert r.returncode == 0, r.stderr
    assert _preset(tmp_path) == "zerotrust"


def test_the_flag_cannot_override_a_locked_zerotrust_install(clone, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "settings.json").write_text(json.dumps({"preset": "zerotrust"}))
    r = _install(clone, tmp_path, "--preset", "solo-dev")
    assert r.returncode != 0 and "immutable" in (r.stderr + r.stdout)
    assert _preset(tmp_path) == "zerotrust" and not _link(tmp_path).exists()


def test_earlier_plain_state_is_called_out_not_hidden(clone, tmp_path):
    ev = tmp_path / "state" / "events" / "abc"
    ev.mkdir(parents=True)
    (ev / "pending.jsonl").write_text('{"kind":"edit"}\n')
    r = _install(clone, tmp_path, "--preset", "team-oss")
    assert r.returncode == 0, r.stderr
    assert "existing state" in r.stdout + r.stderr and "/presence-reset" in r.stdout + r.stderr


def test_the_flag_without_a_name_is_refused(clone, tmp_path):
    r = _install(clone, tmp_path, "--preset")
    assert r.returncode != 0 and "--preset" in r.stderr and not _link(tmp_path).exists()


def test_the_flag_only_applies_to_install(clone, tmp_path):
    r = _install(clone, tmp_path, "--verify", "--preset", "team-oss")
    assert r.returncode != 0 and "--preset applies to install only" in r.stderr
    assert _preset(tmp_path) is None


def test_help_lists_the_flag():
    assert "--preset" in (ROOT / "install.sh").read_text()
