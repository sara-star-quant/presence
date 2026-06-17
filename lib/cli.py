"""presence CLI: hook entry point + future MCP entry point.

This is the fallback path when the Rust client cannot reach the daemon
(socket dead, daemon failed to boot, no Rust binary built). It runs a hook
in-process via the regular Python entry point, just like the bash wrapper
would. Slower than the daemon path, identical semantics.

  python3 lib/cli.py hook session-start    # equivalent to running session-start.sh
  python3 lib/cli.py mcp                   # (v0.4.1) start an MCP JSON-RPC server

The bash wrappers in hooks/scripts/*.sh do NOT route through this CLI; they
exec the per-hook entry directly. cli.py exists for the daemon-fallback path
and for MCP plumbing (v0.4.1+).
"""
from __future__ import annotations

import argparse
import sys

_HOOKS = {
    "session-start": "hook_session_start",
    "user-prompt-submit": "hook_user_prompt_submit",
    "post-tool-bash": "hook_post_tool_bash",
    "pre-tool-bash": "hook_pre_tool_bash",
    "post-tool-edit": "hook_post_tool_edit",
    "stop": "hook_stop",
}


def run_hook(hook_name: str) -> None:
    """Run a hook by its dispatch name (without the ``hook_`` prefix)."""
    module_name = _HOOKS.get(hook_name)
    if module_name is None:
        sys.stderr.write(f"unknown hook: {hook_name}\n")
        sys.exit(1)
    module = __import__(module_name)
    # Wrap in safe_main so this fallback path (daemon failed to start) has the
    # same T1 guarantee as the __main__ path inside each hook module: an unhandled
    # exception logs and exits 0 instead of leaking a traceback / partial stdout.
    from _common import safe_main
    safe_main(module.main)


def run_mcp() -> None:
    """v0.4.1+: start the MCP JSON-RPC server on stdin/stdout."""
    import mcp_server  # type: ignore[import-not-found]
    mcp_server.main()


def main() -> None:
    parser = argparse.ArgumentParser(description="presence: hook + MCP CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    hook_parser = sub.add_parser("hook", help="dispatch a lifecycle hook")
    hook_parser.add_argument("hook_name", choices=list(_HOOKS.keys()))

    sub.add_parser("mcp", help="(v0.4.1+) start the MCP server on stdio")

    args = parser.parse_args()

    if args.command == "hook":
        run_hook(args.hook_name)
    elif args.command == "mcp":
        run_mcp()


if __name__ == "__main__":
    main()
