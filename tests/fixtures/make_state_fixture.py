"""Generate a state-directory fixture by running a past release's real hooks.

    python tests/fixtures/make_state_fixture.py v0.9.2

Checks the tag out into a scratch worktree, drives its hooks against a scratch
repo with a fixed origin URL (so repo_id is stable across machines), and copies
the resulting state tree to tests/fixtures/state/<tag>/. Run it once per
release; the output is committed and never regenerated from newer code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "fixtures" / "state"
ORIGIN = "https://example.invalid/presence-fixture.git"


def sh(*args: str, cwd: Path | None = None, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, **kw)


def main(tag: str) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="presence-fixture-"))
    wt = tmp / "plugin"
    sh("git", "worktree", "add", "--detach", str(wt), tag, cwd=ROOT)
    try:
        repo = tmp / "repo"
        repo.mkdir()
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                    ["remote", "add", "origin", ORIGIN], ["commit", "--allow-empty", "-m", "init", "-q"]):
            sh("git", *cmd, cwd=repo)
        state = tmp / "state"
        state.mkdir()
        env = {**os.environ, "PRESENCE_STATE": str(state), "CLAUDE_PLUGIN_ROOT": str(wt),
               "PRESENCE_NO_DAEMON": "1", "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]}
        transcript = tmp / "t.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Done. The change is in place."}]}}) + "\n")
        cwd = str(repo)
        steps = [
            ("session-start.sh", {"cwd": cwd, "session_id": "fx"}),
            ("user-prompt-submit.sh", {"cwd": cwd, "prompt": "fix the parser"}),
            ("post-tool-edit.sh", {"cwd": cwd, "tool_name": "Edit", "tool_input": {"file_path": "a.py"}}),
            ("post-tool-bash.sh", {"cwd": cwd, "tool_input": {"command": "pytest"}, "tool_response": {"exit_code": 1}}),
            ("post-tool-bash.sh", {"cwd": cwd, "tool_input": {"command": "pytest"}, "tool_response": {"exit_code": 0}}),
            ("post-tool-bash.sh", {"cwd": cwd, "tool_input": {"command": "git push origin main"}, "tool_response": {"exit_code": 0}}),
            ("stop.sh", {"cwd": cwd, "session_id": "fx", "transcript_path": str(transcript)}),
            ("session-start.sh", {"cwd": cwd, "session_id": "fx2"}),
        ]
        for script, payload in steps:
            r = subprocess.run(["bash", str(wt / "hooks" / "scripts" / script)], input=json.dumps(payload),
                               capture_output=True, text=True, env=env, timeout=30, check=False)
            if r.returncode != 0:
                sys.exit(f"{tag}: {script} exited {r.returncode}: {r.stderr[:300]}")
        # Written by skills and the verifier, not by hooks: call the release's own API.
        code = ("from model import append_observation as o; from telemetry import record_outcome as r; "
                f"o('Parser lives in lib/parse.py; prefers small pure functions.', cwd={cwd!r}); "
                "r('ci', 'abc1234', status='success')")
        if (wt / "lib" / "audit.py").exists():
            code += "; from audit import append as a; a('fixture_event', {'n': 1}); a('fixture_event', {'n': 2})"
        subprocess.run([sys.executable, "-c", code], env={**env, "PYTHONPATH": str(wt / "lib")},
                       check=True, capture_output=True, text=True, cwd=str(repo))
        dest = OUT / tag
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(state, dest, ignore=shutil.ignore_patterns("__pycache__", ".python_version_ok", "logs"))
        (dest / "ORIGIN").write_text(ORIGIN + "\n")
        print(f"{tag}: {sum(1 for p in dest.rglob('*') if p.is_file())} files")
    finally:
        sh("git", "worktree", "remove", "--force", str(wt), cwd=ROOT)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1])
