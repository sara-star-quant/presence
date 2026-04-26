"""SessionStart bench on a populated state directory.

Seeds an isolated PRESENCE_STATE with:
  - 10 KB model.md under projects/<repo_id>/model.md
  - 100 events under events/<repo_id>/pending.jsonl
  - 50 telemetry claims under telemetry/claims.jsonl

Then invokes hooks/scripts/session-start.sh end-to-end via bash, with the
'cwd' field of the hook input pointing at a real (small) git repo so repo_id
resolves stably.

Usage:
    python3 bench/session_start_populated.py [--runs N]
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
from _lib import REPO_ROOT, assert_all_ok, emit_report, summarize, time_subprocess  # noqa: E402

HOOK_SCRIPT = REPO_ROOT / "hooks/scripts/session-start.sh"


def _make_repo(parent: Path) -> Path:
    """Create a tiny git repo with one commit so repo_id is stable."""
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
    """Mirror _common.repo_id for the test repo: prefer remote, fall back to root path."""
    out = subprocess.run(  # noqa: S607
        ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
        check=False,
    )
    seed = out.stdout.strip() or str(repo)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _seed_state(state_dir: Path, repo: Path, *, model_kb: int, events: int, claims: int) -> None:
    """Populate state_dir with realistic-shape data of the requested sizes."""
    rid = _repo_id(repo)

    # model.md: 10 KB of structured-looking observation entries.
    proj_dir = state_dir / "projects" / rid
    proj_dir.mkdir(parents=True, exist_ok=True)
    header = "# Project model: maintained by presence (bench fixture)\n\n"
    block = (
        "## 2026-04-26 12:00\n\n"
        "Observation: bench fixture entry. The presence hook surfaced this "
        "during a synthetic SessionStart benchmark run. Padding follows.\n"
    )
    body = block * ((model_kb * 1024) // len(block) + 1)
    (proj_dir / "model.md").write_text(header + body[: model_kb * 1024], encoding="utf-8")

    # events/pending.jsonl: alternating edits and bashes.
    ev_dir = state_dir / "events" / rid
    ev_dir.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    with open(ev_dir / "pending.jsonl", "w", encoding="utf-8") as f:
        for i in range(events):
            kind = "edit" if i % 2 == 0 else "bash"
            row = {
                "ts": now - (events - i),
                "kind": kind,
                "path": f"src/file_{i % 12}.py" if kind == "edit" else None,
                "cmd": "pytest -q" if kind == "bash" else None,
                "exit": 0 if kind == "bash" else None,
            }
            f.write(json.dumps({k: v for k, v in row.items() if v is not None}) + "\n")

    # telemetry/claims.jsonl: 50 commit claims with synthetic SHAs.
    tel_dir = state_dir / "telemetry"
    tel_dir.mkdir(parents=True, exist_ok=True)
    with open(tel_dir / "claims.jsonl", "w", encoding="utf-8") as f:
        for i in range(claims):
            sha = hashlib.sha1(f"bench-claim-{i}".encode()).hexdigest()  # noqa: S324
            row = {
                "ts": now - (claims - i) * 60,
                "kind": "commit",
                "repo": rid,
                "root": str(repo),
                "sha": sha,
                "message": f"bench claim #{i}: synthetic commit message",
                "intent": None,
            }
            f.write(json.dumps(row) + "\n")

    # last_seen so async_scan_for_revert actually runs (instead of returning [] early).
    (proj_dir / "last_seen").write_text(str(now - 3600) + "\n", encoding="utf-8")


def _build_env(state_dir: Path) -> dict:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["PRESENCE_STATE"] = str(state_dir)
    return env


def run(runs: int, model_kb: int, events: int, claims: int) -> dict:
    if not HOOK_SCRIPT.exists():
        raise SystemExit(f"hook script not found: {HOOK_SCRIPT}")

    with tempfile.TemporaryDirectory(prefix="presence-bench-ss-") as td:
        td_path = Path(td)
        state_dir = td_path / "presence"
        state_dir.mkdir(parents=True, exist_ok=True)
        repo = _make_repo(td_path)
        _seed_state(state_dir, repo, model_kb=model_kb, events=events, claims=claims)

        env = _build_env(state_dir)
        cmd = ["bash", str(HOOK_SCRIPT)]
        # SessionStart input: claude code passes hook_event_name + cwd among others.
        stdin_payload = json.dumps({
            "hook_event_name": "SessionStart",
            "cwd": str(repo),
            "session_id": "bench",
        }).encode("utf-8")

        # Warm-up: 3 throwaway runs.
        for _ in range(3):
            time_subprocess(cmd, env=env, stdin_bytes=stdin_payload, cwd=str(repo))

        samples: list[float] = []
        rcs: list[int] = []
        for _ in range(runs):
            t, rc = time_subprocess(cmd, env=env, stdin_bytes=stdin_payload, cwd=str(repo))
            samples.append(t)
            rcs.append(rc)

    assert_all_ok(rcs, "session_start_populated")
    return summarize(samples)


def main() -> int:
    ap = argparse.ArgumentParser(description="presence: SessionStart populated bench")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--model-kb", type=int, default=10)
    ap.add_argument("--events", type=int, default=100)
    ap.add_argument("--claims", type=int, default=50)
    args = ap.parse_args()

    summary = run(args.runs, args.model_kb, args.events, args.claims)
    emit_report(
        "session_start_populated",
        runs=args.runs,
        summary=summary,
        extras={
            "fixture": {
                "model_kb": args.model_kb,
                "events": args.events,
                "telemetry_claims": args.claims,
            },
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
