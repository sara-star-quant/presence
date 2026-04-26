---
description: Quick presence status. Active preset, current repo id, model size, recent reverts. Pass --zerotrust for the full Zero-Trust controls checklist.
argument-hint: "[--zerotrust]"
allowed-tools: [Bash]
---

Parse `$ARGUMENTS`:

- If `--zerotrust` is present: produce a focused checklist showing the status of each Zero-Trust control. Use:
  ```bash
  PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
  PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
  from doctor import zerotrust_report
  for line in zerotrust_report():
      print(line)
  "
  ```
  Show the output verbatim. Then briefly summarize: how many controls are OK vs FAIL, and whether the active preset is `zerotrust` (if not, mention that ZT controls are inactive even if available).

- Otherwise (no flag): produce a *single concise paragraph* summarizing active preset, current repo id (12-char hash), model size (in KB if > 1KB), pending event count, and whether there are any new errors/warnings since last session. Do not show the full doctor report; that's what `/presence-doctor` is for.

  ```bash
  PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
  PYTHONPATH="$PRESENCE_ROOT/lib" python3 "$PRESENCE_ROOT/lib/doctor.py" --cwd "$PWD" --json
  ```

  Format response as one or two sentences. Example: "presence is on preset `solo-dev` for repo `a1b2c3d4e5f6`: 2.3 KB of model notes, 4 pending events, no warnings."
