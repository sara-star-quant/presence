"""Optional webhook notification on confidence-gate verdicts.

Disabled by default: does nothing unless a user opts in locally via their own
settings.json overrides (see below). This repo ships no webhook URL and no
notify config -- the example below is a placeholder, not a configured
endpoint.

Fires from record_confidence() in telemetry.py, which today has exactly one
production call site: hook_stop.py, line 120. Silent on any failure, a
notification must never affect the gate's own decision or block a commit --
including a slow or dead webhook: the actual HTTP POST runs in a fully
detached subprocess (see _dispatch/_send_from_stdin below), never inline in
the Stop hook, matching the one other network call site in this codebase
(update_check.maybe_refresh, wrapped in asyncio.to_thread + a watchdog so an
unresponsive socket can't stall a hook).

Config lives under settings.json's dotted-path "overrides" (see
docs/recipes.md; every real config example in this repo uses this shape --
a bare top-level "notify" key would be silently ignored by settings(),
which only reads "preset" and "overrides"):

    {
      "overrides": {
        "notify.enabled": true,
        "notify.webhook_url": "https://hooks.zapier.com/hooks/catch/xxxx/xxxx/"
      }
    }

The webhook URL lives only in settings.json (~/.claude/presence/settings.json),
never in this file, never in telemetry.jsonl, never committed. redact.py's
secret patterns target known token shapes (Slack API tokens, AWS keys,
etc.), a Zapier catch-hook URL doesn't match any of them, so presence's own
redaction will not protect it if it ends up somewhere it shouldn't.

Payload shape, matches what record_confidence() actually receives, no
numeric confidence score exists anywhere in this codebase:
    claim           str   ("unhedged_success", today the only value used)
    verified        bool
    final_excerpt   str   (first 200 chars of the assistant's final message,
                           run through redact_text() before it ever leaves
                           the machine -- see notify_confidence below)
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request

from _common import now_ts, settings


def notify_confidence(claim: str, verified: bool, **details) -> None:
    cfg = settings()
    # network.egress_allowed: false (the zerotrust posture) hard-disables every
    # network feature, the same two-layer gate update_check.is_enabled() uses --
    # this must be checked before notify.enabled, not instead of it, so a stray
    # `notify.enabled: true` override under zerotrust still can't reach the network.
    if (cfg.get("network") or {}).get("egress_allowed", True) is False:
        return
    notify_cfg = cfg.get("notify") or {}
    if not notify_cfg.get("enabled"):
        return
    url = notify_cfg.get("webhook_url")
    if not url:
        return

    from redact import redact_text
    redact_cfg = cfg.get("redact") or {}
    level = redact_cfg.get("level") or "standard"
    profiles = redact_cfg.get("profiles") or []

    def _clean(v):
        return redact_text(v, level=level, profiles=profiles) if isinstance(v, str) else v

    payload = {
        "claim": claim,
        "verdict": "pass" if verified else "fail",
        "verified": bool(verified),
        "timestamp": now_ts(),
        **{k: _clean(v) for k, v in details.items() if isinstance(v, (str, int, float, bool))},
    }
    _dispatch(url, payload)


def _dispatch(url: str, payload: dict) -> None:
    """Hand the POST off to a fully detached subprocess (setsid'd, no stdout/
    stderr) and return immediately -- a slow or dead webhook must never make
    the calling hook (Stop) wait. The payload goes over the child's stdin,
    not argv or an env var, so it never shows up in a `ps`/argv listing.
    Best-effort: any failure to even spawn the child is swallowed, same
    silent-on-failure contract as the network call itself.
    """
    try:
        proc = subprocess.Popen(
            [sys.executable, __file__, "--send", url],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(payload).encode("utf-8"))
        proc.stdin.close()
        # Reap on a daemon thread instead of leaving it to Popen.__del__: a
        # still-running child at garbage-collection time triggers a
        # ResourceWarning/finalizer error. The thread just blocks on wait(),
        # it does not make the caller wait.
        threading.Thread(target=proc.wait, daemon=True).start()
    except OSError:
        pass  # a notification failure must never affect the gate itself


def _send_from_stdin(url: str) -> None:
    """Detached-child entry point: read the payload from stdin and POST it.
    Runs outside the hook process (see _dispatch), so this function's own
    network timeout can never block Claude's turn.
    """
    try:
        payload = sys.stdin.buffer.read()
    except OSError:
        return
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0):
            pass
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        pass  # a notification failure must never affect the gate itself


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--send":
        _send_from_stdin(sys.argv[2])
