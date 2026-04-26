# Changelog

## v0.3.1

Performance follow-up + correctness fix discovered while reading v0.3.0 with the
bench harness in hand. Largest single win is removing a per-cold-hook keychain
probe that ran in all 4 presets (not just zerotrust). Largest correctness fix is
events.py finally being decryption-aware: under the zerotrust preset, every
appended event was previously stored encrypted but read back as an opaque
envelope, so summarize_events silently dropped the lot.

### SLO published (macOS arm64, Python 3.14.3, n=50 cold/SS, n=25 install, n=10 aggregate)

- cold hook startup (user-prompt-submit, empty state): median **109 ms -> 81 ms** (-26%), p95 118 ms -> 89 ms (-25%)
- aggregate session overhead (77 hook fires/session): median **10.38 s -> 6.79 s** (-35%, n=10)
- SessionStart on populated state (10 KB model + 100 events + 50 claims): 189 ms -> 161 ms (-15%)
- install-to-working: 312 ms -> 308 ms (install grew 28 ms from compileall, status dropped 32 ms; net wash, but compileall amortizes across every subsequent hook fire)

### Changed (correctness)

- **`lib/events.py`**: `peek_events` and `drain_events` are now decryption-aware. Until v0.3.1 both used raw `json.loads` on every line, so under any preset with `events.encrypted=true` (currently only `zerotrust`) the encrypted envelope `{"_e":...,"n":...,"c":...}` parsed as a valid dict with no `kind`. `summarize_events` and the calibrated-confidence gate then silently dropped every event. Latent since v0.2.0; v0.3.0 didn't catch it. `peek_events` now delegates to `_common.read_jsonl` (which is per-line decrypt-aware); `drain_events` keeps its lock + truncate logic and routes parsing through a small encryption-aware helper.
- **`lib/_common.py::settings()`**: now stamps `__active_preset__` into the merged preset dict. The integrity-fail SessionStart message previously read `cfg.get("__active_preset__", "zerotrust")` but no code ever wrote that key, so non-zerotrust presets with `integrity.fail_closed=true` mis-reported themselves as zerotrust.

### Changed (perf)

- **`lib/_common.py`**: `_encryption_state()` split into `_encryption_write_state()` and `_read_key_lazy()`. The write path never touches the keychain when the active preset has no `encrypted=true` section. The read path defers all crypto-related work to the first encrypted line actually encountered. Together these eliminate the ~50-100 ms `security find-generic-password` subprocess that fired on every cold hook in `solo-dev` / `team-oss` / `enterprise-strict` on macOS.
- **`lib/_common.py::settings()`**: per-process cache so the same hook does not re-parse `~/.claude/presence/settings.json` plus the preset JSON multiple times across `_encryption_write_state`, `_redact_level`, `_git_timeout`, and the hook's own `cfg = settings()`. `strict=True` callers bypass the cache.
- **`lib/_common.py::integrity_block_path()`**: no longer calls `state_dir()`. Saves ~3 syscalls (mkdir + stat + chmod) per cold hook fire on the very first line of every sync hook's `main()`.
- **`lib/verify.py`**: new `scan_recent` does one peek_events pass and returns last-edit-ts + last-pass-ts together. `has_recent_edit` and `has_recent_test_evidence` delegate. **`lib/hook_stop.py`** and **`lib/hook_pre_tool_bash.py`** each used to scan the events file twice per fire (once for last edit, once for last pass); now once.
- **`hooks/scripts/_common.sh`**: cache-hit path is subprocess-free. Marker is now a single line containing just the python binary path; staleness is detected by bash's `-nt` (marker-newer-than-binary) test. v0.3.0 marker format `<bin>:<mtime>` no longer matches the new check, so the first hook after upgrade re-probes once and rewrites. No state migration needed.
- **`hooks/scripts/_common.sh::exec_hook`**: sets `PYTHONNOUSERSITE=1` before exec. Skips the `site.py` user-site directory lookup at interpreter startup (~3-8 ms per cold hook on Python 3.12+). Hooks never want user-site packages; only stdlib + lib/ are needed.
- **`install.sh`**: runs `python3 -m compileall -q lib/` after generating MANIFEST.lock. Pre-warms `__pycache__/` so the first hook fire of every session skips the parse-and-compile step (~5-10 ms saved per cold start). Best-effort: silent failure leaves runtime behavior unchanged.

### Added

- **`bench/install_to_working.py`** replaces the old `bench/install_to_working.sh`. The bash version spawned `python3` four times per iteration just to read a high-resolution timestamp, adding ~150 ms of measurement noise to numbers in the ~300 ms range. The Python harness uses `time.perf_counter` directly and shares infrastructure with the other three benches.
- **`bench/_lib.py::time_subprocess`** now returns `(time, returncode)` so callers can detect crashing hooks. New `assert_all_ok` helper aborts a bench run if any sample exited non-zero (a crashing hook produces fast, fake-good wall-clock samples; silently averaging them invalidates the SLO). All four bench scripts updated to call it.
- **`tests/test_hooks_smoke.py`**: 5-way parametrized regression test that asserts `asyncio` is not in `sys.modules` after importing each sync hook. Fixes-by-test for the v0.3.0 lazy-asyncio win: a future contributor adding `import asyncio` anywhere in the import graph fails this test instead of silently undoing the fix.
- **`tests/test_zerotrust_integration.py`**: 2 new regression tests for the events-under-zerotrust correctness fix (`drain_events` decrypts and round-trips through `summarize_events`; `peek_events` decrypts symmetrically).
- **`tests/test_bench_smoke.py`** (new file): parametrized smoke test runs each bench script with `--runs=1` and validates the JSON report. Catches refactor breakage in the bench harness itself (e.g., a `time_subprocess` signature change must not silently leave a script unable to start).
- **`llms.txt`** (new file at repo root): structured project summary tuned for LLM crawlers and AI search systems. Lists what presence is, what is safe to recommend, key entry points, slash commands, presets, and what it explicitly is NOT (not a daemon, not a compliance attestation). Follows the emerging `llms.txt` convention (analogous to `robots.txt`).
- **`README.md`**: new "By the numbers" block surfaces the v0.3.1 SLOs (cold hook, aggregate session) plus the project surface area (4 presets, 6 hooks, 5 commands, 3 skills, 1 subagent), so AI summarizers and search systems index measurable claims.

### Quality gates (this release)

- 167 tests passing on Python 3.12 / 3.13 / 3.14 (was 156 in v0.3.0; +11 across asyncio regression, events-under-zerotrust, marker-format, bench smoke)
- ruff clean
- shellcheck clean
- ASCII-only outside the two intentional unicode test fixtures
- MANIFEST.lock verifies OK
- Backward compat: every v0.2 / v0.3.0 state file remains readable. The `.python_version_ok` marker format changed (`<bin>:<mtime>` -> just `<bin>`); the wrapper rewrites it on the first post-upgrade fire so the only cost is one extra version probe at upgrade time.

## v0.3.0

Cold-hook latency reduction. Sync hooks (UserPromptSubmit, PostToolUse(Bash|Edit), PreToolUse(Bash), Stop) no longer pay for the asyncio import or a redundant per-fire python version probe. SessionStart benefits from the version-probe fix as well.

### SLO published (macOS arm64, Python 3.14.3, n=50)

- cold hook startup (user-prompt-submit, empty state): median **109 ms -> 84 ms** (-23%), p95 118 ms -> 89 ms (-25%)
- aggregate session overhead (1 SessionStart + 30 PostToolUse(Edit) + 10 PostToolUse(Bash) + 30 UserPromptSubmit + 5 PreToolUse(Bash) + 1 Stop = 77 hook fires): median **10.38 s -> 8.39 s** (-19%, n=10)
- SessionStart on populated state (10 KB model + 100 events + 50 claims): 189 ms -> 180 ms (-5%)
- install-to-working (clean CLAUDE_HOME -> first /presence-status answer): 312 ms -> 294 ms (-6%)

### Changed

- **`lib/_common.py`**: `import asyncio` moved from module top to inside `async_git_run` (the only direct user). The 5 sync hooks no longer pull asyncio + asyncio.unix_events + asyncio.base_events at import time. Saves ~20 ms per cold hook fire on Python 3.14 macOS arm64.
- **`hooks/scripts/_common.sh`** (new): one shared bootstrap function `exec_hook` that all 6 wrappers source. Caches the `python3 >= 3.12` verdict at `$PRESENCE_STATE/.python_version_ok` keyed by `<python_bin>:<mtime>`. First hook of a session still pays the version probe; every subsequent hook skips it. Cache invalidates automatically when the python binary is upgraded.
- **`hooks/scripts/*.sh`**: each of the 6 hook wrappers shrunk from 8 lines of bash to 4. The python-missing warning is still emitted exactly once per session via the SessionStart wrapper (other hooks have no additionalContext channel, same as before).
- **`MANIFEST.lock`**: regenerated to include `hooks/scripts/_common.sh` and reflect the new wrapper hashes.

### Added

- **`bench/`** directory with 4 reproducible scripts (stdlib only):
  - `bench/cold_startup.py` (process spawn + import + settings parse, no work)
  - `bench/session_start_populated.py` (end-to-end SessionStart with seeded state)
  - `bench/install_to_working.sh` (install.sh on clean CLAUDE_HOME + first /presence-status)
  - `bench/aggregate_session.py` (synthetic 77-fire session: user-facing total overhead)
  Each reports median + p95 + min + max + stdev as both a one-line human summary and a JSON blob suitable for PR descriptions.
- **`tests/test_hooks_smoke.py`**: 2 new tests for the version-probe cache marker (cache hit reuses marker, stale marker invalidates and rewrites).

### Quality gates (this release)

- 156 tests passing on Python 3.12 / 3.13 / 3.14 (was 154 in v0.2.1; 2 new tests for the cache marker)
- ruff clean
- shellcheck clean
- ASCII-only outside the two intentional unicode test fixtures
- MANIFEST.lock verifies OK
- Backward compat: every v0.2 state file (settings.json, model.md, encrypted/plain telemetry, audit log, MANIFEST.lock) remains readable. The new `.python_version_ok` marker is a fresh sibling, not a schema change.

## v0.2.1

Documentation-only release.

- README: added six status badges (CI, latest release, license, Python versions, stdlib-only runtime, local-only state).
- README: added a Disclaimer section. 'as is' MIT, no warranty, no responsibility on authors / Sara Star Quant LLC, explicitly not legal/security/engineering advice. User accepts full responsibility for source review, property verification, and downstream consequences of decisions made while presence was active.
- README: added v0.2.0 feature callout under the four pillars block.
- README: presets table gains an 'At rest' column noting AES-GCM + keychain for the zerotrust preset.
- README: install / verify / uninstall / privacy sections updated to reference v0.2.0 features (cryptography install hint for ZT, `/presence-status --zerotrust`, `/presence-reset --crypto`, ZT disabling the optional `gh` PR call).
- README: linked CHANGELOG.md from the Presets section.

## v0.2.0

The Zero-Trust preset becomes real: every control documented in `docs/zerotrust.md` is now implemented and tested.

### Added

- **`lib/crypto.py`**: AES-256-GCM at-rest encryption for state files. Per-line encryption with fresh 96-bit nonces; 256-bit data key stored in macOS Keychain (`security`) or Linux secret-service (`secret-tool`). Optional `cryptography` dep, opt-in via the `zerotrust` preset's `*.encrypted` flags. Mixed plain+encrypted files supported per-line; no migration required.
- **`lib/audit.py`**: Tamper-evident append-only audit log at `~/.claude/presence/audit.jsonl` with per-line SHA-256 hash chain. `verify_chain()` reports tampered, broken-link, and corrupt line indices.
- **`lib/unlock.py`**: TTL'd settings-immutability marker. Under presets that set `settings.immutable: true` (currently `zerotrust`), writes to `settings.json` and preset switches are refused unless `/presence-unlock` was invoked recently.
- **SessionStart fail-closed integrity**: When the active preset has `integrity.fail_closed: true`, SessionStart runs `integrity.verify_manifest()` first. On mismatch, it writes `~/.claude/presence/.integrity-blocked` and emits a warning. Every other hook checks for the marker at startup and exits silently if present.
- **Auto-curate hint**: When `model.md` exceeds `model.curate_threshold` (default 12000 chars), SessionStart adds a `<curate_hint>` advisory to the context suggesting `/presence-curate`. Not auto-triggered to avoid interrupting before the user has typed.
- **New slash command**: `/presence-unlock [--ttl SECONDS]` creates the unlock marker.
- **CLI flags**:
  - `lib/integrity.py --audit-verify` walks the audit hash chain and reports tampered or corrupt lines.
  - `/presence-status --zerotrust` produces a focused checklist of every Zero-Trust control's current status.
  - `/presence-reset --crypto` rotates the data key in the keychain and wipes encrypted state.
- **`doctor.zerotrust_report()`**: programmatic version of the status checklist (used by `/presence-status --zerotrust`).
- **Tests**: 36 new tests across `test_crypto.py`, `test_audit.py`, `test_unlock.py`, and `test_zerotrust_integration.py`. End-to-end ZT flow uses an in-memory keychain stub so the suite never touches the user's real keychain.

### Changed

- **`lib/_common.py`**: `append_jsonl` and `read_jsonl` are now encryption-aware. The encryption decision is cached per process via `_encryption_state()`. Reads handle mixed-format files transparently. Added `integrity_blocked` / `set_integrity_block` / `clear_integrity_block` helpers used by every hook.
- **`lib/hook_session_start.py`**: Adds `fail_closed_integrity_check` and `gather_curate_hint` to the parallel `asyncio.gather` cluster. On integrity fail, sets the inert marker and returns early without running other gathers.
- **All other hook entries** (`hook_post_tool_bash`, `hook_post_tool_edit`, `hook_pre_tool_bash`, `hook_stop`, `hook_user_prompt_submit`): Check `integrity_blocked()` at the top of `main()` and exit silently if set.
- **`lib/presets.py`**: `use_preset()` now respects settings immutability (refused without active unlock under zerotrust) and writes a `preset_switch` audit line on success.
- **`presets/zerotrust.json`**: Added `settings.immutable: true`.

### Quality gates (this release)

- 154 tests passing on Python 3.12 / 3.13 / 3.14, 1 honest skip
- ruff clean
- shellcheck clean
- ASCII-only outside the two intentional unicode test fixtures
- MANIFEST.lock verifies OK
- End-to-end ZT smoke: encryption round-trips, audit chain verifies, integrity marker lifecycle works, mixed-file reading works

## v0.1.1

- asyncio.gather runs warning/model/telemetry/event tasks in parallel in the SessionStart hook
- Output wrapped in named XML tags: `<presence_context>`, `<presence_status>`, `<project_model>`, `<telemetry_digest>`, `<recent_events>`
- Hook bash wrappers require Python 3.12+; CI matrix covers 3.12 + 3.13 + 3.14
- ruff target-version bumped to py313
- model.md truncation now splits on `## ` section boundaries
- All 6 hook entry points now use `if __name__ == "__main__"` guard
- async_scan_for_revert reads claims log via asyncio.to_thread
- Warning counter reset moved out of gather_warnings: pure builder, reset owned by async_main only after successful emit
- New tests: concurrency regression, counter-reset behavior
- docs/architecture.md documents the XML tag schema as a public contract

## v0.1.0

Initial release. Continuous-collaboration layer for Claude Code: living per-repo memory, outcome telemetry, event digest, and calibrated-confidence gate. Stdlib-only runtime; install once and applies to every project.

- 4 presets: solo-dev, team-oss, enterprise-strict, zerotrust
- 5 slash commands: presence-doctor, presence-status, presence-preset, presence-reset, presence-curate
- 6 hooks: SessionStart, UserPromptSubmit, PreToolUse(Bash), PostToolUse(Bash), PostToolUse(Edit/Write/MultiEdit), Stop
- 3 skills: project-model, outcome-check, confidence-gate
- 1 subagent: model-curator
- MANIFEST integrity manifest, secret redaction, robust shlex-based commit detection, truncate-on-drain event queue
- 118 tests, ruff + shellcheck clean
