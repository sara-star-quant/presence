"""Robust command parsing. The original regex-based detector blocked false positives like `grep "git commit"`."""
import pytest
from cmdparse import (
    extract_cd_target,
    extract_git_C_target,
    is_gh_pr_create,
    is_git_commit,
    is_git_push,
)


@pytest.mark.parametrize(
    "cmd, expected",
    [
        ("git commit -m 'msg'", True),
        ("git commit", True),
        ("git -C /tmp/repo commit -am foo", True),
        ("GIT_AUTHOR_NAME=x git commit -m foo", True),
        ("cd subrepo && git commit -m foo", True),
        ("git commit-tree abc123", False),  # not the same subcommand
        ('grep -r "git commit" .', False),
        ("echo 'remember to git commit'", False),
        ("# git commit (commented out)", False),
        ("ls && echo done", False),
    ],
)
def test_is_git_commit(cmd, expected):
    assert is_git_commit(cmd) is expected


@pytest.mark.parametrize(
    "cmd, expected",
    [
        ("git push", True),
        ("git push origin main", True),
        ("git -C foo push", True),
        ("echo 'git push tomorrow'", False),
        ("git push-cert verify", False),
    ],
)
def test_is_git_push(cmd, expected):
    assert is_git_push(cmd) is expected


@pytest.mark.parametrize(
    "cmd, expected",
    [
        ("gh pr create --title foo", True),
        ("gh pr create", True),
        ("echo 'gh pr create later'", False),
        ("gh pr list", False),
    ],
)
def test_is_gh_pr_create(cmd, expected):
    assert is_gh_pr_create(cmd) is expected


def test_extract_cd_target():
    assert extract_cd_target("cd /tmp/foo && git commit") == "/tmp/foo"
    assert extract_cd_target("git commit") is None


def test_extract_git_C_target():
    assert extract_git_C_target("git -C /tmp/repo commit") == "/tmp/repo"
    assert extract_git_C_target("git commit") is None


def test_unparseable_command_returns_false():
    # An unclosed quote means shlex bails; we should conservatively return False, not blow up
    assert is_git_commit("git commit -m 'unterminated") is False


# --- the same commands behind a path, a wrapper or a shell -c ---------------------------------

_WRAPPED_COMMIT = [
    "/usr/bin/git commit -m x",
    "/opt/homebrew/bin/git commit -m x",
    "env git commit -m x",
    "env GIT_AUTHOR_NAME=a git commit -m x",
    "env -i git commit -m x",
    "command git commit -m x",
    "exec git commit -m x",
    "time git commit -m x",
    "nohup git commit -m x",
    "git --no-pager commit -m x",
    "git -c core.editor=true --no-pager commit",
    "git --git-dir /x/.git commit -m x",
    "git --no-optional-locks commit -m x",
    "bash -c 'git commit -m x'",
    "sh -c \"cd repo && git commit -m x\"",
    "bash -lc 'git commit -m x'",
    "env bash -c 'git commit -m x'",
]


@pytest.mark.parametrize("cmd", _WRAPPED_COMMIT)
def test_a_wrapped_git_commit_is_still_a_commit(cmd):
    assert is_git_commit(cmd) is True


@pytest.mark.parametrize("cmd", [c.replace("commit", "push") for c in _WRAPPED_COMMIT])
def test_a_wrapped_git_push_is_still_a_push(cmd):
    assert is_git_push(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "bash -c 'echo git commit'",
        "bash script.sh git commit",
        "bash deploy.sh -c 'git commit -m x'",  # -c belongs to the script, not to bash
        "env git status",
        "mygit commit -m x",
        "/usr/bin/gitk commit",
        "git-commit",
        "git --no-pager log",
        "time ls && echo git commit",
        "sh -c 'grep \"git commit\" notes'",
        "bash -c 'git commit -m",  # unterminated: still conservative
    ],
)
def test_lookalikes_are_not_commits(cmd):
    assert is_git_commit(cmd) is False


@pytest.mark.parametrize("cmd", ["/usr/local/bin/gh pr create", "env gh pr create --fill", "bash -c 'gh pr create'", "command gh pr create"])
def test_a_wrapped_gh_pr_create_is_still_one(cmd):
    assert is_gh_pr_create(cmd) is True


def test_shell_nesting_stops_at_a_small_depth():
    cmd = "bash -c \"bash -c \\\"bash -c 'bash -c \\\\\\\"git commit\\\\\\\"'\\\"\""
    assert is_git_commit(cmd) in (True, False)  # must return, not recurse without bound


def test_the_repo_and_cd_targets_are_found_behind_the_same_wrappers():
    assert extract_git_C_target("/usr/bin/git -C /tmp/r commit -m x") == "/tmp/r"
    assert extract_git_C_target("env GIT_AUTHOR_NAME=a git -C /tmp/r commit") == "/tmp/r"
    assert extract_git_C_target("bash -c 'git -C /tmp/r commit'") == "/tmp/r"
    assert extract_cd_target("bash -c 'cd /tmp/r && git commit'") == "/tmp/r"
