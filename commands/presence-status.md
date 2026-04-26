---
description: Quick one-line presence status. Active preset, current repo id, model size, recent reverts. Use this to confirm presence is working in the current repo.
allowed-tools: [Bash]
---

Run the presence diagnostic report in JSON mode and produce a *single concise paragraph* summarizing:
- Active preset name
- Current repo id (the 12-char hash)
- Model size (in KB if > 1KB)
- Pending event count
- Whether there are any new errors/warnings since last session

Do not show the full doctor report. That's what `/presence-doctor` is for.

```bash
PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
PYTHONPATH="$PRESENCE_ROOT/lib" python3 "$PRESENCE_ROOT/lib/doctor.py" --cwd "$PWD" --json
```

Format your response as one or two sentences, not a table or list. Example: "presence is on preset `solo-dev` for repo `a1b2c3d4e5f6`: 2.3 KB of model notes, 4 pending events, no warnings."
