"""Verify by tree: the working copy's tree hash says exactly what a test run covered, whoever made the edits."""
from __future__ import annotations

import subprocess

import pytest
import worktree


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(fake_repo):
    (fake_repo / "lib").mkdir()
    (fake_repo / "lib" / "a.py").write_text("x = 1\n")
    (fake_repo / "README.md").write_text("hi\n")
    (fake_repo / ".gitignore").write_text("build/\n")
    git(fake_repo, "add", "-A")
    git(fake_repo, "commit", "-q", "-m", "seed")
    return fake_repo


def test_a_clean_tree_hashes_to_the_head_tree(repo):
    assert worktree.snapshot(repo)["tree"] == git(repo, "rev-parse", "HEAD^{tree}")


def test_any_change_to_the_working_copy_changes_the_hash(repo):
    clean = worktree.snapshot(repo)["tree"]
    (repo / "lib" / "a.py").write_text("x = 2\n")
    edited = worktree.snapshot(repo)["tree"]
    (repo / "new.py").write_text("y = 1\n")
    untracked = worktree.snapshot(repo)["tree"]
    assert len({clean, edited, untracked}) == 3


def test_ignored_files_do_not_count(repo):
    clean = worktree.snapshot(repo)["tree"]
    (repo / "build").mkdir()
    (repo / "build" / "out.bin").write_text("junk")
    assert worktree.snapshot(repo)["tree"] == clean


def test_computing_a_snapshot_adds_nothing_to_the_repository(repo):
    (repo / "lib" / "a.py").write_text("x = 3\n")
    before = git(repo, "count-objects", "-v")
    index_before = (repo / ".git" / "index").read_bytes()
    worktree.snapshot(repo)
    assert git(repo, "count-objects", "-v") == before
    assert (repo / ".git" / "index").read_bytes() == index_before


def test_outside_a_repository_there_is_no_snapshot(tmp_path):
    assert worktree.snapshot(tmp_path) is None


def test_the_diff_lists_paths_against_the_base_tree_with_blob_ids_only(repo):
    base = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "lib" / "a.py").write_text("x = 2\n")
    (repo / "notes.txt").write_text("n\n")
    snap = worktree.snapshot(repo, base_head_tree=base)
    assert set(snap["diff"]) == {"lib/a.py", "notes.txt"}
    assert all(len(oid) in (40, 64) for oid in snap["diff"].values())


# --- the gate's view -------------------------------------------------------------------------

def _start(repo, sid="s1"):
    worktree.ensure_base(repo, sid)


def test_an_edit_made_outside_the_edit_tools_is_seen(repo, isolated_state):
    _start(repo)
    assert worktree.view(repo, "s1") == {"code_changed": False, "verified_exact": None}
    (repo / "lib" / "a.py").write_text("x = 2\n")  # a sed, a heredoc, a checkout: no hook saw it
    assert worktree.view(repo, "s1")["code_changed"] is True


def test_docs_only_changes_are_not_code(repo, isolated_state):
    _start(repo)
    (repo / "README.md").write_text("changed\n")
    (repo / "notes.txt").write_text("n\n")
    assert worktree.view(repo, "s1")["code_changed"] is False


def test_a_pass_on_this_exact_tree_verifies_it_and_a_later_edit_does_not(repo, isolated_state):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    worktree.record_pass(repo, "s1")
    assert worktree.view(repo, "s1") == {"code_changed": True, "verified_exact": True}
    (repo / "lib" / "a.py").write_text("x = 3\n")
    assert worktree.view(repo, "s1")["verified_exact"] is False


def test_a_failed_run_clears_what_was_verified(repo, isolated_state):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    worktree.record_pass(repo, "s1")
    worktree.record_fail(repo, "s1")
    assert worktree.view(repo, "s1")["verified_exact"] is None


def test_putting_the_tree_back_means_nothing_changed(repo, isolated_state):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    git(repo, "checkout", "--", "lib/a.py")
    assert worktree.view(repo, "s1")["code_changed"] is False


def test_committing_what_was_tested_keeps_it_verified(repo, isolated_state):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    worktree.record_pass(repo, "s1")
    git(repo, "commit", "-q", "-am", "x2")
    assert worktree.view(repo, "s1") == {"code_changed": True, "verified_exact": True}


def test_a_new_session_starts_from_its_own_baseline(repo, isolated_state):
    _start(repo, "s1")
    (repo / "lib" / "a.py").write_text("x = 2\n")
    assert worktree.view(repo, "s1")["code_changed"] is True
    _start(repo, "s2")  # the owner's uncommitted work at the start of a session is not the agent's
    assert worktree.view(repo, "s2")["code_changed"] is False


def test_too_many_changed_paths_is_treated_as_a_code_change(repo, isolated_state):
    _start(repo)
    for i in range(worktree.MAX_DIFF + 5):
        (repo / f"f{i}.md").write_text("d\n")
    assert worktree.view(repo, "s1")["code_changed"] is True  # cannot tell, so assume code


def test_no_view_without_a_baseline_or_outside_a_repository(repo, isolated_state, tmp_path):
    assert worktree.view(repo, "never-started") is None
    assert worktree.view(tmp_path, "s1") is None


# --- a repository too big to hash quickly must not slow every turn ---------------------------------

def _count_calls(monkeypatch):
    calls = []
    real = worktree.snapshot

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(worktree, "snapshot", counting)
    return calls


def test_a_failed_baseline_marks_the_session_slow_and_is_not_retried(repo, isolated_state, monkeypatch):
    monkeypatch.setattr(worktree, "snapshot", lambda *a, **k: None)
    worktree.ensure_base(repo, "s1")
    calls = _count_calls(monkeypatch)
    worktree.ensure_base(repo, "s1")
    assert worktree.view(repo, "s1") is None and worktree.record_pass(repo, "s1") is None
    assert calls == []  # nothing tried again this session


def test_a_snapshot_over_budget_is_used_once_then_skipped(repo, isolated_state, monkeypatch):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")

    class SlowClock:  # each reading jumps ten seconds: every snapshot looks too slow
        t = 0.0

        @classmethod
        def monotonic(cls):
            cls.t += 10.0
            return cls.t

    monkeypatch.setattr(worktree, "time", SlowClock)
    assert worktree.view(repo, "s1")["code_changed"] is True  # the slow answer is still a good answer
    calls = _count_calls(monkeypatch)
    assert worktree.view(repo, "s1") is None and calls == []


def test_a_new_session_tries_again(repo, isolated_state, monkeypatch):
    monkeypatch.setattr(worktree, "snapshot", lambda *a, **k: None)
    worktree.ensure_base(repo, "s1")
    monkeypatch.undo()
    _start(repo, "s2")
    assert worktree.view(repo, "s2") == {"code_changed": False, "verified_exact": None}


# --- the tests themselves leave files behind; those must not change the tree ---------------------

@pytest.mark.parametrize("artifact", [
    "__pycache__/a.cpython-314.pyc", "lib/__pycache__/m.pyc", "stray.pyc", ".pytest_cache/v/cache/lastfailed",
    ".mypy_cache/x.json", ".ruff_cache/y", ".hypothesis/z", "node_modules/pkg/index.js", ".coverage",
    "htmlcov/index.html", ".DS_Store", "pkg.egg-info/PKG-INFO", ".venv/bin/python", ".tox/py/x", "target/debug/bin",
])
def test_known_tool_artifacts_do_not_change_the_tree(repo, artifact):
    clean = worktree.snapshot(repo)["tree"]
    path = repo / artifact
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    assert worktree.snapshot(repo)["tree"] == clean


def test_a_tracked_file_in_an_artifact_directory_still_counts(repo):
    """The list only hides untracked files: committing something there makes it part of the project."""
    (repo / "build_tools").mkdir()
    (repo / "target").mkdir()
    (repo / "target" / "keep.txt").write_text("v1")
    git(repo, "add", "-f", "target/keep.txt")
    git(repo, "commit", "-q", "-m", "track")
    before = worktree.snapshot(repo)["tree"]
    (repo / "target" / "keep.txt").write_text("v2")
    assert worktree.snapshot(repo)["tree"] != before


def test_a_real_untracked_source_file_still_counts(repo):
    clean = worktree.snapshot(repo)["tree"]
    (repo / "lib" / "helper.py").write_text("y = 1\n")
    assert worktree.snapshot(repo)["tree"] != clean


def test_a_same_size_edit_within_the_same_second_is_not_missed(repo):
    """Git's racy-clean rule: an index entry as new as the index itself is re-read. Copying the index
    with a fresh mtime hides that and a quick same-size edit would look unchanged, so the copy keeps it."""
    import os
    index = repo / ".git" / "index"
    stamp = 1_700_000_000
    git(repo, "update-index", "--refresh")
    target = repo / "lib" / "a.py"
    os.utime(target, (stamp, stamp))
    git(repo, "update-index", "--add", "lib/a.py")  # entry now records mtime == stamp
    os.utime(index, (stamp, stamp))                # index as old as its newest entry: racy
    before = worktree.snapshot(repo)["tree"]
    target.write_text("x = 9\n")                   # same size as "x = 1\n"
    os.utime(target, (stamp, stamp))               # and the same mtime
    assert worktree.snapshot(repo)["tree"] != before


def test_a_judged_edit_is_not_counted_again_on_the_next_turn(repo, isolated_state):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    assert worktree.view(repo, "s1", judge=True)["code_changed"] is True  # a claim turn judges the edit
    assert worktree.view(repo, "s1", judge=True)["code_changed"] is False  # a later turn that touched no code
    (repo / "lib" / "a.py").write_text("x = 3\n")
    assert worktree.view(repo, "s1", judge=True)["code_changed"] is True  # new code, judged again


def test_looking_without_judging_still_sees_every_edit_of_the_session(repo, isolated_state):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    worktree.view(repo, "s1", judge=True)
    assert worktree.view(repo, "s1")["code_changed"] is True  # the commit gate asks about the whole session


def test_judging_a_turn_keeps_what_the_last_pass_verified(repo, isolated_state):
    _start(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    worktree.record_pass(repo, "s1")
    worktree.view(repo, "s1", judge=True)
    assert worktree.view(repo, "s1", judge=True)["verified_exact"] is True


def _slow_state(repo):
    import json
    return json.loads((worktree._state_path(repo)).read_text())


def test_a_failed_snapshot_records_why_the_session_fell_back(repo, isolated_state, monkeypatch):
    monkeypatch.setattr(worktree, "snapshot", lambda *a, **k: None)
    worktree.ensure_base(repo, "s1")
    state = _slow_state(repo)
    assert state["slow"] is True and state["slow_reason"] == "failed"


def test_a_snapshot_over_budget_records_the_reason_and_the_time(repo, isolated_state, monkeypatch):
    class SlowClock:
        t = 0.0

        @classmethod
        def monotonic(cls):
            cls.t += 10.0
            return cls.t

    monkeypatch.setattr(worktree, "time", SlowClock)
    worktree.ensure_base(repo, "s1")
    state = _slow_state(repo)
    assert state["slow_reason"] == "over_budget" and state["slow_seconds"] == 10.0


def test_a_snapshot_killed_at_the_budget_counts_as_over_budget_not_failed(repo, isolated_state, monkeypatch):
    class Clock:
        t = 0.0

        @classmethod
        def monotonic(cls):
            cls.t += worktree.BUDGET  # the git call was cut off exactly at the budget
            return cls.t

    monkeypatch.setattr(worktree, "time", Clock)
    monkeypatch.setattr(worktree, "snapshot", lambda *a, **k: None)
    worktree.ensure_base(repo, "s1")
    assert _slow_state(repo)["slow_reason"] == "over_budget"
