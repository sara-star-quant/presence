---
description: Temporarily allow settings.json writes under the zerotrust preset. Creates a 60-second unlock window. Outside zerotrust, settings are always writable and this command is a no-op.
argument-hint: "[--ttl SECONDS]"
allowed-tools: [Bash]
---

Create an unlock marker so the next settings-modifying operation (preset switch via `/presence-preset use`, or any direct `~/.claude/presence/settings.json` edit) is permitted under the zerotrust preset.

If `$ARGUMENTS` contains `--ttl <seconds>`, use that TTL; otherwise default 60 seconds.

```bash
PRESENCE_ROOT="${CLAUDE_PLUGIN_ROOT:-$(realpath ~/.claude/plugins/presence 2>/dev/null || echo .)}"
TTL=60
if [[ "$ARGUMENTS" =~ --ttl[[:space:]]+([0-9]+) ]]; then
  TTL="${BASH_REMATCH[1]}"
fi
PYTHONPATH="$PRESENCE_ROOT/lib" python3 -c "
import unlock
expire = unlock.unlock(ttl_seconds=$TTL)
import time
print(f'unlocked: settings writes permitted for the next $TTL second(s) (until {time.strftime(\"%H:%M:%S\", time.localtime(expire))})')
"
```

After this command, the user has the unlock window to make settings changes. If they don't make changes within the window, the marker expires and immutability resumes automatically.

If the active preset is NOT zerotrust (or any preset that sets `settings.immutable: true`), this command runs but has no practical effect: settings are already writable.

Note: this is a tamper-resistance signal, not a security barrier. A user with filesystem access can always remove `~/.claude/presence/.unlocked` directly. The unlock flow exists to make accidental settings changes during a sensitive session require an explicit conscious step.
