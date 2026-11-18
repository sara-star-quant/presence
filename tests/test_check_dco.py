"""The DCO check: every commit in a pull request carries a sign-off that matches its author or committer."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "check_dco.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_dco", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo, *args, env=None):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Dev")
    git(tmp_path, "config", "user.email", "dev@example.com")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "base")
    return tmp_path


def commit(repo, message, author_email="dev@example.com", name="Dev"):
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": author_email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": author_email, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    git(repo, "commit", "-q", "--allow-empty", "-m", message, env=env)


def check(repo, base="HEAD~1"):
    return _load().check(str(repo), git(repo, "rev-parse", base), "HEAD")


def test_a_signed_commit_passes(repo):
    commit(repo, "add x\n\nSigned-off-by: Dev <dev@example.com>")
    assert check(repo) == []


def test_an_unsigned_commit_from_an_outside_author_is_reported(repo):
    commit(repo, "add x")
    bad = check(repo)
    assert len(bad) == 1 and "add x" in bad[0]


def test_a_sign_off_for_someone_else_does_not_count(repo):
    commit(repo, "add x\n\nSigned-off-by: Someone <someone@example.com>")
    assert len(check(repo)) == 1


def test_a_malformed_sign_off_does_not_count(repo):
    commit(repo, "add x\n\nSigned-off-by: Dev")
    assert len(check(repo)) == 1


@pytest.mark.parametrize("email", [
    "pzverkov@users.noreply.github.com",
    "10436770+pzverkov@users.noreply.github.com",
    "49699333+dependabot[bot]@users.noreply.github.com",
])
def test_the_maintainer_and_bots_are_exempt(repo, email):
    commit(repo, "maintainer change", author_email=email)
    assert check(repo) == []


@pytest.mark.parametrize("email", [
    "pzverkov@users.noreply.github.com.evil.example",
    "evil-pzverkov@users.noreply.github.com",
    "x@evil.example",
])
def test_a_lookalike_of_the_maintainer_is_not_exempt(repo, email):
    commit(repo, "x", author_email=email)
    assert len(check(repo)) == 1


def test_merge_commits_are_ignored(repo):
    main = git(repo, "branch", "--show-current")
    git(repo, "switch", "-q", "-c", "side")
    commit(repo, "side work\n\nSigned-off-by: Dev <dev@example.com>")
    git(repo, "switch", "-q", main)
    commit(repo, "main work\n\nSigned-off-by: Dev <dev@example.com>")
    base = git(repo, "rev-parse", "HEAD~1")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge side", "side")
    assert _load().check(str(repo), base, "HEAD") == []


def test_a_hostile_subject_cannot_inject_workflow_commands(repo):
    commit(repo, "::error::pwned " + chr(27) + "[31m red")
    out = " ".join(check(repo))
    assert "::" not in out and chr(27) not in out
