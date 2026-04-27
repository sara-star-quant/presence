#!/usr/bin/env bash
# presence: installer
#
# Idempotent. Safe to re-run. Does:
#   1. Verify python3 >= 3.12 and git are present (warn if not, don't abort)
#   2. Symlink the plugin into ~/.claude/plugins/presence/
#   3. Create ~/.claude/presence/ state directory with 0700 perms
#   4. Generate MANIFEST.lock
#   5. Pre-compile lib/ to bytecode
#
# Usage:
#   ./install.sh                       # install or refresh (idempotent)
#   ./install.sh --bootstrap           # also install Python 3.13 via uv if missing/old (opt-in network)
#   ./install.sh --verify              # full pre-Claude-Code health check; exits 0 if ready
#   ./install.sh --verify --json       # same as --verify but emits a JSON blob for CI/scripting
#   ./install.sh --update              # git pull + re-install (refuses if dirty)
#   ./install.sh --uninstall           # remove plugin symlink (state preserved)
#   ./install.sh --uninstall --purge   # remove plugin AND state
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
PLUGINS_DIR="$CLAUDE_HOME/plugins"
PLUGIN_LINK="$PLUGINS_DIR/presence"
STATE_DIR="${PRESENCE_STATE:-$CLAUDE_HOME/presence}"

# Flags parsed from the CLI; consulted by install() and verify().
BOOTSTRAP=0
VERIFY_JSON=0

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
warn() { printf '\033[33mwarn :\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36minfo :\033[0m %s\n' "$*"; }
ok()   { printf '\033[32mok   :\033[0m %s\n' "$*"; }

check_python() {
  # Returns 0 iff a usable python3 (>= 3.12) is on PATH. Side effect: prints
  # ok/warn line. Callers (install, bootstrap_python_via_uv) consult the
  # return code to decide whether to invoke the bootstrap.
  local py_bin
  py_bin="$(command -v python3 2>/dev/null || true)"
  if [ -z "$py_bin" ]; then
    warn "python3 not found on PATH. presence will be installed but inactive until Python 3.12+ is available"
    return 1
  fi
  local v
  v=$("$py_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') || true
  case "$v" in
    3.1[2-9]|3.[2-9][0-9])  ok "python3 $v"; return 0 ;;
    *) warn "python3 $v detected. presence requires 3.12+; upgrade Python to enable hooks"; return 1 ;;
  esac
}

check_git() {
  if command -v git >/dev/null 2>&1; then
    ok "git $(git --version | awk '{print $3}')"
  else
    warn "git not found. outcome telemetry (commit tracking, revert detection) will be disabled"
  fi
}

# ---------------------------------------------------------------------------
# Optional Python bootstrap via uv. OPT-IN ONLY (--bootstrap flag). We never
# silently make a network call from install.sh; the project's "no network
# egress in default presets" stance applies to the installer too.
# ---------------------------------------------------------------------------

bootstrap_python_via_uv() {
  info "presence: --bootstrap requested; installing Python 3.13 via uv"
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl not found; cannot install uv. Install Python 3.12+ manually and rerun."
    return 1
  fi

  if ! command -v uv >/dev/null 2>&1; then
    info "downloading uv installer from https://astral.sh"
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
      warn "uv install failed; install Python 3.12+ manually and rerun"
      return 1
    fi
    # Try to source uv into current shell. uv installer writes to ~/.local/bin
    # (or ~/.cargo/bin on some platforms); add both to PATH for this run.
    # shellcheck source=/dev/null
    [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  fi

  if ! command -v uv >/dev/null 2>&1; then
    warn "uv installed but not on PATH; restart your shell and rerun --bootstrap"
    return 1
  fi

  if ! uv python install 3.13 >/dev/null 2>&1; then
    warn "uv python install 3.13 failed; install Python 3.12+ manually and rerun"
    return 1
  fi

  local resolved_path
  resolved_path=$(uv python find 3.13 2>/dev/null || true)
  if [ -z "$resolved_path" ] || [ ! -x "$resolved_path" ]; then
    warn "could not resolve installed Python via 'uv python find 3.13'"
    return 1
  fi
  if ! "$resolved_path" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    warn "uv-installed Python at $resolved_path is not >= 3.12 (unexpected)"
    return 1
  fi

  # Pin the resolved path so runtime hooks find this interpreter even if the
  # user's PATH still points at an older python3.
  mkdir -p "$STATE_DIR"
  printf '%s\n' "$resolved_path" > "$STATE_DIR/.python_bin"
  chmod 600 "$STATE_DIR/.python_bin"
  ok "uv-installed Python pinned: $resolved_path"
}

# ---------------------------------------------------------------------------
# verify subcommand: pre-Claude-Code health check. Each check appends one
# tab-delimited line "<name>\t<true|false>\t<detail>" to a tmp file. At the
# end we either render human-readable output or hand the tmp file to python
# for JSON formatting (which avoids hand-encoding escaping in bash).
# ---------------------------------------------------------------------------

# Resolve which python the runtime would use: prefer .python_bin, fall back
# to PATH. Used by both verify and bootstrap.
_resolve_python() {
  if [ -f "$STATE_DIR/.python_bin" ]; then
    local pinned
    pinned=$(head -n 1 "$STATE_DIR/.python_bin" 2>/dev/null || true)
    if [ -n "$pinned" ] && [ -x "$pinned" ]; then
      printf '%s' "$pinned"
      return 0
    fi
  fi
  command -v python3 2>/dev/null || true
}

verify() {
  local results_file
  results_file=$(mktemp)
  # shellcheck disable=SC2064
  trap "rm -f '$results_file'" EXIT

  _record() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$results_file"; }

  # 1. Symlink check.
  if [ -L "$PLUGIN_LINK" ]; then
    local plugin_target
    plugin_target=$(readlink "$PLUGIN_LINK")
    if [ "$plugin_target" = "$SCRIPT_DIR" ]; then
      _record "symlink" "true" "$PLUGIN_LINK -> $SCRIPT_DIR"
    else
      _record "symlink" "false" "$PLUGIN_LINK -> $plugin_target (expected $SCRIPT_DIR)"
    fi
  else
    _record "symlink" "false" "$PLUGIN_LINK is not a symlink (run install first?)"
  fi

  # 2. Python check (using the same resolution runtime hooks do).
  local py_bin py_v
  py_bin=$(_resolve_python)
  if [ -z "$py_bin" ]; then
    _record "python" "false" "no python3 on PATH and no .python_bin marker"
  else
    if ! py_v=$("$py_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null); then
      _record "python" "false" "$py_bin failed to run"
      py_bin=""
    elif ! "$py_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      _record "python" "false" "$py_bin is $py_v (need >= 3.12)"
      py_bin=""
    else
      _record "python" "true" "$py_bin (Python $py_v)"
    fi
  fi

  # 3. Hook scripts executable (all 6).
  local hook_missing=""
  for h in session-start.sh user-prompt-submit.sh pre-tool-bash.sh post-tool-bash.sh post-tool-edit.sh stop.sh; do
    if [ ! -x "$SCRIPT_DIR/hooks/scripts/$h" ]; then
      hook_missing="$hook_missing $h"
    fi
  done
  if [ -z "$hook_missing" ]; then
    _record "hook_scripts_executable" "true" "all 6 hook scripts have +x"
  else
    _record "hook_scripts_executable" "false" "not executable:$hook_missing"
  fi

  # 4. State perms (portable across BSD/GNU stat via python).
  if [ -d "$STATE_DIR" ]; then
    if [ -n "$py_bin" ]; then
      local mode
      mode=$("$py_bin" -c "import os, stat; print(f'0o{stat.S_IMODE(os.stat(\"$STATE_DIR\").st_mode):03o}')" 2>/dev/null || echo "?")
      if [ "$mode" = "0o700" ]; then
        _record "state_perms" "true" "$STATE_DIR is 0o700"
      else
        _record "state_perms" "false" "$STATE_DIR is $mode (expected 0o700)"
      fi
    else
      _record "state_perms" "false" "no usable python to read perms"
    fi
  else
    _record "state_perms" "false" "$STATE_DIR does not exist"
  fi

  # 5. MANIFEST.lock present + integrity verifies.
  if [ ! -f "$SCRIPT_DIR/MANIFEST.lock" ]; then
    _record "manifest_integrity" "false" "MANIFEST.lock missing (run install)"
  elif [ -z "$py_bin" ]; then
    _record "manifest_integrity" "false" "no usable python to verify"
  elif PYTHONPATH="$SCRIPT_DIR/lib" "$py_bin" "$SCRIPT_DIR/lib/integrity.py" --verify >/dev/null 2>&1; then
    _record "manifest_integrity" "true" "MANIFEST.lock OK"
  else
    _record "manifest_integrity" "false" "MANIFEST.lock present but integrity --verify failed"
  fi

  # 6. Synthetic fire of all 6 hooks. Each must exit 0; stdout (if any) must
  # be valid JSON. Catches import regressions in any hook entry point.
  local hooks_failed=""
  for entry in \
    "session-start.sh:SessionStart" \
    "user-prompt-submit.sh:UserPromptSubmit" \
    "pre-tool-bash.sh:PreToolUse" \
    "post-tool-bash.sh:PostToolUse" \
    "post-tool-edit.sh:PostToolUse" \
    "stop.sh:Stop"
  do
    local script="${entry%:*}"
    local event="${entry##*:}"
    local payload
    payload=$(printf '{"hook_event_name":"%s","cwd":"%s","session_id":"verify"}' "$event" "$SCRIPT_DIR")
    local out rc
    out=$(printf '%s' "$payload" | CLAUDE_PLUGIN_ROOT="$SCRIPT_DIR" PRESENCE_STATE="$STATE_DIR" bash "$SCRIPT_DIR/hooks/scripts/$script" 2>/dev/null) || rc=$?
    rc=${rc:-0}
    if [ "$rc" -ne 0 ]; then
      hooks_failed="${hooks_failed}${script}(rc=$rc) "
    elif [ -n "$out" ] && [ -n "$py_bin" ]; then
      if ! printf '%s' "$out" | "$py_bin" -c 'import json,sys; json.loads(sys.stdin.read())' >/dev/null 2>&1; then
        hooks_failed="${hooks_failed}${script}(invalid-json) "
      fi
    fi
    unset rc
  done
  if [ -z "$hooks_failed" ]; then
    _record "hook_synthetic_fire" "true" "all 6 hooks fired cleanly"
  else
    _record "hook_synthetic_fire" "false" "$hooks_failed"
  fi

  # 7. Doctor pass (optional, informative).
  local doctor_json_file=""
  if [ -n "$py_bin" ]; then
    doctor_json_file=$(mktemp)
    if PYTHONPATH="$SCRIPT_DIR/lib" "$py_bin" "$SCRIPT_DIR/lib/doctor.py" --cwd "$SCRIPT_DIR" --json > "$doctor_json_file" 2>/dev/null; then
      _record "doctor_report" "true" "lib/doctor.py --json succeeded"
    else
      _record "doctor_report" "false" "lib/doctor.py --json failed"
      doctor_json_file=""
    fi
  fi

  # Aggregate + emit.
  local all_ok=true
  while IFS=$'\t' read -r _ check_ok _; do
    [ "$check_ok" = "false" ] && all_ok=false
  done < "$results_file"

  if [ "$VERIFY_JSON" = "1" ] && [ -n "$py_bin" ]; then
    "$py_bin" -c '
import json, sys, pathlib
results_path = sys.argv[1]
doctor_path = sys.argv[2] if len(sys.argv) > 2 else ""
checks = []
for line in pathlib.Path(results_path).read_text().splitlines():
    if not line:
        continue
    parts = line.split("\t", 2)
    if len(parts) != 3:
        continue
    name, ok, detail = parts
    checks.append({"name": name, "ok": ok == "true", "detail": detail})
out = {"ok": all(c["ok"] for c in checks), "checks": checks}
if doctor_path:
    try:
        out["doctor"] = json.loads(pathlib.Path(doctor_path).read_text())
    except Exception:
        out["doctor"] = None
print(json.dumps(out, indent=2))
' "$results_file" "$doctor_json_file"
  else
    echo
    info "presence: verify"
    while IFS=$'\t' read -r name check_ok detail; do
      if [ "$check_ok" = "true" ]; then
        ok "$name: $detail"
      else
        printf '\033[31mFAIL\033[0m: %s: %s\n' "$name" "$detail" >&2
      fi
    done < "$results_file"
    echo
    if [ "$all_ok" = "true" ]; then
      ok "presence is healthy"
      info "Restart Claude Code (or open a new session) and run /presence-status"
    else
      printf '\033[31merror:\033[0m verify failed; see FAIL lines above\n' >&2
    fi
  fi

  [ -n "$doctor_json_file" ] && rm -f "$doctor_json_file"
  if [ "$all_ok" = "true" ]; then
    exit 0
  fi
  exit 1
}

update() {
  info "presence updater"
  info "plugin source: $SCRIPT_DIR"

  if [ ! -d "$SCRIPT_DIR/.git" ]; then
    die "$SCRIPT_DIR is not a git checkout; pull manually and re-run install.sh"
  fi
  if ! command -v git >/dev/null 2>&1; then
    die "git is required for --update but is not on PATH"
  fi

  # Refuse if working tree is dirty (uncommitted or staged changes); we never
  # want --update to clobber the user's WIP. Untracked files are tolerated.
  if ! git -C "$SCRIPT_DIR" diff --quiet || ! git -C "$SCRIPT_DIR" diff --cached --quiet; then
    die "$SCRIPT_DIR has uncommitted changes; commit or stash before --update"
  fi

  local before after
  before=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD)
  info "fetching origin..."
  if ! git -C "$SCRIPT_DIR" fetch --tags origin >/dev/null 2>&1; then
    warn "git fetch failed; proceeding with whatever is already local"
  fi
  if ! git -C "$SCRIPT_DIR" pull --ff-only --quiet >/dev/null 2>&1; then
    die "fast-forward pull failed; resolve diverging history manually"
  fi
  after=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD)

  if [ "$before" = "$after" ]; then
    ok "already at latest ($before)"
  else
    ok "updated $before -> $after"
  fi

  # Re-run the install path: refreshes symlink, regenerates MANIFEST, recompiles
  # bytecode. Idempotent regardless of whether code actually changed.
  install
}

# ---------------------------------------------------------------------------
# Snapshot / restore: cross-machine state portability for non-zerotrust
# presets. Delegates the heavy lifting to lib/snapshot.py; install.sh just
# resolves Python the same way runtime hooks do and forwards the path.
# ---------------------------------------------------------------------------

snapshot_state() {
  local out_path py_bin
  out_path="$1"
  [ -z "$out_path" ] && die "--snapshot needs an output path"
  py_bin="$(_resolve_python)"
  [ -z "$py_bin" ] && die "no usable python3 (need >= 3.12); see ./install.sh --verify"
  PYTHONPATH="$SCRIPT_DIR/lib" PRESENCE_STATE="$STATE_DIR" \
    "$py_bin" "$SCRIPT_DIR/lib/snapshot.py" snapshot "$out_path"
}

restore_state() {
  local in_path overwrite_flag py_bin
  in_path="$1"
  overwrite_flag="$2"
  [ -z "$in_path" ] && die "--restore needs an input path"
  py_bin="$(_resolve_python)"
  [ -z "$py_bin" ] && die "no usable python3 (need >= 3.12); see ./install.sh --verify"
  if [ "$overwrite_flag" = "--overwrite" ]; then
    PYTHONPATH="$SCRIPT_DIR/lib" PRESENCE_STATE="$STATE_DIR" \
      "$py_bin" "$SCRIPT_DIR/lib/snapshot.py" restore "$in_path" --overwrite
  else
    PYTHONPATH="$SCRIPT_DIR/lib" PRESENCE_STATE="$STATE_DIR" \
      "$py_bin" "$SCRIPT_DIR/lib/snapshot.py" restore "$in_path"
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

build_ext() {
  # Build the optional Rust extension. Two artifacts:
  #   1. presence-client (the daemon Unix-socket client; required for the
  #      v0.4.0 cold-hook latency speedup). Built with cargo.
  #   2. presence_ext Python wheel (libgit2 + native keychain bindings;
  #      secondary speedup on a few read paths). Built with maturin if
  #      available; skipped silently otherwise.
  info "building native Rust extension (presence-ext)..."
  if ! command -v cargo >/dev/null 2>&1; then
    die "cargo not found. Install Rust (https://rustup.rs/) and rerun --build-ext."
  fi
  if [ ! -d "$SCRIPT_DIR/ext" ]; then
    die "$SCRIPT_DIR/ext is missing. Rust extension source is not bundled with this checkout."
  fi

  local py_bin
  py_bin="$(_resolve_python)"
  [ -z "$py_bin" ] && die "no usable python3 found to build the extension; see ./install.sh --verify"

  # Step 1: presence-client (required for the daemon-path perf win).
  info "compiling presence-client (Rust client binary)..."
  if ! (cd "$SCRIPT_DIR/ext" && cargo build --release --bin presence-client --no-default-features); then
    warn "presence-client cargo build failed; hooks will fall back to direct python exec"
    return 0
  fi
  local client_bin="$SCRIPT_DIR/ext/target/release/presence-client"
  if [ -x "$client_bin" ]; then
    cp "$client_bin" "$SCRIPT_DIR/lib/presence-client"
    chmod 755 "$SCRIPT_DIR/lib/presence-client"
    ok "presence-client installed: $SCRIPT_DIR/lib/presence-client"
  else
    warn "expected $client_bin to exist after cargo build; skipping client install"
  fi

  # Step 2: presence_ext wheel (optional secondary speedup).
  info "compiling presence_ext wheel via maturin (optional)..."
  local venv_dir
  venv_dir=$(mktemp -d)
  if ! "$py_bin" -m venv "$venv_dir" >/dev/null 2>&1; then
    warn "could not create venv for maturin; skipping wheel build"
    rm -rf "$venv_dir"
    return 0
  fi
  if ! "$venv_dir/bin/pip" install --quiet maturin >/dev/null 2>&1; then
    warn "could not pip install maturin; skipping wheel build"
    rm -rf "$venv_dir"
    return 0
  fi
  if ! (cd "$SCRIPT_DIR/ext" && PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
        "$venv_dir/bin/maturin" build --release --out target/wheels >/dev/null 2>&1); then
    warn "maturin build failed; presence-client (above) is still installed"
    rm -rf "$venv_dir"
    return 0
  fi
  local wheel_file
  wheel_file=$(find "$SCRIPT_DIR/ext/target/wheels" -name '*.whl' -type f | head -n 1 || true)
  if [ -n "$wheel_file" ]; then
    "$venv_dir/bin/pip" install --quiet --target "$SCRIPT_DIR/lib" "$wheel_file" >/dev/null 2>&1 || true
    ok "presence_ext wheel installed: $wheel_file"
  fi
  rm -rf "$venv_dir"
}

download_ext() {
  # Pull pre-built presence-client from the latest GitHub Release matching
  # this host's platform. Skips if curl is missing or no asset matches.
  if ! command -v curl >/dev/null 2>&1; then
    die "curl not found; rerun with --build-ext (requires Rust toolchain) or install curl"
  fi

  local repo asset uname_s uname_m
  repo="sara-star-quant/presence"
  uname_s=$(uname -s)
  uname_m=$(uname -m)
  case "$uname_s/$uname_m" in
    Darwin/arm64)        asset="presence-client-macos-arm64" ;;
    Darwin/x86_64)       asset="presence-client-macos-x86_64" ;;
    Linux/x86_64)        asset="presence-client-linux-x86_64" ;;
    *) die "no pre-built presence-client for $uname_s/$uname_m; use --build-ext instead" ;;
  esac

  info "fetching $asset from latest release of $repo..."
  local url
  url="https://github.com/${repo}/releases/latest/download/${asset}"
  local target="$SCRIPT_DIR/lib/presence-client"
  if ! curl -fsSL --output "$target" "$url"; then
    die "could not download $asset from $url; verify a release exists with that asset, or use --build-ext"
  fi
  chmod 755 "$target"
  ok "presence-client downloaded: $target"
}

install() {
  info "presence installer"
  info "plugin source: $SCRIPT_DIR"
  info "claude home  : $CLAUDE_HOME"
  info "state dir    : $STATE_DIR"
  echo

  if ! check_python; then
    if [ "$BOOTSTRAP" = "1" ]; then
      bootstrap_python_via_uv || warn "bootstrap did not complete; install will continue but hooks remain inert until Python is fixed"
    else
      info "Python 3.12+ required. Install it yourself, or rerun with --bootstrap to auto-install via uv (single binary, no sudo, requires curl to https://astral.sh)."
    fi
  fi
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
  1. Run $SCRIPT_DIR/install.sh --verify to confirm everything works
     (no need to open Claude Code yet; verify checks symlink, Python, perms,
     manifest, and synthetically fires all 6 hooks)
  2. Restart Claude Code (or open a new session)
  3. Run /presence-status to confirm it is active
  4. Run /presence-doctor for the full diagnostic later
  5. To switch presets:    /presence-preset use solo-dev|team-oss|enterprise-strict|zerotrust
  6. To wipe state:        /presence-reset --all

The Zero-Trust preset's at-rest encryption (AES-GCM, key in OS keychain) is
opt-in via the cryptography library:
  pip install --user cryptography
Other presets and Zero-Trust controls (integrity check, redaction, gates,
audit log) are stdlib-only and require no extra install.

To update later:
  $SCRIPT_DIR/install.sh --update           (git pull + reinstall; refuses if dirty)

To uninstall:
  $SCRIPT_DIR/install.sh --uninstall          (preserves state)
  $SCRIPT_DIR/install.sh --uninstall --purge  (removes everything)
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing. We accept flags in any order so `--bootstrap install` and
# `install --bootstrap` and `--bootstrap` (default to install) all work.

SUBCOMMAND=""
SNAPSHOT_PATH=""
RESTORE_PATH=""
RESTORE_OVERWRITE=""
expect_path_for=""
for arg in "$@"; do
  if [ -n "$expect_path_for" ]; then
    case "$expect_path_for" in
      snapshot) SNAPSHOT_PATH="$arg" ;;
      restore)  RESTORE_PATH="$arg" ;;
    esac
    expect_path_for=""
    continue
  fi
  case "$arg" in
    --bootstrap)    BOOTSTRAP=1 ;;
    --json)         VERIFY_JSON=1 ;;
    --overwrite)    RESTORE_OVERWRITE="--overwrite" ;;
    --build-ext)    SUBCOMMAND="build_ext" ;;
    --download-ext) SUBCOMMAND="download_ext" ;;
    --snapshot)
      [ -z "$SUBCOMMAND" ] && SUBCOMMAND="--snapshot"
      expect_path_for="snapshot"
      ;;
    --restore)
      [ -z "$SUBCOMMAND" ] && SUBCOMMAND="--restore"
      expect_path_for="restore"
      ;;
    install|--update|update|--verify|verify|--uninstall|uninstall|-h|--help)
      [ -z "$SUBCOMMAND" ] && SUBCOMMAND="$arg" ;;
    --purge) ;;  # forwarded to uninstall
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done
[ -z "$SUBCOMMAND" ] && SUBCOMMAND="install"

case "$SUBCOMMAND" in
  install)               install ;;
  --update|update)       update ;;
  --verify|verify)       verify ;;
  build_ext)             build_ext ;;
  download_ext)          download_ext ;;
  --snapshot)            snapshot_state "$SNAPSHOT_PATH" ;;
  --restore)             restore_state "$RESTORE_PATH" "$RESTORE_OVERWRITE" ;;
  --uninstall|uninstall)
    purge_flag=""
    for arg in "$@"; do
      [ "$arg" = "--purge" ] && purge_flag="--purge"
    done
    if [ -n "$purge_flag" ]; then
      uninstall --purge
    else
      uninstall
    fi
    ;;
  -h|--help)
    cat <<EOF
presence installer

Usage:
  ./install.sh                          install (or refresh an existing install)
  ./install.sh --bootstrap              install AND auto-install Python 3.13 via uv
                                        if missing/old (opt-in network call to astral.sh)
  ./install.sh --verify                 full pre-Claude-Code health check (exits 0 if ready)
  ./install.sh --verify --json          same as --verify but emits a JSON blob
  ./install.sh --update                 git pull + re-install (refuses if dirty)
  ./install.sh --build-ext              build the optional Rust extension locally
                                        (needs cargo from https://rustup.rs/)
  ./install.sh --download-ext           download a pre-built Rust client binary from
                                        the latest GitHub Release (faster path; no Rust
                                        toolchain needed; macOS arm64/x86_64 + Linux x86_64)
  ./install.sh --snapshot <out.tar.gz>  back up state for cross-machine portability
                                        (refused under zerotrust; see issue #11)
  ./install.sh --restore <in.tar.gz>    restore state from a snapshot (refuses if state
                                        already exists; pass --overwrite to clobber)
  ./install.sh --uninstall              remove plugin symlink (state preserved)
  ./install.sh --uninstall --purge      remove plugin and wipe state
  ./install.sh --help                   this help

Environment:
  CLAUDE_HOME       (default: ~/.claude)
  PRESENCE_STATE    (default: \$CLAUDE_HOME/presence)
EOF
    ;;
esac
