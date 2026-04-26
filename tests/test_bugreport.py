"""Tests for lib/bugreport.py + the /presence-bugreport bundle.

assemble() must always return a dict with the documented keys. to_markdown()
must produce a paste-friendly block that mentions every section even when
sources are empty. Failure modes (verify unavailable, no warnings) must
degrade gracefully rather than raise.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import _common
import bugreport
import warnings_log

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_assemble_returns_documented_keys(isolated_state):
    importlib.reload(_common)
    importlib.reload(bugreport)
    bundle = bugreport.assemble(str(REPO_ROOT))
    expected_keys = {
        "presence_version", "platform", "python", "active_preset",
        "verify", "doctor", "recent_warnings", "state_sizes",
    }
    assert expected_keys.issubset(bundle.keys())


def test_assemble_doctor_has_pinned_python_field(isolated_state):
    """v0.3.3 added pinned_python; bugreport surfaces it via doctor."""
    importlib.reload(_common)
    importlib.reload(bugreport)
    bundle = bugreport.assemble(str(REPO_ROOT))
    assert "pinned_python" in bundle["doctor"]


def test_to_markdown_emits_all_sections_when_empty(isolated_state):
    importlib.reload(_common)
    importlib.reload(bugreport)
    bundle = bugreport.assemble(str(REPO_ROOT))
    md = bugreport.to_markdown(bundle)
    assert "## presence bug report" in md
    assert "Version" in md
    assert "Platform" in md
    assert "Python" in md
    assert "install.sh --verify --json" in md
    assert "lib/doctor.py --json" in md
    assert "Recent warnings" in md
    assert "State sizes" in md


def test_to_markdown_includes_fix_lines(isolated_state):
    importlib.reload(_common)
    importlib.reload(warnings_log)
    importlib.reload(bugreport)
    warnings_log.warn("test_with_fix", "the warning text", fix="here is the fix")
    bundle = bugreport.assemble(str(REPO_ROOT))
    md = bugreport.to_markdown(bundle)
    assert "test_with_fix" in md
    assert "the warning text" in md
    assert "here is the fix" in md


def test_to_markdown_handles_no_warnings():
    """When the bundle has no warnings, the section says (none) instead of
    crashing. We construct the bundle directly here rather than going through
    assemble() because the synthetic hook fire inside _run_verify_json may
    itself produce a warning, which would defeat the test's intent."""
    bundle = {
        "presence_version": "0.0.0",
        "platform": "test",
        "python": "3.14",
        "active_preset": "solo-dev",
        "verify": {"ok": True, "checks": []},
        "doctor": {"python_ok": True},
        "recent_warnings": [],
        "state_sizes": {"model_md_bytes": 0},
    }
    md = bugreport.to_markdown(bundle)
    assert "Recent warnings" in md
    assert "(none)" in md


def test_cli_md_flag_emits_markdown(isolated_state, tmp_path, monkeypatch):
    """Smoke-test the CLI surface used by /presence-bugreport."""
    monkeypatch.setenv("PRESENCE_STATE", str(tmp_path / "presence"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(REPO_ROOT / "lib" / "bugreport.py"), "--md"],
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(REPO_ROOT / "lib"),
        },
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert r.stdout.startswith("## presence bug report"), r.stdout[:200]


def test_cli_default_emits_json(isolated_state, tmp_path, monkeypatch):
    monkeypatch.setenv("PRESENCE_STATE", str(tmp_path / "presence"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(REPO_ROOT / "lib" / "bugreport.py")],
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(REPO_ROOT / "lib"),
        },
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert r.returncode == 0
    parsed = json.loads(r.stdout)
    assert "presence_version" in parsed
    assert "doctor" in parsed
