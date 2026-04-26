---
description: Bundle install verify + doctor report + recent warnings + state sizes into a paste-friendly markdown blob for filing issues at https://github.com/sara-star-quant/presence/issues. Read-only.
allowed-tools: [Bash]
---

Run the presence bug-report bundler and display its output verbatim. Then tell the user to paste the output into the issue template at https://github.com/sara-star-quant/presence/issues/new?template=bug.yml in the "Output of ..." field.

```bash
PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
PYTHONPATH="$PRESENCE_ROOT/lib" python3 "$PRESENCE_ROOT/lib/bugreport.py" --md --cwd "$PWD"
```

This is a read-only command. It does not modify any state.
