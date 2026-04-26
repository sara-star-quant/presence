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
