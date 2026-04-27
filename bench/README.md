# presence bench harness

Four reproducible scripts that quantify the runtime cost of presence on Claude Code's hot paths. All stdlib-only, no external dependencies. Used to publish SLOs in the CHANGELOG and the GitHub release notes, and to catch performance regressions in PRs.

## Modes (v0.4.0+)

The same scripts produce different numbers depending on whether the optional Rust daemon client is installed:

- **Default (stdlib only)**: hooks fire via the classical `bash` -> `python3 hook_*.py` exec path. v0.3.x baseline numbers (cold hook ~80 ms median).
- **`--build-ext`** (or `--download-ext`): hooks route through `lib/presence-client` -> warm Python daemon. v0.4.0 perf numbers (cold hook ~9 ms median).

Run `./install.sh --build-ext` to opt in; remove `lib/presence-client` to fall back to the default path. The bench scripts auto-detect which path is active (whichever the bash wrapper resolves to).

See [HISTORY.md](HISTORY.md) for verified per-version numbers in both modes.

## Scripts

| Script | What it measures | Default sample count |
|---|---|---|
| `cold_startup.py` | One sync hook fire (`user-prompt-submit.sh` by default) on an empty `PRESENCE_STATE`. Captures bash + python startup + module imports + settings parse. | n=50 |
| `session_start_populated.py` | One end-to-end SessionStart fire against a state dir seeded with 10 KB `model.md`, 100 events, 50 telemetry claims. Captures the heaviest single hook. | n=50 |
| `install_to_working.py` | `install.sh` against a fresh `CLAUDE_HOME` plus the `python3 lib/doctor.py --json --cwd <repo>` invocation that `/presence-status` runs. Captures the new-user first-impression path. | n=25 |
| `aggregate_session.py` | A synthetic 77-fire session: 1 SessionStart + 30 PostToolUse(Edit) + 10 PostToolUse(Bash) + 30 UserPromptSubmit + 5 PreToolUse(Bash) + 1 Stop. Captures the user-facing cumulative cost. | n=10 |

## Conventions

- Each script discards 3 warm-up runs before recording samples. We measure steady state, not cold-cold.
- Each script aborts on any non-zero hook exit (`bench/_lib.py::assert_all_ok`). A crashing hook produces fast, fake-good wall-clock samples; silently averaging them invalidates the SLO.
- Numbers are reported as median + p95 + min + max + stdev.
- Output is both a one-line human summary AND a JSON blob suitable for pasting into a PR description or release body.
- Reproduce locally with `python3 bench/<name>.py [--runs N]`. Higher N reduces noise; default N is sized for a quick check.

## Running

```bash
python3 bench/cold_startup.py            # n=50
python3 bench/cold_startup.py --runs 100 # higher confidence
python3 bench/session_start_populated.py
python3 bench/install_to_working.py
python3 bench/aggregate_session.py
```

For the full set in one go:

```bash
for s in cold_startup session_start_populated install_to_working aggregate_session; do
  python3 bench/$s.py
  echo
done
```

## Reference numbers

**v0.4.0 with `--build-ext`** (Rust daemon client, macOS arm64, Python 3.14.4):

- `cold_startup` median **8.6 ms** / p95 9.3 ms (n=50)
- `session_start_populated` median **8.5 ms** / p95 9.2 ms (n=50)
- `aggregate_session` median **698 ms** for 77 fires (n=10)

**v0.4.0 stdlib-only** (no `--build-ext`, same machine):

- `cold_startup` median 82 ms / p95 84 ms (n=50)
- `session_start_populated` median 112 ms / p95 139 ms (n=50)
- `install_to_working` total median 246 ms (install 158 + status 88), n=10
- `aggregate_session` median 6.5 s for 77 fires (n=10)

See [`HISTORY.md`](HISTORY.md) for the full version-by-version benchmark history.

Linux numbers are typically 10-25% slower depending on the runner; the CI matrix bench tier (if/when added) will publish per-platform medians.

## Adding a bench

Add a new script when:

1. Shipping a new SLO that does not fit one of the existing four. (Don't add benches for individual functions; use `python3 -m timeit` for those.)
2. Catching a regression that the existing four would not have caught. Pair the bench with a unit test that asserts the SLO holds within a margin.

Pattern to follow (in this order):

- Reuse `bench/_lib.py::time_subprocess` and `bench/_lib.py::assert_all_ok`.
- Discard the first 3 warm-up samples.
- Emit the same `<bench-name>: n=... median=... p95=...` summary line + indented JSON blob.
- Add a smoke test in `tests/test_bench_smoke.py` so a refactor that breaks the new bench is caught immediately.

## Anti-patterns

- Don't time ad-hoc shell commands for "perf evidence" without going through the bench harness; numbers won't be reproducible.
- Don't skip the warm-up; first-fire numbers are dominated by FS cache + bytecode compile state and don't reflect steady-state user experience.
- Don't trust a single sample. Always n >= 10 before publishing.
- Don't compare numbers across machines as if they were absolute. Compare deltas (before vs after on the same machine).
