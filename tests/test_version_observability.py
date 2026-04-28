"""Tests for v0.6.0 version-observability surfaces:
  - lib/_common.check_ext_compat() (phase 3)
  - lib/doctor._version_observability + render() integration (phase 2)
  - lib/hook_session_start.gather_version_warn (phase 3)

Fail-open contract from docs/ROADMAP.md "Version observability and freshness":
  Any import error or unparseable version -> silent, no warning.
  The subprocess fallback (lib/telemetry.py, lib/crypto.py) handles ext absence
  silently; a stale ext should warn-but-never-block.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types


def _install_fake_ext(monkeypatch, version):
    """Inject a fake `presence_ext` module into sys.modules.

    `version` may be a str (sets __version__), None (no attribute), or the
    sentinel `"DELETE"` to simulate ImportError on subsequent import.
    """
    if version == "DELETE":
        monkeypatch.delitem(sys.modules, "presence_ext", raising=False)
        # Block re-import via meta_path: insert a finder that raises.
        class _Blocker:
            def find_module(self, name, path=None):
                return self if name == "presence_ext" else None
            def find_spec(self, name, path=None, target=None):
                if name == "presence_ext":
                    raise ImportError("blocked for test")
        blocker = _Blocker()
        monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
        return
    m = types.ModuleType("presence_ext")
    if version is not None:
        m.__version__ = version
    monkeypatch.setitem(sys.modules, "presence_ext", m)


# ---------------- check_ext_compat ----------------


def test_check_ext_compat_absent_is_silent(monkeypatch):
    """ext not installed -> (True, None, None). The subprocess fallback handles this."""
    _install_fake_ext(monkeypatch, "DELETE")
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is True
    assert ver is None
    assert msg is None


def test_check_ext_compat_no_version_attr_is_silent(monkeypatch):
    """ext loaded but missing __version__ -> fail-open (True, None, None)."""
    _install_fake_ext(monkeypatch, None)
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is True
    assert ver is None
    assert msg is None


def test_check_ext_compat_empty_version_is_silent(monkeypatch):
    """ext.__version__ == '' -> fail-open."""
    _install_fake_ext(monkeypatch, "")
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is True
    assert ver is None
    assert msg is None


def test_check_ext_compat_at_min_is_ok(monkeypatch):
    """ext exactly at _MIN_EXT_VERSION -> OK."""
    import __init__ as plugin_init
    _install_fake_ext(monkeypatch, plugin_init._MIN_EXT_VERSION)
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is True
    assert ver == plugin_init._MIN_EXT_VERSION
    assert msg is None


def test_check_ext_compat_above_min_is_ok(monkeypatch):
    _install_fake_ext(monkeypatch, "999.0.0")
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is True
    assert ver == "999.0.0"
    assert msg is None


def test_check_ext_compat_below_min_is_stale(monkeypatch):
    """ext older than _MIN_EXT_VERSION -> (False, ver, msg with fix hint)."""
    _install_fake_ext(monkeypatch, "0.0.1")
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is False
    assert ver == "0.0.1"
    assert msg is not None
    assert "0.0.1" in msg
    assert "install.sh --update --build-ext" in msg


def test_check_ext_compat_unparseable_is_silent(monkeypatch):
    """ROADMAP fail-open contract: unparseable version -> silent, no warning.
    The original implementation regressed here (returned stale); this pins it.
    """
    _install_fake_ext(monkeypatch, "garbage-not-semver")
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is True, f"unparseable version must fail-open silent, got {(ok, ver, msg)}"
    assert msg is None


def test_check_ext_compat_version_with_suffix_parses(monkeypatch):
    """0.2.0-rc1 should parse as 0.2.0 and meet a 0.2.0 minimum."""
    _install_fake_ext(monkeypatch, "0.2.0-rc1")
    import _common
    importlib.reload(_common)
    ok, ver, msg = _common.check_ext_compat()
    assert ok is True
    assert ver == "0.2.0-rc1"


# ---------------- doctor _version_observability + render ----------------


def test_doctor_report_includes_version_observability_block(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "999.0.0")
    import _common
    import doctor
    importlib.reload(_common)
    importlib.reload(doctor)
    rep = doctor.report(str(fake_repo))
    vo = rep.get("version_observability")
    assert vo is not None
    assert set(vo.keys()) >= {
        "plugin_version", "ext_version", "min_ext_version",
        "ext_compat_ok", "ext_compat_message",
    }
    assert vo["ext_version"] == "999.0.0"
    assert vo["ext_compat_ok"] is True


def test_doctor_render_shows_plugin_version(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "999.0.0")
    import __init__ as plugin_init
    import _common
    import doctor
    importlib.reload(_common)
    importlib.reload(doctor)
    out = doctor.render(doctor.report(str(fake_repo)))
    assert f"plugin       : v{plugin_init.__version__}" in out


def test_doctor_render_ok_line_when_ext_meets_min(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "999.0.0")
    import _common
    import doctor
    importlib.reload(_common)
    importlib.reload(doctor)
    out = doctor.render(doctor.report(str(fake_repo)))
    assert "ext (rust)   : 999.0.0" in out
    assert "OK" in out


def test_doctor_render_not_installed_line_when_ext_absent(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "DELETE")
    import _common
    import doctor
    importlib.reload(_common)
    importlib.reload(doctor)
    out = doctor.render(doctor.report(str(fake_repo)))
    assert "ext (rust)   : not installed" in out


def test_doctor_render_stale_line_when_ext_below_min(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "0.0.1")
    import _common
    import doctor
    importlib.reload(_common)
    importlib.reload(doctor)
    out = doctor.render(doctor.report(str(fake_repo)))
    assert "ext (rust)   : 0.0.1" in out
    assert "STALE" in out
    assert "install.sh --update --build-ext" in out


# ---------------- gather_version_warn ----------------


def test_gather_version_warn_returns_empty_string(monkeypatch, isolated_state, fake_repo):
    """Surface is the warnings banner (gather_warnings), not an inline block."""
    _install_fake_ext(monkeypatch, "999.0.0")
    import _common
    import hook_session_start
    importlib.reload(_common)
    importlib.reload(hook_session_start)
    result = asyncio.run(hook_session_start.gather_version_warn())
    assert result == ""


def test_gather_version_warn_emits_on_stale_ext(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "0.0.1")
    import _common
    import hook_session_start
    importlib.reload(_common)
    importlib.reload(hook_session_start)
    from warnings_log import clear_warnings_state, read_warnings
    clear_warnings_state()
    asyncio.run(hook_session_start.gather_version_warn())
    warnings = read_warnings()
    matching = [w for w in warnings if w.get("category") == "ext_version_stale"]
    assert len(matching) == 1, f"expected 1 ext_version_stale warning, got {warnings!r}"
    assert "fix" in matching[0]
    assert "install.sh --update --build-ext" in matching[0]["fix"]


def test_gather_version_warn_silent_when_ok(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "999.0.0")
    import _common
    import hook_session_start
    importlib.reload(_common)
    importlib.reload(hook_session_start)
    from warnings_log import clear_warnings_state, read_warnings
    clear_warnings_state()
    asyncio.run(hook_session_start.gather_version_warn())
    warnings = [w for w in read_warnings() if w.get("category") == "ext_version_stale"]
    assert warnings == []


def test_gather_version_warn_silent_when_ext_absent(monkeypatch, isolated_state, fake_repo):
    _install_fake_ext(monkeypatch, "DELETE")
    import _common
    import hook_session_start
    importlib.reload(_common)
    importlib.reload(hook_session_start)
    from warnings_log import clear_warnings_state, read_warnings
    clear_warnings_state()
    asyncio.run(hook_session_start.gather_version_warn())
    warnings = [w for w in read_warnings() if w.get("category") == "ext_version_stale"]
    assert warnings == []


def test_gather_version_warn_does_not_nag_across_sessions(monkeypatch, isolated_state, fake_repo):
    """Stale ext should warn ONCE per ext upgrade, not every SessionStart.
    Uses warn_once semantics so the warning counter doesn't stay pinned at 1+
    every session for a user who hasn't yet upgraded.
    """
    _install_fake_ext(monkeypatch, "0.0.1")
    import _common
    import hook_session_start
    importlib.reload(_common)
    importlib.reload(hook_session_start)
    from warnings_log import clear_warnings_state, read_warnings
    clear_warnings_state()
    asyncio.run(hook_session_start.gather_version_warn())
    asyncio.run(hook_session_start.gather_version_warn())
    asyncio.run(hook_session_start.gather_version_warn())
    matching = [w for w in read_warnings() if w.get("category") == "ext_version_stale"]
    assert len(matching) == 1, (
        f"expected exactly 1 ext_version_stale warning across 3 SessionStarts, "
        f"got {len(matching)}: {matching!r}"
    )
