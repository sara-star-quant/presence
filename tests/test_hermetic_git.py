"""The suite must not inherit the developer's git setup.

Commit signing, a global hooks directory or a commit template made every test commit about six times
slower on one machine and tied results to it. CI has none of that, so the tests must not need it either.
"""
from __future__ import annotations

import os
import subprocess


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False).stdout.strip()


def test_git_reads_no_global_or_system_config(tmp_path):
    assert os.environ.get("GIT_CONFIG_GLOBAL") == os.devnull
    assert os.environ.get("GIT_CONFIG_NOSYSTEM") == "1"
    for key in ("commit.gpgsign", "tag.gpgsign", "core.hookspath", "commit.template"):
        assert _git("config", "--get", key, cwd=tmp_path) == ""


def test_a_commit_in_a_scratch_repo_is_unsigned_and_hook_free(tmp_path):
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", *cmd], cwd=tmp_path, check=True, capture_output=True)
    assert "gpgsig" not in _git("cat-file", "-p", "HEAD", cwd=tmp_path)


def test_the_suite_never_starts_a_daemon_by_accident():
    """install.sh --verify runs the compiled client when one exists, and the client spawns a daemon per state
    directory that outlives the test. CI has no such binary; a developer machine does."""
    assert os.environ.get("PRESENCE_NO_DAEMON") == "1"
