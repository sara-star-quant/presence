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

## Side-by-side install support via --name suffix

**Status**: niche; deferred unless plugin authors ask for it.

**Today**: `install.sh` symlinks at `~/.claude/plugins/presence/`. Only one version installable at a time. Maintainers testing `main` vs a branch must swap symlinks manually.

**Proposal**: `install.sh --name presence-dev` symlinks at `~/.claude/plugins/presence-dev/` and uses `~/.claude/presence-dev/` for state.

**Why deferred**: niche use case (only repo maintainers + plugin authors). Not worth the install.sh complexity until someone other than the maintainer asks for it.

## Raise statement coverage to 80% (OpenSSF Silver target)

**Tracking**: #39

**Status**: deterministic gate at 74% (74.7% measured); climbing to 80 incrementally.

**Today**: the `coverage` job measures statement coverage in-process, so the number is stable (the earlier subprocess capture swung 60-67% run to run). `daemon.py` is omitted - it only runs as a spawned subprocess, so in-process coverage can't see it; it is behavior-tested by `tests/test_daemon.py`. The v0.7.0 cycle added tests for the previously under-tested modules - `cli` (0 -> 96%), `hook_user_prompt_submit` (0 -> 83%), the integrity CLI (52 -> 78%), `telemetry` (29 -> 57%), `crypto` key management (48 -> 56%) - stepping the gate 67 -> 74. The remaining gap to 80% is in `crypto`'s keychain ops, `doctor`, `redact`, and the deeper `_common`/`hook_session_start` paths.

**Proposal**: add branch tests for those next-largest gaps and step the CI `--fail-under` up toward 80.

**Why incremental**: 80% is the Silver `test_statement_coverage80` criterion, and Silver already blocks on the single-maintainer rules (2+ contributors, bus factor >= 2, two-person review). Worth doing regardless, but no rush to the exact number while those block the badge.

## Verify the audit hash-chain fail-closed at SessionStart

**Tracking**: #59

**Status**: half shipped in v0.7.0; hot-path verification deferred.

**Today**: v0.7.0's Zero-Trust hardening made the fail-closed integrity gate also fail on extra (undeclared) plugin files, and an integrity failure now appends an `integrity_fail` line to the tamper-evident audit chain. But `audit.verify_chain()` still runs only on demand (`/presence-doctor`, `integrity.py --audit-verify`); a truncated or tampered audit log does not block a session.

**Proposal**: run `verify_chain()` in the Zero-Trust SessionStart gate and fail closed when the chain is broken.

**Why deferred**: it changes behavior (a corrupt audit log would make hooks inert), so it needs a deliberate call on what counts as broken (corrupt line vs broken link vs truncation), how a user recovers, and the cold-hook cost of walking an unbounded chain each session.

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

