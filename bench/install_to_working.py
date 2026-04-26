"""Install + first-status bench.

Times two things per iteration:
  install_ms: install.sh on a fresh CLAUDE_HOME directory
  status_ms: the python invocation that /presence-status runs (lib/doctor.py
             --json --cwd .) -- this is what Claude Code actually executes
             to produce the slash-command output.

Replaces the prior bash version. The .sh harness spawned `python3` four
times per iteration just to read a high-resolution timestamp, adding
~150 ms of measurement noise to numbers in the ~300 ms range. This Python
harness uses time.perf_counter directly and shares the rest of the bench
infrastructure with cold_startup / session_start_populated / aggregate_session.

Usage:
    python3 bench/install_to_working.py [--runs N]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import REPO_ROOT, assert_all_ok, percentile, time_subprocess  # noqa: E402

INSTALL_SH = REPO_ROOT / "install.sh"
DOCTOR_PY = REPO_ROOT / "lib" / "doctor.py"


def run(runs: int) -> dict:
    install_samples: list[float] = []
    status_samples: list[float] = []
    install_rcs: list[int] = []
    status_rcs: list[int] = []

    for _ in range(runs):
        with tempfile.TemporaryDirectory(prefix="presence-bench-install-") as fake_home:
            env = {
                **os.environ,
                "CLAUDE_HOME": fake_home,
                "PRESENCE_STATE": str(Path(fake_home) / "presence"),
            }
            t, rc = time_subprocess(["bash", str(INSTALL_SH)], env=env)
            install_samples.append(t)
            install_rcs.append(rc)

            status_env = {**env, "PYTHONPATH": str(REPO_ROOT / "lib")}
            t, rc = time_subprocess(
                [sys.executable, str(DOCTOR_PY), "--cwd", str(REPO_ROOT), "--json"],
                env=status_env,
            )
            status_samples.append(t)
            status_rcs.append(rc)

    assert_all_ok(install_rcs, "install_to_working[install]")
    assert_all_ok(status_rcs, "install_to_working[status]")

    install_ms = [s * 1000 for s in install_samples]
    status_ms = [s * 1000 for s in status_samples]

    def _summary(vals: list[float]) -> dict:
        return {
            "n": len(vals),
            "min_ms": round(min(vals), 2),
            "median_ms": round(statistics.median(vals), 2),
            "p95_ms": round(percentile(vals, 95), 2),
            "max_ms": round(max(vals), 2),
            "mean_ms": round(statistics.fmean(vals), 2),
            "stdev_ms": round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0.0,
        }

    return {
        "install": _summary(install_ms),
        "status": _summary(status_ms),
        "total_median_ms": round(
            statistics.median(install_ms) + statistics.median(status_ms), 2
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="presence: install + first-status bench")
    ap.add_argument("--runs", type=int, default=10)
    args = ap.parse_args()

    rep = run(args.runs)
    line = (
        f"install_to_working: n={args.runs}  "
        f"install_median={rep['install']['median_ms']} ms  "
        f"status_median={rep['status']['median_ms']} ms  "
        f"total_median={rep['total_median_ms']} ms  "
        f"install_p95={rep['install']['p95_ms']} ms  "
        f"status_p95={rep['status']['p95_ms']} ms"
    )
    print(line)
    print(json.dumps({
        "bench": "install_to_working",
        "env": {
            "platform": f"{platform.system()} {platform.machine()} {platform.release()}",
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
        **rep,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
