# Changelog

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
