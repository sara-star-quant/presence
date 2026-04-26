"""Regression: B2. _emergency_truncate must log the kept-line count without relying on dir() lookups."""
from __future__ import annotations

import json

from events import _emergency_truncate, append_event, event_path


def test_emergency_truncate_logs_kept_count(isolated_state, fake_repo):
    """Force the queue past the size cap and confirm the truncate path logs
    'events_overflow' with a numeric `kept` value (not None)."""
    # Write enough events to exceed MAX_EVENT_BYTES
    p = event_path()
    for i in range(50):
        append_event({"kind": "edit", "path": "x.py", "i": i, "blob": "a" * 200})

    # Manually trigger truncate (size may not have crossed threshold; force it)
    _emergency_truncate(p)

    # Read the warnings log
    warnings_file = isolated_state / "logs" / "warnings.log"
    assert warnings_file.exists(), "warning should have been written"
    lines = [json.loads(line) for line in warnings_file.read_text().splitlines() if line.strip()]
    overflow = [w for w in lines if w.get("category") == "events_overflow"]
    assert overflow, f"expected 'events_overflow' warning, got: {lines}"
    # The 'kept' detail must be a real number, not None or missing
    details = overflow[-1].get("details", {})
    assert isinstance(details.get("kept"), int), \
        f"'kept' should be an int, got {type(details.get('kept'))}: {details}"
