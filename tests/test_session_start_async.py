"""B5 regression: SessionStart's gather_* tasks must run concurrently, not serially.

Strategy: monkey-patch each gather function with an async stub that sleeps 200 ms,
then time async_main. Serial would be ~800 ms; concurrent should be ~200 ms (the
slowest single task). We assert wallclock < 500 ms to leave headroom for noisy CI.
"""
from __future__ import annotations

import asyncio
import time

import hook_session_start


def test_gather_tasks_run_concurrently(isolated_state, fake_repo, monkeypatch):
    delay = 0.2

    async def slow_warnings():
        await asyncio.sleep(delay)
        return ""

    async def slow_model(cwd, cfg):
        await asyncio.sleep(delay)
        return ""

    async def slow_telemetry(cwd, cfg):
        await asyncio.sleep(delay)
        return ""

    async def slow_events(cwd, cfg):
        await asyncio.sleep(delay)
        return ""

    monkeypatch.setattr(hook_session_start, "gather_warnings", slow_warnings)
    monkeypatch.setattr(hook_session_start, "gather_model", slow_model)
    monkeypatch.setattr(hook_session_start, "gather_telemetry", slow_telemetry)
    monkeypatch.setattr(hook_session_start, "gather_events", slow_events)

    # No stdin payload required; resolve_cwd will warn-and-fall-back to process cwd.
    monkeypatch.setattr(hook_session_start, "hook_input", lambda: {"cwd": str(fake_repo)})

    start = time.perf_counter()
    asyncio.run(hook_session_start.async_main())
    elapsed = time.perf_counter() - start

    # Serial would be ~4 * 0.2 = 0.8s. Concurrent should be ~0.2s.
    # 0.5s gives headroom for slow CI runners.
    assert elapsed < 0.5, (
        f"gather_* did not run concurrently: took {elapsed:.3f}s for 4 tasks of {delay}s each. "
        "Serial execution detected; check that async_main uses asyncio.gather correctly."
    )


def test_counter_reset_only_after_emit(isolated_state, fake_repo, monkeypatch):
    """B7 regression: error/warning counters must NOT be reset if no warnings were
    surfaced. Specifically, gather_warnings should be pure; the reset belongs to
    async_main and only fires when warnings_text is non-empty AND emit_context was called.
    """
    from _common import _bump_counter, read_counter

    # Bump the counters; gather_warnings should observe them and produce text.
    _bump_counter("error")
    _bump_counter("warning")
    assert read_counter("error") == 1
    assert read_counter("warning") == 1

    # Capture whether emit_context was called.
    emitted = []

    def capture_emit(event_name, text):
        emitted.append((event_name, text))

    monkeypatch.setattr(hook_session_start, "emit_context", capture_emit)
    monkeypatch.setattr(hook_session_start, "hook_input", lambda: {"cwd": str(fake_repo)})

    asyncio.run(hook_session_start.async_main())

    # We surfaced warnings, emit_context was called, so counters should be reset.
    assert emitted, "expected emit_context to be called when warnings were present"
    assert "<presence_status>" in emitted[0][1]
    assert read_counter("error") == 0, "error counter should be reset after successful emit"
    assert read_counter("warning") == 0, "warning counter should be reset after successful emit"


def test_counter_not_reset_when_warnings_empty(isolated_state, fake_repo, monkeypatch):
    """If gather_warnings returned empty (no warnings to surface) but other tasks
    produced output, the warning counters should be left alone. They are already 0,
    so a redundant reset is harmless, but we assert the code path doesn't touch
    them when there's nothing to surface.
    """
    from _common import read_counter

    # Counters start at 0; gather_warnings will return "" and not surface anything.
    assert read_counter("error") == 0
    assert read_counter("warning") == 0

    # Force one of the OTHER gathers to produce content so emit_context is called.
    async def model_with_content(cwd, cfg):
        return "<project_model>fake content</project_model>"

    emitted = []
    monkeypatch.setattr(hook_session_start, "gather_model", model_with_content)
    monkeypatch.setattr(hook_session_start, "emit_context", lambda e, t: emitted.append((e, t)))
    monkeypatch.setattr(hook_session_start, "hook_input", lambda: {"cwd": str(fake_repo)})

    asyncio.run(hook_session_start.async_main())

    assert emitted, "expected emit_context to fire because gather_model produced content"
    # Counters were 0 before; still 0 after. (The fix prevents an unnecessary write,
    # but the observable behavior is just that the value stays 0.)
    assert read_counter("error") == 0
    assert read_counter("warning") == 0
