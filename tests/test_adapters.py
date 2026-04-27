"""Tests for the host-AI-tool adapter seam (v0.4.0).

The seam exists so v0.4.2 can add Cursor / Gemini / Codex / claude-code /
clawbot / etc. without touching every emit_context() call site. v0.4.0
ships only ClaudeAdapter; v0.4.0 tests must lock in the default behavior
so a future host adapter can't silently break Claude Code output.
"""
from __future__ import annotations

import importlib
import io
import json
import sys

import _common


def test_get_adapter_default_is_claude(monkeypatch):
    monkeypatch.delenv("PRESENCE_HOST", raising=False)
    from adapters import ClaudeAdapter, get_adapter
    a = get_adapter()
    assert isinstance(a, ClaudeAdapter)


def test_get_adapter_explicit_claude(monkeypatch):
    monkeypatch.setenv("PRESENCE_HOST", "claude")
    from adapters import ClaudeAdapter, get_adapter
    a = get_adapter()
    assert isinstance(a, ClaudeAdapter)


def test_get_adapter_unknown_host_falls_back_to_claude(monkeypatch):
    """Forward compat: an unknown PRESENCE_HOST must not raise; presence's
    'never break a hook' stance applies even to misconfiguration."""
    monkeypatch.setenv("PRESENCE_HOST", "future-tool-not-yet-implemented")
    from adapters import ClaudeAdapter, get_adapter
    a = get_adapter()
    assert isinstance(a, ClaudeAdapter)


def test_claude_adapter_emits_expected_json(monkeypatch):
    """ClaudeAdapter.emit_context produces the exact JSON shape Claude Code
    consumes via the SessionStart additionalContext field. This is a public
    contract; future adapters must mimic the structure when relevant."""
    from adapters import ClaudeAdapter
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake)
    ClaudeAdapter().emit_context("SessionStart", "<presence_context>hi</presence_context>")
    out = fake.getvalue()
    parsed = json.loads(out)
    assert parsed == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "<presence_context>hi</presence_context>",
        }
    }


def test_claude_adapter_empty_text_emits_nothing(monkeypatch):
    """Empty context payload is a noop; presence never wants to inject empty
    additionalContext (would just be noise)."""
    from adapters import ClaudeAdapter
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake)
    ClaudeAdapter().emit_context("Stop", "")
    assert fake.getvalue() == ""


def test_claude_adapter_escapes_special_chars(monkeypatch):
    """ClaudeAdapter output must be valid JSON even when the text contains
    quotes, backslashes, newlines, or control chars. Without proper escaping,
    a malicious commit message or file path could break the JSON envelope
    Claude Code parses."""
    from adapters import ClaudeAdapter
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake)
    nasty = 'quote"backslash\\newline\nnull\x00tab\t'
    ClaudeAdapter().emit_context("SessionStart", nasty)
    out = fake.getvalue()
    parsed = json.loads(out)   # MUST parse cleanly
    assert parsed["hookSpecificOutput"]["additionalContext"] == nasty


def test_emit_context_routes_through_adapter(isolated_state, monkeypatch):
    """_common.emit_context() must delegate to the adapter selected by
    PRESENCE_HOST. The hook code paths use _common.emit_context, not the
    adapter directly; this binding is the one that v0.4.2 depends on."""
    importlib.reload(_common)
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake)
    _common.emit_context("UserPromptSubmit", "test payload")
    out = fake.getvalue()
    parsed = json.loads(out)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert parsed["hookSpecificOutput"]["additionalContext"] == "test payload"
