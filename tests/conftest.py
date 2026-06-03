"""Pytest configuration: add lib/ to sys.path so tests import the same way hooks do."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Point PRESENCE_STATE at a tmp dir so each test gets clean state."""
    state = tmp_path / "presence-state"
    state.mkdir()
    monkeypatch.setenv("PRESENCE_STATE", str(state))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    # Reload _common so the env vars take effect
    import importlib

    import _common
    importlib.reload(_common)
    return state


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Create a tmp git repo and chdir into it so repo_id() is stable per-test."""
    import subprocess
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture
def hook_runner(isolated_state, fake_repo, monkeypatch):
    """Drive a hook's main() in-process. Returns (run, state, repo).

    run(hook_name, payload, settings=None) plants settings.json (use dotted
    override keys, e.g. {"overrides": {"confidence.stop_action": "block"}}),
    reloads _common + the hook so they bind this test's PRESENCE_STATE and a
    fresh settings cache, feeds payload as stdin, and calls main(). Read stdout
    with the capsys fixture; inspect what the hook wrote under `state`.

    In-process (not subprocess) so coverage is measured deterministically.
    """
    import importlib
    import io
    import json
    import sys
    state = isolated_state

    def run(hook_name: str, payload: dict, settings: dict | None = None) -> None:
        if settings is not None:
            (state / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        import _common
        importlib.reload(_common)
        mod = importlib.import_module(hook_name)
        importlib.reload(mod)
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        mod.main()

    return run, state, fake_repo
