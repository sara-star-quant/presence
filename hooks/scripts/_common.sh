# presence: shared bootstrap for hook wrappers.
#
# Sourced by every hooks/scripts/*.sh wrapper. Provides one function:
#
#   exec_hook <python-entry-relative-to-lib>
#
# Behavior, in order:
#   1. If python3 is missing from PATH: emit a one-time SessionStart warning
#      (only for the SessionStart hook; other hooks just exit 0 silently).
#   2. Cache the python3 >= 3.12 verdict at $state_dir/.python_version_ok.
#      Cache key is just the python_bin path; staleness is detected by bash
#      `-nt` (marker newer than the python binary). Cache HIT path is
#      subprocess-free: zero `stat`, zero `head`, zero command substitutions.
#      Cache MISS path: run `python3 -c '...'` once and rewrite the marker.
#   3. exec the requested python entry point with PYTHONPATH set.
#
# Marker format (v0.3.1+): single line, just the python binary path. The
# v0.3.0 format `<bin>:<mtime>` does not match the new check, so the first
# hook after upgrade re-probes once and rewrites the marker. No state
# migration needed.
#
# Set -u only; we never want -e here because a hook must NEVER make Claude
# Code observe an error from presence. safe_main inside python is the real
# guard.

# shellcheck shell=bash
set -u

_presence_state_dir() {
  printf '%s' "${PRESENCE_STATE:-$HOME/.claude/presence}"
}

_presence_pinned_python() {
  # Honor a pinned interpreter at $state_dir/.python_bin so installs that
  # bootstrapped Python via uv (install.sh --bootstrap) use the exact same
  # binary at runtime even when the user's PATH still points at an older
  # python3. Echo the path iff the file exists AND the path is executable;
  # print nothing on any miss so the caller falls through to PATH lookup.
  local marker pinned
  marker="$(_presence_state_dir)/.python_bin"
  [ -f "$marker" ] || return 1
  IFS= read -r pinned < "$marker" 2>/dev/null || return 1
  { [ -n "$pinned" ] && [ -x "$pinned" ]; } || return 1
  printf '%s' "$pinned"
}

_presence_python_ok_cached() {
  # Cache hit iff: marker exists, marker is newer than python_bin (so python
  # hasn't been upgraded since we wrote it), and marker's first line equals
  # the current python_bin path. All-builtin: zero subprocesses on hit.
  # Returns 0 on hit, 1 on miss.
  local bin marker first_line
  bin="$1"
  marker="$(_presence_state_dir)/.python_version_ok"
  [ -f "$marker" ] || return 1
  [ "$marker" -nt "$bin" ] || return 1
  IFS= read -r first_line < "$marker" 2>/dev/null || return 1
  [ "$first_line" = "$bin" ]
}

_presence_record_python_ok() {
  local bin state_dir marker
  bin="$1"
  state_dir="$(_presence_state_dir)"
  marker="$state_dir/.python_version_ok"
  mkdir -p "$state_dir" 2>/dev/null || return 0
  printf '%s\n' "$bin" > "$marker" 2>/dev/null || true
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
  # Prefer a pinned (uv-bootstrapped) interpreter; fall back to PATH.
  python_bin="$(_presence_pinned_python || true)"
  [ -z "$python_bin" ] && python_bin="$(command -v python3 2>/dev/null || true)"
  if [ -z "$python_bin" ]; then
    _presence_warn_python_missing_for_session_start "$hook_entry"
    exit 0
  fi
  if ! _presence_python_ok_cached "$python_bin"; then
    if ! "$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      _presence_warn_python_missing_for_session_start "$hook_entry"
      exit 0
    fi
    _presence_record_python_ok "$python_bin"
  fi
  # PYTHONNOUSERSITE=1 skips the site.py user-site directory lookup at
  # interpreter startup (~3-8 ms saved per cold hook fire on Python 3.12+).
  # Hooks never want user-site packages: they only need stdlib + lib/.
  PYTHONNOUSERSITE=1 \
  PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib${PYTHONPATH:+:$PYTHONPATH}" \
    exec "$python_bin" "${CLAUDE_PLUGIN_ROOT}/lib/${hook_entry}"
}
