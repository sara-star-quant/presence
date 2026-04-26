---
description: Wipe presence state for the current project, all projects, or specific subsystems. Asks for confirmation before destructive action.
argument-hint: "[--project | --telemetry | --events | --warnings | --crypto | --all]"
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
| `--crypto` | Rotate the AES-GCM data key in the OS keychain AND wipe all encrypted state files (telemetry, events). Plain state files untouched. |
| `--all` | Wipe **everything** under `~/.claude/presence/` (state only; plugin files untouched). Does NOT touch the keychain key. |

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

# --crypto (rotate key + wipe encrypted state; user must confirm separately)
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
import shutil
from pathlib import Path
import crypto
from _common import telemetry_dir, events_dir, state_dir

# Wipe encrypted state files (telemetry/events). Plain state stays.
# We can't easily distinguish per-line which files are mixed, so we wipe both
# directories entirely. Caller has confirmed via AskUserQuestion.
for d in (telemetry_dir(), state_dir() / 'events'):
    if d.exists():
        shutil.rmtree(d)
        print(f'wiped: {d}')

# Rotate the data key (existing ciphertext, if any survived, becomes unreadable)
new_key = crypto.rotate_key()
if new_key:
    print('keychain data key rotated; existing encrypted state is unreadable from now on')
else:
    print('warning: could not rotate key (cryptography lib or keychain unavailable)')
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
