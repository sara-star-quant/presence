#!/usr/bin/env bash
set -u
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; exit(0 if sys.version_info >= (3, 12) else 1)'; then
  PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib${PYTHONPATH:+:$PYTHONPATH}" \
    exec python3 "${CLAUDE_PLUGIN_ROOT}/lib/hook_post_tool_bash.py"
fi
exit 0
