# Changelog

## v0.3.3

Zero-friction first install. Fixes a real bug (the installer accepted Python 3.10/3.11 even though the runtime requires 3.12+, so users on those versions got `ok` from install.sh and then every hook silently no-op'd). Adds a pre-Claude-Code health check, an opt-in Python bootstrap via uv, and a docs pass for first-time users. Plus governance docs (SECURITY.md, CONTRIBUTING.md, bench/README.md, GitHub issue + PR templates).

### Fixed

- **Python version contract corrected from 3.10 to 3.12 in install.sh + commands/presence-doctor.md.** The runtime (`hooks/scripts/_common.sh`, `lib/doctor.py`) has always required 3.12+; the installer was lying. Users on 3.10/3.11 will now see a clear message instead of silent no-op hooks. Four sites fixed: `install.sh` header comment, missing-python warning, version case statement, upgrade message; `commands/presence-doctor.md` doctor-failure advice line.

### Added

- **`install.sh --verify`**: pre-Claude-Code health check. Validates symlink, Python (using the same resolution runtime hooks do), all 6 hook scripts executable, state perms (0o700), `MANIFEST.lock` integrity, and synthetically fires all 6 hooks (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`(Bash), `PostToolUse`(Edit), `Stop`) against the real `lib/` tree. Exit 0 means ready; any FAIL line names exactly what is missing. The synthetic-fire-of-all-6-hooks check catches import regressions in any hook entry point (the original ultraplan only fired `SessionStart`, which would let a broken `hook_post_tool_bash.py` pass the check).
- **`install.sh --verify --json`**: machine-readable variant. Emits `{"ok": bool, "checks": [{"name", "ok", "detail"}], "doctor": {...}}`. Useful for CI scripts wrapping install + a sanity check.
- **`install.sh --bootstrap`**: opt-in Python bootstrap via uv. Skips silently when Python 3.12+ is already on PATH. When triggered: downloads uv from https://astral.sh (if not already installed), runs `uv python install 3.13`, resolves the binary path, writes it to `~/.claude/presence/.python_bin`, and pins it. The runtime hook wrapper (`hooks/scripts/_common.sh::_presence_pinned_python`) honors the marker so the pinned interpreter is used even when the user's PATH still points at an older python3. **Opt-in by design**: presence's "no network egress in default presets" stance applies to the installer too; the user must explicitly pass `--bootstrap`.
- **`lib/doctor.py --fix`**: auto-corrects recoverable issues (state directory or file perms drifted from 0o700 / 0o600; `MANIFEST.lock` missing; stale `.integrity-blocked` marker present but the manifest now verifies). **Refuses to silently regenerate a MISMATCHED manifest** because that would mask tampering under zerotrust; the user has to investigate and run `python3 lib/integrity.py --write` themselves. Reports every action taken.
- **`pinned_python` field in `lib/doctor.py::report()`**: surfaces the contents of `~/.claude/presence/.python_bin` so `/presence-doctor` shows which interpreter hooks will actually use (vs the one currently running doctor).
- **Five new `--verify` tests in `tests/test_install_update.py`**: --help mentions --verify and --bootstrap, --verify passes on a healthy install, --verify fails when symlink is missing, --verify --json emits valid JSON, --verify covers all 6 hooks (asserts the `hook_synthetic_fire` check is present and passes).
- **Five new `--fix` tests in `tests/test_doctor_fix.py`** (new file): chmods state dir to 0o700, chmods state files to 0o600, refuses to regenerate a mismatched manifest (the zerotrust safety guarantee), regenerates a missing manifest, clears a stale `.integrity-blocked` marker.

### Added (governance docs)

- **`SECURITY.md`**: vulnerability disclosure policy (use GitHub Security Advisory; do not file public issues), supported versions table, what is in-scope vs out-of-scope. Crosslinks `docs/security.md` and `docs/zerotrust.md`.
- **`CONTRIBUTING.md`**: hard constraints (stdlib-only runtime, ASCII-only outside two intentional unicode test fixtures, no em-dashes, branch + PR + wait-for-merge), dev environment via PEP 735 (`pip install --group dev`), local check matrix (pytest + ruff + shellcheck + integrity verify), MANIFEST regeneration triggers, slash command / skill / agent / preset additions, release flow, performance work convention.
- **`bench/README.md`**: what each of the 4 bench scripts measures, the warm-up / sample-discard convention, the `assert_all_ok` crash guard, reference numbers from v0.3.2, when to add a new bench, anti-patterns.
- **`.github/ISSUE_TEMPLATE/bug.yml`**: structured bug report (version, preset, Python, platform, expected, actual, doctor output, steps).
- **`.github/ISSUE_TEMPLATE/feature.yml`**: structured feature request (what, why, scope, alternatives) with a pointer to the `roadmap`-labeled issues so users see what is already deferred.
- **`.github/ISSUE_TEMPLATE/security.yml`**: redirect to the private security advisory flow (forbids public security disclosures via issues).
- **`.github/ISSUE_TEMPLATE/config.yml`**: disables blank issues; lists external links (security advisory, threat model doc, architecture doc).
- **`.github/pull_request_template.md`**: short template (summary, what changed, test plan checklist, backward-compat statement, ASCII / em-dash / stdlib / CHANGELOG / MANIFEST checklist).

### Changed

- **`hooks/scripts/_common.sh::exec_hook`**: now prefers `~/.claude/presence/.python_bin` over `command -v python3`. Stale-marker handling is automatic (non-executable path -> fall through to PATH lookup). The cache marker (`.python_version_ok`) keys on the resolved binary so a uv-bootstrapped path participates in the same cache.
- **`pyproject.toml`**: PEP 735 `[dependency-groups]` `dev` group (pytest, cryptography, ruff). Install with `pip install --group dev`.
- **`README.md`**: install section restructured into a **Quickstart** with two commands (install + verify) for first-time users; existing marketplace + git clone alternatives moved under "Other install methods". New "Platforms" row in the By-the-numbers table makes Linux support explicit and points Windows users at WSL2.
- **`llms.txt`**: install one-liner mentions `--bootstrap` and `--verify`; quick facts list adds the platforms row.
- **`commands/presence-doctor.md`**: mentions the new `--fix` flag.
- **`install.sh`** post-install "Next steps": first step is now `--verify` rather than "open Claude Code and hope".

### Quality gates (this release)

- 187 tests passing on Python 3.12 / 3.13 / 3.14 (was 177 in v0.3.2; +10 across `--verify` and `--fix` tests)
- ruff clean
- shellcheck clean
- ASCII-only outside the two intentional unicode test fixtures
- MANIFEST.lock verifies OK
- Backward compat: every v0.3.x state file remains readable. The `.python_bin` marker is a new sibling, not a schema change. The wrapper falls through to PATH lookup when the marker is absent or stale; existing installs work unchanged.

## v0.3.2

Distribution release: the plugin can now be installed via the `/plugin marketplace add` flow that the README has always advertised, and a real `--update` flag in `install.sh` makes the existing flow easier to keep current. No runtime behavior changes; only install/update plumbing and tests.

### Added

- **`.claude-plugin/marketplace.json`**: single-plugin marketplace manifest at the repo root. Makes `/plugin marketplace add github.com/sara-star-quant/presence` followed by `/plugin install presence` actually work (until v0.3.2 the README advertised this flow but the file was missing). Schema mirrors the format Anthropic's own marketplaces use (e.g. `anthropics/life-sciences`): `name`, `owner`, `metadata` (version + description), `plugins[]` with `name`, `source`, `description`, `category`, `tags`. `source: "./"` means "the marketplace repo itself is the plugin".
- **`install.sh --update`** flag: `git fetch` + `git pull --ff-only` + re-run of the installer. Refuses to proceed if the working tree has uncommitted changes (never clobbers WIP). Reports the old SHA -> new SHA. Falls through cleanly when there is nothing to update. Documented in `--help` and in the post-install `cat <<EOF` block.
- **`tests/test_marketplace.py`** (6 tests): JSON validity, required fields (`name`, `owner`, `metadata`, `plugins`), well-formed plugin entry, name + owner consistency between `marketplace.json` and `plugin.json`. Catches name drift that would silently break `/plugin install presence` for users.
- **`tests/test_install_update.py`** (4 tests): `--update` documented in `--help`; refuses on a non-git directory; refuses on a dirty working tree; behaves predictably on a clean tree with no remote (either pulls cleanly or fails non-fatally without corrupting state).

### Changed

- **`lib/integrity.py`**: added `.claude-plugin/marketplace.json` to `_INCLUDE_GLOBS` so the marketplace manifest is covered by the SHA-256 manifest. Tampering with the marketplace listing now fails the SessionStart fail-closed check under any preset with `integrity.fail_closed=true` (default in `zerotrust`).
- **`install.sh`**: post-install next-steps text updated. Stale "v0.2 Zero-Trust ... when shipped" line replaced with a concise opt-in note (`pip install --user cryptography`); new "To update later" line points at `--update`.
- **`README.md`**: install section now lists three methods clearly (marketplace flow, curl, git clone) and the marketplace flow no longer says "(once published)" since the manifest now exists. New "Update" subsection documents `./install.sh --update`. "By the numbers" block converted to a table for easier scanning; numbers refreshed against Python 3.14.4 measurements (cold hook 80 ms median, SessionStart 108 ms median, install-to-working 237 ms total median, aggregate session 6.4 s for 77 fires). Recent-changes callout shortened to a single block; full per-version detail lives in CHANGELOG.

### Quality gates (this release)

- 177 tests passing on Python 3.12 / 3.13 / 3.14 (was 167 in v0.3.1; +10 across `test_marketplace` and `test_install_update`)
- ruff clean
- shellcheck clean
- ASCII-only outside the two intentional unicode test fixtures
- MANIFEST.lock verifies OK (now includes `.claude-plugin/marketplace.json`)
- Backward compat: every v0.3.x state file remains readable. The marketplace.json is a new file, not a schema change to anything existing.

## v0.3.1

Performance follow-up + correctness fix discovered while reading v0.3.0 with the
bench harness in hand. Largest single win is removing a per-cold-hook keychain
probe that ran in all 4 presets (not just zerotrust). Largest correctness fix is
events.py finally being decryption-aware: under the zerotrust preset, every
appended event was previously stored encrypted but read back as an opaque
envelope, so summarize_events silently dropped the lot.

### SLO published (macOS arm64, Python 3.14.3, n=50 cold/SS, n=25 install, n=10 aggregate)

- cold hook startup (user-prompt-submit, empty state): median **109 ms -> 82 ms** (-25%), p95 118 ms -> 89 ms (-25%)
- **SessionStart on populated state (10 KB model + 100 events + 50 claims): 189 ms -> 113 ms (-40%)**
- **aggregate session overhead (77 hook fires/session): 10.38 s -> 6.52 s (-37%)**
- **install-to-working: 312 ms -> 246 ms (-21%)** (install grew 30 ms from compileall, status dropped 102 ms from cached repo_id + dir-ensures + lazy keychain)

### Changed (correctness)

- **`lib/events.py`**: `peek_events` and `drain_events` are now decryption-aware. Until v0.3.1 both used raw `json.loads` on every line, so under any preset with `events.encrypted=true` (currently only `zerotrust`) the encrypted envelope `{"_e":...,"n":...,"c":...}` parsed as a valid dict with no `kind`. `summarize_events` and the calibrated-confidence gate then silently dropped every event. Latent since v0.2.0; v0.3.0 didn't catch it. `peek_events` now delegates to `_common.read_jsonl` (which is per-line decrypt-aware); `drain_events` keeps its lock + truncate logic and routes parsing through a small encryption-aware helper.
- **`lib/_common.py::settings()`**: now stamps `__active_preset__` into the merged preset dict. The integrity-fail SessionStart message previously read `cfg.get("__active_preset__", "zerotrust")` but no code ever wrote that key, so non-zerotrust presets with `integrity.fail_closed=true` mis-reported themselves as zerotrust.

### Changed (perf)

- **`lib/_common.py`**: `_encryption_state()` split into `_encryption_write_state()` and `_read_key_lazy()`. The write path never touches the keychain when the active preset has no `encrypted=true` section. The read path defers all crypto-related work to the first encrypted line actually encountered. Together these eliminate the ~50-100 ms `security find-generic-password` subprocess that fired on every cold hook in `solo-dev` / `team-oss` / `enterprise-strict` on macOS.
- **`lib/_common.py::settings()`**: per-process cache so the same hook does not re-parse `~/.claude/presence/settings.json` plus the preset JSON multiple times across `_encryption_write_state`, `_redact_level`, `_git_timeout`, and the hook's own `cfg = settings()`. `strict=True` callers bypass the cache.
- **`lib/_common.py::integrity_block_path()`**: no longer calls `state_dir()`. Saves ~3 syscalls (mkdir + stat + chmod) per cold hook fire on the very first line of every sync hook's `main()`.
- **`lib/_common.py::repo_id()`**: per-process cache keyed by resolved cwd. Each call previously spawned up to 2 git subprocesses (`rev-parse --show-toplevel`, then `config --get remote.origin.url`); the SessionStart asyncio.gather fan-out alone called it 4+ times per fire across `project_dir` / `events_dir` / scan helpers. The cache eliminates 6+ subprocess spawns per heavy hook. Single source of the SessionStart 189 ms -> 113 ms drop.
- **`lib/_common.py::_ensure_dir()`**: per-process cache of paths already mkdir+stat+chmod'd. Hook lifetime is short, so a stale entry cannot drift in practice; saves ~3 syscalls per redundant `state_dir()` / `project_dir()` / etc. call.
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
