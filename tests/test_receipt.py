"""Verification receipts: built at commit time, attached as a git note, checked without presence state."""
from __future__ import annotations

import json
import subprocess

import pytest
import receipt
from events import append_event


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo):
    (repo / "a.txt").write_text("x")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "add a")
    return _git(repo, "rev-parse", "HEAD")


def test_a_commit_after_a_passing_run_gets_a_verified_receipt(isolated_state, fake_repo):
    append_event({"kind": "edit", "file": "a.txt"}, cwd=fake_repo)
    append_event({"kind": "test_pass", "cmd": "pytest -q"}, cwd=fake_repo)
    sha = _commit(fake_repo)
    r = receipt.record(fake_repo, sha)
    assert r["commit"] == sha and r["tree"] == _git(fake_repo, "rev-parse", f"{sha}^{{tree}}")
    assert r["verified_since_edit"] is True
    assert [e["cmd"] for e in r["evidence"]] == ["pytest -q"]


def test_an_edit_after_the_last_pass_is_recorded_as_unverified(isolated_state, fake_repo):
    append_event({"kind": "test_pass", "cmd": "pytest -q"}, cwd=fake_repo)
    append_event({"kind": "edit", "file": "a.txt"}, cwd=fake_repo)
    r = receipt.record(fake_repo, _commit(fake_repo))
    assert r["verified_since_edit"] is False and r["evidence"] == []


def test_attach_then_verify_round_trip(isolated_state, fake_repo):
    append_event({"kind": "test_pass", "cmd": "pytest -q"}, cwd=fake_repo)
    sha = _commit(fake_repo)
    receipt.record(fake_repo, sha)
    receipt.attach(fake_repo, sha)
    res = receipt.verify(fake_repo, sha)
    assert res["status"] == "verified", res


def test_verify_needs_no_presence_state(isolated_state, fake_repo, monkeypatch, tmp_path):
    append_event({"kind": "test_pass", "cmd": "pytest -q"}, cwd=fake_repo)
    sha = _commit(fake_repo)
    receipt.record(fake_repo, sha)
    receipt.attach(fake_repo, sha)
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.setenv("PRESENCE_STATE", str(empty))
    assert receipt.verify(fake_repo, sha)["status"] == "verified"


def test_a_note_edited_after_the_fact_fails_the_digest(isolated_state, fake_repo):
    append_event({"kind": "edit", "file": "a.txt"}, cwd=fake_repo)
    sha = _commit(fake_repo)
    receipt.record(fake_repo, sha)
    receipt.attach(fake_repo, sha)
    note = json.loads(_git(fake_repo, "notes", "--ref=presence", "show", sha))
    note["verified_since_edit"] = True
    _git(fake_repo, "notes", "--ref=presence", "add", "-f", "-m", json.dumps(note), sha)
    assert receipt.verify(fake_repo, sha)["status"] == "tampered"


def test_a_note_copied_onto_another_commit_is_rejected(isolated_state, fake_repo):
    append_event({"kind": "test_pass", "cmd": "pytest -q"}, cwd=fake_repo)
    sha = _commit(fake_repo)
    receipt.record(fake_repo, sha)
    receipt.attach(fake_repo, sha)
    note = _git(fake_repo, "notes", "--ref=presence", "show", sha)
    (fake_repo / "b.txt").write_text("y")
    _git(fake_repo, "add", "b.txt")
    _git(fake_repo, "commit", "-q", "-m", "add b")
    other = _git(fake_repo, "rev-parse", "HEAD")
    _git(fake_repo, "notes", "--ref=presence", "add", "-f", "-m", note, other)
    assert receipt.verify(fake_repo, other)["status"] == "mismatch"


def test_unverified_receipt_is_reported_not_passed(isolated_state, fake_repo):
    append_event({"kind": "edit", "file": "a.txt"}, cwd=fake_repo)
    sha = _commit(fake_repo)
    receipt.record(fake_repo, sha)
    receipt.attach(fake_repo, sha)
    assert receipt.verify(fake_repo, sha)["status"] == "unverified"


def test_no_note_means_none(isolated_state, fake_repo):
    sha = _commit(fake_repo)
    assert receipt.verify(fake_repo, sha)["status"] == "none"


def test_attach_without_a_recorded_receipt_refuses(isolated_state, fake_repo):
    sha = _commit(fake_repo)
    with pytest.raises(LookupError):
        receipt.attach(fake_repo, sha)


def test_hook_to_cli_end_to_end(isolated_state, fake_repo, tmp_path):
    """Real hook scripts and the real CLI, real host payload shapes: edit, pass, commit, attach, verify."""
    import os
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PRESENCE_STATE": str(isolated_state), "CLAUDE_PLUGIN_ROOT": str(root),
           "PRESENCE_NO_DAEMON": "1", "PYTHONPATH": str(root / "lib"),
           "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]}
    cwd = str(fake_repo)

    def hook(script, payload):
        r = subprocess.run(["bash", str(root / "hooks" / "scripts" / script)], input=json.dumps({"cwd": cwd, **payload}),
                           capture_output=True, text=True, env=env, timeout=30, check=False)
        assert r.returncode == 0, r.stderr

    def cli(*args):
        return subprocess.run([sys.executable, str(root / "lib" / "cli.py"), *args], cwd=cwd, env=env,
                              capture_output=True, text=True, check=False)

    hook("post-tool-edit.sh", {"tool_name": "Write", "tool_input": {"file_path": "a.txt"}})
    hook("post-tool-bash.sh", {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                               "tool_input": {"command": "python -m pytest -q"},
                               "tool_response": {"stdout": "1 passed", "interrupted": False}})
    sha = _commit(fake_repo)
    hook("post-tool-bash.sh", {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                               "tool_input": {"command": "git commit -m 'add a'"},
                               "tool_response": {"stdout": f"[main {sha[:7]}] add a", "interrupted": False}})

    shown = cli("receipt")
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["commit"] == sha
    assert cli("verify-receipt").returncode == 1  # recorded locally, not attached yet: no note
    assert cli("receipt", "--attach").returncode == 0
    out = cli("verify-receipt")
    assert out.returncode == 0 and out.stdout.startswith("verified"), out.stdout + out.stderr
    assert "pytest -q" in out.stdout
