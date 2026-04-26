#!/usr/bin/env bash
# presence: installer
#
# Idempotent. Safe to re-run. Does:
#   1. Verify python3 >= 3.10 and git are present (warn if not, don't abort)
#   2. Symlink the plugin into ~/.claude/plugins/presence/
#   3. Create ~/.claude/presence/ state directory with 0700 perms
#   4. Generate MANIFEST.lock
#
# Usage:
#   ./install.sh                 # install (default)
#   ./install.sh --uninstall     # remove plugin symlink (state preserved)
#   ./install.sh --uninstall --purge   # remove plugin AND state
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
PLUGINS_DIR="$CLAUDE_HOME/plugins"
PLUGIN_LINK="$PLUGINS_DIR/presence"
STATE_DIR="${PRESENCE_STATE:-$CLAUDE_HOME/presence}"

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
warn() { printf '\033[33mwarn :\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36minfo :\033[0m %s\n' "$*"; }
ok()   { printf '\033[32mok   :\033[0m %s\n' "$*"; }

check_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    warn "python3 not found on PATH. presence will be installed but inactive until Python 3.10+ is available"
    return
  fi
  local v
  v=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') || true
  case "$v" in
    3.1[0-9]|3.[2-9][0-9])  ok "python3 $v" ;;
    *) warn "python3 $v detected. presence requires 3.10+; upgrade Python to enable hooks" ;;
  esac
}

check_git() {
  if command -v git >/dev/null 2>&1; then
    ok "git $(git --version | awk '{print $3}')"
  else
    warn "git not found. outcome telemetry (commit tracking, revert detection) will be disabled"
  fi
}

uninstall() {
  local purge=0
  for arg in "$@"; do
    [ "$arg" = "--purge" ] && purge=1
  done
  if [ -L "$PLUGIN_LINK" ]; then
    rm -f "$PLUGIN_LINK"
    ok "removed plugin symlink: $PLUGIN_LINK"
  elif [ -e "$PLUGIN_LINK" ]; then
    warn "$PLUGIN_LINK exists but is not a symlink; refusing to delete (manual review needed)"
  else
    info "no plugin symlink to remove"
  fi
  if [ "$purge" -eq 1 ]; then
    if [ -d "$STATE_DIR" ]; then
      rm -rf "$STATE_DIR"
      ok "purged state: $STATE_DIR"
    fi
  else
    info "state at $STATE_DIR preserved (pass --purge to also wipe)"
  fi
  exit 0
}

install() {
  info "presence installer"
  info "plugin source: $SCRIPT_DIR"
  info "claude home  : $CLAUDE_HOME"
  info "state dir    : $STATE_DIR"
  echo

  check_python
  check_git

  # Sanity: are we in the right directory?
  [ -f "$SCRIPT_DIR/.claude-plugin/plugin.json" ] || die "expected $SCRIPT_DIR/.claude-plugin/plugin.json; is this the presence repo root?"

  # Create plugins directory
  mkdir -p "$PLUGINS_DIR"

  # Symlink (or replace existing symlink)
  if [ -L "$PLUGIN_LINK" ]; then
    local existing
    existing=$(readlink "$PLUGIN_LINK")
    if [ "$existing" = "$SCRIPT_DIR" ]; then
      ok "plugin already linked: $PLUGIN_LINK -> $SCRIPT_DIR"
    else
      info "updating plugin symlink (was $existing)"
      rm -f "$PLUGIN_LINK"
      ln -s "$SCRIPT_DIR" "$PLUGIN_LINK"
      ok "plugin linked: $PLUGIN_LINK -> $SCRIPT_DIR"
    fi
  elif [ -e "$PLUGIN_LINK" ]; then
    die "$PLUGIN_LINK exists and is not a symlink; refusing to overwrite"
  else
    ln -s "$SCRIPT_DIR" "$PLUGIN_LINK"
    ok "plugin linked: $PLUGIN_LINK -> $SCRIPT_DIR"
  fi

  # Create state directory with restrictive perms
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  ok "state directory ready (0700): $STATE_DIR"

  # Make hook scripts executable (in case clone dropped perms)
  chmod +x "$SCRIPT_DIR"/hooks/scripts/*.sh
  ok "hook scripts executable"

  # Generate MANIFEST.lock if python3 is available
  if command -v python3 >/dev/null 2>&1; then
    if PYTHONPATH="$SCRIPT_DIR/lib" python3 "$SCRIPT_DIR/lib/integrity.py" --write >/dev/null 2>&1; then
      ok "MANIFEST.lock generated"
    else
      warn "could not generate MANIFEST.lock (integrity verification will be skipped in zerotrust preset)"
    fi
    # Pre-compile lib/ to .pyc so the first hook fire of every session skips
    # the parse-and-compile step (~5-10 ms saved per cold start). Best-effort:
    # if compileall fails (read-only fs, version mismatch, etc.) the runtime
    # behavior is unchanged, just slightly slower on first fire.
    if python3 -m compileall -q "$SCRIPT_DIR/lib" >/dev/null 2>&1; then
      ok "lib/ pre-compiled to bytecode"
    fi
  fi

  echo
  ok "install complete"
  cat <<EOF

Next steps:
  1. Restart Claude Code (or open a new session)
  2. Run /presence-status to confirm it's active
  3. Run /presence-doctor for a full diagnostic
  4. To switch presets:        /presence-preset use solo-dev|team-oss|enterprise-strict|zerotrust
  5. To wipe state and start over:    /presence-reset --all

For the v0.2 Zero-Trust encryption layer (when shipped), install cryptography:
  pip install --user cryptography
v0.1 Zero-Trust works without it; the integrity check, redaction, and hard
commit/push gates are all already wired in.

To uninstall:
  $SCRIPT_DIR/install.sh --uninstall          (preserves state)
  $SCRIPT_DIR/install.sh --uninstall --purge  (removes everything)
EOF
}

# ---------------------------------------------------------------------------

case "${1:-install}" in
  install)            install ;;
  --uninstall|uninstall) shift || true; uninstall "$@" ;;
  -h|--help)
    cat <<EOF
presence installer

Usage:
  ./install.sh                          install (or update an existing install)
  ./install.sh --uninstall              remove plugin symlink (state preserved)
  ./install.sh --uninstall --purge      remove plugin and wipe state
  ./install.sh --help                   this help

Environment:
  CLAUDE_HOME       (default: ~/.claude)
  PRESENCE_STATE    (default: \$CLAUDE_HOME/presence)
EOF
    ;;
  *) die "unknown argument: $1 (try --help)" ;;
esac
