"""Aggregate session bench: total wall-clock presence adds to a realistic session.

A "session" here is a synthetic mix of hook fires that approximates a 30-minute
coding session:

  1 x SessionStart             (cwd = real test repo, populated state)
  30 x PostToolUse(Edit)       (drives append_event)
  10 x PostToolUse(Bash)       (assorted exits)
  30 x UserPromptSubmit        (drains the events appended above)
  5 x PreToolUse(Bash)         (`git commit -m ...`, exercises the gate)
  1 x Stop

Total: 77 hook fires per session. Reports total session overhead and per-hook
breakdown (median + p95 across all sessions).

Usage:
    python3 bench/aggregate_session.py [--runs N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import REPO_ROOT, emit_report, percentile, summarize, time_subprocess  # noqa: E402

SCRIPTS_DIR = REPO_ROOT / "hooks" / "scripts"

# Hook fire mix per session.
EDIT_FIRES = 30
POST_BASH_FIRES = 10
USER_PROMPT_FIRES = 30
PRE_COMMIT_FIRES = 5


def _make_repo(parent: Path) -> Path:
    repo = parent / "fake-repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)  # noqa: S607
    subprocess.run(["git", "config", "user.email", "b@b"], cwd=repo, check=True)  # noqa: S607
    subprocess.run(["git", "config", "user.name", "bench"], cwd=repo, check=True)  # noqa: S607
    subprocess.run(  # noqa: S607
        ["git", "commit", "--allow-empty", "-m", "init", "-q"],
        cwd=repo,
        check=True,
    )
    return repo


def _repo_id(repo: Path) -> str:
    out = subprocess.run(  # noqa: S607
        ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
        check=False,
    )
    seed = out.stdout.strip() or str(repo)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _seed_state(state_dir: Path, repo: Path) -> None:
    """Same shape as session_start_populated: 10 KB model + 100 events + 50 claims."""
    rid = _repo_id(repo)
    proj_dir = state_dir / "projects" / rid
    proj_dir.mkdir(parents=True, exist_ok=True)
    block = (
        "## 2026-04-26 12:00\n\n"
        "Observation: bench fixture entry. Padding follows.\n"
    )
    body = block * (10 * 1024 // len(block) + 1)
    (proj_dir / "model.md").write_text(
        "# Project model: maintained by presence (bench fixture)\n\n" + body[:10 * 1024],
        encoding="utf-8",
    )
    ev_dir = state_dir / "events" / rid
    ev_dir.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    with open(ev_dir / "pending.jsonl", "w", encoding="utf-8") as f:
        for i in range(100):
            kind = "edit" if i % 2 == 0 else "bash"
            row = {"ts": now - (100 - i), "kind": kind}
            if kind == "edit":
                row["path"] = f"src/file_{i % 12}.py"
            else:
                row["cmd"] = "pytest -q"
                row["exit"] = 0
            f.write(json.dumps(row) + "\n")
    tel_dir = state_dir / "telemetry"
    tel_dir.mkdir(parents=True, exist_ok=True)
    with open(tel_dir / "claims.jsonl", "w", encoding="utf-8") as f:
        for i in range(50):
            sha = hashlib.sha1(f"bench-{i}".encode()).hexdigest()  # noqa: S324
            f.write(json.dumps({
                "ts": now - (50 - i) * 60,
                "kind": "commit",
                "repo": rid,
                "root": str(repo),
                "sha": sha,
                "message": f"bench claim #{i}",
            }) + "\n")
    (proj_dir / "last_seen").write_text(str(now - 3600) + "\n", encoding="utf-8")


def _build_env(state_dir: Path) -> dict:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["PRESENCE_STATE"] = str(state_dir)
    return env


def _run_one_session(env: dict, repo: Path) -> dict:
    """Execute one full session worth of hook fires. Return per-hook timing lists."""
    cwd = str(repo)
    timings: dict[str, list[float]] = {
        "session_start": [], "post_tool_edit": [], "post_tool_bash": [],
        "user_prompt_submit": [], "pre_tool_bash": [], "stop": [],
    }

    def run(script: str, payload: dict, key: str) -> None:
        timings[key].append(time_subprocess(
            ["bash", str(SCRIPTS_DIR / script)],
            env=env,
            stdin_bytes=json.dumps(payload).encode("utf-8"),
            cwd=cwd,
        ))

    # 1. SessionStart
    run("session-start.sh", {"cwd": cwd, "session_id": "agg-bench"}, "session_start")

    # 2. Interleaved edits + bashes + user-prompt-submits to mimic real flow.
    #    The exact order doesn't change total wall-clock; the mix matters for
    #    realism (event-queue grows, then drains).
    for i in range(max(EDIT_FIRES, USER_PROMPT_FIRES, POST_BASH_FIRES)):
        if i < EDIT_FIRES:
            run("post-tool-edit.sh", {
                "cwd": cwd, "tool_name": "Edit",
                "tool_input": {"file_path": f"src/m_{i % 8}.py"},
            }, "post_tool_edit")
        if i < POST_BASH_FIRES:
            run("post-tool-bash.sh", {
                "cwd": cwd,
                "tool_input": {"command": "pytest -q"},
                "tool_response": {"exit_code": 0 if i % 3 else 1},
            }, "post_tool_bash")
        if i < USER_PROMPT_FIRES:
            run("user-prompt-submit.sh", {"cwd": cwd, "prompt": "next"}, "user_prompt_submit")

    # 3. Pre-commit gate fires.
    for i in range(PRE_COMMIT_FIRES):
        run("pre-tool-bash.sh", {
            "cwd": cwd,
            "tool_input": {"command": f'git commit -m "bench {i}"'},
        }, "pre_tool_bash")

    # 4. Stop.
    run("stop.sh", {"cwd": cwd}, "stop")

    return timings


def main() -> int:
    ap = argparse.ArgumentParser(description="presence: aggregate-session bench")
    ap.add_argument("--runs", type=int, default=10,
                    help="number of full sessions to time (each = 77 hook fires)")
    args = ap.parse_args()

    if not SCRIPTS_DIR.exists():
        raise SystemExit(f"scripts dir not found: {SCRIPTS_DIR}")

    with tempfile.TemporaryDirectory(prefix="presence-bench-agg-") as td:
        td_path = Path(td)
        state_dir = td_path / "presence"
        state_dir.mkdir(parents=True, exist_ok=True)
        repo = _make_repo(td_path)
        _seed_state(state_dir, repo)
        env = _build_env(state_dir)

        # Warm-up: 1 throwaway session to populate caches (.python_version_ok, FS).
        _run_one_session(env, repo)
        # Re-seed events file (warm-up drained it).
        _seed_state(state_dir, repo)

        per_hook_all: dict[str, list[float]] = {
            "session_start": [], "post_tool_edit": [], "post_tool_bash": [],
            "user_prompt_submit": [], "pre_tool_bash": [], "stop": [],
        }
        session_totals: list[float] = []
        for _ in range(args.runs):
            t = _run_one_session(env, repo)
            session_total = sum(sum(v) for v in t.values())
            session_totals.append(session_total)
            for k, v in t.items():
                per_hook_all[k].extend(v)
            _seed_state(state_dir, repo)

    session_summary = summarize(session_totals)
    per_hook_summary = {
        k: {
            "fires_per_session": len(v) // args.runs,
            "total_fires": len(v),
            "median_ms": round(sorted([s * 1000 for s in v])[len(v) // 2], 2),
            "p95_ms": round(percentile([s * 1000 for s in v], 95), 2),
        }
        for k, v in per_hook_all.items()
    }

    emit_report(
        "aggregate_session",
        runs=args.runs,
        summary=session_summary,
        extras={
            "fires_per_session": sum(len(v) for v in per_hook_all.values()) // args.runs,
            "per_hook": per_hook_summary,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
