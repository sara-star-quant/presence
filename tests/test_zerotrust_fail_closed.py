"""A preset that requires encryption never falls back to plain text: the record is not written, and it is loud."""
from __future__ import annotations

import importlib
import json
import sys

import pytest

ZERO = {"preset": "zerotrust"}
KEY = b"k" * 32


@pytest.fixture
def common(isolated_state, monkeypatch):
    """_common reloaded under a chosen preset with a chosen crypto, so its per-process caches start empty."""
    def load(preset=ZERO, available=True, key=KEY, import_error=False, encrypt_raises=False):
        (isolated_state / "settings.json").write_text(json.dumps(preset), encoding="utf-8")
        import crypto
        monkeypatch.setattr(crypto, "is_available", lambda: available)
        monkeypatch.setattr(crypto, "get_or_create_key", lambda: key)
        if encrypt_raises:
            monkeypatch.setattr(crypto, "encrypt_line", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
        if import_error:
            monkeypatch.setitem(sys.modules, "crypto", None)  # "from crypto import ..." now raises ImportError
        import _common
        return importlib.reload(_common)
    return load


def _read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _errors(state):
    f = state / "logs" / "errors.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


@pytest.mark.parametrize(
    "why",
    [dict(available=False), dict(key=None), dict(import_error=True), dict(encrypt_raises=True)],
    ids=["no-keychain", "no-key", "no-library", "encrypt-fails"],
)
def test_a_record_that_cannot_be_encrypted_is_not_written(common, isolated_state, why):
    c = common(**why)
    target = isolated_state / "events" / "x" / "pending.jsonl"
    c.append_jsonl(target, {"kind": "bash", "cmd": "ls"})
    assert "ls" not in _read(target) and _read(target) == ""
    assert c.read_counter("error") == 1
    assert "encryption" in _errors(isolated_state) and "plain" in _errors(isolated_state)


def test_the_refusal_is_counted_once_per_process_not_once_per_record(common, isolated_state):
    c = common(available=False)
    target = isolated_state / "t.jsonl"
    for i in range(5):
        c.append_jsonl(target, {"i": i})
    assert c.read_counter("error") == 1 and _read(target) == ""


def test_another_hook_process_does_not_repeat_the_report_within_the_hour(common, isolated_state):
    """Hooks are short-lived processes: without a cooldown every one of them would add an error to the count."""
    import os
    import time
    c = common(available=False)
    c.append_jsonl(isolated_state / "t.jsonl", {"i": 1})
    c2 = common(available=False)  # a fresh process: the per-process flag starts empty
    c2.append_jsonl(isolated_state / "t.jsonl", {"i": 2})
    assert c2.read_counter("error") == 1 and _read(isolated_state / "t.jsonl") == ""
    marker = isolated_state / "logs" / "encryption_refused"
    old = time.time() - 2 * 3600
    os.utime(marker, (old, old))
    c3 = common(available=False)
    c3.append_jsonl(isolated_state / "t.jsonl", {"i": 3})
    assert c3.read_counter("error") == 2  # an hour later the report comes again, so it cannot go stale


def test_the_refusal_does_not_carry_the_record_into_the_error_log(common, isolated_state):
    c = common(available=False)
    c.append_jsonl(isolated_state / "t.jsonl", {"secret": "TOPSECRETVALUE"})
    assert "TOPSECRETVALUE" not in _errors(isolated_state)


def test_a_preset_that_does_not_ask_for_encryption_still_writes_plain_text(common, isolated_state):
    c = common(preset={"preset": "solo-dev"}, available=False)
    target = isolated_state / "t.jsonl"
    c.append_jsonl(target, {"kind": "edit"})
    assert json.loads(_read(target).strip()) == {"kind": "edit"}
    assert c.read_counter("error") == 0


def test_when_encryption_works_the_line_is_encrypted(common, isolated_state):
    pytest.importorskip("cryptography")
    c = common()
    target = isolated_state / "t.jsonl"
    c.append_jsonl(target, {"kind": "edit", "file": "VISIBLE"})
    text = _read(target)
    assert "VISIBLE" not in text and '"_e"' in text and c.read_counter("error") == 0


def test_older_plain_lines_stay_readable_after_a_refusal(common, isolated_state):
    target = isolated_state / "t.jsonl"
    target.write_text(json.dumps({"old": 1}) + "\n", encoding="utf-8")
    c = common(available=False)
    c.append_jsonl(target, {"new": 2})
    assert [r.get("old") for r in c.read_jsonl(target)] == [1]


def test_the_session_start_banner_names_the_refusal(common, isolated_state):
    c = common(available=False)
    c.append_jsonl(isolated_state / "t.jsonl", {"i": 1})
    import hook_session_start
    importlib.reload(hook_session_start)
    import asyncio
    banner = asyncio.run(hook_session_start.gather_warnings())
    assert "hook error" in banner and "errors.log" in banner


def test_a_hook_under_zerotrust_without_encryption_still_exits_cleanly(hook_runner, capsys):
    run, state, repo = hook_runner
    import crypto
    crypto_is = crypto.is_available
    crypto.is_available = lambda: False
    try:
        run("hook_post_tool_bash", {"cwd": str(repo), "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"},
                                    "hook_event_name": "PostToolUse", "session_id": "s1"}, settings=ZERO)
    finally:
        crypto.is_available = crypto_is
    assert list(state.rglob("pending.jsonl")) in ([], [p for p in state.rglob("pending.jsonl") if p.read_text() == ""])
