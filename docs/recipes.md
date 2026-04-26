# Recipes

Common customizations as copy-paste snippets. All `overrides` go in `~/.claude/presence/settings.json`:

```json
{
  "preset": "solo-dev",
  "overrides": {
    "<dotted.key>": <value>
  }
}
```

Dotted keys are walked as nested objects. The full set of recognized keys lives in the four shipped presets under `presets/`; the [glossary](glossary.md) defines the concepts.

## I want zerotrust gates without encryption

Useful when you want hard commit/push blocks + audit log but your environment has no usable OS keychain (or you don't want the dependency on `cryptography`).

```json
{
  "preset": "zerotrust",
  "overrides": {
    "model.encrypted": false,
    "telemetry.encrypted": false,
    "events.encrypted": false
  }
}
```

The integrity check, audit chain, redaction, and gates all stay on; only at-rest encryption flips off.

## I want a warn-only commit gate (just nudge, never block)

```json
{
  "preset": "team-oss",
  "overrides": {
    "confidence.commit_gate": "warn"
  }
}
```

Valid values: `"off"`, `"warn"`, `"ask"`, `"block"`. The Stop hook still surfaces unverified-claim warnings under any setting; this only affects PreToolUse(Bash) on `git commit` / `git push`.

## I want telemetry but no PR check

The optional `gh pr` outcome check makes one network call to GitHub's API. Disable it without disabling the rest of telemetry:

```json
{
  "preset": "team-oss",
  "overrides": {
    "telemetry.pr_check": false
  }
}
```

## I want a longer transcript scan

The Stop hook tail-reads the transcript looking for the final assistant message. Default cap is 256 KiB; very long sessions might cut off useful claims. Bump to 1 MiB:

```json
{
  "preset": "solo-dev",
  "overrides": {
    "transcript.max_bytes": 1048576
  }
}
```

## I want to disable the model file entirely

Useful for ephemeral or one-off sessions where you don't want presence to learn about the repo:

```json
{
  "preset": "solo-dev",
  "overrides": {
    "model.enabled": false
  }
}
```

## I want a smaller curate threshold (compress model.md sooner)

Default is 12000 chars; below that the SessionStart hook surfaces a `/presence-curate` nudge. Lower it for tighter pruning:

```json
{
  "preset": "solo-dev",
  "overrides": {
    "model.curate_threshold": 6000
  }
}
```

## I want to back up my state

```bash
~/.claude/plugins/presence/install.sh --snapshot ~/presence-backup.tar.gz
```

To restore on another machine (or after `--uninstall --purge`):

```bash
~/.claude/plugins/presence/install.sh --restore ~/presence-backup.tar.gz
# add --overwrite to clobber existing state
```

Snapshots refuse under `zerotrust` (key portability is unsolved; tracked in [roadmap.md](roadmap.md)). Switch to a non-zerotrust preset first if you need to migrate.

## I want to verify presence is healthy without opening Claude Code

```bash
~/.claude/plugins/presence/install.sh --verify
```

Or for machine-readable output:

```bash
~/.claude/plugins/presence/install.sh --verify --json | jq .
```

## I want to file a bug report

In Claude Code, run `/presence-bugreport`. The output is markdown formatted to drop straight into the [bug template](https://github.com/sara-star-quant/presence/issues/new?template=bug.yml).

Or from the shell:

```bash
PYTHONPATH=~/.claude/plugins/presence/lib python3 ~/.claude/plugins/presence/lib/bugreport.py --md
```

## I want to author a custom preset

Drop a JSON at `~/.claude/presence/presets/<name>.json`. Use one of the shipped presets under `presets/` as a starting template. Activate with:

```
/presence-preset use <name>
```

Note: there is no formal preset schema yet (tracked as a roadmap item). A typo'd key is silently ignored. Reference the four shipped presets to confirm spelling.
