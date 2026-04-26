---
description: List or switch presence presets. Run with no args to list; with "use <name>" to activate.
argument-hint: "[use <preset-name>]"
allowed-tools: [Bash, AskUserQuestion]
---

Parse the user's argument (`$ARGUMENTS`) to determine the action:

- If empty or the word `list`: list all available presets, marking the active one. Use:
  ```bash
  PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
  PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
  from presets import list_presets, active_preset_name
  active = active_preset_name()
  for name, source in list_presets().items():
      mark = '* ' if name == active else '  '
      print(f'{mark}{name:24} ({source})')
  "
  ```
  Then briefly describe each preset by reading the `_description` field from `$PRESENCE_ROOT/presets/<name>.json`.

- If `use <name>`: activate that preset. Use:
  ```bash
  PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
  PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
  import sys
  from presets import use_preset
  res = use_preset('<NAME>')
  if res.ok:
      print(f'activated preset: <NAME> (from {res.source})')
  else:
      print(f'ERROR: {res.error}', file=sys.stderr)
      sys.exit(1)
  "
  ```
  Replace `<NAME>` with the user's chosen name. If activation fails because the preset doesn't exist, list the available ones (using the script above) and ask the user to pick one via AskUserQuestion. If it fails due to a parse error, surface the parse error verbatim. Do not silently fall back to a different preset.

- If switching to `zerotrust`: warn the user that hard commit gates will activate and that v0.2 features (encryption, audit log) are not yet shipped. Confirm via AskUserQuestion before activating.

The available built-in presets are: `solo-dev` (default), `team-oss`, `enterprise-strict`, `zerotrust`. Custom presets can be added under `~/.claude/presence/presets/<name>.json`.
