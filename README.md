# presence

A Claude Code plugin that turns every session into part of a continuum.

`presence` adds four things to Claude Code, globally, with one install and zero per-project setup:

1. **Living project model.** Claude builds and reuses notes about each repo it touches. No more re-deriving the same architecture every session.
2. **Outcome telemetry.** Tracks what Claude committed, then watches for reverts, amends, and PR closes. Future sessions see "your last 3 changes here were reverted within 24h" instead of repeating the same mistake.
3. **Event digest.** File changes, test failures, and build results that happened between turns are surfaced at the next prompt instead of needing to be polled.
4. **Calibrated confidence.** The Stop hook checks whether success claims ("fixed", "done", "works") are backed by actual verification (tests run, build green) since the change. Warns when they're not. Optional hard gate on `git commit`/`push`.

State lives in `~/.claude/presence/`, fully local, never uploaded.

## Install

### Via marketplace (once published)

```
/plugin marketplace add github.com/sara-star-quant/presence
/plugin install presence
```

### Local install

> Available once the repo is pushed publicly to GitHub.

```bash
curl -fsSL https://raw.githubusercontent.com/sara-star-quant/presence/main/install.sh | bash
```

Or clone and run:

```bash
git clone https://github.com/sara-star-quant/presence ~/code/presence
~/code/presence/install.sh
```

The installer symlinks the plugin into `~/.claude/plugins/presence` and creates the state directory at `~/.claude/presence/`. It is idempotent.

## Verify install

In any Claude Code session:

```
/presence-status
```

You should see your active preset, the project ID for the current repo, and the size of the model + telemetry stores.

## Presets

`presence` ships with four preset bundles. Switch any time:

```
/presence-preset use solo-dev
/presence-preset use team-oss
/presence-preset use enterprise-strict
/presence-preset use zerotrust
```

| Preset | Model | Telemetry | Commit gate | Stop gate |
|---|---|---|---|---|
| `solo-dev` (default) | on, terse | on, no PR check | off (advisory only via Stop) | silent (logged, surfaced next session) |
| `team-oss` | on, verbose | on, optional PR check | warn (advisory text injected) | silent |
| `enterprise-strict` | on, verbose, audit | on, audit log | block (refuses commit) | block (re-prompts on unverified success) |
| `zerotrust` | on, audit | on, audit, no PR check | block | block |

Custom presets: drop a `<name>.json` in `~/.claude/presence/presets/` and switch to it.

See [`docs/zerotrust.md`](docs/zerotrust.md) for what the Zero-Trust preset adds and what is shipped vs planned.

## Uninstall

```
/plugin uninstall presence
```

Or, for local install:

```bash
~/.claude/plugins/presence/install.sh --uninstall
```

State at `~/.claude/presence/` is preserved by default. Pass `--purge` to also remove state.

## Privacy

- All state is local. Nothing is ever uploaded.
- No analytics, no telemetry-to-vendor, no remote calls.
- The `outcome-check` skill makes one optional `gh` call to read PR status if `gh` is on `$PATH` and authenticated; this hits GitHub's API directly, not any third party. Disable in preset.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full design: what each hook does, how state is laid out, and how to write a custom preset.

## License

MIT, see [LICENSE](LICENSE).
