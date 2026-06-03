# Benchmark History

Version-by-version benchmark results on the same machine (macOS arm64, Apple Silicon). All numbers are median values unless noted. Reproduce with `python3 bench/<name>.py`.

---

## v0.4.0 -- Rust Daemon Client + MCP + Adapter Pattern

**Date**: 2026-04-27
**Platform**: macOS arm64, Python 3.14.4
**Mode**: `--build-ext` (Rust daemon client active)

| Benchmark | Median | p95 | Min | Max | Stdev | n |
|---|---|---|---|---|---|---|
| `cold_startup` | **8.64 ms** | 9.30 ms | 8.12 ms | 9.35 ms | 0.35 ms | 50 |
| `session_start_populated` | **8.52 ms** | 9.22 ms | 7.99 ms | 10.05 ms | 0.38 ms | 50 |
| `aggregate_session` (77 fires) | **698 ms** | 703 ms | 690 ms | 703 ms | 3.25 ms | 10 |

Per-hook breakdown (aggregate session):

| Hook | Fires/Session | Median | p95 |
|---|---|---|---|
| `session_start` | 1 | 8.69 ms | 9.11 ms |
| `post_tool_edit` | 30 | 9.10 ms | 9.91 ms |
| `post_tool_bash` | 10 | 9.31 ms | 9.81 ms |
| `user_prompt_submit` | 30 | 8.93 ms | 9.57 ms |
| `pre_tool_bash` | 5 | 8.57 ms | 9.05 ms |
| `stop` | 1 | 8.60 ms | 9.17 ms |

**Changes**: Ephemeral auto-healing Python daemon + Rust Unix socket client (`presence-client`). The Rust binary connects to a warm resident Python process via `~/.claude/presence/presence.sock`, eliminating bash + Python interpreter startup from every hook fire. Daemon auto-exits after 5 min idle; auto-respawns on next request.

---

## v0.4.0 -- Stdlib-only mode (no `--build-ext`)

**Date**: 2026-04-27
**Platform**: macOS arm64, Python 3.14.4
**Mode**: Default (no native extensions)

| Benchmark | Median | p95 | Min | Max | Stdev | n |
|---|---|---|---|---|---|---|
| `cold_startup` | 81.76 ms | 83.84 ms | 79.67 ms | 84.68 ms | 1.13 ms | 50 |
| `session_start_populated` | 112.46 ms | 138.99 ms | 109.32 ms | 154.82 ms | 8.92 ms | 50 |
| `install_to_working` | 245.77 ms | -- | -- | -- | -- | 10 |
| `aggregate_session` (77 fires) | 6,460 ms | 7,071 ms | 6,369 ms | 7,071 ms | 186 ms | 10 |

**Changes**: Added `PYTHON_JIT=1`, `python3.14t` preference, lazy `orjson` imports, lazy `presence_ext` imports. No daemon; classical bash -> Python exec path.

---

## v0.3.2 -- Baseline (published SLOs)

**Date**: 2026-04 (pre-optimization)
**Platform**: macOS arm64, Python 3.14.4
**Mode**: Default (stdlib only)

| Benchmark | Median | p95 | n |
|---|---|---|---|
| `cold_startup` | 80 ms | 87 ms | 50 |
| `session_start_populated` | 108 ms | 113 ms | 50 |
| `install_to_working` | 237 ms | -- | 25 |
| `aggregate_session` (77 fires) | 6,400 ms | -- | 10 |

**Baseline**: Pure Python, stdlib-only. No JIT, no native extensions, no daemon.

---

## Version Comparison Summary

| Metric | v0.3.2 | v0.4.0 (stdlib) | v0.4.0 (`--build-ext`) | Speedup vs v0.3.2 |
|---|---|---|---|---|
| Cold startup | 80 ms | 82 ms | **8.6 ms** | **9.3x** |
| SessionStart | 108 ms | 112 ms | **8.5 ms** | **12.7x** |
| Aggregate (77 fires) | 6.4 s | 6.5 s | **698 ms** | **9.2x** |
