"""Cold hook startup bench: process spawn + import + settings parse, no real work.

Targets ``user-prompt-submit.sh`` because it is the lightest hook on the empty
path: with no pending events and an empty preset section, it short-circuits
right after settings load. The wall-clock therefore reflects bash + python
startup + plugin module imports + settings json parse.

Usage:
    python3 bench/cold_startup.py [--runs N] [--target user-prompt-submit|post-tool-bash]

The first 3 runs are discarded (warm the FS cache + page-in interpreter).
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import REPO_ROOT, assert_all_ok, emit_report, summarize, time_subprocess  # noqa: E402

HOOK_SCRIPTS = {
    "user-prompt-submit": "hooks/scripts/user-prompt-submit.sh",
    "post-tool-bash": "hooks/scripts/post-tool-bash.sh",
}


def _build_env(state_dir: Path) -> dict:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["PRESENCE_STATE"] = str(state_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "0"  # allow .pyc cache; we measure both states
    return env


def run(target: str, runs: int) -> dict:
    if target not in HOOK_SCRIPTS:
        raise SystemExit(f"unknown target {target!r}; choose from {list(HOOK_SCRIPTS)}")

    script = REPO_ROOT / HOOK_SCRIPTS[target]
    if not script.exists():
        raise SystemExit(f"hook script not found: {script}")

    with tempfile.TemporaryDirectory(prefix="presence-bench-cold-") as td:
        state_dir = Path(td) / "presence"
        state_dir.mkdir(parents=True, exist_ok=True)
        env = _build_env(state_dir)

        cmd = ["bash", str(script)]
        stdin_payload = b'{}\n'  # empty hook input

        # Warm-up: 3 throwaway runs so we measure steady state, not cold-cold.
        for _ in range(3):
            time_subprocess(cmd, env=env, stdin_bytes=stdin_payload, cwd=str(REPO_ROOT))

        samples: list[float] = []
        rcs: list[int] = []
        for _ in range(runs):
            t, rc = time_subprocess(cmd, env=env, stdin_bytes=stdin_payload, cwd=str(REPO_ROOT))
            samples.append(t)
            rcs.append(rc)

    assert_all_ok(rcs, f"cold_startup[{target}]")
    return summarize(samples)


def main() -> int:
    ap = argparse.ArgumentParser(description="presence: cold hook startup bench")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--target", default="user-prompt-submit", choices=list(HOOK_SCRIPTS))
    args = ap.parse_args()

    summary = run(args.target, args.runs)
    emit_report(
        f"cold_startup[{args.target}]",
        runs=args.runs,
        summary=summary,
        extras={"target": args.target, "script": HOOK_SCRIPTS[args.target]},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
