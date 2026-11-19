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


def run_receipt(rev: str, attach: bool, sign_key: str | None = None, statement: bool = False) -> int:
    import json
    import os

    import receipt
    try:
        r = receipt.attach(os.getcwd(), rev, sign_key) if attach else receipt.find(os.getcwd(), rev)
        if statement:
            r = receipt.to_statement(r)
    except (LookupError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(json.dumps(r, indent=2, sort_keys=True) + "\n")
    return 0


def run_verify_receipt(rev: str, allowed_signers: str | None = None) -> int:
    import os

    import receipt
    try:
        res = receipt.verify(os.getcwd(), rev, allowed_signers)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    # One line, plain ASCII: the note is untrusted text from the repo.
    detail = "; ".join(receipt.safe_text(e["cmd"]) for e in res.get("evidence", []))
    line = f"{res['status']} {res.get('commit', '')[:12]}"
    if res["status"] == "verified":
        line += f" (signed by {receipt.safe_text(res['signer'])})" if res.get("signed") else " (unsigned receipt: the committer's machine says so)"
    sys.stdout.write(line + (f" [{detail}]" if detail else "") + "\n")
    return 0 if res["status"] == "verified" else 1


def run_verify_evidence(rev: str, repo: str) -> int:
    import os

    import ci_evidence
    try:
        res = ci_evidence.verify(os.getcwd(), rev, repo)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    line = f"{res['status']} tree {res['tree'][:12]}"
    if res["status"] == "verified":
        line += f" (CI run {res['run']})"
    sys.stdout.write(line + "\n")
    return 0 if res["status"] == "verified" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="presence: hook + MCP CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    hook_parser = sub.add_parser("hook", help="dispatch a lifecycle hook")
    hook_parser.add_argument("hook_name", choices=list(_HOOKS.keys()))

    sub.add_parser("mcp", help="(v0.4.1+) start the MCP server on stdio")

    rc = sub.add_parser("receipt", help="show the verification receipt recorded for a commit")
    rc.add_argument("rev", nargs="?", default="HEAD")
    rc.add_argument("--attach", action="store_true", help="also write it into the git note refs/notes/presence")
    rc.add_argument("--sign-key", help="sign the note with this SSH key (implies --attach); a .pub path signs via ssh-agent")
    rc.add_argument("--statement", action="store_true", help="print the receipt as an in-toto Statement instead of the raw note")

    vr = sub.add_parser("verify-receipt", help="check the receipt note on a commit (needs only the repo)")
    vr.add_argument("rev", nargs="?", default="HEAD")
    vr.add_argument("--allowed-signers", help="trust only receipts signed by a key in this ssh allowed_signers file")

    ve = sub.add_parser("verify-evidence", help="check that CI re-ran the tests on a commit's tree and signed the result (needs gh)")
    ve.add_argument("rev", nargs="?", default="HEAD")
    ve.add_argument("--repo", required=True, help="owner/name of the repository whose CI must have signed it")

    args = parser.parse_args()

    if args.command == "hook":
        run_hook(args.hook_name)
    elif args.command == "mcp":
        run_mcp()
    elif args.command == "receipt":
        sys.exit(run_receipt(args.rev, args.attach or bool(args.sign_key), args.sign_key, args.statement))
    elif args.command == "verify-evidence":
        sys.exit(run_verify_evidence(args.rev, args.repo))
    elif args.command == "verify-receipt":
        sys.exit(run_verify_receipt(args.rev, args.allowed_signers))


if __name__ == "__main__":
    main()
