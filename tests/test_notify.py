"""Tests for lib/notify.py: opt-in gating, redaction, and non-blocking dispatch."""
from __future__ import annotations

import importlib
import json
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler

import _common
import notify


def _reload_modules_with_isolated_state(state_dir, monkeypatch):
    monkeypatch.setenv("PRESENCE_STATE", str(state_dir))
    importlib.reload(_common)
    importlib.reload(notify)
    return notify


def _write_notify_settings(state_dir, url: str) -> None:
    (state_dir / "settings.json").write_text(
        json.dumps({"overrides": {"notify.enabled": True, "notify.webhook_url": url}}),
        encoding="utf-8",
    )


def test_disabled_by_default_never_dispatches(isolated_state, monkeypatch):
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    calls = []
    monkeypatch.setattr(n, "_dispatch", lambda url, payload: calls.append((url, payload)))
    n.notify_confidence("unhedged_success", True, final_excerpt="all good")
    assert calls == []


def test_enabled_without_url_never_dispatches(isolated_state, monkeypatch):
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    (isolated_state / "settings.json").write_text(
        json.dumps({"overrides": {"notify.enabled": True}}), encoding="utf-8"
    )
    calls = []
    monkeypatch.setattr(n, "_dispatch", lambda url, payload: calls.append((url, payload)))
    n.notify_confidence("unhedged_success", True, final_excerpt="all good")
    assert calls == []


def test_non_http_scheme_never_dispatches(isolated_state, monkeypatch):
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    _write_notify_settings(isolated_state, "file:///etc/passwd")
    calls = []
    monkeypatch.setattr(n, "_dispatch", lambda url, payload: calls.append((url, payload)))
    n.notify_confidence("unhedged_success", True, final_excerpt="all good")
    assert calls == []


def test_zerotrust_egress_block_wins_even_if_notify_is_enabled(isolated_state, monkeypatch):
    """network.egress_allowed: false must hard-disable notify regardless of
    notify.enabled -- the same two-layer gate update_check.is_enabled() uses,
    so a stray override under zerotrust can't reach the network."""
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    (isolated_state / "settings.json").write_text(
        json.dumps({
            "overrides": {
                "network.egress_allowed": False,
                "notify.enabled": True,
                "notify.webhook_url": "https://example.invalid/hook",
            }
        }),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(n, "_dispatch", lambda url, payload: calls.append((url, payload)))
    n.notify_confidence("unhedged_success", False, final_excerpt="fine")
    assert calls == []


def test_final_excerpt_is_redacted_before_dispatch(isolated_state, monkeypatch):
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    _write_notify_settings(isolated_state, "https://example.invalid/hook")
    calls = []
    monkeypatch.setattr(n, "_dispatch", lambda url, payload: calls.append((url, payload)))
    n.notify_confidence("unhedged_success", False, final_excerpt="key is AKIAABCDEFGHIJKLMNOP done")
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://example.invalid/hook"
    assert "AKIAABCDEFGHIJKLMNOP" not in payload["final_excerpt"]
    assert payload["claim"] == "unhedged_success"
    assert payload["verified"] is False


def test_dispatch_returns_immediately_even_against_a_slow_endpoint(isolated_state, monkeypatch):
    """The bug this guards against: notify_confidence() used to POST inline
    with a 5s timeout directly in the Stop hook's path. _dispatch() must hand
    the request off to a detached subprocess and return right away."""
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            time.sleep(2)
            received["body"] = json.loads(body)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    try:
        n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
        url = f"http://127.0.0.1:{port}/hook"
        _write_notify_settings(isolated_state, url)

        start = time.time()
        n.notify_confidence("unhedged_success", False, final_excerpt="fine")
        elapsed = time.time() - start
        assert elapsed < 1.0, f"notify_confidence() blocked for {elapsed:.2f}s waiting on a slow endpoint"

        deadline = time.time() + 5
        while "body" not in received and time.time() < deadline:
            time.sleep(0.1)
        assert received.get("body", {}).get("claim") == "unhedged_success"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_plain_http_to_a_remote_host_never_dispatches(isolated_state, monkeypatch):
    """A webhook over http sends redacted claim text in the clear and lets anyone on the path edit it."""
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    calls = []
    monkeypatch.setattr(n, "_dispatch", lambda url, payload: calls.append((url, payload)))
    for url in ("http://hooks.example.com/x", "http://127.0.0.1.evil.example/x", "http://localhost.evil.example/x"):
        _write_notify_settings(isolated_state, url)
        n.notify_confidence("unhedged_success", True, final_excerpt="all good")
    assert calls == []


def test_loopback_http_and_remote_https_still_dispatch(isolated_state, monkeypatch):
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    calls = []
    monkeypatch.setattr(n, "_dispatch", lambda url, payload: calls.append(url))
    for url in ("http://127.0.0.1:8080/x", "http://localhost/x", "http://[::1]:9/x", "https://hooks.example.com/x"):
        _write_notify_settings(isolated_state, url)
        n.notify_confidence("unhedged_success", True, final_excerpt="all good")
    assert len(calls) == 4


def test_webhook_url_never_appears_in_the_child_argv(isolated_state, monkeypatch):
    """The URL is usually the secret (Slack and Zapier hooks are bearer URLs); argv is world-readable in ps."""
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    seen = {}

    class FakeProc:
        stdin = type("S", (), {"write": lambda self, b: seen.setdefault("stdin", b), "close": lambda self: None})()
        def wait(self): pass

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        return FakeProc()

    monkeypatch.setattr(n.subprocess, "Popen", fake_popen)
    n._dispatch("https://hooks.example.com/SECRET-TOKEN", {"claim": "c"})
    assert "SECRET-TOKEN" not in " ".join(seen["argv"])
    assert seen["stdin"].startswith(b"https://hooks.example.com/SECRET-TOKEN\n")


def test_a_rejected_webhook_url_is_reported_not_silent(isolated_state, monkeypatch):
    """An upgrade must not quietly turn off someone's notifications: doctor has to be able to say why."""
    n = _reload_modules_with_isolated_state(isolated_state, monkeypatch)
    _write_notify_settings(isolated_state, "http://hooks.example.com/x")
    n.notify_confidence("unhedged_success", True, final_excerpt="all good")
    log = (isolated_state / "logs" / "warnings.log").read_text()
    assert "notify_url_rejected" in log and "https" in log
