"""bench/gate_replay.py: the definitions in the evaluation plan, pinned on synthetic transcripts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
import gate_replay as gr  # noqa: E402

CWD = "/work/repo"


class Session:
    """Builds a transcript in the shape Claude Code writes."""

    def __init__(self):
        self.lines, self.t, self.n = [], 1_000_000, 0

    def _add(self, obj):
        self.t += 10
        obj.setdefault("cwd", CWD)
        obj["timestamp"] = f"2026-11-15T10:{self.t // 60 % 60:02d}:{self.t % 60:02d}Z"
        obj["sessionId"] = "s1"
        self.lines.append(json.dumps(obj))

    def prompt(self, text="do it"):
        self._add({"type": "user", "message": {"role": "user", "content": text}})
        return self

    def edit(self, path):
        self.n += 1
        self._add({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{self.n}", "name": "Edit", "input": {"file_path": path}}]}})
        self._add({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{self.n}", "content": "ok"}]}})
        return self

    def run(self, cmd, ok=True, output="x"):
        self.n += 1
        self._add({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{self.n}", "name": "Bash", "input": {"command": cmd}}]}})
        self._add({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{self.n}", "is_error": not ok, "content": output}]}})
        return self

    def final(self, text):
        self._add({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        return self

    def write(self, tmp_path, name="s1.jsonl"):
        p = tmp_path / name
        p.write_text("\n".join(self.lines) + "\n")
        return p


def _turns(tmp_path, session):
    turns, skipped = gr.replay(session.write(tmp_path))
    return turns, skipped


def test_an_unverified_claim_on_code_that_later_fails_is_a_false_done_the_gate_fired_on(tmp_path):
    s = Session().prompt().edit(f"{CWD}/a.py").final("Fixed, it works now.").prompt("run it").run("pytest -q", ok=False)
    turns, _ = _turns(tmp_path, s)
    t = [x for x in turns if x["claim"]][0]
    assert (t["fired"], t["edit_class"], t["outcome"]) == (True, "code", "false_done")


def test_a_verified_claim_that_passes_again_is_a_true_done_the_gate_did_not_fire_on(tmp_path):
    s = Session().prompt().edit(f"{CWD}/a.py").run("pytest -q").final("Fixed, tests pass.").prompt("again").run("pytest -q")
    t = [x for x in _turns(tmp_path, s)[0] if x["claim"]][0]
    assert (t["fired"], t["outcome"]) == (False, "true_done")


def test_a_later_edit_ends_the_window_so_the_claim_stays_unresolved(tmp_path):
    s = Session().prompt().edit(f"{CWD}/a.py").final("Done.").prompt("more").edit(f"{CWD}/a.py").run("pytest -q", ok=False)
    assert [x for x in _turns(tmp_path, s)[0] if x["claim"]][0]["outcome"] == "unresolved"


def test_a_piped_run_with_no_summary_is_not_a_resolving_outcome(tmp_path):
    s = Session().prompt().edit(f"{CWD}/a.py").final("Done.").prompt("check").run("pytest | tail -3", ok=True)
    assert [x for x in _turns(tmp_path, s)[0] if x["claim"]][0]["outcome"] == "unresolved"


def test_a_piped_run_resolves_through_its_summary_line(tmp_path):
    red = Session().prompt().edit(f"{CWD}/a.py").final("Done.").prompt("check").run(
        "pytest -q | tail -3", output="1 failed, 3 passed in 0.5s")
    assert [x for x in _turns(tmp_path, red)[0] if x["claim"]][0]["outcome"] == "false_done"
    green = Session().prompt().edit(f"{CWD}/a.py").run("pytest -q 2>&1 | tail -3", output="4 passed in 0.5s").final("Done, tests pass.")
    t = [x for x in _turns(tmp_path, green)[0] if x["claim"]][0]
    assert (t["fired"], t["eligible"]) == (False, True)


@pytest.mark.parametrize("path", [f"{CWD}/README.md", "/home/u/.claude/memory/x.md"])
def test_docs_and_outside_edits_are_eligible_but_the_gate_does_not_fire(tmp_path, path):
    t = [x for x in _turns(tmp_path, Session().prompt().edit(path).final("Done."))[0] if x["claim"]][0]
    assert (t["eligible"], t["fired"]) == (True, False)


@pytest.mark.parametrize("paths, expected", [
    ([f"{CWD}/README.md", f"{CWD}/notes.txt"], "docs"),
    ([f"{CWD}/a.py"], "code"),
    ([f"{CWD}/a.py", f"{CWD}/README.md"], "code"),
    (["/home/u/.claude/memory/x.md"], "outside"),
    ([f"{CWD}/a.py", "/home/u/.claude/memory/x.md"], "code"),
    ([f"{CWD}/README.md", "/home/u/.claude/memory/x.md"], "docs"),
])
def test_edit_class(tmp_path, paths, expected):
    s = Session().prompt()
    for p in paths:
        s.edit(p)
    s.final("Done.")
    assert [x for x in _turns(tmp_path, s)[0] if x["claim"]][0]["edit_class"] == expected


def test_a_turn_without_a_claim_or_without_edits_is_not_fired(tmp_path):
    s = Session().prompt().final("Done.").prompt().edit(f"{CWD}/a.py").final("Here is what I changed.")
    turns, _ = _turns(tmp_path, s)
    assert not any(t["fired"] for t in turns)


def test_hedged_claim_is_not_a_claim(tmp_path):
    s = Session().prompt().edit(f"{CWD}/a.py").final("Probably fixed, untested.")
    assert not any(t["claim"] for t in _turns(tmp_path, s)[0])


def test_unparseable_lines_are_counted_not_fatal(tmp_path):
    p = Session().prompt().edit(f"{CWD}/a.py").final("Done.").write(tmp_path)
    p.write_text(p.read_text() + "not json\n{broken\n")
    _, skipped = gr.replay(p)
    assert skipped == 2


def test_wilson_interval_known_values():
    lo, hi = gr.wilson(0, 10)
    assert lo == 0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = gr.wilson(5, 10)
    assert (lo, hi) == pytest.approx((0.2366, 0.7634), abs=1e-3)


def test_no_rate_is_reported_below_the_resolved_threshold():
    rows = [{"eligible": True, "fired": True, "claim": True, "edit_class": "code", "outcome": "false_done", "session": "a"}] * 5
    row = next(ln for ln in gr.summarize(rows).splitlines() if ln.startswith("| code"))
    assert "not enough evidence (5 resolved)" in row and " to " not in row


def test_a_rate_with_an_interval_appears_once_enough_turns_resolved():
    rows = [{"eligible": True, "fired": True, "claim": True, "edit_class": "code",
             "outcome": "false_done" if i < 15 else "true_done", "session": f"s{i % 7}"} for i in range(40)]
    row = next(ln for ln in gr.summarize(rows).splitlines() if ln.startswith("| code"))
    assert "38% (" in row and "n=40" in row
