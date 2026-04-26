"""Event queue: append, drain (truncates!), peek, summarize."""

from events import append_event, drain_events, event_path, peek_events, summarize_events


def test_append_and_peek(isolated_state, fake_repo):
    append_event({"kind": "edit", "path": "foo.py"})
    append_event({"kind": "bash", "cmd": "ls", "exit": 0})
    events = peek_events()
    assert len(events) == 2
    assert events[0]["kind"] == "edit"


def test_drain_truncates_file(isolated_state, fake_repo):
    append_event({"kind": "edit", "path": "a.py"})
    append_event({"kind": "edit", "path": "b.py"})
    drained = drain_events()
    assert len(drained) == 2
    # File should now be empty (or near-empty)
    p = event_path()
    assert not p.exists() or p.stat().st_size == 0


def test_drain_then_drain_again_returns_empty(isolated_state, fake_repo):
    append_event({"kind": "edit", "path": "a.py"})
    drain_events()
    assert drain_events() == []


def test_drain_missing_file_returns_empty(isolated_state, fake_repo):
    assert drain_events() == []


def test_summarize_empty():
    assert summarize_events([]) == ""


def test_summarize_edits_and_failures():
    events = [
        {"kind": "edit", "path": "a.py", "ts": 1},
        {"kind": "edit", "path": "b.py", "ts": 2},
        {"kind": "bash", "cmd": "false", "exit": 1, "ts": 3},
    ]
    out = summarize_events(events)
    assert "Edits:" in out
    assert "a.py" in out and "b.py" in out
    assert "Failed commands" in out
    assert "exit 1" in out


def test_drain_only_returns_what_was_in_file_at_drain_time(isolated_state, fake_repo, monkeypatch):
    """Concurrent appends after the drain snapshot must NOT be re-drained."""
    append_event({"kind": "edit", "path": "before.py"})
    drained1 = drain_events()
    assert len(drained1) == 1
    # New append after drain should appear in next drain, not be lost
    append_event({"kind": "edit", "path": "after.py"})
    drained2 = drain_events()
    assert len(drained2) == 1
    assert drained2[0]["path"] == "after.py"
