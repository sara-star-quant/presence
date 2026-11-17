"""Branch tests for hook_stop: the calibrated-confidence gate."""
from __future__ import annotations

import json


def _write_transcript(path, *messages):
    """Write a JSONL transcript of assistant messages (string content)."""
    lines = [json.dumps({"type": "assistant", "message": {"content": m}}) for m in messages]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed(repo, *, edit_age=None, pass_age=None):
    import events
    from _common import now_ts
    t = now_ts()
    if edit_age is not None:
        events.append_event({"kind": "edit", "ts": t - edit_age}, cwd=str(repo))
    if pass_age is not None:
        events.append_event({"kind": "test_pass", "ts": t - pass_age}, cwd=str(repo))


def _warnings(state):
    f = state / "logs" / "warnings.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _confidence(state):
    f = state / "telemetry" / "confidence.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


# --- early returns -----------------------------------------------------------

def test_disabled_confidence_returns(hook_runner, capsys, tmp_path):
    run, state, repo = hook_runner
    t = tmp_path / "t.jsonl"
    _write_transcript(t, "I fixed it, it works.")
    _seed(repo, edit_age=10)
    run("hook_stop", {"cwd": str(repo), "transcript_path": str(t)},
        settings={"preset": "solo-dev", "overrides": {"confidence.enabled": False}})
    assert capsys.readouterr().out.strip() == ""
    assert _confidence(state) == []


def test_missing_transcript_returns(hook_runner, capsys):
    run, state, repo = hook_runner
    run("hook_stop", {"cwd": str(repo)})  # no transcript_path
    assert capsys.readouterr().out.strip() == ""


def test_no_assistant_text_warns(hook_runner, tmp_path):
    run, state, repo = hook_runner
    t = tmp_path / "empty.jsonl"
    t.write_text('{"type":"user","message":{"content":"hi"}}\n', encoding="utf-8")
    run("hook_stop", {"cwd": str(repo), "transcript_path": str(t)})
    assert "transcript_no_assistant_text" in _warnings(state)


def test_hedged_claim_does_nothing(hook_runner, capsys, tmp_path):
    run, state, repo = hook_runner
    t = tmp_path / "t.jsonl"
    _write_transcript(t, "I fixed it but it is untested and needs verification.")
    _seed(repo, edit_age=10)
    run("hook_stop", {"cwd": str(repo), "transcript_path": str(t)})
    assert _confidence(state) == []  # hedged -> not a claim


def test_claim_without_recent_edit_returns(hook_runner, tmp_path):
    run, state, repo = hook_runner
    t = tmp_path / "t.jsonl"
    _write_transcript(t, "All done, it works.")
    # no edit seeded -> has_recent_edit False
    run("hook_stop", {"cwd": str(repo), "transcript_path": str(t)})
    assert _confidence(state) == []


# --- the meaningful outcomes -------------------------------------------------

def test_verified_claim_records_verified(hook_runner, tmp_path):
    run, state, repo = hook_runner
    t = tmp_path / "t.jsonl"
    _write_transcript(t, "Fixed and all tests pass.")
    _seed(repo, edit_age=10, pass_age=5)  # edit + a passing test in window
    run("hook_stop", {"cwd": str(repo), "transcript_path": str(t)})
    rows = _confidence(state)
    assert len(rows) == 1 and rows[0]["verified"] is True
    assert "unverified_success_claim" not in _warnings(state)


def test_unverified_claim_default_warns(hook_runner, capsys, tmp_path):
    run, state, repo = hook_runner
    t = tmp_path / "t.jsonl"
    _write_transcript(t, "Done, it works now.")
    _seed(repo, edit_age=10)  # edit, no pass -> unverified
    run("hook_stop", {"cwd": str(repo), "transcript_path": str(t)})
    rows = _confidence(state)
    assert len(rows) == 1 and rows[0]["verified"] is False
    assert "unverified_success_claim" in _warnings(state)
    assert capsys.readouterr().out.strip() == ""  # default stop_action is silent


def test_unverified_claim_block_emits_decision(hook_runner, capsys, tmp_path):
    run, state, repo = hook_runner
    t = tmp_path / "t.jsonl"
    _write_transcript(t, "Done, it works now.")
    _seed(repo, edit_age=10)
    run("hook_stop", {"cwd": str(repo), "transcript_path": str(t)},
        settings={"preset": "solo-dev", "overrides": {"confidence.stop_action": "block"}})
    out = capsys.readouterr().out
    assert '"decision":"block"' in out


def test_message_in_the_payload_is_used_without_a_transcript(hook_runner, capsys):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)
    run("hook_stop", {"cwd": str(repo), "last_assistant_message": "Done, it works now."},
        settings={"preset": "solo-dev", "overrides": {"confidence.stop_action": "block"}})
    assert '"decision":"block"' in capsys.readouterr().out
    assert len(_confidence(state)) == 1


def test_second_stop_after_a_block_does_not_block_again(hook_runner, capsys):
    run, state, repo = hook_runner
    _seed(repo, edit_age=10)
    run("hook_stop", {"cwd": str(repo), "last_assistant_message": "Done, it works now.", "stop_hook_active": True},
        settings={"preset": "solo-dev", "overrides": {"confidence.stop_action": "block"}})
    assert capsys.readouterr().out.strip() == ""
    assert len(_confidence(state)) == 1  # still recorded, just not blocked


# --- pure helpers ------------------------------------------------------------

def test_transcript_max_bytes_override_and_invalid():
    import hook_stop
    assert hook_stop._transcript_max_bytes({"transcript": {"max_bytes": 4096}}) == 4096
    assert hook_stop._transcript_max_bytes({"transcript": {"max_bytes": 10}}) == 1024  # floor
    assert hook_stop._transcript_max_bytes({"transcript": {"max_bytes": "nope"}}) == \
        hook_stop.TRANSCRIPT_TAIL_BYTES_DEFAULT


def test_last_assistant_text_string_and_list(tmp_path):
    import hook_stop
    p = tmp_path / "mix.jsonl"
    p.write_text(
        json.dumps({"type": "assistant", "message": {"content": "first"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "block A"}, {"type": "text", "text": "block B"}]}}) + "\n",
        encoding="utf-8",
    )
    assert hook_stop._last_assistant_text(p) == "block A\nblock B"


def _stop_after_edit(hook_runner, edited_path):
    run, state, repo = hook_runner
    run("hook_post_tool_edit", {"cwd": str(repo), "tool_name": "Edit", "tool_input": {"file_path": edited_path}})
    run("hook_stop", {"cwd": str(repo), "last_assistant_message": "Done, it works now."})
    f = state / "telemetry" / "confidence.jsonl"
    return f.read_text() if f.exists() else ""


def test_claiming_done_after_editing_only_docs_does_not_trip_the_gate(hook_runner):
    _, _, repo = hook_runner
    assert _stop_after_edit(hook_runner, f"{repo}/README.md") == ""


def test_claiming_done_after_editing_a_file_outside_the_project_does_not_trip_the_gate(hook_runner):
    assert _stop_after_edit(hook_runner, "/home/someone/.claude/memory/note.md") == ""


def test_claiming_done_after_editing_code_without_a_test_still_trips_the_gate(hook_runner):
    _, _, repo = hook_runner
    assert "unhedged_success" in _stop_after_edit(hook_runner, f"{repo}/lib/a.py")


def test_a_turn_with_no_new_code_is_not_flagged_for_an_edit_already_judged(hook_runner, tmp_path):
    import subprocess

    import worktree
    run, state, repo = hook_runner
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    worktree.ensure_base(repo, "s1")
    t = tmp_path / "t.jsonl"
    _write_transcript(t, "I fixed it, it works.")
    payload = {"cwd": str(repo), "transcript_path": str(t), "session_id": "s1"}
    (repo / "a.py").write_text("x = 2\n")
    run("hook_stop", payload)
    assert _warnings(state).count("unverified_success_claim") == 1
    run("hook_stop", payload)  # a later turn that edited nothing
    assert _warnings(state).count("unverified_success_claim") == 1
    (repo / "a.py").write_text("x = 3\n")
    run("hook_stop", payload)  # new code, so asked again
    assert _warnings(state).count("unverified_success_claim") == 2
