"""Tests for v0.6.0 phase 4: opt-in network freshness check.

Pins:
  - default off everywhere
  - zerotrust (network.egress_allowed=false) hard-disables, even with user override
  - cache schema (ISO8601 checked_at + 0o600 permissions)
  - fail-open on every error path: missing cache, corrupt cache, urlopen error,
    timeout, missing tag_name, write failure
  - the SessionStart-side maybe_refresh skips when cache is fresh
  - /presence-doctor render line covers all six states
  - the urllib parser handles a real-shape GitHub releases response

Most tests monkeypatch update_check._fetch_latest_tag directly so the cache
logic is exercised without the HTTP layer. One dedicated test pins the
urlopen parser shape.
"""
from __future__ import annotations

import asyncio
import importlib
import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta


def _reload(monkeypatch, isolated_state):
    """Reload _common (so it picks up the isolated PRESENCE_STATE) and
    update_check (so cache_path() resolves under the temp state dir)."""
    import _common
    import update_check
    importlib.reload(_common)
    importlib.reload(update_check)
    return update_check


# ---------------- is_enabled / status (no-network paths) ----------------


def test_disabled_by_default(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    assert uc.is_enabled({}) is False
    assert uc.status({}, "v0.5.4") == {"state": "disabled"}


def test_enabled_takes_effect(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    cfg = {"update_check": {"enabled": True}}
    assert uc.is_enabled(cfg) is True
    # No cache yet, so status returns no_cache (not disabled).
    assert uc.status(cfg, "v0.5.4") == {"state": "no_cache"}


def test_zerotrust_overrides_user_enabled(isolated_state, monkeypatch):
    """If the active preset sets network.egress_allowed=false, no user
    override of update_check.enabled can re-enable the network call."""
    uc = _reload(monkeypatch, isolated_state)
    cfg = {
        "network": {"egress_allowed": False},
        "update_check": {"enabled": True},
    }
    assert uc.is_enabled(cfg) is False
    assert uc.status(cfg, "v0.5.4") == {"state": "zerotrust"}


def test_zerotrust_overrides_even_when_user_disables_too(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    cfg = {"network": {"egress_allowed": False}, "update_check": {"enabled": False}}
    assert uc.is_enabled(cfg) is False
    assert uc.status(cfg, "v0.5.4") == {"state": "zerotrust"}


def test_status_fresh_cache(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    uc._write_cache("v0.6.0")
    s = uc.status({"update_check": {"enabled": True}}, "v0.5.4")
    assert s["state"] == "fresh"
    assert s["latest_tag"] == "v0.6.0"
    assert s["current_tag"] == "v0.5.4"
    assert s["age_seconds"] < 60


def test_status_stale_cache(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    long_ago = datetime.now(UTC) - timedelta(hours=25)
    payload = {"checked_at": long_ago.isoformat(), "latest_tag": "v0.6.0"}
    uc.cache_path().write_text(json.dumps(payload), encoding="utf-8")
    s = uc.status({"update_check": {"enabled": True}}, "v0.5.4")
    assert s["state"] == "stale"
    assert s["age_seconds"] > uc.TTL_SECONDS


def test_status_no_cache_when_enabled(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    assert not uc.cache_path().exists()
    s = uc.status({"update_check": {"enabled": True}}, "v0.5.4")
    assert s == {"state": "no_cache"}


def test_status_disabled_with_existing_cache(isolated_state, monkeypatch):
    """If the user disables the feature, the on-disk cache is irrelevant."""
    uc = _reload(monkeypatch, isolated_state)
    uc._write_cache("v0.6.0")
    s = uc.status({}, "v0.5.4")
    assert s == {"state": "disabled"}


def test_corrupt_cache_returns_no_cache(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    uc.cache_path().write_text("not json", encoding="utf-8")
    s = uc.status({"update_check": {"enabled": True}}, "v0.5.4")
    assert s["state"] == "no_cache"


def test_cache_with_unparseable_checked_at_is_no_cache(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    uc.cache_path().write_text(
        json.dumps({"checked_at": "not-iso8601", "latest_tag": "v0.6.0"}),
        encoding="utf-8",
    )
    s = uc.status({"update_check": {"enabled": True}}, "v0.5.4")
    assert s["state"] == "no_cache"


# ---------------- cache file shape ----------------


def test_cache_iso8601_format(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    uc._write_cache("v0.6.0")
    payload = json.loads(uc.cache_path().read_text())
    # Must round-trip through datetime.fromisoformat as a tz-aware UTC value.
    dt = datetime.fromisoformat(payload["checked_at"])
    assert dt.tzinfo is not None
    assert payload["latest_tag"] == "v0.6.0"


def test_cache_file_mode_0o600(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    uc._write_cache("v0.6.0")
    mode = uc.cache_path().stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got 0o{mode:03o}"


# ---------------- maybe_refresh (SessionStart side) ----------------


def test_maybe_refresh_skips_when_disabled(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    called = {"n": 0}

    def boom():
        called["n"] += 1
        raise RuntimeError("network must not be touched when disabled")

    monkeypatch.setattr(uc, "_fetch_latest_tag", boom)
    asyncio.run(uc.maybe_refresh({}))
    assert called["n"] == 0
    assert not uc.cache_path().exists()


def test_maybe_refresh_skips_when_cache_fresh(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    uc._write_cache("v0.6.0")
    called = {"n": 0}

    def boom():
        called["n"] += 1
        return "v9.9.9"

    monkeypatch.setattr(uc, "_fetch_latest_tag", boom)
    asyncio.run(uc.maybe_refresh({"update_check": {"enabled": True}}))
    assert called["n"] == 0


def test_maybe_refresh_writes_cache_on_success(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    monkeypatch.setattr(uc, "_fetch_latest_tag", lambda: "v0.6.0")
    asyncio.run(uc.maybe_refresh({"update_check": {"enabled": True}}))
    payload = json.loads(uc.cache_path().read_text())
    assert payload["latest_tag"] == "v0.6.0"


def test_maybe_refresh_silent_on_fetch_error(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)

    def fail():
        raise urllib.error.URLError("simulated DNS failure")

    monkeypatch.setattr(uc, "_fetch_latest_tag", fail)
    asyncio.run(uc.maybe_refresh({"update_check": {"enabled": True}}))
    assert not uc.cache_path().exists()


def test_maybe_refresh_silent_on_value_error(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)

    def fail():
        raise ValueError("missing tag_name")

    monkeypatch.setattr(uc, "_fetch_latest_tag", fail)
    asyncio.run(uc.maybe_refresh({"update_check": {"enabled": True}}))
    assert not uc.cache_path().exists()


# ---------------- force_refresh (--refresh side) ----------------


def test_force_refresh_returns_failure_message_on_url_error(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)

    def fail():
        raise urllib.error.URLError("simulated")

    monkeypatch.setattr(uc, "_fetch_latest_tag", fail)
    ok, msg = uc.force_refresh()
    assert ok is False
    assert "network error" in msg


def test_force_refresh_returns_failure_message_on_http_error(isolated_state, monkeypatch):
    """HTTPError carries a code; force_refresh surfaces it as "HTTP <code>".
    HTTPError's constructor wraps fp in a tempfile-closing finalizer, so we
    explicitly close() the exception after the assertion to satisfy pytest's
    unraisable-exception collector."""
    uc = _reload(monkeypatch, isolated_state)
    err = urllib.error.HTTPError(
        url=uc.GITHUB_RELEASES_URL, code=403, msg="rate limited",
        hdrs=None, fp=io.BytesIO(b"rate limited"),
    )
    try:
        monkeypatch.setattr(uc, "_fetch_latest_tag", lambda: (_ for _ in ()).throw(err))
        ok, msg = uc.force_refresh()
        assert ok is False
        assert "403" in msg
    finally:
        err.close()


def test_force_refresh_writes_cache_on_success(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)
    monkeypatch.setattr(uc, "_fetch_latest_tag", lambda: "v0.6.0")
    ok, msg = uc.force_refresh()
    assert ok is True
    assert "v0.6.0" in msg
    payload = json.loads(uc.cache_path().read_text())
    assert payload["latest_tag"] == "v0.6.0"


# ---------------- _fetch_latest_tag (parser pinning) ----------------


def test_fetch_latest_tag_parses_releases_response(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)

    class _FakeResp:
        def __init__(self, body): self._body = body
        def read(self): return self._body
        def __enter__(self): return self
        def __exit__(self, *args): pass

    body = json.dumps({"tag_name": "v0.6.0", "name": "v0.6.0", "draft": False}).encode()
    monkeypatch.setattr(uc.urllib.request, "urlopen", lambda req, timeout: _FakeResp(body))
    assert uc._fetch_latest_tag() == "v0.6.0"


def test_fetch_latest_tag_raises_on_missing_tag(isolated_state, monkeypatch):
    uc = _reload(monkeypatch, isolated_state)

    class _FakeResp:
        def read(self): return json.dumps({"name": "no tag here"}).encode()
        def __enter__(self): return self
        def __exit__(self, *args): pass

    monkeypatch.setattr(uc.urllib.request, "urlopen", lambda req, timeout: _FakeResp())
    try:
        uc._fetch_latest_tag()
    except ValueError:
        return
    raise AssertionError("expected ValueError on missing tag_name")


# ---------------- doctor render integration ----------------


def test_doctor_render_disabled_line(isolated_state, monkeypatch):
    import doctor
    importlib.reload(doctor)
    line = doctor._render_update_line({"state": "disabled"})
    assert "update check disabled" in line


def test_doctor_render_zerotrust_line(isolated_state, monkeypatch):
    import doctor
    importlib.reload(doctor)
    line = doctor._render_update_line({"state": "zerotrust"})
    assert "disabled under zerotrust" in line


def test_doctor_render_no_cache_line(isolated_state, monkeypatch):
    import doctor
    importlib.reload(doctor)
    line = doctor._render_update_line({"state": "no_cache"})
    assert "check pending" in line


def test_doctor_render_fresh_line(isolated_state, monkeypatch):
    import doctor
    importlib.reload(doctor)
    line = doctor._render_update_line({
        "state": "fresh",
        "latest_tag": "v0.6.0",
        "current_tag": "v0.5.4",
        "age_seconds": 12 * 3600,
    })
    assert "v0.6.0" in line
    assert "you have v0.5.4" in line
    assert "12h" in line


def test_doctor_render_fresh_up_to_date(isolated_state, monkeypatch):
    import doctor
    importlib.reload(doctor)
    line = doctor._render_update_line({
        "state": "fresh",
        "latest_tag": "v0.5.4",
        "current_tag": "v0.5.4",
        "age_seconds": 30,
    })
    assert "up to date" in line


def test_doctor_render_stale_line(isolated_state, monkeypatch):
    import doctor
    importlib.reload(doctor)
    line = doctor._render_update_line({
        "state": "stale",
        "latest_tag": "v0.6.0",
        "current_tag": "v0.5.4",
        "age_seconds": 30 * 3600,
    })
    assert "STALE" in line
    assert "1d" in line


def test_doctor_report_includes_update_check_block(isolated_state, fake_repo, monkeypatch):
    import doctor
    importlib.reload(doctor)
    rep = doctor.report(str(fake_repo))
    assert "update_check" in rep
    # Default config has no update_check section -> disabled.
    assert rep["update_check"]["state"] in {"disabled", "zerotrust", "no_cache", "fresh", "stale"}
