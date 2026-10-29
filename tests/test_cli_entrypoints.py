"""CLI entry points of snapshot, bugreport and the notify detached child."""
from __future__ import annotations

import io
import json
import sys
import urllib.error

import bugreport
import notify
import snapshot


def _argv(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["prog", *args])


def test_snapshot_cli_roundtrip_and_error(isolated_state, tmp_path, monkeypatch, capsys):
    (isolated_state / "marker.txt").write_text("x")
    out = tmp_path / "s.tar.gz"
    _argv(monkeypatch, "snapshot", str(out))
    assert snapshot._cli() == 0 and "wrote" in capsys.readouterr().out
    _argv(monkeypatch, "restore", str(out))
    assert snapshot._cli() == 1 and "error:" in capsys.readouterr().err
    _argv(monkeypatch, "restore", str(out), "--overwrite")
    assert snapshot._cli() == 0 and "restored from" in capsys.readouterr().out


def test_bugreport_cli_json_and_markdown(isolated_state, monkeypatch, capsys):
    _argv(monkeypatch, "--cwd", str(isolated_state))
    assert bugreport._cli() == 0
    assert isinstance(json.loads(capsys.readouterr().out), dict)
    _argv(monkeypatch, "--cwd", str(isolated_state), "--md")
    assert bugreport._cli() == 0
    assert "State sizes" in capsys.readouterr().out


def test_notify_send_from_stdin_posts_payload(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["data"] = req.full_url, req.data

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Ctx()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(b'{"k":1}')})())
    notify._send_from_stdin("https://hooks.example/x")
    assert seen == {"url": "https://hooks.example/x", "data": b'{"k":1}'}


def test_notify_send_from_stdin_swallows_network_errors(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(b"{}")})())
    notify._send_from_stdin("https://hooks.example/x")
