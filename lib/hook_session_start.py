"""SessionStart hook: inject living model + outcome digest + pending events + warning surfaces."""
from __future__ import annotations

import time

from _common import (
    atomic_write,
    emit_context,
    hook_input,
    project_dir,
    read_counter,
    reset_counter,
    safe_main,
    settings,
)
from events import drain_events, summarize_events
from model import read_model
from telemetry import scan_for_revert
from warnings_log import read_warnings


def _resolve_cwd(inp: dict) -> str:
    """Prefer hook-supplied cwd. Warn if absent and fall back to process cwd."""
    cwd = inp.get("cwd")
    if cwd:
        return str(cwd)
    import os

    from warnings_log import warn
    warn("hook_cwd_missing", "SessionStart hook input lacked 'cwd'; using process cwd")
    return os.getcwd()


def main() -> None:
    inp = hook_input()
    cfg = settings()
    cwd = _resolve_cwd(inp)

    parts: list[str] = []

    # 1. Surface accumulated errors/warnings; first thing the user sees, every session.
    err = read_counter("error")
    warn = read_counter("warning")
    if err or warn:
        msg = "=== presence: status ==="
        if err:
            msg += f"\n  [!] {err} hook error(s) since last session. See ~/.claude/presence/logs/errors.log"
        if warn:
            recent = read_warnings(limit=3)
            cats = ", ".join(sorted({w.get("category", "?") for w in recent}))
            msg += f"\n  [!] {warn} new warning(s) since last session ({cats}). Run /presence-doctor for details."
        parts.append(msg)
        reset_counter("error")
        reset_counter("warning")

    # 2. Living project model
    if (cfg.get("model") or {}).get("enabled", True):
        max_tokens = int((cfg.get("model") or {}).get("max_tokens", 4000))
        model_text = read_model(cwd, max_chars=max_tokens * 4)
        if model_text:
            parts.append("=== presence: living project model ===\n" + model_text)

    # 3. Telemetry digest: reverts since last seen
    last_seen_path = project_dir(cwd) / "last_seen"
    last_seen = 0
    if last_seen_path.exists():
        try:
            last_seen = int(last_seen_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            from warnings_log import warn
            warn(
                "last_seen_corrupt",
                f"could not parse {last_seen_path}: {exc}; treating as first visit",
                path=str(last_seen_path),
            )
            last_seen = 0

    if (cfg.get("telemetry") or {}).get("enabled", True) and last_seen:
        findings = scan_for_revert(cwd, last_seen)
        if findings:
            lines = [
                "=== presence: outcome telemetry ===",
                f"Since {time.strftime('%Y-%m-%d %H:%M', time.localtime(last_seen))}, "
                f"{len(findings)} of your tracked commits were reverted:",
            ]
            for f in findings[:5]:
                lines.append(f"  - {f['tracked'][:8]} reverted by {f['by'][:8]}: {f['message'][:80]}")
            if len(findings) > 5:
                lines.append(f"  (+{len(findings) - 5} more; /presence-status to see all)")
            parts.append("\n".join(lines))

    atomic_write(last_seen_path, str(int(time.time())) + "\n")

    # 4. Pending events digest
    if (cfg.get("events") or {}).get("enabled", True):
        events = drain_events(cwd)
        digest = summarize_events(events)
        if digest:
            parts.append("=== presence: events since last session ===\n" + digest)

    if parts:
        emit_context("SessionStart", "\n\n".join(parts))


safe_main(main)
