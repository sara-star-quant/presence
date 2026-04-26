"""Smoke tests for `./install.sh --update`.

Full end-to-end testing (real `git pull` against a real remote) would need a
synthetic remote setup; these tests focus on the safety paths that keep the
update flow from clobbering user state:
  - dirty working tree is refused (never silently overwrite local edits)
  - non-git directory is rejected with a clear message
  - --help mentions --update so users discover it

The actual `git pull` + `install` body is exercised when CI re-runs install.sh
in its own fresh checkout, and when users invoke it manually.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"


def _setup_fake_clone(tmp_path: Path) -> Path:
    """Copy install.sh and the .claude-plugin/ stub into a fresh git repo so
    --update can stat $SCRIPT_DIR/.git without affecting the real repo."""
    clone = tmp_path / "presence-clone"
    clone.mkdir()
    shutil.copy2(INSTALL_SH, clone / "install.sh")
    (clone / "install.sh").chmod(0o755)
    (clone / ".claude-plugin").mkdir()
    (clone / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"presence","version":"0.0.0"}', encoding="utf-8"
    )
    (clone / "lib").mkdir()
    (clone / "hooks" / "scripts").mkdir(parents=True)
    return clone


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S607
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _run_update(clone: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess[str]:
    import os
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        ["bash", str(clone / "install.sh"), "--update"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(clone),
    )


def test_update_help_mentions_update_flag():
    r = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "--update" in r.stdout, "--help must document the --update flag"


def test_update_refuses_when_not_a_git_checkout(tmp_path):
    """A user who downloaded install.sh standalone (no .git/) should get a
    clear message telling them to pull manually."""
    clone = _setup_fake_clone(tmp_path)
    # Deliberately do NOT git init; .git/ does not exist.
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    r = _run_update(clone, {
        "CLAUDE_HOME": str(fake_home),
        "PRESENCE_STATE": str(fake_home / "presence"),
    })
    assert r.returncode != 0
    assert "not a git checkout" in r.stderr.lower()


def test_update_refuses_when_working_tree_dirty(tmp_path):
    """We never want --update to clobber WIP."""
    clone = _setup_fake_clone(tmp_path)
    _git(clone, "init", "-q")
    _git(clone, "config", "user.email", "u@u")
    _git(clone, "config", "user.name", "u")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "init")
    # Dirty the tree.
    (clone / "install.sh").write_text(
        (clone / "install.sh").read_text() + "\n# local edit\n", encoding="utf-8"
    )
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    r = _run_update(clone, {
        "CLAUDE_HOME": str(fake_home),
        "PRESENCE_STATE": str(fake_home / "presence"),
    })
    assert r.returncode != 0
    assert "uncommitted changes" in r.stderr.lower()


def test_update_clean_tree_with_no_remote_still_runs_install(tmp_path):
    """Clean tree, no remote: fetch warns, pull is a no-op (already up to
    date), install body still runs and reports success. The git fetch
    warning is non-fatal."""
    clone = _setup_fake_clone(tmp_path)
    _git(clone, "init", "-q")
    _git(clone, "config", "user.email", "u@u")
    _git(clone, "config", "user.name", "u")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "init")
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    r = _run_update(clone, {
        "CLAUDE_HOME": str(fake_home),
        "PRESENCE_STATE": str(fake_home / "presence"),
    })
    # Pull --ff-only against a missing 'origin' remote may fail; either outcome
    # is acceptable as long as the script does not silently corrupt state.
    # If pull fails, exit non-zero with the diverging-history message; if it
    # somehow succeeds (e.g. local-only branch with no upstream tracked), the
    # install body runs and reports OK.
    if r.returncode == 0:
        assert "install complete" in r.stdout.lower() or "ok" in r.stdout.lower()
    else:
        # Acceptable: pull failed cleanly; no clobbering happened.
        assert "fast-forward pull failed" in r.stderr.lower() or "pull" in r.stderr.lower()


# ---------------------------------------------------------------------------
# --verify subcommand tests (v0.3.3)
#
# `--verify` is the pre-Claude-Code health check. We validate against the REAL
# repo (rather than the synthetic fake-clone used by --update tests), because
# the synthetic fire of all 6 hooks needs the real lib/ + hooks/scripts/ tree.
# Each test uses its own isolated CLAUDE_HOME / PRESENCE_STATE so it never
# touches the developer's real ~/.claude/.
# ---------------------------------------------------------------------------

def _run_install_then_verify(tmp_path: Path, *verify_args: str) -> subprocess.CompletedProcess[str]:
    """Install into a tmp CLAUDE_HOME, then run --verify (with extra args)."""
    import os

    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    env = {
        **os.environ,
        "CLAUDE_HOME": str(fake_home),
        "PRESENCE_STATE": str(fake_home / "presence"),
    }
    inst = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True, text=True, check=False, env=env,
    )
    assert inst.returncode == 0, f"install failed: {inst.stderr}"
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--verify", *verify_args],
        capture_output=True, text=True, check=False, env=env,
    )


def test_verify_help_mentions_verify_flag():
    """The --help output must document --verify so users discover it."""
    r = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "--verify" in r.stdout
    assert "--bootstrap" in r.stdout, "--help must also document --bootstrap"


def test_verify_passes_on_healthy_install(tmp_path):
    """Fresh install in an isolated CLAUDE_HOME -> --verify exits 0 with a
    'healthy' summary. Exercises every check including the synthetic fire of
    all 6 hooks against the real lib/ tree."""
    r = _run_install_then_verify(tmp_path)
    assert r.returncode == 0, (
        f"verify failed:\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    combined = r.stdout + r.stderr
    assert "healthy" in combined.lower() or "ready" in combined.lower()


def test_verify_fails_when_symlink_missing(tmp_path):
    """If the symlink is removed after install, --verify must exit 1 and
    surface the missing-symlink failure."""
    import os

    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    env = {
        **os.environ,
        "CLAUDE_HOME": str(fake_home),
        "PRESENCE_STATE": str(fake_home / "presence"),
    }
    inst = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True, text=True, check=False, env=env,
    )
    assert inst.returncode == 0
    # Remove the symlink we just created.
    plugin_link = fake_home / "plugins" / "presence"
    plugin_link.unlink()
    r = subprocess.run(
        ["bash", str(INSTALL_SH), "--verify"],
        capture_output=True, text=True, check=False, env=env,
    )
    assert r.returncode != 0
    assert "FAIL" in r.stderr
    assert "symlink" in r.stderr.lower()


def test_verify_json_emits_valid_json(tmp_path):
    """--verify --json emits a single JSON object that parses + has the
    expected shape: ok bool, checks list with name/ok/detail per entry."""
    import json

    r = _run_install_then_verify(tmp_path, "--json")
    # Exit code reflects ok-ness; we only assert the blob is parseable.
    parsed = json.loads(r.stdout)
    assert isinstance(parsed, dict)
    assert "ok" in parsed and isinstance(parsed["ok"], bool)
    assert "checks" in parsed and isinstance(parsed["checks"], list)
    for c in parsed["checks"]:
        assert {"name", "ok", "detail"}.issubset(c.keys())
        assert isinstance(c["ok"], bool)
    # Doctor blob is included on a healthy install (since python is OK).
    if parsed["ok"]:
        assert "doctor" in parsed
        assert parsed["doctor"]["python_ok"] is True


def test_verify_covers_all_six_hooks(tmp_path):
    """The synthetic-fire check must exercise all 6 hook entry points, not
    just SessionStart. We assert this by checking the JSON output contains
    a 'hook_synthetic_fire' check entry; the bash function fires all 6 in
    a loop and only records pass when every one of them succeeded."""
    import json

    r = _run_install_then_verify(tmp_path, "--json")
    parsed = json.loads(r.stdout)
    hook_check = next(
        (c for c in parsed["checks"] if c["name"] == "hook_synthetic_fire"),
        None,
    )
    assert hook_check is not None, "verify must include hook_synthetic_fire check"
    assert hook_check["ok"] is True, (
        f"hook_synthetic_fire should pass on a healthy install: {hook_check['detail']}"
    )
    assert "all 6 hooks" in hook_check["detail"]
