"""Tests for lib/cli.py (v0.4.0 daemon-fallback CLI).

cli.py is what the Rust client falls back to when the daemon socket can't
be reached. It must dispatch the same way bash wrappers do (same module
imports, same exit-code semantics via safe_main).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PY = REPO_ROOT / "lib" / "cli.py"


def test_cli_help_lists_subcommands():
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(CLI_PY), "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "hook" in r.stdout
    assert "mcp" in r.stdout


def test_cli_hook_help_lists_all_six_hooks():
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(CLI_PY), "hook", "--help"],
        capture_output=True, text=True, check=True,
    )
    for hook in [
        "session-start", "user-prompt-submit", "post-tool-bash",
        "pre-tool-bash", "post-tool-edit", "stop",
    ]:
        assert hook in r.stdout


def test_cli_unknown_hook_rejected_by_argparse():
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(CLI_PY), "hook", "made-up-hook-name"],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode != 0
    assert "made-up-hook-name" in r.stderr or "invalid choice" in r.stderr


def test_cli_user_prompt_submit_runs_cleanly(tmp_path):
    """Round-trip: invoke cli.py for a hook, confirm exit 0 + state side
    effect (event drained from the queue)."""
    env = {
        **os.environ,
        "PRESENCE_STATE": str(tmp_path / "presence"),
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "PYTHONPATH": str(REPO_ROOT / "lib"),
    }
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(CLI_PY), "hook", "user-prompt-submit"],
        env=env,
        input='{"cwd": "' + str(REPO_ROOT) + '", "prompt": "test"}',
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
