"""Shared helpers for the presence bench scripts.

Stdlib only. Each bench script seeds an isolated state directory, runs the
target N times, and prints both a one-line human summary and a JSON blob the
PR description can quote verbatim.
"""
from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile. Avoids numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def time_subprocess(
    cmd: list[str],
    env: dict,
    stdin_bytes: bytes = b"",
    cwd: str | None = None,
) -> tuple[float, int]:
    """Run cmd, return (wall-clock seconds, returncode). Discards stdout; keeps
    stderr in memory only long enough to drop it (we never want bench output
    polluted by hook chatter, but we do want returncode so callers can
    invalidate runs where the hook crashed).
    """
    t0 = time.perf_counter()
    r = subprocess.run(  # noqa: S603
        cmd,
        env=env,
        input=stdin_bytes,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=cwd,
        check=False,
    )
    return time.perf_counter() - t0, r.returncode


def assert_all_ok(returncodes: list[int], label: str) -> None:
    """Abort the bench run if any sample exited non-zero. A crashing hook
    produces fast, fake-good wall-clock samples; silently averaging them in
    invalidates the SLO."""
    bad = [i for i, rc in enumerate(returncodes) if rc != 0]
    if bad:
        raise SystemExit(
            f"bench '{label}' invalidated: {len(bad)}/{len(returncodes)} "
            f"samples exited non-zero (first index {bad[0]}). "
            f"Hook is crashing; numbers below would not be meaningful."
        )


def summarize(samples_s: list[float]) -> dict:
    samples_ms = [s * 1000.0 for s in samples_s]
    return {
        "n": len(samples_ms),
        "min_ms": round(min(samples_ms), 2),
        "median_ms": round(statistics.median(samples_ms), 2),
        "p95_ms": round(percentile(samples_ms, 95), 2),
        "max_ms": round(max(samples_ms), 2),
        "mean_ms": round(statistics.fmean(samples_ms), 2),
        "stdev_ms": round(statistics.pstdev(samples_ms), 2) if len(samples_ms) > 1 else 0.0,
    }


def env_info() -> dict:
    return {
        "platform": f"{platform.system()} {platform.machine()} {platform.release()}",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }


def emit_report(name: str, runs: int, summary: dict, extras: dict | None = None) -> None:
    extras = extras or {}
    full = {"bench": name, "env": env_info(), "summary": summary, **extras}
    line = (
        f"{name}: n={summary['n']}  median={summary['median_ms']} ms  "
        f"p95={summary['p95_ms']} ms  min={summary['min_ms']} ms  "
        f"max={summary['max_ms']} ms  stdev={summary['stdev_ms']} ms"
    )
    print(line)
    print(json.dumps(full, indent=2))
