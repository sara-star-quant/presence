# presence: shared bootstrap for hook wrappers.
#
# Sourced by every hooks/scripts/*.sh wrapper. Provides one function:
#
#   exec_hook <python-entry-relative-to-lib>
#
# Behavior, in order:
#   1. If python3 is missing from PATH: emit a one-time SessionStart warning
#      (only for the SessionStart hook; other hooks just exit 0 silently).
#   2. Cache the python3 >= 3.12 verdict at $state_dir/.python_version_ok
#      keyed by <python_bin>:<mtime>. Cache hit -> skip the version check entirely.
#      This eliminates ~20 ms (a separate `python3 -c '...'` process spawn) on
#      every hook fire after the first one in a session.
#   3. exec the requested python entry point with PYTHONPATH set.
#
# Set -u only; we never want -e here because a hook must NEVER make Claude Code
# observe an error from presence. safe_main inside python is the real guard.

# shellcheck shell=bash
set -u

_presence_state_dir() {
  printf '%s' "${PRESENCE_STATE:-$HOME/.claude/presence}"
}

_presence_mtime() {
  # Try GNU stat first, BSD second. Reverse order is unsafe on Linux: GNU
  # stat treats `-f` as `--file-system` and dumps multi-line filesystem stats
  # to stdout when called as `-f %m <file>`, which corrupts the cache marker.
  # BSD stat rejects `-c` cleanly with empty stdout, so GNU-first works on macOS too.
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || printf ''
}

_presence_python_ok_cached() {
  # Echo "ok" if cache hit, nothing if miss. Cache key: "<bin>:<mtime>".
  local bin marker want got
  bin="$1"
  marker="$(_presence_state_dir)/.python_version_ok"
  [ -f "$marker" ] || return 0
  want="${bin}:$(_presence_mtime "$bin")"
  # read first line; tolerate trailing newline absence
  got="$(head -n 1 "$marker" 2>/dev/null || printf '')"
  [ "$got" = "$want" ] && printf 'ok'
}

_presence_record_python_ok() {
  local bin state_dir marker
  bin="$1"
  state_dir="$(_presence_state_dir)"
  marker="$state_dir/.python_version_ok"
  mkdir -p "$state_dir" 2>/dev/null || return 0
  printf '%s:%s\n' "$bin" "$(_presence_mtime "$bin")" > "$marker" 2>/dev/null || true
  chmod 600 "$marker" 2>/dev/null || true
}

_presence_warn_python_missing_for_session_start() {
  # Only the SessionStart hook can surface a one-time UI warning; other hooks
  # have no additionalContext channel that Claude Code reads.
  local hook_entry state_dir marker
  hook_entry="$1"
  case "$hook_entry" in
    hook_session_start.py) ;;
    *) return 0 ;;
  esac
  state_dir="$(_presence_state_dir)"
  marker="$state_dir/.python3_warning_shown"
  if [ ! -f "$marker" ]; then
    mkdir -p "$state_dir" 2>/dev/null && : > "$marker" 2>/dev/null
    printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"presence: python3 (>=3.12) was not found on PATH. The plugin is installed but inactive. Install Python 3.12+ to enable."}}\n'
  fi
}

exec_hook() {
  local hook_entry python_bin
  hook_entry="$1"
  python_bin="$(command -v python3 2>/dev/null || true)"
  if [ -z "$python_bin" ]; then
    _presence_warn_python_missing_for_session_start "$hook_entry"
    exit 0
  fi
  if [ -z "$(_presence_python_ok_cached "$python_bin")" ]; then
    if ! "$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      _presence_warn_python_missing_for_session_start "$hook_entry"
      exit 0
    fi
    _presence_record_python_ok "$python_bin"
  fi
  PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib${PYTHONPATH:+:$PYTHONPATH}" \
    exec "$python_bin" "${CLAUDE_PLUGIN_ROOT}/lib/${hook_entry}"
}
