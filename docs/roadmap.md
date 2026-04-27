# Roadmap

Things `presence` is **not** doing today, but where we have a written decision and a target shape. Each item below has (or will have) a tracking GitHub issue with the same title; comments and design discussion live there.

The bar to add an item here is: someone asked, the maintainer thought about it, decided "not now," and wrote down both the reason and the realistic shape of the eventual work. Items disappear from this list when they ship or when we conclude they will not ship.

## Native Windows support without WSL2

**Status**: WSL2 is the supported Windows path; native deferred until demand.

**What works today**: WSL2 path is supported; the bash wrappers run unchanged inside WSL2 Ubuntu. README and llms.txt document this.

**What is blocked native on Windows**:
- `hooks/scripts/*.sh` are bash; cmd/PowerShell cannot run them.
- `fcntl.flock` (in `lib/_common.py:_flock`) does not exist on Windows.
- POSIX `0o700` / `0o600` perms do not translate; `_ensure_dir` in `lib/_common.py` would need a Windows code path.
- Claude Code's hook contract on Windows is its own set of unknowns.

**Three options, in increasing scope**:

1. **WSL2-only support** (~1 day, already shipped in v0.3.3 docs). Zero code change. Probably what 80% of Windows devs already use for Claude Code.
2. **Pure-Python wrappers** (~2 weeks). Rewrite `hooks/scripts/*.sh` as Python entry points with shebang `#!/usr/bin/env python3`. Replace bash version-probe with cached Python. Replace `fcntl.flock` with `portalocker` (one optional dep) or msvcrt-aware abstraction. Cross-platform out of the box. Loses the cheap-bash startup shortcut from v0.3.0 but eliminates the bash dependency entirely.
3. **PowerShell parallel** (~1 week). Keep bash for nix, add `.ps1` siblings. Splits the codebase. Least appealing.

**Recommended decision**: stay on option 1 until a real Windows user files an issue requesting native. Then revisit, prefer option 2 (pure-Python) over option 3 (split codebase).

## Cross-machine state snapshot and migration tooling

**Status**: partially shipped in v0.3.4 (non-zerotrust path); zerotrust case still open.

**Today**: `install.sh --snapshot` and `--restore` work for non-zerotrust presets (v0.3.4+). The remaining gap is zerotrust, where state is encrypted with a per-machine OS-keychain-stored key. Snapshotting that state across machines requires either re-wrapping the data key for the destination's keychain or stripping encryption.

**Proposal for the open case**: extend `lib/snapshot.py` with a `--rewrap-for <machine-pubkey>` flag that derives a transport-encryption key from a destination keypair the user provides. Or simpler: `--decrypt-on-snapshot` that strips encryption (with a loud warning) so the snapshot tarball is plain and the destination machine re-encrypts on restore.

**Why deferred**: encryption story needs a real design call. Key portability across platforms is its own subproblem (macOS Keychain != Linux secret-service != hypothetical other backend). Conflict resolution if both sides made writes between snapshots.

## Preset JSON schema validation

**Status**: schema needs to be locked before adding the validator.

**Today**: presets are arbitrary JSON parsed by `lib/_common.py::_load_preset`. A user-authored custom preset with a typo (`telematry.enabled: false`) silently does nothing because the typo'd key is never read.

**Proposal**: ship `presets/_schema.json` (JSON Schema draft 7) describing every recognized field. `_load_preset` validates against it on read; unknown keys -> warn (not fail). `/presence-doctor` surfaces validation warnings.

**Why deferred**: small but adds a `jsonschema` dep (or a stdlib-only schema walker, more code). Want to see real custom-preset usage before locking the schema; otherwise we lock in the wrong shape and have to relax it later.

## Side-by-side install support via --name suffix

**Status**: niche; deferred unless plugin authors ask for it.

**Today**: `install.sh` symlinks at `~/.claude/plugins/presence/`. Only one version installable at a time. Maintainers testing `main` vs a branch must swap symlinks manually.

**Proposal**: `install.sh --name presence-dev` symlinks at `~/.claude/plugins/presence-dev/` and uses `~/.claude/presence-dev/` for state.

**Why deferred**: niche use case (only repo maintainers + plugin authors). Not worth the install.sh complexity until someone other than the maintainer asks for it.

## Agent Client Protocol (ACP) for Zed and other ACP-aware tools

**Status**: distinct from MCP; tracked separately for a future minor once a real Zed-side use case shows up.

**Today**: v0.4.1 ships an MCP server (any MCP client can read presence's living model + telemetry). v0.4.2 ships the AGENTS.md adapter (cross-tool file refresh). Both are "give me context" mechanisms. ACP (Zed's protocol) is "control the agent's chat session": distinct mechanism, distinct verbs.

**Proposal**: `lib/acp_server.py` implementing the Agent Client Protocol so Zed's chat panel can be driven by presence (e.g., proactive nudges from the calibrated-confidence Stop hook delivered as Zed chat messages). Probably routes through the same `lib/cli.py` pattern as the MCP server.

**Why deferred**: ACP is Zed-specific in practice. Building support without a Zed user testing the round-trip is guess-work. The MCP server (v0.4.1) already serves Zed's reading needs since Zed has MCP support; ACP is the writing/control side, which is a different project.

**Decision criterion**: ship when (a) we have a documented Zed user who wants the chat-control flow specifically, or (b) a second tool adopts ACP and the multi-host story changes shape.

## Universal install: paths beyond Claude Code-only

**Status**: deferred; presence is a Claude Code plugin with read-only projections. No path to native install in another tool is scheduled.

**Today**: presence's active behavior (outcome telemetry on commit, revert detection at Stop, calibrated-confidence gate, event digest, integrity check) fires on Claude Code lifecycle hooks (`SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop`, `PreToolUse`, `SessionEnd`). The cross-tool surfaces shipped in v0.4.1 + v0.4.2 are read-only: the MCP server lets clients pull presence's living model + telemetry over JSON-RPC stdio; the AGENTS.md adapter pushes the SessionStart context into a file other tools read. Neither lets presence observe a non-Claude-Code session and react to its events.

**Why this is hard**: no other AI coding tool currently exposes a hook contract comparable to Claude Code's. Cursor has `.cursorrules` (file-based rules) but no lifecycle hooks. Codex CLI has commands but not session events. Gemini CLI has extensions but not the granular pre/post tool-use surface. Continue and Claude Desktop are MCP clients only. GitHub Copilot has Chat Participants in VS Code (closer to a hook) but not bidirectional session control. So "make presence work in Cursor" is not a packaging problem; it is a "what events fire" problem.

**Three paths to actual universality, in increasing scope**:

1. **Daemon mode** (~6-8 weeks, large rewrite). Run a long-lived background process that watches git activity (poll or fsnotify on `.git/HEAD`), the working tree (file changes), and project state (`model.md`, `audit.jsonl`). Replace the current hook-fired Python entry points with daemon-side observers. Works everywhere a daemon can run; tool-agnostic.
   - **Loss**: precision. The current architecture knows "Claude wrote this commit" because PostToolUse fires after Bash. A daemon sees the commit but cannot tell whether the human, the AI, or another tool authored it; the outcome telemetry's value drops sharply.
   - **Loss**: the calibrated-confidence gate. That gate fires on Claude Code's `Stop` event (end of an AI turn). A daemon has no analogue; a polled "did tests pass since the last commit" check is a strict downgrade.
   - **Cost**: separate process to manage (start/stop, crash recovery, log rotation, pid-file conventions). New attack surface under zerotrust (the daemon would need its own integrity story).

2. **Per-tool plugins** (~2-4 weeks per tool, N codebases to maintain). Author native plugins for each tool that exposes a plugin / extension surface. Cursor: no public plugin API as of verified docs (April 2026); `.cursorrules` is the closest, file-based. Codex CLI: no plugin system. Gemini CLI: extensions framework, but lifecycle granularity is coarser than Claude Code's. VS Code Copilot Chat: Chat Participants are closer to a hook but per-participant, not session-wide.
   - **Loss**: every tool has a different event model. "Outcome telemetry" means something different in each. The shared vocabulary the current presence assumes (session start, user prompt, tool use, stop) maps cleanly to Claude Code only.
   - **Cost**: linear with the number of tools. Each plugin is its own bug surface, its own release cadence, its own integrity story.

3. **Editor-level extension** (VS Code / JetBrains, ~3-4 weeks for one editor). Ship as a VS Code extension that observes editor events: `vscode.workspace.onDidChangeTextDocument`, `vscode.tasks.onDidEndTask`, `chat.participants.*` for AI-assistant chat events. Tool-agnostic at the editor level: any AI assistant running in the same editor would be observable.
   - **Loss**: the editor sees all edits the same way. A file change might come from the human typing, an AI assistant, or a formatter. The current architecture's value comes from knowing which is which; the editor cannot reliably distinguish them. `chat.participants.*` is per-participant and only covers AIs that register as a chat participant (Copilot Chat does; others may not).
   - **Cost**: editor-specific. JetBrains and VS Code have different APIs; each needs its own port. Doesn't help anyone running an AI tool outside an editor (Codex CLI, Gemini CLI standalone).

**Why all three are deferred**: none of the three give back what we have today. Daemon mode loses the AI/human distinction. Per-tool plugins fragment the codebase across dissimilar event models. Editor extensions cannot see the AI/human boundary either. The cross-tool projection surfaces (MCP + AGENTS.md) deliver 80% of the cross-tool value at near-zero cost while keeping the precise behavioral layer that runs only inside Claude Code.

**Decision criterion**: ship one of these three paths when (a) a non-Claude-Code AI tool ships a public hook contract with comparable lifecycle granularity (then a per-tool plugin is the right path), OR (b) a documented user with a real cross-tool need quantifies the value of partial coverage (then daemon mode becomes worth the rewrite), OR (c) the cross-tool projection surfaces (MCP, AGENTS.md, eventually ACP) prove insufficient for a specific user workflow and that workflow is described in writing.

**What we will NOT do as a workaround**:
- "Auto-detect Cursor" or any other heuristic that pretends to be a hook layer. Either the host fires events presence subscribes to, or it does not.
- Ship a half-rewrite that runs daemon-side telemetry without the calibrated-confidence gate. The four pillars (living model, telemetry, event digest, calibrated confidence) are co-designed; degraded versions get returned by users as "but X doesn't work" issues.
- Frame any of the existing read-only projections as "install presence on Cursor". A Cursor user does not install presence; a Claude Code user installs presence and a Cursor user reads its projection.

## Version observability and freshness

**Status**: deferred to v0.6.0 (or whenever the next bigger feature ships); designed.

**Today**: presence has version *strings* in five places and **zero runtime checks**:

| Surface | Version string | Runtime exposure | Cross-check |
|---|---|---|---|
| `.claude-plugin/plugin.json` | tracked, manifest | Read by Claude Code at install | None |
| `lib/__init__.py` (`__version__`) | tracked | Importable, but nothing imports it | None |
| `ext/Cargo.toml` (presence_ext crate) | tracked | Compiled metadata only | None |
| `presence_ext` Python module | NOT exposed | None | None |
| `presence-client` binary | NOT exposed (no `--version` flag) | None | None |
| GitHub Releases (latest) | exists | Not surfaced anywhere in the runtime | None |

Real-world cost of this gap: dependabot PR #17 (April 2026) bumped `pyo3 0.21 -> 0.24` with green CI. The wheel build was actually broken with 15 compile errors; CI did not catch it because neither `ci.yml` nor `release.yml` builds the wheel. A user running `git pull` + forgetting `--build-ext` after the merge would have hit subtly wrong behavior with no diagnostic.

**Why this is one roadmap entry, not several**: the four sub-items below are co-designed; each makes the next more useful. Solving #1 and #2 alone is just cosmetic; #3 is what catches real bugs; #4 is the freshness layer on top. Shipping any one without the others leaves a half-feature.

**Realistic shape, in increasing scope** (each item builds on the prior):

1. **Static version surfaces** (~30 minutes, ext-only).
   - `ext/src/lib.rs`: add `m.add("__version__", env!("CARGO_PKG_VERSION"))?` inside the `#[pymodule]` body so `presence_ext.__version__` returns the compiled crate version.
   - `ext/src/client.rs`: add `--version` arg parsing; print `env!("CARGO_PKG_VERSION")` and exit 0.
   - Bumps ext crate `0.1.x -> 0.2.0` (per the ext-versioning rule; minor bump because new public surface).
   - **Standalone value**: low. Two new strings users can read but nothing reads them yet.

2. **Doctor cross-check** (~1 hour, lib-only on top of #1).
   - `lib/doctor.py::report()` adds a `version_observability` block: `plugin_version` (from `lib/__init__.py.__version__`), `ext_version` (from `presence_ext.__version__` if importable, else `None`), `expected_ext_version` (see #3 for where this comes from).
   - `lib/doctor.py::render()` shows `ext (rust)  : 0.1.3 (expected >= 0.1.3) OK` or `ext (rust)  : not installed (using subprocess fallback)`.
   - When the ext is installed but older than `expected_ext_version`: `ext (rust)  : 0.1.0 STALE; run install.sh --update --build-ext to refresh`.
   - **Standalone value**: medium. Users now have one place to check that their wheel matches their Python.

3. **Compatibility bound + SessionStart warn** (~1 hour, lib-only on top of #2).
   - `lib/__init__.py` adds `_MIN_EXT_VERSION = "0.1.3"` as a constant; the plugin asserts compatibility with any ext crate at-or-above this version. Bumped manually whenever a Python-side change requires a new ext API surface.
   - `lib/_common.py` adds `check_ext_compat() -> tuple[ok, message]` that imports `presence_ext.__version__`, parses both with the existing `presence_ext` import path, and returns `(False, "...")` on mismatch.
   - `lib/hook_session_start.py` calls `check_ext_compat()` once per session-start; on mismatch, calls `warn("ext_version_stale", ...)` with a fix hint (`run install.sh --update --build-ext`). Reuses the existing `warnings_log.warn()` infrastructure so the warning surfaces in the standard `/presence-doctor` warnings panel without new UI code.
   - Fail-open: any import error or unparseable version -> silent, no warning. The fallback to subprocess git is unaffected.
   - **Standalone value**: high. This is what would have caught the PR #17 silent-stale-wheel scenario described above.

4. **Network freshness check (opt-in, cached, fail-open)** (~3 hours, new surface).
   - One outbound call to `https://api.github.com/repos/sara-star-quant/presence/releases/latest` with a 30-second timeout. Returns the highest-semver release tag.
   - Default OFF in every shipped preset, including non-zerotrust ones. Enabled via `update_check.enabled: true` in user settings; zerotrust preset hard-codes this to false (the same way `outcome_check.enabled` is forced off).
   - Cache: `~/.claude/presence/.update_check_cache.json` with TTL 24h. Schema: `{"checked_at": "ISO8601", "latest_tag": "v0.6.0", "current_tag": "v0.5.3"}`.
   - Surfacing: `/presence-doctor` shows `latest release: v0.6.0 (you have v0.5.3)`. NOT surfaced in SessionStart (too noisy). NOT a blocking gate; never refuses to run.
   - Fail-open: any network/DNS/parse error -> cache stays stale, doctor shows "(check failed)", no warning. Hooks never break on this.
   - **Standalone value**: medium. Users who run `/presence-doctor` get notified of new releases without leaving Claude Code.

**Why all four are deferred to v0.6.0 (or later)**:

- v0.5.x has been a release-only stabilization line: redaction profiles (v0.5.0), CHANGELOG-and-doc accuracy (v0.5.1), CI cross-compile fixes (v0.5.2), pyo3 migration (v0.5.3). Adding new public surface mid-stabilization-line breaks the "no behavioral change for v0.5.x users" contract.
- Items #1 + #2 are tiny but only useful with #3, which adds a settings-file constant and a SessionStart codepath; that is a v-minor change.
- Item #4 introduces network egress (opt-in but new surface) and a settings key (`update_check.enabled`); definitely v-minor.

**Decision criterion**: ship together as a single PR or PR-pair when (a) we have a v0.6.0 anchor feature that justifies the minor bump, OR (b) a user reports a "I ran git pull but presence_ext is stale and behaves wrong" incident that #3 would have caught.

**Implementation order if/when it ships**: #1 -> #2 -> #3 -> #4. Each step is independently testable; the wheel build can be exercised locally with `maturin build` to confirm `presence_ext.__version__` is correct, then `/presence-doctor` smoke-tests #2 and #3, then settings-toggle exercises #4.

**What we will NOT do as a workaround**:

- **Auto-update.** presence never modifies its own install. The user runs `install.sh --update` deliberately. Anything that pulls a new version mid-session is out of scope.
- **Block hooks on a stale ext.** The fallback-to-subprocess path in `lib/telemetry.py::get_head_commit` and `lib/crypto.py` already handles the "no ext" case silently; "stale ext" should warn but never block.
- **Cross-check at every hook fire.** SessionStart only. The cost of importing `presence_ext` and parsing `__version__` is microseconds, but doing it 6+ times per turn adds up and the result rarely changes within a session.
- **Hit GitHub on every SessionStart.** Cache TTL is the whole point; without it we drown the API in requests across the user base.
- **Mark presence "incompatible" on minor pyo3 bumps.** `_MIN_EXT_VERSION` is a runtime check between *our* plugin Python and *our* ext crate, not a check on pyo3 itself. The pyo3 version is internal to the ext.

## Wheel build in CI

**Status**: deferred; designed. Implementation is a single new job in `.github/workflows/ci.yml`; can land in any patch release.

**Today**: `.github/workflows/ci.yml` has 4 jobs: `test` (Python 3.12 / 3.13 / 3.14 x ubuntu-latest / macos-latest = 6 cells), `shellcheck`, `manifest-integrity`, `bench`. None build the `presence_ext` wheel. `release.yml` builds the `presence-client` binary on tag push for 3 architectures (Linux x86_64 + macOS arm64 + macOS x86_64 cross-compile post v0.5.2) but also does not build the wheel. The wheel build only happens locally via `./install.sh --build-ext` for end users (line 461 of install.sh: `maturin build --release --out target/wheels`).

**The gap**: dependabot PR #17 (April 2026) bumped `pyo3 0.21 -> 0.24` with green CI on all 6 test cells + shellcheck + manifest + bench. The wheel build was actually broken with 15 compile errors from the missing Bound API migration. CI did not catch this because no job exercises `maturin build` or any pyext-feature-enabled cargo build. The breakage was caught locally with `maturin build` during PR review (see v0.5.3 / PR #29). A non-vigilant maintainer who trusted CI green would have merged a wheel-broken plugin.

**Realistic shape**: one new job in `.github/workflows/ci.yml`:

```yaml
wheel-build:
  name: wheel build (${{ matrix.os }})
  strategy:
    fail-fast: false
    matrix:
      os: [ubuntu-latest, macos-latest]
  runs-on: ${{ matrix.os }}
  steps:
    - uses: actions/checkout@v5
    - uses: actions/setup-python@v6
      with:
        python-version: "3.13"
    - uses: dtolnay/rust-toolchain@stable
    - name: Install Linux system libraries
      if: runner.os == 'Linux'
      run: |
        sudo apt-get update
        sudo apt-get install -y --no-install-recommends \
          pkg-config libssh2-1-dev libssl-dev zlib1g-dev
    - name: Cache cargo registry + ext target
      uses: actions/cache@v4
      with:
        path: |
          ~/.cargo/registry
          ~/.cargo/git
          ext/target
        key: wheel-build-${{ matrix.os }}-${{ hashFiles('ext/Cargo.lock') }}
    - name: Install maturin
      run: pip install maturin
    - name: Build wheel
      run: cd ext && maturin build --release --out target/wheels
    - name: Smoke-test the wheel
      run: |
        WHEEL=$(find ext/target/wheels -name '*.whl' -type f | head -1)
        pip install --force-reinstall "$WHEEL"
        python3 -c "
        import presence_ext
        head = presence_ext.git.get_head_commit('.')
        assert head is None or 'sha' in head, f'unexpected get_head_commit shape: {head}'
        print('wheel smoke-test ok')
        "
```

**Three things this catches that current CI does not**:

1. Bound API breakage from any pyo3 / pyext-feature-gated dep bump.
2. Platform-specific build failures in the wheel path (e.g., a future `secret-service` regression that affects only Linux's `cfg(target_os = "linux")` branch). The Linux + macOS cells together cover both `cfg` branches in `ext/src/crypto.rs`.
3. Dynamic-link / ABI mismatches that compile-time misses but `import presence_ext` catches.

**Cost**: ~2-4 minutes per PR (two parallel cells, ~1-2 min each on warm cache). First-run on a clean cache is ~3-4 min for libgit2-sys + zbus + secret-service compilation. The cargo registry cache (above) makes the warm-path closer to ~30 seconds. Acceptable for a gate that catches a class of bug current CI misses entirely.

**Why deferred** (and shorter than the version-observability deferral above):

- It is a CI workflow change, not a code change. Lower risk profile; could ship in any patch release.
- It is partially redundant with item #2 (doctor cross-check) of the version-observability entry: doctor catches the issue post-install on the user's machine, wheel-CI catches it pre-merge. They are complementary; shipping wheel-CI first does not block the version-observability work and vice versa.
- The deferral is a "small queue item" not a "needs design call". The only design questions (matrix shape, smoke-test depth, cache strategy) are answered above.

**Decision criterion**: ship when (a) the next pyo3 / pyext-gated dep bump is on the horizon (proactive defense; dependabot will eventually open the next pyo3 bump), OR (b) anyone refactors `ext/src/{lib,git,crypto}.rs` and wants the safety net, OR (c) we are doing a v-patch that is otherwise small and want to bundle the CI hardening with it.

**What we will NOT do as a workaround**:

- **Block CI on the wheel build for all 6 test cells** (3 Pythons x 2 platforms). The wheel-build job runs once per platform with Python 3.13. The matrix-Python angle is the existing `test` job's responsibility - it exercises subprocess fallback paths (`telemetry.py:get_head_commit` falls through to `git_run_safe` when `import presence_ext` fails), not wheel-loading.
- **Build wheels for Windows.** presence is documented as "install in WSL2" for Windows; wheel-CI does not need to lead the Windows native story.
- **Run on every push event.** `pull_request` + `push: branches: [main]` is the right scope (mirrors the existing `test` job).
- **Smoke-test deeply.** The wheel-CI smoke test verifies "the wheel imports and the basic shape of one function works". Full ext behavior is the responsibility of `tests/test_zerotrust_integration.py` and the daemon-fallback paths in the existing `test` job.
- **Publish the wheel.** The wheel is a build-time artifact for verification only. presence does not distribute wheels via GitHub Releases (per `docs/architecture.md` the ext is built locally with `--build-ext`). Adding wheel publishing is a separate decision that this entry does not make.

**Critical files referenced** (for the implementer's eventual use):

- `.github/workflows/ci.yml` (one new top-level job)
- `install.sh:413-470` (existing `--build-ext` logic; mirror the cargo + maturin invocation but skip the venv-creation step since CI's `actions/setup-python` already provides the interpreter)
- `ext/Cargo.toml` and `ext/src/lib.rs` (no changes; just the build target)
