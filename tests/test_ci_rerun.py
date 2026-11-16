"""The CI re-run helper: retry GitHub's queue cancellations once, never a real failure."""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "rerun_cancelled.sh"
QUEUED = {"conclusion": "cancelled", "runner_name": ""}      # waited for a runner, then GitHub gave up
STOPPED = {"conclusion": "cancelled", "runner_name": "GitHub Actions 7"}  # started, then someone cancelled it
OK = {"conclusion": "success", "runner_name": "GitHub Actions 1"}
RED = {"conclusion": "failure", "runner_name": "GitHub Actions 2"}


@pytest.fixture
def run_script(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(f"""#!/bin/sh
case "$*" in
  *"/jobs"*) jq .jobs {tmp_path}/jobs.json ;;  # the real call passes --jq .jobs
  "run rerun"*) echo "$*" > {tmp_path}/rerun ;;
esac
""")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    def go(jobs, attempt="1"):
        (tmp_path / "jobs.json").write_text(json.dumps({"jobs": jobs}))
        env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
        r = subprocess.run(["bash", str(SCRIPT), "123", attempt, "acme/widget"], env=env, capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr
        marker = tmp_path / "rerun"
        return marker.read_text().strip() if marker.exists() else None

    return go


def test_jobs_that_never_got_a_runner_are_rerun_once(run_script):
    assert run_script([OK, QUEUED, QUEUED]) == "run rerun 123 --failed --repo acme/widget"


def test_a_real_failure_is_never_retried_even_next_to_a_queue_cancellation(run_script):
    assert run_script([OK, RED, QUEUED]) is None


def test_a_job_someone_cancelled_while_it_ran_is_left_alone(run_script):
    assert run_script([OK, STOPPED]) is None
    assert run_script([OK, QUEUED, STOPPED]) is None


def test_the_second_attempt_is_never_retried_again(run_script):
    assert run_script([OK, QUEUED], attempt="2") is None


def test_nothing_to_retry_when_everything_passed(run_script):
    assert run_script([OK, OK]) is None


def test_the_workflow_is_unprivileged_beyond_actions_write_and_uses_no_untrusted_input():
    text = (ROOT / ".github" / "workflows" / "rerun-cancelled.yml").read_text()
    assert "workflow_run:" in text and "actions: write" in text and "contents: read" in text
    assert "pull_request" not in text and "head_ref" not in text and "head_branch" not in text
    assert "rerun_cancelled.sh" in text
