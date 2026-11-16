"""CI test evidence: the verifier must pin who signed it and match the tree it was made for."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import ci_evidence
import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = "acme/widget"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def commit(fake_repo):
    (fake_repo / "a.py").write_text("x = 1\n")
    _git(fake_repo, "add", "a.py")
    _git(fake_repo, "commit", "-q", "-m", "a")
    return _git(fake_repo, "rev-parse", "HEAD"), _git(fake_repo, "rev-parse", "HEAD^{tree}")


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    """A `gh` that records its argv and prints what the test chose."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log, out = tmp_path / "argv", tmp_path / "out.json"
    script = bindir / "gh"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\ncp \"$3\" {tmp_path}/subject 2>/dev/null\n"
                      f"cat {out}\nexit $(cat {tmp_path}/rc 2>/dev/null || echo 0)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

    def configure(predicate=None, rc=0, raw=None):
        (tmp_path / "rc").write_text(str(rc))
        out.write_text(raw if raw is not None else json.dumps([{"verificationResult": {"statement": {
            "predicateType": ci_evidence.PREDICATE_TYPE, "predicate": predicate}}}]))
        return log

    return configure


def _predicate(tree, **over):
    p = {"tree": tree, "commit": "c" * 40, "run_url": "https://github.com/acme/widget/actions/runs/1",
         "jobs": {"test": "success", "ruff": "success"}}
    p.update(over)
    return p


def test_the_subject_is_derived_from_the_tree_alone():
    """A consumer must be able to rebuild it without CI's help."""
    assert ci_evidence.subject_text("abc") == "presence test evidence v1\ntree abc\n"


def test_a_signed_ci_run_on_this_tree_verifies(fake_repo, commit, fake_gh):
    log = fake_gh(_predicate(commit[1]))
    res = ci_evidence.verify(fake_repo, commit[0], REPO)
    assert res["status"] == "verified" and res["tree"] == commit[1]
    args = log.read_text().split()
    for pin in ("--signer-workflow", f"{REPO}/.github/workflows/ci.yml", "--source-ref", "refs/heads/main",
                "--predicate-type", ci_evidence.PREDICATE_TYPE, "--deny-self-hosted-runners", "--repo", REPO):
        assert pin in args, pin


def test_the_subject_file_gh_checks_matches_the_tree(fake_repo, commit, fake_gh, tmp_path):
    fake_gh(_predicate(commit[1]))
    ci_evidence.verify(fake_repo, commit[0], REPO)
    # the fake copied its first argument, the subject file, before the temp dir was removed
    assert (tmp_path / "subject").read_text() == ci_evidence.subject_text(commit[1])


def test_no_attestation_for_the_tree_is_not_attested(fake_repo, commit, fake_gh):
    fake_gh(None, rc=1, raw="")
    assert ci_evidence.verify(fake_repo, commit[0], REPO)["status"] == "not_attested"


def test_a_predicate_for_another_tree_is_a_mismatch(fake_repo, commit, fake_gh):
    fake_gh(_predicate("0" * 40))
    assert ci_evidence.verify(fake_repo, commit[0], REPO)["status"] == "mismatch"


def test_a_run_with_a_failed_job_is_not_evidence(fake_repo, commit, fake_gh):
    fake_gh(_predicate(commit[1], jobs={"test": "success", "ruff": "failure"}))
    assert ci_evidence.verify(fake_repo, commit[0], REPO)["status"] == "failed_jobs"


@pytest.mark.parametrize("raw", ["not json", "{}", "[]", '[{"verificationResult": {}}]'])
def test_unreadable_gh_output_is_never_a_pass(fake_repo, commit, fake_gh, raw):
    fake_gh(None, raw=raw)
    assert ci_evidence.verify(fake_repo, commit[0], REPO)["status"] == "not_attested"


@pytest.mark.parametrize("repo", ["", "no-slash", "a/b/c", "a/b; rm -rf ~", "--repo/x", "a/ b"])
def test_repo_must_look_like_owner_slash_name(fake_repo, commit, repo):
    with pytest.raises(ValueError):
        ci_evidence.verify(fake_repo, commit[0], repo)


def test_an_option_like_rev_is_refused(fake_repo):
    with pytest.raises(ValueError):
        ci_evidence.verify(fake_repo, "--output=x", REPO)


def test_missing_gh_is_an_error_not_a_pass(fake_repo, commit, monkeypatch, tmp_path):
    only_git = tmp_path / "only-git"
    only_git.mkdir()
    (only_git / "git").symlink_to(__import__("shutil").which("git"))
    monkeypatch.setenv("PATH", str(only_git))
    with pytest.raises(ValueError):
        ci_evidence.verify(fake_repo, commit[0], REPO)


def test_cli_exit_code_follows_the_status(fake_repo, commit, fake_gh, isolated_state):
    fake_gh(_predicate(commit[1]))
    env = {**os.environ, "PRESENCE_STATE": str(isolated_state), "PYTHONPATH": str(ROOT / "lib")}

    def cli():
        return subprocess.run([sys.executable, str(ROOT / "lib" / "cli.py"), "verify-evidence", commit[0], "--repo", REPO],
                              cwd=fake_repo, env=env, capture_output=True, text=True, check=False)
    ok = cli()
    assert ok.returncode == 0 and ok.stdout.startswith("verified"), ok.stdout + ok.stderr
    fake_gh(None, rc=1, raw="")
    assert cli().returncode == 1


def test_ci_workflow_attests_only_after_every_job_passed_on_main():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = text[text.index("  attest-tests:"):]
    job = job[: job.find("\n  wheel-build:")] if "\n  wheel-build:" in job else job
    assert "if: github.event_name == 'push'" in job and "needs:" in job
    for needed in ("test", "coverage", "ruff", "bandit", "shellcheck", "manifest-integrity", "ascii", "bench"):
        assert needed in job.split("needs:")[1].split("\n")[0], needed
    assert "id-token: write" in job and "attestations: write" in job
    assert ci_evidence.PREDICATE_TYPE in job
