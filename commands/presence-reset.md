---
description: Wipe presence state for the current project (or all projects, or specific subsystems). Asks for confirmation before destructive action.
argument-hint: "[--project | --telemetry | --events | --warnings | --all]"
allowed-tools: [Bash, AskUserQuestion]
---

Parse `$ARGUMENTS` for one of these flags. If none given, ask the user via AskUserQuestion which scope they want.

Available scopes:

| Flag | Effect |
|---|---|
| `--project` | Delete model.md and event log for the **current repo only** |
| `--telemetry` | Delete claims/outcomes/confidence (all projects) |
| `--events` | Delete event log for the current repo |
| `--warnings` | Clear warnings.log and one-shot warning markers |
| `--all` | Wipe **everything** under `~/.claude/presence/` (state only; plugin files untouched) |

**Always** confirm with the user before deleting via AskUserQuestion. Show them exactly what paths will be removed first.

For each scope, the operation is:

```bash
PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"

# --project
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
from _common import project_dir, events_dir
import shutil, sys
for d in (project_dir('$PWD'), events_dir('$PWD')):
    if d.exists():
        shutil.rmtree(d)
        print(f'removed {d}')
"

# --telemetry
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
from _common import telemetry_dir
import shutil
d = telemetry_dir()
if d.exists():
    shutil.rmtree(d); print(f'removed {d}')
"

# --events
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
from _common import events_dir
import shutil
d = events_dir('$PWD')
if d.exists():
    shutil.rmtree(d); print(f'removed {d}')
"

# --warnings
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
from warnings_log import clear_warnings_state
from _common import reset_counter
clear_warnings_state()
reset_counter('warning'); reset_counter('error')
print('warnings cleared')
"

# --all
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
from _common import state_dir
import shutil
d = state_dir()
if d.exists():
    shutil.rmtree(d); print(f'removed {d}')
"
```

The plugin install itself (under `~/.claude/plugins/presence/`) is **never** touched by reset. Only the state directory.
