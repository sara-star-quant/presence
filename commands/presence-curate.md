---
description: Compress the project model. Invokes the model-curator subagent to consolidate observations in model.md into a tighter form.
allowed-tools: [Task, Read, Write]
---

Invoke the `model-curator` subagent to compress and reorganize the project model for the current repo.

The current model lives at `~/.claude/presence/projects/<repo-id>/model.md`. To find the path:

```bash
PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
from model import model_path
print(model_path('$PWD'))
"
```

Then use the Task tool with `subagent_type=model-curator` to read the file, compress duplicate/stale entries into a tight set of architecture facts and conventions, and write the result back atomically. The curator should preserve the file header and the most recent N entries verbatim, but may rewrite anything older into a consolidated section.

Report back to the user with the size before/after and a one-line summary of what was kept.
