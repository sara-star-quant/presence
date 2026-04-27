"""Tests for lib/mcp_server.py (v0.4.1).

The MCP server is a small JSON-RPC dispatch over stdin/stdout. We exercise
the three real handlers (initialize, resources/list, resources/read), the
notification path (no response), and the two error codes (method not found,
internal error).

End-to-end stdio loop is also tested by piping input through a subprocess.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import mcp_server

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PY = REPO_ROOT / "lib" / "cli.py"
MCP_PY = REPO_ROOT / "lib" / "mcp_server.py"


def test_handle_initialize_returns_protocol_version_and_server_info():
    out = mcp_server.handle_initialize({})
    assert out["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert out["serverInfo"]["name"] == "presence-mcp"
    assert "capabilities" in out
    assert "resources" in out["capabilities"]


def test_handle_resources_list_lists_two_resources(isolated_state, fake_repo):
    out = mcp_server.handle_resources_list({})
    uris = [r["uri"] for r in out["resources"]]
    assert any(u.endswith("/model") for u in uris)
    assert any(u.endswith("/telemetry") for u in uris)
    # Each resource has the documented fields.
    for r in out["resources"]:
        assert "uri" in r and "name" in r and "description" in r and "mimeType" in r


def test_handle_resources_read_model_returns_markdown(isolated_state, fake_repo):
    from _common import project_dir
    project_dir().mkdir(parents=True, exist_ok=True)
    (project_dir() / "model.md").write_text("# test model\nhello", encoding="utf-8")

    list_out = mcp_server.handle_resources_list({})
    model_uri = next(r["uri"] for r in list_out["resources"] if r["uri"].endswith("/model"))

    read_out = mcp_server.handle_resources_read({"uri": model_uri})
    assert read_out["contents"][0]["mimeType"] == "text/markdown"
    assert read_out["contents"][0]["text"] == "# test model\nhello"


def test_handle_resources_read_model_when_missing_returns_empty(isolated_state, fake_repo):
    """If model.md does not exist (fresh repo), the read returns empty text
    rather than raising. Clients should be robust to a brand-new repo with
    no accumulated context."""
    list_out = mcp_server.handle_resources_list({})
    model_uri = next(r["uri"] for r in list_out["resources"] if r["uri"].endswith("/model"))
    read_out = mcp_server.handle_resources_read({"uri": model_uri})
    assert read_out["contents"][0]["text"] == ""


def test_handle_resources_read_telemetry_returns_json(isolated_state, fake_repo):
    """Telemetry resource returns JSON-formatted claims as a string blob,
    so MCP clients that don't auto-parse content can still display it."""
    from telemetry import claims_path
    claims_path().write_text(
        '{"ts":1,"kind":"commit","sha":"deadbeef"}\n',
        encoding="utf-8",
    )
    list_out = mcp_server.handle_resources_list({})
    tel_uri = next(r["uri"] for r in list_out["resources"] if r["uri"].endswith("/telemetry"))
    read_out = mcp_server.handle_resources_read({"uri": tel_uri})
    parsed = json.loads(read_out["contents"][0]["text"])
    assert parsed[0]["sha"] == "deadbeef"


def test_handle_resources_read_unknown_uri_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown resource"):
        mcp_server.handle_resources_read({"uri": "presence://abc/madeup"})


def test_dispatch_unknown_method_raises_method_not_found():
    import pytest
    with pytest.raises(mcp_server._MethodNotFound) as exc:
        mcp_server.dispatch({"method": "notes/list"})
    assert exc.value.method == "notes/list"


def test_dispatch_notifications_initialized_returns_none():
    """Notifications (no response expected) must return None so the main
    loop knows to skip emitting a response."""
    out = mcp_server.dispatch({"method": "notifications/initialized"})
    assert out is None


def test_main_responds_to_initialize_request_via_stdin(isolated_state, fake_repo, monkeypatch, capsys):
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(req) + "\n"))
    mcp_server.main()
    captured = capsys.readouterr()
    resp = json.loads(captured.out.strip())
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "presence-mcp"


def test_main_handles_malformed_json_without_crashing(isolated_state, fake_repo, monkeypatch, capsys):
    """Malformed JSON drops a stderr message and keeps reading. The next
    valid line still gets a response."""
    payload = "this is not json {{{\n"
    payload += json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    mcp_server.main()
    captured = capsys.readouterr()
    # Exactly one response (for the second line); first line was junk.
    out_lines = [ln for ln in captured.out.strip().split("\n") if ln]
    assert len(out_lines) == 1
    parsed = json.loads(out_lines[0])
    assert parsed["id"] == 2
    assert "presence-mcp" in captured.err  # stderr mentions parse failure


def test_main_unknown_method_returns_method_not_found_error(isolated_state, fake_repo, monkeypatch, capsys):
    req = {"jsonrpc": "2.0", "id": 3, "method": "totally/unknown"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(req) + "\n"))
    mcp_server.main()
    captured = capsys.readouterr()
    resp = json.loads(captured.out.strip())
    assert resp["id"] == 3
    assert resp["error"]["code"] == -32601
    assert "totally/unknown" in resp["error"]["message"]


def test_main_internal_error_returns_minus32603(isolated_state, fake_repo, monkeypatch, capsys):
    """An exception inside a handler maps to JSON-RPC -32603 (internal error)
    with the exception message as the user-facing string."""
    req = {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "presence://x/badroute"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(req) + "\n"))
    mcp_server.main()
    captured = capsys.readouterr()
    resp = json.loads(captured.out.strip())
    assert resp["error"]["code"] == -32603
    assert "unknown resource" in resp["error"]["message"]


def test_cli_mcp_subcommand_round_trips(tmp_path):
    """End-to-end: invoke `python3 lib/cli.py mcp`, send an initialize
    request via stdin, parse the response."""
    env = {
        **os.environ,
        "PRESENCE_STATE": str(tmp_path / "presence"),
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "PYTHONPATH": str(REPO_ROOT / "lib"),
    }
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(CLI_PY), "mcp"],
        input=req + "\n",
        capture_output=True, text=True, env=env, timeout=10, check=False,
    )
    assert r.returncode == 0, f"cli.py mcp exited non-zero:\nstderr={r.stderr}"
    resp = json.loads(r.stdout.strip())
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "presence-mcp"
