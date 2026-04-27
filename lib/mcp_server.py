"""Model Context Protocol (MCP) JSON-RPC stdio server.

Exposes presence state as MCP resources so any MCP-aware client (Claude
Desktop, Cursor, Continue, custom agents) can read the living project
model + outcome telemetry without going through Claude Code-specific hook
plumbing.

Resources:
  presence://<repo_id>/model      The living model.md (Markdown)
  presence://<repo_id>/telemetry  Recent commit/revert claims (JSON)

Wiring:
  Each MCP client has its own config format. The common ground is:
    - command: python3 (or the pinned interpreter at .python_bin)
    - args:    [<plugin_root>/lib/cli.py, mcp]
  See docs/mcp.md for per-client config snippets.

Protocol notes:
  - JSON-RPC 2.0 framed as one message per stdin line (the simplest of the
    transports MCP supports; chosen here because it is human-debuggable).
  - Implements: initialize, resources/list, resources/read,
    notifications/initialized.
  - All other methods reply with JSON-RPC error -32601 (method not found).
  - Errors during dispatch reply with code -32603 (internal error).

This module is read-only by design: it never mutates presence state, never
fires hooks, and never writes to the audit log. The MCP client gets a view
of presence's memory; the writing path remains the hook system.
"""
from __future__ import annotations

import json
import sys

from _common import _dumps, _loads
from telemetry import claims_path

# Lazy imports for project_dir / repo_id / read_jsonl deferred until first
# use so this module can be imported even when state isn't initialized.

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "presence-mcp"
SERVER_VERSION = "0.1.0"


def _read_file_safe(path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def handle_initialize(_params: dict) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"resources": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def handle_resources_list(_params: dict) -> dict:
    from _common import repo_id
    rid = repo_id()
    return {
        "resources": [
            {
                "uri": f"presence://{rid}/model",
                "name": "Living Project Model",
                "description": "Cross-session knowledge presence has accumulated about this repository.",
                "mimeType": "text/markdown",
            },
            {
                "uri": f"presence://{rid}/telemetry",
                "name": "Outcome Telemetry",
                "description": "Recent commits, revert detections, and verification claims.",
                "mimeType": "application/json",
            },
        ]
    }


def handle_resources_read(params: dict) -> dict:
    from _common import project_dir, read_jsonl

    uri = params.get("uri", "")
    if uri.endswith("/model"):
        content = _read_file_safe(project_dir() / "model.md")
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": content}]}
    if uri.endswith("/telemetry"):
        claims = read_jsonl(claims_path())
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(claims, indent=2),
            }]
        }
    raise ValueError(f"unknown resource URI: {uri}")


_HANDLERS = {
    "initialize": handle_initialize,
    "resources/list": handle_resources_list,
    "resources/read": handle_resources_read,
}


def dispatch(req: dict) -> dict | None:
    method = req.get("method", "")
    params = req.get("params") or {}
    if method == "notifications/initialized":
        return None  # no response on notifications
    handler = _HANDLERS.get(method)
    if handler is None:
        raise _MethodNotFound(method)
    return handler(params)


class _MethodNotFound(Exception):
    def __init__(self, method: str):
        super().__init__(method)
        self.method = method


def _emit_response(req_id, result=None, error=None) -> None:
    """Write a JSON-RPC 2.0 response line to stdout. Either result or error
    must be provided; never both. Notifications (req_id is None) emit nothing."""
    if req_id is None:
        return
    payload: dict = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(_dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Run the JSON-RPC stdio loop until stdin closes.

    One message per line. Empty lines skipped. Malformed JSON drops a
    parse-error line on stderr and continues (the client may recover).
    """
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = _loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            sys.stderr.write(f"presence-mcp: invalid JSON: {exc}\n")
            continue
        if not isinstance(req, dict):
            continue
        req_id = req.get("id")
        try:
            result = dispatch(req)
        except _MethodNotFound as exc:
            _emit_response(req_id, error={"code": -32601, "message": f"method not found: {exc.method}"})
            continue
        except Exception as exc:  # noqa: BLE001  outermost guard for the JSON-RPC loop
            _emit_response(req_id, error={"code": -32603, "message": str(exc)})
            continue
        if result is not None:
            _emit_response(req_id, result=result)


if __name__ == "__main__":
    main()
