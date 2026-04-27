# Changelog

## v0.5.0

Composable redaction profiles for jurisdiction-aware sensitive-data handling.

A regulated-workload user asking "does presence support GDPR / HIPAA / PCI?" used to get a wishy-washy "kind of, via aggressive redaction" answer. v0.5.0 ships an honest one: opt-in pattern bundles for jurisdiction-relevant data plus a written-down `docs/compliance.md` that says exactly what presence does and does not do.

The hard rule for this release is what is NOT shipping: no preset named after a compliance framework (`fedramp`, `hipaa`, `us-gov`, etc.). Such a name would imply certification we do not have. Profile names describe the data class (`pii-eu`, `pci-dss`), not the framework.

### Added

- **`presets/redaction/`** (new directory): three composable redaction profiles, opt-in via `redact.profiles` in settings. Each profile JSON declares `_schema_version`, `_description`, `_disclaimer`, `_last_reviewed`, `_review_owner`, and a list of `patterns`. Each pattern declares `name`, `pattern` (Python regex), `kind` (used in the `[REDACTED:<kind>]` replacement), optional `validator` (registered post-match check), and optional `notes`.
  - `pii-eu.json`: EU IBAN, Dutch BSN (with prefix), Italian codice fiscale, French INSEE/NIR (with prefix).
  - `pii-us.json`: US SSN (with hyphens), US EIN (with prefix), US bank routing (with prefix).
  - `pci-dss.json`: PAN candidates 13-19 digits, gated by Luhn validator so non-PAN 16-digit strings pass through.
- **`lib/redact.py`**: extended with `profiles=` kwarg on `redact_text` / `redact_command` / `redact_iter`. New `_VALIDATORS` registry (currently `luhn` only) so future structured patterns plug in without touching the redaction loop. New `ProfileLoadResult` type carries load status (`ok`, `not_found`, `parse_error`, `compile_error`, `unknown_validator`, `partial`) so failed loads surface in `/presence-doctor` instead of warning silently. Process-cached. User-authored profiles in `~/.claude/presence/presets/redaction/<name>.json` shadow built-ins of the same name.
- **`python3 -m redact` CLI**: read-only inspector. `--list-profiles` (status, last_reviewed, pattern count); `--show-profile NAME` (full metadata); `--test-profile NAME --input FILE` or `--stdin` (redact and print result). Stdlib-only; usable as a pre-commit check.
- **`/presence-doctor` redact section**: shows level + active profiles + per-profile load status. A typo'd profile name now shows up here as `not_found` instead of disappearing.
- **`docs/compliance.md`** (new): honest scope for regulated workloads. Lists what presence does (local-only, AES-GCM at rest under zerotrust, audit log with hash chain, fail-closed integrity, redaction profiles) and what it explicitly does NOT do (no certification, no ATO, no formal attestation, not legal/security advice). Recommended posture for regulated users.
- **`presets/redaction/README.md`** (new): profile JSON schema, how to author custom profiles, where they live, the bar for shipping a built-in.
- **`tests/test_redact_profiles.py`** (new, 27 tests): per-profile positive + negative coverage, composition test, backward-compat test (no-profile call equals v0.4.x behavior), Luhn unit tests with PCI test card numbers, load-failure modes (malformed JSON, unknown validator, bad regex, partial load), user-override-shadows-builtin, forward-compat schema-version compat-mode.
- **`docs/index.md`** + **`README.md` Privacy** + **`llms.txt`**: link to `docs/compliance.md` and call out the opt-in profile flow.

### Changed

- **`lib/telemetry.py`**: new `_redact_profiles()` helper alongside `_redact_level()`; threaded through `record_commit_claim` and `record_push_claim` so profile-configured patterns redact telemetry events the same as the standard set.
- **`lib/hook_post_tool_bash.py`**: same `_redact_profiles(cfg)` threading; bash event payloads honor configured profiles.
- **`lib/integrity.py`**: `presets/redaction/*.json` added to `_INCLUDE_GLOBS` so the SHA-256 manifest covers profile files. Tampering with a profile is detected at SessionStart under zerotrust.
- **`install.sh`**: `SCRIPT_DIR` now uses `pwd -P` instead of `pwd`, so `install.sh --verify` invoked through the `~/.claude/plugins/presence` symlink no longer false-positives the symlink check. The bug was visible only when running verify through the symlink (CI invokes from the repo, where it worked).
- **`docs/roadmap.md`**: redaction-profiles entry removed (shipped here). ACP-for-Zed entry kept; em-dash replaced with colon to keep the file ASCII-only.
- **`.claude-plugin/plugin.json`** and **`lib/__init__.py`**: version `0.4.2` -> `0.5.0`.

### Backward compat

- Every existing user sees zero behavior change unless they add `redact.profiles` to their settings. The `profiles=` kwarg defaults to `None`, which is identical to the v0.4.x code path. The 4 shipped presets (`solo-dev`, `team-oss`, `enterprise-strict`, `zerotrust`) do NOT add profiles by default; opt-in only.

### What's NOT in v0.5.0 (deliberate)

- **Compliance-framework-named presets** (`fedramp`, `hipaa`, `us-gov`, `cmmc`, etc.). Names imply certification we do not have.
- **`phi-hipaa.json` and `cui-us-gov.json` profiles**. Documented as deferred until a contributor with healthcare or federal-contractor domain expertise validates the patterns.
- **Auto-detection of jurisdiction**. The user names the profile explicitly.
- **A "compliance dashboard"**. The existing `audit.jsonl` + `lib/integrity.py --audit-verify` is the audit surface.
- **JSON Schema validation of profile files**. Defers to the existing roadmap item "Preset JSON schema validation".

### Quality gates

- 291 tests passing on Python 3.12 / 3.13 / 3.14 (was 256 in v0.4.2; +27 from `test_redact_profiles.py`, +3 from `test_telemetry.py`, +1 from `test_post_tool_bash.py`, +2 from `test_zerotrust_integration.py` covering the regulated-workload e2e path: zerotrust + `redact.profiles=["pii-eu"]` -> IBAN redacted before encryption + negative control without the profile).
- MANIFEST regenerated and verifies; the `presets/redaction/*.json` profiles are SHA-256 covered by zerotrust integrity.

### Native extension

- `ext/Cargo.toml` 0.1.0 -> 0.1.1: secret-service 3.x has no default async-runtime feature, so the Linux Rust build was failing transitively on zbus (`async_fs` / `async_io` / `blocking` modules unresolved). Pinned `features = ["rt-async-io-crypto-rust"]` so zbus compiles with its async-io backend. macOS path unchanged. Local macOS builds never exercised this because the `cfg(target_os = "linux")` deps are not resolved on macOS; the failure surfaced on the first real CI Linux Rust build during the v0.5.0 release.

## v0.4.2

Cross-tool AGENTS.md adapter. Closes roadmap issue #8 (multi-AI-tool support).

The original v0.4.2 plan called for per-tool adapters (Cursor, Gemini, Codex, claude-code, clawbot, generic). Verification against current docs (April 2026) revealed that **AGENTS.md is now an open standard under the Agentic AI Foundation (Linux Foundation)**, read by Codex, Cursor, Gemini CLI, Windsurf, GitHub Copilot, and dozens of other tools. That collapses the design to **one adapter** that refreshes the project's `AGENTS.md` at Claude Code's SessionStart event, with a filename override for users who prefer a tool-specific name (`GEMINI.md`, `.cursor/rules/presence.mdc`, etc.).

### Added

- **`lib/adapters/agents_md.py`**: `AgentsMdAdapter`. Refreshes a delimited section (`<!-- presence:start --> ... <!-- presence:end -->`) of `<repo_root>/AGENTS.md` on `SessionStart` events. Idempotent; preserves user-authored content outside the markers; never raises (failed write is silent). Honors `PRESENCE_AGENTS_MD_FILENAME` for filename override (e.g., `GEMINI.md`, `.cursor/rules/presence.mdc`). Subdirectory paths in the override work; parent dirs are created.
- **`lib/adapters/generic.py`**: `GenericAdapter`. Plain-text stdout for unknown / debug hosts. Useful when running presence outside Claude Code.
- **`lib/adapters/__init__.py`**: `PRESENCE_HOST` env var dispatches between `claude` (default), `agents-md` (with `agents_md` and `agents` aliases), `generic`, and any unknown value (falls through to `ClaudeAdapter`).
- **`docs/multi-host.md`** (new): full guide for the cross-tool flow. Hosts that read AGENTS.md (verified April 2026), the file-contract guarantees (idempotent, user-content-preserving, refresh-only-on-SessionStart), filename override examples, the should-I-commit-AGENTS.md tradeoff, and a comparison with MCP (v0.4.1).
- **`docs/index.md`**: links to the new `multi-host.md`.
- **16 new tests** in `tests/test_adapter_agents_md.py`: pure-unit coverage of `_replace_section` (idempotent, append-when-missing, replace-in-place, preserve-prefix-suffix, malformed-marker tolerance), integration coverage with a real git repo (writes/skips by event, preserves user content, filename override including subdirectory paths, write-failure swallowed), and dispatch coverage (all 3 PRESENCE_HOST aliases routing correctly).

### Changed

- **`README.md`**: recent-changes callout names v0.4.2 as the cross-tool release; v0.4.1 (MCP) is now positioned as the live-pull complement to v0.4.2's push-to-file approach.
- **`README.md` "By the numbers"**: surface area row updated to mention the multi-host adapter (alongside the existing MCP server).

### What's NOT in v0.4.2

- **Per-tool adapters** (separate Cursor, Gemini, Codex classes): unnecessary because AGENTS.md serves all of them. The `PRESENCE_AGENTS_MD_FILENAME` override covers the rare case where a user prefers a specific tool's filename over the cross-tool standard.
- **`clawbot` adapter**: not shipping. The tool is not publicly documented in any source verified at v0.4.2 time. File an issue with a pointer to the spec; we'll add a v0.4.3 patch.
- **ACP (Agent Client Protocol from Zed)**: distinct from AGENTS.md (chat-session control vs. give-me-context). Tracked as v0.4.3 / v0.5.0.

### Closes

- Roadmap issue #8 (Multi-AI-tool adapter architecture). Originally planned as v1.0 work; brought forward to v0.4.x and shipped in 3 minor releases (v0.4.0 seam, v0.4.1 MCP, v0.4.2 AGENTS.md). The remaining open question (Zed ACP) is its own scope and stays open under a separate roadmap entry.

### Quality gates

- 256 tests passing on Python 3.12 / 3.13 / 3.14 (was 240 in v0.4.1; +16 from `test_adapter_agents_md.py`).
- ruff clean. shellcheck clean. MANIFEST verifies. ASCII-only. No em-dashes.
- Backward compat: every v0.3.x / v0.4.x state file remains readable. The `claude` host (default) is byte-identical to v0.4.1 behavior. AGENTS.md adapter only writes when `PRESENCE_HOST=agents-md` is explicitly set; default users see no change to their working tree.

## v0.4.1

Ships the Model Context Protocol (MCP) server (`lib/mcp_server.py`) deferred from v0.4.0. Any MCP-aware client (Claude Desktop, Cursor, Continue, custom agents) can now read presence's living project model and outcome telemetry over JSON-RPC stdio without going through Claude Code-specific hook plumbing.

Also belatedly ships the v0.4.0 CHANGELOG entry (originally missed; the v0.4.0 GitHub Release was created manually as a fallback because the auto-release workflow could not extract a section that did not exist).

### Added

- **`lib/mcp_server.py`**: JSON-RPC 2.0 stdio MCP server implementing the `2024-11-05` protocol. Three handlers: `initialize`, `resources/list`, `resources/read`. Plus the `notifications/initialized` no-op. Unknown methods return JSON-RPC error -32601; handler exceptions return -32603. Exposes two read-only resources per repo:
  - `presence://<repo_id>/model` -> the living `model.md` (Markdown)
  - `presence://<repo_id>/telemetry` -> recent commit / revert / verification claims (JSON array)
- **`lib/cli.py mcp`**: now wired to `mcp_server.main()` (was a placeholder in v0.4.0). Start with `python3 ~/.claude/plugins/presence/lib/cli.py mcp`.
- **`docs/mcp.md`** (new): per-client config snippets for Claude Desktop, Cursor, Continue, and a generic JSON-RPC walkthrough. Documents the resources contract, the working-directory caveat, security posture, and what's deliberately NOT exposed (audit log, events queue, settings).
- **`docs/index.md`**: links to the new `mcp.md`.
- **13 new tests** in `tests/test_mcp_server.py`: handler outputs, malformed JSON resilience, method-not-found, internal-error mapping, end-to-end stdio round-trip via `cli.py mcp`.

### Changed

- **`README.md`**: surface area row now lists the MCP server. Recent-changes callout names v0.4.1; v0.4.2 still on deck for multi-host adapters.

### What's NOT in v0.4.1

- The MCP server has no `repo_id` parameter on `resources/read`; it resolves the current working directory at request time. Single-repo clients work fine; cross-repo readers need a server-per-project config or the v0.4.2 follow-up.
- The audit log and events queue are deliberately excluded from MCP exposure (security posture: read-only view of memory, not of write paths).
- Multi-host adapters (Cursor, Gemini, Codex, claude-code, clawbot, generic): still v0.4.2.
- ACP (Agent Client Protocol): tracked as v0.4.3 / v0.5.0; ACP is chat-session control, distinct from MCP's "give me context."

### Quality gates

- 240 tests passing on Python 3.12 / 3.13 / 3.14 (was 227 in v0.4.0; +13 from `test_mcp_server.py`).
- ruff clean. shellcheck clean. MANIFEST verifies. ASCII-only. No em-dashes.
- Backward compat: every v0.3.x and v0.4.0 state file remains readable. The MCP server is read-only and never writes presence state. The `cli.py mcp` subcommand was a placeholder in v0.4.0 (raised on import); it now does its documented job.

## v0.4.0

The first release with optional native acceleration. A Rust Unix-socket client (`presence-client`) talks to a warm resident Python daemon (`lib/daemon.py`) instead of spawning a fresh bash + python3 process per hook fire. Cuts cold-hook latency from 82 ms to 8.9 ms median (-89%) on macOS arm64 when `--build-ext` is opted in. The default-install path is unchanged: stdlib-only, byte-identical to v0.3.4 runtime behavior. Native acceleration is opt-in via `./install.sh --build-ext` (compile locally with cargo) or `./install.sh --download-ext` (pull a pre-built binary from the latest GitHub Release).

This release also introduces a host-AI-tool adapter seam (`lib/adapters/`). v0.4.0 ships only `ClaudeAdapter`. v0.4.1 added the MCP server. v0.4.2 ships adapters for Cursor, Gemini, Codex, claude-code, clawbot, and any other host with a documented context-injection mechanism.

### SLO published (macOS arm64, Python 3.14.4, with `--build-ext`)

| Benchmark | v0.3.4 default | v0.4.0 `--build-ext` | Speedup |
|---|---|---|---|
| `cold_startup` median | 80 ms | **8.9 ms** | 9.0x |
| `cold_startup` p95 | 87 ms | 10.2 ms | 8.5x |
| `session_start_populated` median | 108 ms | **9.1 ms** | 11.9x |
| `aggregate_session` (77 fires) median | 6.4 s | **770 ms** | 8.3x |

The `install_to_working` bench is unchanged (~245 ms total) because it measures the install + first `/presence-status` invocation, which doesn't go through the daemon path.

### Added

- **`ext/`** (new directory): Rust source for `presence-client` (Unix-socket client, `ext/src/client.rs`), plus a PyO3 extension (`ext/src/lib.rs`, `crypto.rs`, `git.rs`) providing native fast paths for keychain access (`security-framework` on macOS, `secret-service` on Linux) and `git log` reads (libgit2 via `git2`). The Python source under `lib/crypto.py` and `lib/telemetry.py` falls back to the existing subprocess-based code path when `presence_ext` is not importable.
- **`lib/daemon.py`**: asyncio Unix-socket daemon. Pre-imports all 6 hook modules so dispatch is a function call, not an import. Auto-exits after 5 min idle; auto-respawns on the next client request. Socket is `0o600`; PID file at `~/.claude/presence/presence.pid` for stale-process cleanup.
- **`lib/cli.py`**: fallback path the Rust client spawns when the daemon socket is unreachable. Same dispatch table as the daemon. Reserves the `mcp` subcommand (wired in v0.4.1).
- **`lib/adapters/`** (new directory): host-AI-tool adapter seam. `Adapter` base class + `ClaudeAdapter` (default; emits Claude Code's `hookSpecificOutput` JSON shape). `lib/_common.py::emit_context()` now delegates to `get_adapter()` instead of hardcoding the JSON. v0.4.2 will add `Cursor`, `Gemini`, `Codex`, `claude-code`, `clawbot`, and a generic-fallback selected via `PRESENCE_HOST=...`.
- **`hooks/scripts/_common.sh::exec_hook`**: fast path that exec()s `lib/presence-client` if the binary exists; falls through to the classical Python exec when not. The fall-through means default installs are byte-identical to v0.3.x runtime behavior. `PRESENCE_NO_DAEMON=1` forces the slow path (debug + test escape hatch).
- **`install.sh --build-ext`**: build the Rust extension locally via cargo. Builds `presence-client` (always) plus an optional `presence_ext` Python wheel (only if maturin is available).
- **`install.sh --download-ext`**: download a pre-built `presence-client` from the latest GitHub Release. Maps `(uname -s, uname -m)` to one of three pre-built artifacts.
- **`.github/workflows/release.yml`**: extended to build `presence-client` on three matrix cells (macOS arm64, macOS x86_64, Linux x86_64) and attach the binaries as release assets when a `v*` tag is pushed.
- **`bench/HISTORY.md`** (new): per-version perf history, both `--build-ext` and stdlib columns.
- **19 new tests** across `tests/test_adapters.py`, `tests/test_cli.py`, `tests/test_daemon.py` covering: idle-timeout auto-exit, cache invalidation between requests, multiple sequential requests, JSON escaping, unknown hosts/hooks, malformed JSON, socket perms 0o600, missing-python fallback.

### Changed

- **`lib/_common.py`**: `_dumps()` and `_loads()` helpers added at the top. Six previously-inline `try: import orjson` blocks consolidated into the helpers. Optional `orjson` is honored when present but never required; the stdlib-only path is the default. `emit_context()` now delegates to `lib/adapters/get_adapter()`.
- **`lib/crypto.py`**: `is_available()` and `_backend_ops()` check for `presence_ext.crypto` first; fall through to the subprocess-based macOS Keychain / Linux secret-service code path when not present. Behaviorally identical when `presence_ext` is missing.
- **`lib/telemetry.py`**: `get_head_commit()` and `scan_for_revert()` (sync + async) check for `presence_ext.git` first (libgit2 wrapper); fall through to `git_run_safe()` when not. Both paths produce identical results.
- **`README.md`**: "By the numbers" table now has separate columns for default and `--build-ext`. Recent-changes callout names the v0.4.0 -> v0.4.2 progression.
- **`bench/README.md`**: notes the daemon-path numbers + how to switch between modes.

### Quality gates

- 227 tests passing on Python 3.12 / 3.13 / 3.14 (was 208 in v0.3.4; +19 across `test_adapters`, `test_cli`, `test_daemon`).
- ruff clean. shellcheck clean. ASCII-only outside the two intentional unicode test fixtures. MANIFEST.lock verifies OK.
- Backward compat: every v0.3.x state file remains readable. The Rust client + daemon are entirely opt-in; the default path is unchanged.

### Known issue (released-as)

- The original v0.4.0 GitHub Release was published manually because the auto-release workflow could not extract this CHANGELOG section (it was missed in the merge commit). Future tag pushes work correctly: the v0.4.1 PR adds this section retroactively so the workflow's regex picks it up.
- The Linux x86_64 build of `presence-client` failed in the v0.4.0 release.yml run (libgit2 system-library deps missing on the bare ubuntu-latest runner). Pre-built binaries are available for macOS arm64 only at v0.4.0; macOS x86_64 and Linux users should use `--build-ext` (cargo) until v0.4.x adds the missing `apt-get install pkg-config libssh2-dev libssl-dev` step.

## v0.3.4

Bundle of five orthogonal threads, none of which conflict: release automation, perf-regression CI, bug-report ergonomics, snapshot/restore for non-zerotrust state, and documentation polish. Closes roadmap issue #10 (release automation) and partial-closes #11 (snapshot tooling; the zerotrust case stays open).

### Added

- **`.github/workflows/release.yml`**: triggered on `push: tags: 'v*'`. Extracts the matching `## v<TAG>` section from `CHANGELOG.md`, asserts ASCII + no em-dash / en-dash, derives a release title from the first non-blank line, marks `--latest` if this tag is the highest semver in the repo, then `gh release create`. Replaces the manual `gh release create --notes-file /tmp/...` flow used for v0.3.0 through v0.3.3. All values flowing into shell pass through `env:` blocks per the GitHub Actions injection-prevention guidance.
- **`.github/workflows/ci.yml::bench` job**: perf-regression gate. Single matrix cell (ubuntu-latest, py 3.13). Runs `bench/cold_startup.py --runs 20` and `bench/aggregate_session.py --runs 5`; asserts median is under threshold (300 ms cold, 12000 ms aggregate). 2-3x headroom over local Python 3.14.4 numbers (cold ~80 ms, aggregate ~6.4 s); CI Linux is typically 1.5-2x slower. Runs in parallel with the existing `test` / `shellcheck` / `manifest-integrity` jobs; bumping the thresholds is a deliberate, reviewable change.
- **`install.sh --snapshot <out.tar.gz>`** and **`install.sh --restore <in.tar.gz> [--overwrite]`**: cross-machine state portability for non-zerotrust presets. The snapshot tarball is schema-versioned via a `_snapshot_meta.json` at the root; restore validates the format before extracting. Per-machine markers (`.python_bin`, `.python_version_ok`, `.integrity-blocked`, `.unlock-*`, `logs/.warned-*`) are excluded automatically. Restore refuses by default if the destination state dir is non-empty; pass `--overwrite` to clobber. Restore also rejects path-traversal members in untrusted tarballs.
- **`lib/snapshot.py`** (new): `snapshot()` + `restore()` + `SnapshotError`. Refuses snapshot when the active preset has any of `model.encrypted`, `telemetry.encrypted`, `events.encrypted` set true (the zerotrust key-rewrap case is its own design call; tracked in [docs/roadmap.md](docs/roadmap.md) and issue #11). 8 new tests in `tests/test_snapshot.py`.
- **`lib/bugreport.py`** (new): bundles `install.sh --verify --json` + `lib/doctor.py --json` + recent warnings + state sizes into one structured blob. CLI: `python3 lib/bugreport.py` (JSON) or `--md` (markdown for pasting into the bug-report issue template). 7 new tests in `tests/test_bugreport.py`.
- **`commands/presence-bugreport.md`** (new slash command): runs `lib/bugreport.py --md` and tells the user where to paste the result.
- **`docs/index.md`** (new): table of contents for `docs/` with one-line descriptions of each page; cross-links to README, CHANGELOG, SECURITY, CONTRIBUTING, bench/README, llms.txt.
- **`docs/glossary.md`** (new): 11 project-specific terms defined for new users (living model, outcome telemetry, calibrated confidence, integrity manifest, audit chain, pinned Python, hook event names, snapshot, etc.).
- **`docs/recipes.md`** (new): 10 copy-paste customizations covering common preset overrides, snapshot/restore, bug-report flow, custom-preset authoring.

### Changed

- **`lib/warnings_log.py::warn()` and `warn_once()`**: new optional `fix=` keyword argument. When provided, the recovery hint is stored as a top-level field on the JSONL line. **Backward compatible**: 14 existing callers that don't pass `fix=` continue to work unchanged. 5 high-signal callers in `lib/_common.py` retrofitted with concrete fix hints (`crypto_lib_missing` -> `pip install --user cryptography`; `crypto_keychain_missing` -> macOS/Linux keychain hints; `crypto_key_failed` -> `/presence-reset --crypto`; `git_missing` -> install git; `settings_corrupt` -> inspect or reset). The remaining categories (`git_timeout`, `jsonl_corrupt`, `hook_input_malformed`, etc.) stay as-is and can be retrofitted incrementally.
- **`lib/doctor.py::render()`**: when a warning has a `fix:` field, an indented `fix: <hint>` line appears under it. JSON output unchanged; the `fix` key was already passed through by `read_warnings()`.
- **`README.md`**: new Documentation subsection under Architecture pointing at `docs/index.md` and listing each page in `docs/` with one-liners.

### Closes

- Roadmap issue #10 (Automate GitHub releases on tag push).

### Partial progress

- Roadmap issue #11 (Cross-machine state snapshot and migration tooling): the non-zerotrust path ships in v0.3.4. The zerotrust key-rewrap case remains open.

### Quality gates (this release)

- 208 tests passing on Python 3.12 / 3.13 / 3.14 (was 187 in v0.3.3; +21 across `test_warnings_fix_field`, `test_bugreport`, `test_snapshot`).
- ruff clean.
- shellcheck clean.
- ASCII-only outside the two intentional unicode test fixtures.
- MANIFEST.lock verifies OK (now includes `commands/presence-bugreport.md`).
- Backward compat: every v0.3.x state file remains readable. The `fix:` field is additive on warnings; existing readers ignore unknown keys. Snapshot tarballs are a new artifact, not a state-format change.

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
- **`docs/roadmap.md`**: written record of six items the maintainer has decided not to ship now and why, with realistic shape sketches for each: multi-tool adapter architecture, native Windows support, release automation on tag push, cross-machine state snapshot/migration, preset JSON schema validation, side-by-side install support. Each item gets (or will get) a tracking GitHub issue with the same title for discussion; this doc is the durable in-repo summary.

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
