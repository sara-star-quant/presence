"""warn() and warn_once() accept an optional fix= recovery hint (added v0.3.4).

Backward compat is critical: 14 existing callers do not pass fix=. None should
break. Doctor render must surface the fix line when present and not when absent.
"""
from __future__ import annotations

import importlib
import json

import _common
import doctor
import warnings_log


def test_warn_with_fix_writes_fix_field(isolated_state):
    importlib.reload(_common)
    importlib.reload(warnings_log)
    warnings_log.warn("test_cat", "test message", fix="run /presence-reset")
    rows = warnings_log.read_warnings()
    assert len(rows) >= 1
    assert rows[-1]["fix"] == "run /presence-reset"
    assert rows[-1]["category"] == "test_cat"
    assert rows[-1]["message"] == "test message"


def test_warn_without_fix_omits_fix_field(isolated_state):
    importlib.reload(_common)
    importlib.reload(warnings_log)
    warnings_log.warn("test_cat", "no recovery hint here")
    rows = warnings_log.read_warnings()
    assert len(rows) >= 1
    assert "fix" not in rows[-1]
    # Confirm the on-disk JSON also omits the key (no null).
    raw = (warnings_log.WARNINGS_PATH()).read_text(encoding="utf-8").strip().splitlines()[-1]
    parsed = json.loads(raw)
    assert "fix" not in parsed


def test_warn_once_passes_fix_through(isolated_state):
    importlib.reload(_common)
    importlib.reload(warnings_log)
    warnings_log.warn_once("once_cat", "first time", fix="do the thing")
    # Second call with same category is a no-op.
    warnings_log.warn_once("once_cat", "second time should not record", fix="ignored")
    rows = warnings_log.read_warnings()
    one_cat = [r for r in rows if r["category"] == "once_cat"]
    assert len(one_cat) == 1
    assert one_cat[0]["fix"] == "do the thing"
    assert one_cat[0]["message"] == "first time"


def test_doctor_render_shows_fix_line(isolated_state, tmp_path, monkeypatch):
    importlib.reload(_common)
    importlib.reload(warnings_log)
    importlib.reload(doctor)
    warnings_log.warn("with_fix", "something needs attention", fix="install foo from https://example.com")
    warnings_log.warn("without_fix", "no recovery hint")
    monkeypatch.chdir(tmp_path)
    rep = doctor.report(str(tmp_path))
    rendered = doctor.render(rep)
    # Fix line appears under the warning that has one.
    assert "install foo from https://example.com" in rendered
    # The bare 'fix:' string should appear exactly once (only the one warning).
    assert rendered.count("    fix:") == 1


def test_doctor_json_includes_fix(isolated_state, tmp_path, monkeypatch):
    importlib.reload(_common)
    importlib.reload(warnings_log)
    importlib.reload(doctor)
    warnings_log.warn("json_test", "msg", fix="recovery here")
    monkeypatch.chdir(tmp_path)
    rep = doctor.report(str(tmp_path))
    fixes = [w.get("fix") for w in rep["recent_warnings"]]
    assert "recovery here" in fixes


def test_existing_callers_still_work_without_fix(isolated_state):
    """The 14 existing call sites that pass no fix= still work unchanged.
    Smoke check: invoke a warn that mirrors a real caller pattern."""
    importlib.reload(_common)
    importlib.reload(warnings_log)
    warnings_log.warn("git_timeout", "git rev-parse timed out", cmd=["rev-parse"])
    rows = warnings_log.read_warnings()
    assert len(rows) >= 1
    assert rows[-1]["category"] == "git_timeout"
    assert rows[-1]["details"] == {"cmd": ["rev-parse"]}
    assert "fix" not in rows[-1]
