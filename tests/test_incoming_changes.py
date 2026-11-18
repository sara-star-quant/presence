"""Code that arrives by pull, merge, switch or a clean rebase is not the agent's work; code the agent wrote
still is. The rule only ever narrows the warning: anything unproven behaves as before."""
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
    git(fake_repo, "add", "-A")
    git(fake_repo, "commit", "-q", "-m", "seed")
    return fake_repo


@pytest.fixture
def upstream(repo, tmp_path):
    """A second clone that plays the remote; publish() commits new code there."""
    clone = tmp_path / "upstream"
    git(tmp_path, "clone", "-q", str(repo), str(clone))
    git(clone, "config", "user.email", "t@t")
    git(clone, "config", "user.name", "t")
    git(repo, "remote", "add", "up", str(clone))
    return clone


def publish(upstream, name="lib/b.py", text="y = 1\n"):
    (upstream / name).parent.mkdir(exist_ok=True)
    (upstream / name).write_text(text)
    git(upstream, "add", "-A")
    git(upstream, "commit", "-q", "-m", f"add {name}")


def branch(repo):
    return git(repo, "branch", "--show-current")


def judged(repo, sid="s1"):
    """Start a session and judge one quiet turn, so the next judge has a turn to compare with."""
    worktree.ensure_base(repo, sid)
    assert worktree.view(repo, sid, judge=True)["code_changed"] is False


def turn(repo, sid="s1"):
    return worktree.view(repo, sid, judge=True)


# --- incoming work is quiet ------------------------------------------------------------------

def test_a_fast_forward_pull_is_not_the_agents_work(repo, upstream, isolated_state):
    judged(repo)
    publish(upstream)
    git(repo, "pull", "-q", "--ff-only", "up", branch(repo))
    view = turn(repo)
    assert view["code_changed"] is False
    assert view["incoming"] is True


def test_a_fast_forward_merge_is_not_the_agents_work(repo, upstream, isolated_state):
    judged(repo)
    publish(upstream)
    git(repo, "fetch", "-q", "up")
    git(repo, "merge", "-q", "--ff-only", f"up/{branch(repo)}")
    assert turn(repo)["code_changed"] is False


def fetched_branch(repo, upstream, name="other"):
    """A branch holding code the agent did not write, fetched without touching HEAD."""
    git(upstream, "switch", "-q", "-c", name)
    publish(upstream, "lib/c.py", "z = 1\n")
    git(upstream, "switch", "-q", "-")
    git(repo, "fetch", "-q", "up", f"{name}:{name}")


def test_switching_to_another_branch_is_not_the_agents_work(repo, upstream, isolated_state):
    fetched_branch(repo, upstream)
    judged(repo)
    git(repo, "switch", "-q", "other")
    assert turn(repo)["code_changed"] is False


def test_a_pull_that_rebases_earlier_local_commits_is_not_the_agents_work(repo, upstream, isolated_state):
    (repo / "lib" / "local.py").write_text("l = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "local")
    publish(upstream)
    judged(repo)
    git(repo, "pull", "-q", "--rebase", "up", branch(repo))
    assert turn(repo)["code_changed"] is False


def test_a_clean_rebase_onto_a_new_base_is_not_the_agents_work(repo, upstream, isolated_state):
    (repo / "lib" / "local.py").write_text("l = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "local")
    publish(upstream)
    judged(repo)
    git(repo, "fetch", "-q", "up")
    git(repo, "rebase", "-q", f"up/{branch(repo)}")
    assert turn(repo)["code_changed"] is False


# --- the agent's own work stays loud ---------------------------------------------------------

def test_code_the_agent_commits_is_still_flagged(repo, isolated_state):
    judged(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    git(repo, "commit", "-q", "-am", "agent change")
    view = turn(repo)
    assert view["code_changed"] is True
    assert not view.get("incoming")


def test_an_uncommitted_edit_next_to_a_pull_is_still_flagged(repo, upstream, isolated_state):
    judged(repo)
    publish(upstream)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    git(repo, "pull", "-q", "--ff-only", "up", branch(repo))
    assert turn(repo)["code_changed"] is True


def test_a_commit_and_a_pull_in_one_window_is_still_flagged(repo, upstream, isolated_state):
    judged(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    git(repo, "commit", "-q", "-am", "agent change")
    publish(upstream)
    git(repo, "pull", "-q", "--no-rebase", "--no-edit", "up", branch(repo))
    assert turn(repo)["code_changed"] is True


def test_stash_pull_pop_is_still_flagged(repo, upstream, isolated_state):
    judged(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    publish(upstream)
    git(repo, "stash", "-q")
    git(repo, "pull", "-q", "--ff-only", "up", branch(repo))
    git(repo, "stash", "pop", "-q")
    assert turn(repo)["code_changed"] is True


def test_a_conflict_resolved_by_hand_is_still_flagged(repo, upstream, isolated_state):
    (repo / "lib" / "a.py").write_text("x = local\n")
    git(repo, "commit", "-q", "-am", "local edit")
    publish(upstream, "lib/a.py", "x = remote\n")
    judged(repo)
    git(repo, "fetch", "-q", "up")
    subprocess.run(["git", "rebase", f"up/{branch(repo)}"], cwd=repo, capture_output=True, check=False)  # stops on the conflict
    (repo / "lib" / "a.py").write_text("x = hand merged\n")
    git(repo, "add", "-A")
    subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=repo, check=True, capture_output=True)
    assert turn(repo)["code_changed"] is True


def test_a_reset_that_removes_code_is_still_flagged(repo, isolated_state):
    (repo / "lib" / "b.py").write_text("y = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "more")
    judged(repo)
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    assert turn(repo)["code_changed"] is True


# --- when the history cannot prove it, nothing gets quieter ----------------------------------

def test_a_round_trip_between_branches_is_ambiguous_and_stays_loud(repo, upstream, isolated_state):
    main = branch(repo)
    fetched_branch(repo, upstream)
    judged(repo)
    for target in ("other", main, "other"):
        git(repo, "switch", "-q", target)
    assert turn(repo)["code_changed"] is True


def test_an_expired_reflog_stays_loud(repo, upstream, isolated_state):
    judged(repo)
    publish(upstream)
    git(repo, "pull", "-q", "--ff-only", "up", branch(repo))
    git(repo, "reflog", "expire", "--expire=now", "--all")
    assert turn(repo)["code_changed"] is True


def test_a_dirty_previous_turn_has_no_anchor_and_stays_loud(repo, upstream, isolated_state):
    judged(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    assert turn(repo)["code_changed"] is True  # judged with an edit nothing has verified
    git(repo, "checkout", "--", ".")
    publish(upstream)
    git(repo, "pull", "-q", "--ff-only", "up", branch(repo))
    assert turn(repo)["code_changed"] is True


def test_checking_out_a_commit_directly_is_not_the_agents_work(repo, upstream, isolated_state):
    judged(repo)
    publish(upstream)
    git(repo, "fetch", "-q", "up")
    git(repo, "checkout", "-q", "--detach", f"up/{branch(repo)}")
    assert turn(repo)["code_changed"] is False


# --- what must not change --------------------------------------------------------------------

def test_the_commit_gate_still_sees_pulled_code_in_the_session(repo, upstream, isolated_state):
    judged(repo)
    (repo / "lib" / "a.py").write_text("x = 2\n")
    git(repo, "commit", "-q", "-am", "agent change, never tested")
    turn(repo)  # judged and flagged
    publish(upstream)
    git(repo, "pull", "-q", "--no-rebase", "--no-edit", "up", branch(repo))
    turn(repo)
    assert worktree.view(repo, "s1")["code_changed"] is True  # a later push still warns


def test_a_turn_with_no_code_change_does_not_read_the_reflog(repo, isolated_state, monkeypatch):
    judged(repo)
    calls = []
    real = worktree._git

    def spy(cwd, *args, **kw):
        calls.append(args)
        return real(cwd, *args, **kw)

    monkeypatch.setattr(worktree, "_git", spy)
    assert turn(repo)["code_changed"] is False
    assert not any("reflog" in a for a in calls)


# --- the text git writes, pinned -------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "pull --ff-only: Fast-forward",
    "pull: Fast-forward",
    "pull -q --rebase (start): checkout 4cd3b6fdbc62",
    "pull -q --rebase (pick): local commit",
    "pull -q --rebase (finish): returning to refs/heads/main",
    "pull -q --no-rebase --no-edit up main: Merge made by the 'ort' strategy.",
    "merge feat: Fast-forward",
    "merge f2: Merge made by the 'ort' strategy.",
    "checkout: moving from main to feature/x",
    "rebase (start): checkout origin/main",
    "rebase (pick): local commit",
    "rebase (finish): returning to refs/heads/feat",
])
def test_these_movements_count_as_work_that_arrived(message):
    assert worktree._INCOMING.match(message)


@pytest.mark.parametrize("message", [
    "commit: add x",
    "commit (amend): add x",
    "commit (merge): resolved",
    "commit (initial): first",
    "cherry-pick: add x",
    "revert: undo x",
    "reset: moving to HEAD~1",
    "rebase (continue): local",
    "rebase (squash): local",
    "rebase (fixup): local",
    "rebase (reword): local",
    "rebase (edit): local",
    "pull -q --rebase (continue): local",
    "am: add x",
    "clone: from /tmp/x",
    "commit: pull: looks like a pull",
    "commit: checkout: moving from a to b",
    "pull https://example.com/r.git main: Fast-forward",  # arguments with a colon: unknown, so loud
    "",
])
def test_these_movements_are_the_agents_work_or_unknown(message):
    assert not worktree._INCOMING.match(message)


def test_a_huge_hostile_message_is_matched_in_linear_time():
    import time
    start = time.monotonic()
    for text in ("pull " + "-q " * 40_000, "merge " + "a" * 100_000, "checkout: moving from " + "a" * 100_000, "rebase (" * 20_000):
        worktree._INCOMING.match(text)
    assert time.monotonic() - start < 1.0
