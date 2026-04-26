#!/usr/bin/env bash
set -u
if command -v python3 >/dev/null 2>&1; then
  PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib${PYTHONPATH:+:$PYTHONPATH}" \
    exec python3 "${CLAUDE_PLUGIN_ROOT}/lib/hook_pre_tool_bash.py"
fi
exit 0
