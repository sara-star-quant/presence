"""Tests for doctor.py's report()/render(): notify status + confidence-gate stats.

These reconstruct preset history purely from audit.jsonl's preset_switch
events, without stamping confidence.jsonl rows -- see _confidence_stats()'s
docstring in lib/doctor.py.
"""
from __future__ import annotations

import importlib

import _common
import doctor


def _reload_modules_with_isolated_state(state_dir, monkeypatch):
    monkeypatch.setenv("PRESENCE_STATE", str(state_dir))
    importlib.reload(_common)
    importlib.reload(doctor)
    return doctor


def test_notify_summary_reflects_settings_without_leaking_url(isolated_state, monkeypatch):
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    settings_path = isolated_state / "settings.json"
    settings_path.write_text(
        '{"overrides": {"notify.enabled": true, "notify.webhook_url": "https://hooks.example/secret-path"}}',
        encoding="utf-8",
    )
    rep = d.report(cwd=".")
    assert rep["notify"] == {
        "enabled": True, "webhook_configured": True, "blocked_by_zerotrust": False, "active": True,
    }
    rendered = d.render(rep)
    assert "https://hooks.example/secret-path" not in rendered
    import json
    assert "https://hooks.example/secret-path" not in json.dumps(rep)


def test_notify_summary_disabled_by_default(isolated_state, monkeypatch):
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    rep = d.report(cwd=".")
    assert rep["notify"] == {
        "enabled": False, "webhook_configured": False, "blocked_by_zerotrust": False, "active": False,
    }


def test_notify_summary_blocked_by_zerotrust_even_if_enabled(isolated_state, monkeypatch):
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    (isolated_state / "settings.json").write_text(
        '{"overrides": {"network.egress_allowed": false, '
        '"notify.enabled": true, "notify.webhook_url": "https://hooks.example/secret-path"}}',
        encoding="utf-8",
    )
    rep = d.report(cwd=".")
    assert rep["notify"]["blocked_by_zerotrust"] is True
    assert rep["notify"]["active"] is False
    rendered = d.render(rep)
    assert "BLOCKED by zerotrust" in rendered


def test_confidence_stats_no_switches_lands_under_active_preset(isolated_state, monkeypatch):
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    from telemetry import confidence_path
    from _common import append_jsonl_rotating

    append_jsonl_rotating(confidence_path(), {"ts": 100, "claim": "unhedged_success", "verified": True})
    append_jsonl_rotating(confidence_path(), {"ts": 200, "claim": "unhedged_success", "verified": False})

    rep = d.report(cwd=".")
    stats = rep["confidence_stats"]
    assert stats["all_time"] == {"total": 2, "caught": 1, "passed": 1}
    assert stats["by_preset"] == {"solo-dev": {"total": 2, "caught": 1, "passed": 1}}


def test_confidence_stats_bucketed_and_summed_across_repeated_preset(isolated_state, monkeypatch):
    """Switches solo-dev -> zerotrust (ts=100) -> solo-dev (ts=200); rows land
    in the right window and solo-dev's two separate windows are summed."""
    d = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    from telemetry import confidence_path
    from audit import audit_path
    from _common import append_jsonl_rotating

    append_jsonl_rotating(audit_path(), {
        "ts": 100, "event": "preset_switch",
        "details": {"new_preset": "zerotrust", "previous": "solo-dev"},
    })
    append_jsonl_rotating(audit_path(), {
        "ts": 200, "event": "preset_switch",
        "details": {"new_preset": "solo-dev", "previous": "zerotrust"},
    })

    # before first switch: solo-dev
    append_jsonl_rotating(confidence_path(), {"ts": 50, "claim": "unhedged_success", "verified": True})
    # during zerotrust window
    append_jsonl_rotating(confidence_path(), {"ts": 150, "claim": "unhedged_success", "verified": False})
    # after switching back to solo-dev
    append_jsonl_rotating(confidence_path(), {"ts": 250, "claim": "unhedged_success", "verified": False})

    rep = d.report(cwd=".")
    stats = rep["confidence_stats"]
    assert stats["all_time"] == {"total": 3, "caught": 2, "passed": 1}
    assert stats["by_preset"] == {
        "solo-dev": {"total": 2, "caught": 1, "passed": 1},
        "zerotrust": {"total": 1, "caught": 1, "passed": 0},
    }
    totals = {"total": 0, "caught": 0, "passed": 0}
    for t in stats["by_preset"].values():
        for k in totals:
            totals[k] += t[k]
    assert totals == stats["all_time"]
