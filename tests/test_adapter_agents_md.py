"""Tests for the AgentsMdAdapter (v0.4.2).

Cross-tool: AGENTS.md is the open standard read by Codex, Cursor, Gemini
CLI, Windsurf, GitHub Copilot. The adapter refreshes a delimited section
on SessionStart so any AGENTS.md-aware tool the user opens after presence
runs sees fresh project context.

Critical guarantees:
  - Idempotent: writing twice produces the same file content.
  - Preserves user-authored content outside the markers.
  - Acts only on SessionStart (not on every UserPromptSubmit fire).
  - Filename overridable via PRESENCE_AGENTS_MD_FILENAME.
  - Never raises (failed write -> silent; never breaks a hook).
"""
from __future__ import annotations

import pytest
from adapters.agents_md import (
    END_MARKER,
    START_MARKER,
    AgentsMdAdapter,
    _build_section,
    _replace_section,
)

# ---------------------------------------------------------------------------
# _replace_section: pure unit tests, no filesystem.
# ---------------------------------------------------------------------------

def test_replace_section_appends_when_missing():
    existing = "# my project\n\nSome notes.\n"
    new = _build_section("test payload")
    out = _replace_section(existing, new)
    assert out.startswith(existing)
    assert START_MARKER in out
    assert "test payload" in out


def test_replace_section_replaces_in_place():
    existing = (
        "# my project\n\n"
        f"{START_MARKER}\nold content\n{END_MARKER}\n"
        "Below the section.\n"
    )
    new = _build_section("fresh content")
    out = _replace_section(existing, new)
    assert "old content" not in out
    assert "fresh content" in out
    # Below the section is preserved exactly.
    assert "Below the section." in out
    # User-authored prefix preserved.
    assert out.startswith("# my project\n\n")


def test_replace_section_idempotent():
    """Two writes with the same content produce identical output."""
    existing = "# my project\n\n"
    new = _build_section("payload v1")
    once = _replace_section(existing, new)
    twice = _replace_section(once, new)
    assert once == twice


def test_replace_section_handles_empty_existing():
    new = _build_section("first time")
    out = _replace_section("", new)
    assert out == new


def test_replace_section_handles_malformed_markers():
    """Marker only at start (no end) -> treated as missing; appended cleanly."""
    existing = f"random text {START_MARKER} but no end marker\n"
    new = _build_section("payload")
    out = _replace_section(existing, new)
    # Old half-marker preserved (we don't try to repair it); new full section appended.
    assert START_MARKER in out
    assert END_MARKER in out


# ---------------------------------------------------------------------------
# AgentsMdAdapter: integration with a real working tree.
# ---------------------------------------------------------------------------

@pytest.fixture
def repo_with_state(tmp_path, monkeypatch):
    """A tmp dir set up as cwd + git repo so repo_root() resolves cleanly."""
    import subprocess
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    return repo


def test_session_start_writes_agents_md(repo_with_state):
    adapter = AgentsMdAdapter()
    adapter.emit_context("SessionStart", "<presence_context>hello</presence_context>")
    target = repo_with_state / "AGENTS.md"
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert START_MARKER in content
    assert END_MARKER in content
    assert "<presence_context>hello</presence_context>" in content


def test_non_session_start_event_does_nothing(repo_with_state):
    adapter = AgentsMdAdapter()
    adapter.emit_context("UserPromptSubmit", "ignored payload")
    assert not (repo_with_state / "AGENTS.md").exists()


def test_empty_text_does_not_create_file(repo_with_state):
    adapter = AgentsMdAdapter()
    adapter.emit_context("SessionStart", "")
    assert not (repo_with_state / "AGENTS.md").exists()


def test_existing_agents_md_user_content_preserved(repo_with_state):
    """User-authored AGENTS.md content outside the presence section must
    survive. This is the critical contract: presence is a guest in the
    user's file."""
    target = repo_with_state / "AGENTS.md"
    target.write_text(
        "# Project Conventions\n\n"
        "Use 2-space indentation.\n\n"
        "## Style\n\n"
        "ASCII-only.\n",
        encoding="utf-8",
    )
    AgentsMdAdapter().emit_context("SessionStart", "fresh presence content")
    after = target.read_text(encoding="utf-8")
    # User content untouched.
    assert "Use 2-space indentation." in after
    assert "ASCII-only." in after
    # presence section appended.
    assert "fresh presence content" in after
    assert START_MARKER in after


def test_filename_override_via_env(repo_with_state, monkeypatch):
    monkeypatch.setenv("PRESENCE_AGENTS_MD_FILENAME", "GEMINI.md")
    AgentsMdAdapter().emit_context("SessionStart", "hi")
    assert (repo_with_state / "GEMINI.md").exists()
    # Default file NOT created when override is set.
    assert not (repo_with_state / "AGENTS.md").exists()


def test_filename_override_supports_subdirectory(repo_with_state, monkeypatch):
    """Cursor's new-format rules live under .cursor/rules/. The override
    should be allowed to specify a path with a directory; the adapter
    creates parent dirs."""
    monkeypatch.setenv("PRESENCE_AGENTS_MD_FILENAME", ".cursor/rules/presence.mdc")
    AgentsMdAdapter().emit_context("SessionStart", "rules payload")
    target = repo_with_state / ".cursor" / "rules" / "presence.mdc"
    assert target.exists()
    assert "rules payload" in target.read_text(encoding="utf-8")


def test_idempotent_writes_produce_same_file(repo_with_state):
    adapter = AgentsMdAdapter()
    payload = "<presence_context>same text</presence_context>"
    adapter.emit_context("SessionStart", payload)
    first = (repo_with_state / "AGENTS.md").read_text()
    adapter.emit_context("SessionStart", payload)
    second = (repo_with_state / "AGENTS.md").read_text()
    assert first == second


def test_refresh_replaces_old_payload_only(repo_with_state):
    """A second SessionStart with new content replaces the OLD presence
    section; user content stays intact."""
    target = repo_with_state / "AGENTS.md"
    target.write_text("# user header\n\nstable content\n", encoding="utf-8")
    AgentsMdAdapter().emit_context("SessionStart", "round 1")
    AgentsMdAdapter().emit_context("SessionStart", "round 2")
    final = target.read_text(encoding="utf-8")
    assert "stable content" in final
    assert "round 2" in final
    assert "round 1" not in final


def test_write_failure_does_not_raise(repo_with_state, monkeypatch):
    """If the target file can't be written (read-only fs, permission issue),
    the adapter must swallow the error - hooks must never break Claude Code."""
    target = repo_with_state / "AGENTS.md"
    target.write_text("existing\n", encoding="utf-8")
    # Make the directory read-only.
    import stat
    repo_with_state.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        # Must not raise.
        AgentsMdAdapter().emit_context("SessionStart", "payload")
    finally:
        # Restore so cleanup works.
        repo_with_state.chmod(0o700)


# ---------------------------------------------------------------------------
# Adapter dispatch via PRESENCE_HOST.
# ---------------------------------------------------------------------------

def test_presence_host_agents_md_routes_to_agents_md_adapter(monkeypatch):
    monkeypatch.setenv("PRESENCE_HOST", "agents-md")
    from adapters import get_adapter
    assert isinstance(get_adapter(), AgentsMdAdapter)


def test_presence_host_underscore_alias_routes_to_agents_md_adapter(monkeypatch):
    monkeypatch.setenv("PRESENCE_HOST", "agents_md")
    from adapters import get_adapter
    assert isinstance(get_adapter(), AgentsMdAdapter)


def test_presence_host_short_alias_routes_to_agents_md_adapter(monkeypatch):
    monkeypatch.setenv("PRESENCE_HOST", "agents")
    from adapters import get_adapter
    assert isinstance(get_adapter(), AgentsMdAdapter)


def test_presence_host_generic_routes_to_generic_adapter(monkeypatch):
    monkeypatch.setenv("PRESENCE_HOST", "generic")
    from adapters import GenericAdapter, get_adapter
    assert isinstance(get_adapter(), GenericAdapter)
