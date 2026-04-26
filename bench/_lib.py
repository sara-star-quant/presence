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


def time_subprocess(cmd: list[str], env: dict, stdin_bytes: bytes = b"", cwd: str | None = None) -> float:
    """Run cmd, return wall-clock seconds. Discards output."""
    t0 = time.perf_counter()
    subprocess.run(  # noqa: S603
        cmd,
        env=env,
        input=stdin_bytes,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=cwd,
        check=False,
    )
    return time.perf_counter() - t0


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
