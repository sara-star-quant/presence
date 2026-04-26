---
description: Show presence diagnostic report. Active preset, warnings, error counts, state sizes, integrity status. Run this when something seems off.
allowed-tools: [Bash]
---

Run the presence diagnostic report and display its output verbatim. Then, if there are any warnings or errors, briefly summarize what the user should do about them.

```bash
PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
PYTHONPATH="$PRESENCE_ROOT/lib" python3 "$PRESENCE_ROOT/lib/doctor.py" --cwd "$PWD"
```

After showing the output:
- If `errors_since_last_session > 0`, tell the user to inspect `~/.claude/presence/logs/errors.log`.
- If `warnings_since_last_session > 0`, the recent warnings are already in the report; explain the most common categories (e.g. `git_timeout`, `jsonl_corrupt`, `hook_input_malformed`).
- If `python_ok` is false, tell them to install Python 3.10+.
- If `git_available` is false, tell them telemetry is disabled.
- If `integrity` is FAILED, tell them to reinstall presence: the plugin files have changed and may be tampered.
- Otherwise, say "presence is healthy."

Do not modify any state. This is a read-only command.
