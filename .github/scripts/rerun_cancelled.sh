#!/usr/bin/env bash
# Re-run a CI run once when its only problem is jobs GitHub cancelled before any runner picked
# them up (the macOS queue does this). A real failure, or a job someone cancelled while it ran,
# is never retried: a red test is information, not weather.
#   rerun_cancelled.sh <run id> <run attempt> <owner/repo>
set -euo pipefail

run="$1" attempt="$2" repo="$3"
[ "$attempt" = "1" ] || { echo "attempt $attempt: not retrying again"; exit 0; }

jobs=$(gh api "repos/$repo/actions/runs/$run/jobs?per_page=100" --jq '.jobs')
count() { jq "[.[] | select($1)] | length" <<<"$jobs"; }

# "CI result" fails whenever any job did, so it is not evidence of a second problem
failed=$(count '.name != "CI result" and (.conclusion == "failure" or .conclusion == "timed_out")')
queued=$(count '.conclusion == "cancelled" and ((.runner_name // "") == "")')
stopped=$(count '.conclusion == "cancelled" and ((.runner_name // "") != "")')

if [ "$failed" -gt 0 ] || [ "$stopped" -gt 0 ] || [ "$queued" -eq 0 ]; then
  echo "nothing to retry (failed=$failed, cancelled while running=$stopped, cancelled in the queue=$queued)"
  exit 0
fi
echo "re-running $queued job(s) GitHub cancelled before they got a runner"
gh run rerun "$run" --failed --repo "$repo"
