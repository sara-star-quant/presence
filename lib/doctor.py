"""/presence-doctor support: diagnostic snapshot of presence's local state."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from _common import (
    PLUGIN_ROOT,
    logs_dir,
    read_counter,
    repo_id,
    state_dir,
)
from events import event_path, peek_events
from model import model_size
from telemetry import claims_path, confidence_path, outcomes_path
from warnings_log import read_warnings

from presets import active_preset_name, list_presets


def python_version_ok() -> tuple[bool, str]:
    v = sys.version_info
    return ((v.major, v.minor) >= (3, 12), f"{v.major}.{v.minor}.{v.micro}")


def has_git() -> bool:
    return shutil.which("git") is not None


def integrity_status() -> str:
    try:
        from integrity import load_manifest, verify_manifest

        if load_manifest() is None:
            return "no MANIFEST.lock present (skipped)"
        missing, mismatched, _extra = verify_manifest()
        if missing or mismatched:
            return f"FAILED: {len(missing)} missing, {len(mismatched)} mismatched"
        return "OK"
    except Exception as exc:  # noqa: BLE001
        return f"check error: {exc}"


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _pinned_python() -> str | None:
    """Return the contents of $state_dir/.python_bin if the file exists.

    This is what install.sh --bootstrap writes when it auto-installs a Python
    via uv. The runtime hook wrapper (_common.sh::_presence_pinned_python)
    honors the same marker; surfacing it here lets /presence-doctor confirm
    which interpreter hooks will actually use.
    """
    p = state_dir() / ".python_bin"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _redact_summary() -> dict:
    """Surface active redaction config so regulated-workload users can verify it.

    Returns level + configured profile names, plus per-profile load status so a
    typo'd or broken profile shows up here instead of failing silently.
    """
    from _common import settings
    from redact import _load_profile, list_available_profiles
    cfg = (settings().get("redact") or {})
    level = cfg.get("level") or "standard"
    raw = cfg.get("profiles") or []
    names = [str(p) for p in raw if isinstance(p, str)]
    statuses = []
    for n in names:
        r = _load_profile(n)
        statuses.append({
            "name": n,
            "status": r.status,
            "patterns": len(r.patterns),
            "last_reviewed": r.last_reviewed,
            "error": r.error,
        })
    return {
        "level": level,
        "profiles": names,
        "profile_statuses": statuses,
        "available_profiles": [n for n, _ in list_available_profiles()],
    }


def _version_observability() -> dict:
    """Plugin / ext crate / min-required ext version cross-check for the doctor.

    Returns a dict with plugin_version (lib/__init__.py.__version__),
    ext_version (presence_ext.__version__ or None when the wheel is absent),
    min_ext_version (lib/__init__.py._MIN_EXT_VERSION), ext_compat_ok, and
    ext_compat_message. Reuses lib/_common.check_ext_compat which is fail-open
    by design so a broken ext never breaks the doctor.
    """
    from __init__ import _MIN_EXT_VERSION, __version__
    from _common import check_ext_compat
    ok, ext_ver, msg = check_ext_compat()
    return {
        "plugin_version": __version__,
        "ext_version": ext_ver,
        "min_ext_version": _MIN_EXT_VERSION,
        "ext_compat_ok": ok,
        "ext_compat_message": msg,
    }


def _update_check_block() -> dict:
    """Read-only update-check status. Reads cfg via settings() so report() does
    not need a new parameter; matches the pattern used by active_preset_name()
    and the redact helpers. Never makes a network call — the SessionStart
    background gather and `lib/doctor.py --refresh` are the only callers
    that touch the network.
    """
    from __init__ import __version__
    from _common import settings
    from update_check import status
    return status(settings(), current_tag=f"v{__version__}")


def _format_age(seconds: int) -> str:
    """Compact age string for the update-check render line: 'Nm', 'Nh', 'Nd'."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _render_update_line(uc: dict) -> str:
    """One column-aligned line summarising the update-check state for `render()`.
    All six possible states are handled; unknown future states fall through to a
    bare 'latest       : (unknown)' rather than KeyError.
    """
    state = uc.get("state")
    if state == "disabled":
        return "latest       : (update check disabled; enable via update_check.enabled in settings)"
    if state == "zerotrust":
        return "latest       : (disabled under zerotrust)"
    if state == "no_cache":
        return "latest       : (check pending; will refresh next session)"
    if state == "fresh":
        latest = uc.get("latest_tag", "?")
        current = uc.get("current_tag", "?")
        age = _format_age(int(uc.get("age_seconds", 0)))
        version_part = "(up to date)" if latest == current else f"(you have {current})"
        return f"latest       : {latest} {version_part} [checked {age} ago]"
    if state == "stale":
        latest = uc.get("latest_tag", "?")
        current = uc.get("current_tag", "?")
        age = _format_age(int(uc.get("age_seconds", 0)))
        version_part = "(up to date)" if latest == current else f"(you have {current})"
        return f"latest       : {latest} {version_part} [STALE: checked {age} ago]"
    return "latest       : (unknown)"


def report(cwd: str | None = None) -> dict:
    cwd = cwd or "."
    rid = repo_id(cwd)
    py_ok, py_ver = python_version_ok()
    return {
        "presence_root": str(PLUGIN_ROOT),
        "state_dir": str(state_dir()),
        "active_preset": active_preset_name(),
        "available_presets": list_presets(),
        "current_repo_id": rid,
        "errors_since_last_session": read_counter("error"),
        "warnings_since_last_session": read_counter("warning"),
        "recent_warnings": read_warnings(limit=10),
        "model_size_bytes": model_size(cwd),
        "pending_events_bytes": _file_size(event_path(cwd)),
        "pending_event_count": len(peek_events(cwd)),
        "claims_bytes": _file_size(claims_path()),
        "outcomes_bytes": _file_size(outcomes_path()),
        "confidence_bytes": _file_size(confidence_path()),
        "errors_log_bytes": _file_size(logs_dir() / "errors.log"),
        "warnings_log_bytes": _file_size(logs_dir() / "warnings.log"),
        "python_ok": py_ok,
        "python_version": py_ver,
        "pinned_python": _pinned_python(),
        "git_available": has_git(),
        "integrity": integrity_status(),
        "redact": _redact_summary(),
        "version_observability": _version_observability(),
        "update_check": _update_check_block(),
    }


def render(rep: dict) -> str:
    redact = rep.get("redact") or {}
    redact_profiles = redact.get("profiles") or []
    if redact_profiles:
        prof_lines = []
        for s in redact.get("profile_statuses") or []:
            tag = "OK" if s["status"] == "ok" else f"!! {s['status']}"
            extra = f" ({s['error']})" if s.get("error") else ""
            prof_lines.append(
                f"               - {s['name']:<16} {tag}  patterns={s['patterns']}  "
                f"reviewed={s.get('last_reviewed') or '(none)'}{extra}"
            )
        profiles_block = "\n".join(prof_lines)
    else:
        profiles_block = "               (none beyond level)"

    vo = rep.get("version_observability") or {}
    if vo.get("ext_version") is None:
        ext_line = "ext (rust)   : not installed (using subprocess fallback)"
    elif vo.get("ext_compat_ok"):
        ext_line = f"ext (rust)   : {vo['ext_version']} (>= {vo['min_ext_version']}) OK"
    else:
        ext_line = f"ext (rust)   : {vo['ext_version']} STALE: {vo.get('ext_compat_message', '')}"

    update_line = _render_update_line(rep.get("update_check") or {})

    lines = [
        "presence: doctor report",
        "-" * 40,
        f"plugin       : v{vo.get('plugin_version', '?')}",
        ext_line,
        update_line,
        f"plugin root  : {rep['presence_root']}",
        f"state dir    : {rep['state_dir']}",
        f"active preset: {rep['active_preset']}",
        f"presets      : {', '.join(rep['available_presets']) or '(none)'}",
        f"repo id      : {rep['current_repo_id']}",
        "",
        f"python       : {rep['python_version']} {'OK' if rep['python_ok'] else 'FAIL (need 3.12+)'}",
        f"pinned python: {rep['pinned_python'] or '(none; using PATH python3)'}",
        f"git on PATH  : {'OK' if rep['git_available'] else 'FAIL (telemetry disabled)'}",
        f"integrity    : {rep['integrity']}",
        "",
        f"redact level : {redact.get('level', 'standard')}",
        "redact profiles:",
        profiles_block,
        "",
        f"errors since last session   : {rep['errors_since_last_session']}",
        f"warnings since last session : {rep['warnings_since_last_session']}",
        "",
        "state sizes",
        f"  model.md            : {rep['model_size_bytes']:>10} bytes",
        f"  pending events      : {rep['pending_events_bytes']:>10} bytes ({rep['pending_event_count']} entries)",
        f"  telemetry/claims    : {rep['claims_bytes']:>10} bytes",
        f"  telemetry/outcomes  : {rep['outcomes_bytes']:>10} bytes",
        f"  telemetry/confidence: {rep['confidence_bytes']:>10} bytes",
        f"  logs/errors         : {rep['errors_log_bytes']:>10} bytes",
        f"  logs/warnings       : {rep['warnings_log_bytes']:>10} bytes",
    ]
    if rep["recent_warnings"]:
        lines.append("")
        lines.append("recent warnings (newest last):")
        for w in rep["recent_warnings"]:
            lines.append(f"  [{w.get('category', '?'):30}] {w.get('message', '')[:80]}")
            fix = w.get("fix")
            if fix:
                lines.append(f"    fix: {fix}")
    return "\n".join(lines)


def fix() -> tuple[list[str], list[str]]:
    """Auto-correct recoverable issues. Returns (actions_taken, issues_remaining).

    Safe fixes only - never touches things that need user judgment (settings.json
    corruption, missing lib/ files, encryption key mismatches):
      - state directory or file perms drifted from 0o700/0o600
      - MANIFEST.lock missing OR mismatched (regenerate; the tampered case is
        not distinguishable from "user is on a fresh checkout that hasn't run
        --write yet", so we always regenerate when --fix is asked)
      - .integrity-blocked marker present but the regenerated manifest verifies
    """
    import os
    import stat as stat_mod

    actions: list[str] = []
    remaining: list[str] = []

    # 1. Perms drift on state dir + everything under it.
    sd = state_dir()
    try:
        cur = stat_mod.S_IMODE(sd.stat().st_mode)
        if cur != 0o700:
            sd.chmod(0o700)
            actions.append(f"chmod 0o700 {sd}")
    except OSError as exc:
        remaining.append(f"could not chmod {sd}: {exc}")

    for root, dirs, files in os.walk(sd):
        for d in dirs:
            p = Path(root) / d
            try:
                cur = stat_mod.S_IMODE(p.stat().st_mode)
                if cur != 0o700:
                    p.chmod(0o700)
                    actions.append(f"chmod 0o700 {p}")
            except OSError:
                pass
        for f in files:
            p = Path(root) / f
            try:
                cur = stat_mod.S_IMODE(p.stat().st_mode)
                if cur != 0o600:
                    p.chmod(0o600)
                    actions.append(f"chmod 0o600 {p}")
            except OSError:
                pass

    # 2. Manifest: regenerate ONLY when missing. A mismatched manifest is
    # ambiguous (could be local edits OR tampering); silently regenerating
    # would mask the tampering case under zerotrust. The user has to
    # investigate and run `python3 lib/integrity.py --write` themselves once
    # they've confirmed the files are intact.
    try:
        from integrity import load_manifest, write_manifest
        if load_manifest() is None:
            target = write_manifest()
            actions.append(f"regenerated missing {target}")
        else:
            from integrity import verify_manifest
            missing, mismatched, _extra = verify_manifest()
            if missing or mismatched:
                remaining.append(
                    f"MANIFEST.lock mismatched ({len(missing)} missing, {len(mismatched)} mismatched); "
                    "investigate then run `python3 lib/integrity.py --write` if files are intact"
                )
    except Exception as exc:  # noqa: BLE001
        remaining.append(f"could not check/regenerate MANIFEST.lock: {exc}")

    # 3. Stale .integrity-blocked: clear if manifest now verifies.
    try:
        from _common import clear_integrity_block, integrity_block_path
        from integrity import integrity_ok
        bp = integrity_block_path()
        if bp.exists() and integrity_ok():
            clear_integrity_block()
            actions.append(f"cleared stale {bp}")
    except Exception as exc:  # noqa: BLE001
        remaining.append(f"could not check/clear .integrity-blocked: {exc}")

    return actions, remaining


def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="presence diagnostic report")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    ap.add_argument("--cwd", default=".", help="project directory to inspect")
    ap.add_argument("--fix", action="store_true",
                    help="auto-correct recoverable issues (perm drift, missing manifest, stale block marker)")
    ap.add_argument("--refresh", action="store_true",
                    help="force a synchronous update-check network call (bypasses cache TTL)")
    args = ap.parse_args()
    if args.refresh:
        from _common import settings
        from update_check import force_refresh, is_enabled
        if not is_enabled(settings()):
            print("update_check disabled (or zerotrust active); not refreshing")
            return 1
        ok, msg = force_refresh()
        print(msg)
        return 0 if ok else 1
    if args.fix:
        actions, remaining = fix()
        if args.json:
            print(json.dumps({"actions": actions, "remaining": remaining}, indent=2))
        else:
            if actions:
                print("presence: doctor --fix")
                for a in actions:
                    print(f"  fixed: {a}")
            else:
                print("presence: doctor --fix (nothing to do)")
            if remaining:
                print("\nstill needs attention:")
                for r in remaining:
                    print(f"  - {r}")
        return 1 if remaining else 0
    rep = report(args.cwd)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(render(rep))
    return 0


def zerotrust_report() -> list[str]:
    """Return a list of one-line status entries focused on Zero-Trust controls."""
    from presets import active_preset_name

    lines = []
    active = active_preset_name()
    lines.append(f"active preset       : {active}{' (ZT controls active)' if active == 'zerotrust' else ' (ZT controls INACTIVE; switch with /presence-preset use zerotrust)'}")

    # Plugin file integrity
    integ = integrity_status()
    lines.append(f"plugin integrity    : {integ}")

    # State at rest encryption
    try:
        from crypto import is_available as crypto_available
        from crypto import keychain_backend
        if crypto_available():
            backend = keychain_backend()
            lines.append(f"crypto available    : OK (cryptography lib + {backend} keychain)")
        else:
            lines.append("crypto available    : FAIL (install cryptography or set up keychain backend)")
    except ImportError:
        lines.append("crypto available    : FAIL (cryptography lib not importable)")

    # Audit log chain
    try:
        from audit import verify_chain
        chain = verify_chain()
        if not chain["exists"]:
            lines.append("audit chain         : (no audit log yet; will populate on first ZT-relevant event)")
        elif chain["ok"]:
            lines.append(f"audit chain         : OK ({chain['lines']} line(s) verified)")
        else:
            lines.append(
                f"audit chain         : FAIL ({len(chain['tampered'])} tampered, "
                f"{len(chain['broken_link'])} broken-link, {len(chain['corrupt'])} corrupt)"
            )
    except Exception as exc:  # noqa: BLE001
        lines.append(f"audit chain         : check error: {exc}")

    # Settings immutability + unlock state
    try:
        from unlock import is_immutable, is_unlocked
        if is_immutable():
            unlocked = is_unlocked()
            lines.append(
                f"settings immutable  : ON ({'currently UNLOCKED' if unlocked else 'locked'})"
            )
        else:
            lines.append("settings immutable  : OFF (active preset does not request immutability)")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"settings immutable  : check error: {exc}")

    # Network egress
    lines.append("network egress      : OK (presence makes no outbound calls in v0.2)")

    # State permissions
    try:
        import stat
        s = state_dir().stat()
        mode = stat.S_IMODE(s.st_mode)
        lines.append(f"state perms         : {'OK' if mode == 0o700 else f'FAIL (got 0o{mode:03o}, want 0o700)'}")
    except OSError as exc:
        lines.append(f"state perms         : check error: {exc}")

    return lines


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = ["report", "render", "zerotrust_report"]
