#!/usr/bin/env bash
# presence: SessionStart hook wrapper.
# - exec the python entry with lib/ on PYTHONPATH
# - if python3 is missing, surface a one-time warning to the user via additionalContext
set -u
if command -v python3 >/dev/null 2>&1; then
  PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib${PYTHONPATH:+:$PYTHONPATH}" \
    exec python3 "${CLAUDE_PLUGIN_ROOT}/lib/hook_session_start.py"
fi

state_dir="${PRESENCE_STATE:-$HOME/.claude/presence}"
marker="$state_dir/.python3_warning_shown"
if [ ! -f "$marker" ]; then
  mkdir -p "$state_dir" 2>/dev/null && : > "$marker"
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"presence: python3 was not found on PATH. The plugin is installed but inactive. Install Python 3.10+ to enable."}}\n'
fi
exit 0
