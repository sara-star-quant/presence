#!/usr/bin/env bash
# Bench: time install.sh against a clean CLAUDE_HOME, then time the python
# invocation that /presence-status runs to produce its answer.
#
# Two numbers per iteration:
#   install_ms : wall-clock for ./install.sh on an empty CLAUDE_HOME
#   status_ms  : wall-clock for `python3 lib/doctor.py --json --cwd .` (what
#                /presence-status executes via the Bash allowed-tool block)
#
# Reports median + p95 + min + max + stdev for both, plus a one-line summary.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS="${1:-10}"

mkdir_tmp() {
  local prefix="$1"
  case "$(uname -s)" in
    Darwin|Linux) mktemp -d -t "${prefix}.XXXXXX" 2>/dev/null || mktemp -d "/tmp/${prefix}.XXXXXX" ;;
    *) mktemp -d ;;
  esac
}

# Helper: pick the highest-resolution timer available.
hr_now_ms() {
  python3 -c 'import time; print(int(time.perf_counter()*1000))'
}

install_samples=()
status_samples=()

for _ in $(seq 1 "$RUNS"); do
  fake_home="$(mkdir_tmp presence-bench-install)"
  state_dir="$fake_home/presence"
  export CLAUDE_HOME="$fake_home"
  export PRESENCE_STATE="$state_dir"
  # Force the install.sh to symlink the repo (relative to its own location).
  t0=$(hr_now_ms)
  bash "$REPO_ROOT/install.sh" >/dev/null 2>&1 || true
  t1=$(hr_now_ms)
  install_samples+=( "$((t1 - t0))" )

  # /presence-status executes this exact command per commands/presence-status.md.
  t2=$(hr_now_ms)
  PYTHONPATH="$REPO_ROOT/lib" python3 "$REPO_ROOT/lib/doctor.py" --cwd "$REPO_ROOT" --json >/dev/null 2>&1 || true
  t3=$(hr_now_ms)
  status_samples+=( "$((t3 - t2))" )

  # Clean up the symlink we created in CLAUDE_HOME so the next iteration is fresh.
  rm -rf "$fake_home"
done

unset CLAUDE_HOME PRESENCE_STATE

# Hand the samples to a tiny python summary so the format matches the other benches.
python3 - "$RUNS" "${install_samples[@]}" "${status_samples[@]}" <<'PY'
import json, statistics, sys, platform

argv = sys.argv[1:]
runs = int(argv[0])
nums = [int(x) for x in argv[1:]]
install_ms = nums[:runs]
status_ms = nums[runs:]

def pct(values, p):
    s = sorted(values)
    if not s: return 0
    k = max(0, min(len(s)-1, int(round((p/100.0)*(len(s)-1)))))
    return s[k]

def summary(name, vals):
    return {
        "n": len(vals),
        "min_ms": min(vals),
        "median_ms": int(statistics.median(vals)),
        "p95_ms": pct(vals, 95),
        "max_ms": max(vals),
        "mean_ms": int(statistics.fmean(vals)),
        "stdev_ms": int(statistics.pstdev(vals)) if len(vals) > 1 else 0,
    }

inst = summary("install", install_ms)
stat = summary("status", status_ms)
total_median = inst["median_ms"] + stat["median_ms"]

print(
    "install_to_working: n={n}  install_median={i_med} ms  status_median={s_med} ms  "
    "total_median={t} ms  install_p95={i_p95} ms  status_p95={s_p95} ms".format(
        n=runs, i_med=inst["median_ms"], s_med=stat["median_ms"],
        t=total_median, i_p95=inst["p95_ms"], s_p95=stat["p95_ms"],
    )
)
print(json.dumps({
    "bench": "install_to_working",
    "env": {
        "platform": "{} {} {}".format(platform.system(), platform.machine(), platform.release()),
        "python": "{}.{}.{}".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro),
    },
    "install": inst,
    "status": stat,
    "total_median_ms": total_median,
}, indent=2))
PY
