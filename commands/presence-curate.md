---
description: Compress the project model. Invokes the model-curator subagent to consolidate observations in the project model into a tighter form.
allowed-tools: [Task, Bash]
---

Invoke the `model-curator` subagent to compress and reorganize the project model for the current repo.

The model can be encrypted on disk, so the curator reads it with `model show` and writes it back with `model replace`, both run from the project directory:

```bash
PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
python3 "$PRESENCE_ROOT/lib/cli.py" model show
```

Use the Task tool with `subagent_type=model-curator` to compress duplicate and stale entries into a tight set of architecture facts and conventions. The curator preserves the header and the most recent entries verbatim, and may rewrite anything older into a consolidated section.

Report back to the user with the size before and after and a one-line summary of what was kept.
