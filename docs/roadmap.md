# Roadmap

Things `presence` is **not** doing today, but where we have a written decision and a target shape. Each item below has (or will have) a tracking GitHub issue with the same title; comments and design discussion live there.

The bar to add an item here is: someone asked, the maintainer thought about it, decided "not now," and wrote down both the reason and the realistic shape of the eventual work. Items disappear from this list when they ship or when we conclude they will not ship.

## Multi-tool adapter architecture (Gemini, Codex, Cursor, ...)

**Status**: deferred to a future major version (v1.0+).

**What's asked**: ship presence's session-continuity behaviors (living model, outcome telemetry, event digest, calibrated confidence) on AI coding tools other than Claude Code.

**Why this is not a patch**: each tool has its own extension model. Hook event names differ (Claude Code's `SessionStart` vs Gemini's lifecycle vs Cursor's vs whatever Codex exposes). Context-injection mechanisms differ (Claude Code's `additionalContext` is unique). Plugin packaging formats differ (`.claude-plugin/` vs `.cursorrules` vs Gemini's format vs nothing). Some tools do not expose hooks at all.

**Realistic shape**:

```
presence-core/             tool-agnostic state, redaction, telemetry, crypto
adapters/
  claude-code/             current code, refactored into adapter
  gemini-code/             new
  codex/                   new
  cursor/                  new
```

**Cost estimate**: months of work, repo restructure, possibly a rebrand from `presence` to a tool-agnostic name.

**Decision criteria**: do not start until presence has documented Claude Code users actually requesting cross-tool support. First prove the value on one platform.

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

## Automate GitHub releases on tag push

**Status**: every release is currently manual; automation is one workflow file away.

**Today**: `gh release create ... --notes-file /tmp/...` for v0.3.0, v0.3.1, v0.3.2, v0.3.3. Risk: someone forgets to attach the CHANGELOG section, or pastes the wrong one, or includes em-dashes that should not be there.

**Proposal**: `.github/workflows/release.yml` triggered on `push: tags: 'v*'`. Steps: extract the matching `## v<tag>` section from `CHANGELOG.md` (same `awk`/`python` extraction we use locally); create the GitHub Release with that body and `--latest` if the tag is the highest semver; assert ASCII-only and no em-dash in the body before posting.

**Why deferred**: small file, but adds a public side-effect to every tag push. Want one more manual release cycle to confirm the format is stable before automating.

## Cross-machine state snapshot and migration tooling

**Status**: design discussion needed; deferred.

**Today**: `~/.claude/presence/` lives on one machine. A user with macOS-at-home + Linux-at-work has two disjoint memories per repo. The `outcome-check` skill could surface "you reverted X on the other box" but does not, because state is not shared.

**Proposal**: `install.sh --snapshot <path.tar.gz>` writes a redacted, optionally encrypted tarball of the state dir; `install.sh --restore <path.tar.gz>` re-imports. Or a separate `lib/snapshot.py` exposing the same. Schema-versioned so v0.4 changes do not break old snapshots.

**Why deferred**: needs design discussion. Encryption story (does the snapshot carry the data key, and how does that survive a key rotation?). Key portability across platforms when zerotrust is involved. Conflict resolution if both sides made writes between snapshots.

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
