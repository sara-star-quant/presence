"""SessionStart hook: inject living model + outcome digest + pending events + warning surfaces."""
from __future__ import annotations

import asyncio
import os
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
from telemetry import async_scan_for_revert
from warnings_log import read_warnings


def _resolve_cwd(inp: dict) -> str:
    """Prefer hook-supplied cwd. Warn if absent and fall back to process cwd."""
    cwd = inp.get("cwd")
    if cwd:
        return str(cwd)
    from warnings_log import warn
    warn("hook_cwd_missing", "SessionStart hook input lacked 'cwd'; using process cwd")
    return os.getcwd()


async def gather_warnings() -> str:
    """Build the warnings/errors banner. Pure: does not reset the counters.
    Counter reset is owned by ``async_main`` and only happens after a successful emit.
    """
    err = read_counter("error")
    warn_count = read_counter("warning")
    if not (err or warn_count):
        return ""

    parts = ["<presence_status>"]
    if err:
        parts.append(f"  [!] {err} hook error(s) since last session. See ~/.claude/presence/logs/errors.log")
    if warn_count:
        recent = read_warnings(limit=3)
        cats = ", ".join(sorted({w.get("category", "?") for w in recent}))
        parts.append(f"  [!] {warn_count} new warning(s) since last session ({cats}). Run /presence-doctor for details.")
    parts.append("</presence_status>")
    return "\n".join(parts)


async def gather_model(cwd: str, cfg: dict) -> str:
    if not (cfg.get("model") or {}).get("enabled", True):
        return ""
    max_tokens = int((cfg.get("model") or {}).get("max_tokens", 4000))
    # run sync model reading in executor to not block asyncio thread
    model_text = await asyncio.to_thread(read_model, cwd, max_chars=max_tokens * 4)
    if model_text:
        return f"<project_model>\n{model_text}\n</project_model>"
    return ""


async def gather_telemetry(cwd: str, cfg: dict) -> str:
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

    out = ""
    if (cfg.get("telemetry") or {}).get("enabled", True) and last_seen:
        findings = await async_scan_for_revert(cwd, last_seen)
        if findings:
            lines = [
                "<telemetry_digest>",
                f"Since {time.strftime('%Y-%m-%d %H:%M', time.localtime(last_seen))}, "
                f"{len(findings)} of your tracked commits were reverted:",
            ]
            for f in findings[:5]:
                lines.append(f"  - {f['tracked'][:8]} reverted by {f['by'][:8]}: {f['message'][:80]}")
            if len(findings) > 5:
                lines.append(f"  (+{len(findings) - 5} more; /presence-status to see all)")
            lines.append("</telemetry_digest>")
            out = "\n".join(lines)

    await asyncio.to_thread(atomic_write, last_seen_path, str(int(time.time())) + "\n")
    return out


async def gather_events(cwd: str, cfg: dict) -> str:
    if not (cfg.get("events") or {}).get("enabled", True):
        return ""
    events = await asyncio.to_thread(drain_events, cwd)
    digest = summarize_events(events)
    if digest:
        return f"<recent_events>\n{digest}\n</recent_events>"
    return ""


async def async_main():
    inp = hook_input()
    cfg = settings()
    cwd = _resolve_cwd(inp)

    # Execute all I/O bound tasks concurrently
    warnings_text, model_text, telemetry_text, events_text = await asyncio.gather(
        gather_warnings(),
        gather_model(cwd, cfg),
        gather_telemetry(cwd, cfg),
        gather_events(cwd, cfg),
    )
    parts = [t for t in (warnings_text, model_text, telemetry_text, events_text) if t]

    if parts:
        context = "<presence_context>\n" + "\n\n".join(parts) + "\n</presence_context>"
        emit_context("SessionStart", context)
        # Reset counters AFTER successful emit, and only if we surfaced them.
        # If emit_context raises (it shouldn't; it's stdout-only), counters preserve.
        if warnings_text:
            reset_counter("error")
            reset_counter("warning")


def main():
    # async_main is wrapped here so safe_main (the outermost guard) catches
    # any exception including those from inside the asyncio loop.
    # asyncio.run will close the loop in its finally block before re-raising,
    # so safe_main sees a normal exception and logs it cleanly.
    asyncio.run(async_main())


if __name__ == "__main__":
    safe_main(main)
