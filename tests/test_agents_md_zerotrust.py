"""The AGENTS.md adapter writes the model, digest and events into the repo working tree, where it may be
committed. A preset that assumes compromise must never do that."""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def adapter(isolated_state, fake_repo, monkeypatch):
    monkeypatch.setenv("PRESENCE_HOST", "agents_md")

    def load(settings):
        (isolated_state / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        import _common
        importlib.reload(_common)
        from adapters import agents_md
        importlib.reload(agents_md)
        monkeypatch.chdir(fake_repo)
        monkeypatch.setattr(agents_md, "_project_root", lambda: fake_repo)
        return agents_md.AgentsMdAdapter(), fake_repo / "AGENTS.md"
    return load


def test_the_default_preset_still_writes_the_section(adapter):
    a, target = adapter({"preset": "solo-dev"})
    a.emit_context("SessionStart", "model text and digest")
    assert "model text and digest" in target.read_text(encoding="utf-8")


def test_zerotrust_writes_nothing_into_the_repo(adapter, isolated_state):
    a, target = adapter({"preset": "zerotrust"})
    a.emit_context("SessionStart", "SENSITIVE project model text")
    assert not target.exists()


def test_zerotrust_leaves_an_existing_file_as_it_is(adapter):
    a, target = adapter({"preset": "zerotrust"})
    target.write_text("# my project\n\nnotes\n", encoding="utf-8")
    a.emit_context("SessionStart", "SENSITIVE project model text")
    assert target.read_text(encoding="utf-8") == "# my project\n\nnotes\n"


def test_the_refusal_is_reported_where_doctor_looks(adapter, isolated_state):
    a, _ = adapter({"preset": "zerotrust"})
    a.emit_context("SessionStart", "x")
    log = isolated_state / "logs" / "warnings.log"
    assert log.exists() and "agents_md_refused" in log.read_text(encoding="utf-8")


def test_the_refusal_never_copies_the_text_into_the_log(adapter, isolated_state):
    a, _ = adapter({"preset": "zerotrust"})
    a.emit_context("SessionStart", "SENSITIVE project model text")
    log = isolated_state / "logs" / "warnings.log"
    assert "SENSITIVE" not in log.read_text(encoding="utf-8")


def test_a_preset_the_user_writes_without_the_lock_may_still_use_it(adapter, isolated_state):
    (isolated_state / "presets").mkdir(parents=True, exist_ok=True)
    (isolated_state / "presets" / "mine.json").write_text(json.dumps({"confidence": {"enabled": True}}), encoding="utf-8")
    a, target = adapter({"preset": "mine"})
    a.emit_context("SessionStart", "my own choice")
    assert "my own choice" in target.read_text(encoding="utf-8")


# --- the repository is hostile input: AGENTS.md may not be what it looks like ----------------------------------


def test_an_agents_md_that_points_outside_the_repository_is_not_written_through(adapter, tmp_path):
    a, target = adapter({"preset": "solo-dev"})
    victim = tmp_path / "outside" / "important.txt"
    victim.parent.mkdir()
    victim.write_text("keep me\n", encoding="utf-8")
    target.symlink_to(victim)
    a.emit_context("SessionStart", "model text")
    assert victim.read_text(encoding="utf-8") == "keep me\n"


def test_an_agents_md_that_links_to_another_file_in_the_repository_still_works(adapter, fake_repo):
    a, target = adapter({"preset": "solo-dev"})
    real = fake_repo / "CLAUDE.md"
    real.write_text("# notes\n", encoding="utf-8")
    target.symlink_to(real)
    a.emit_context("SessionStart", "model text")
    assert "model text" in real.read_text(encoding="utf-8")


def test_an_agents_md_that_is_a_named_pipe_does_not_hang_the_hook(adapter):
    import os
    import signal
    a, target = adapter({"preset": "solo-dev"})
    os.mkfifo(target)

    def stuck(*_):
        raise TimeoutError("the adapter blocked on a named pipe")
    signal.signal(signal.SIGALRM, stuck)
    signal.alarm(5)
    try:
        a.emit_context("SessionStart", "model text")
    finally:
        signal.alarm(0)
