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
