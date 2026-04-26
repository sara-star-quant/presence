"""Secret redaction for any user-controllable strings before they hit logs/state.

Two levels:
- ``standard``: catches well-known token shapes (AWS, GitHub, Slack, Stripe, JWT, Bearer)
  and ``KEY=value`` env-style assignments where KEY hints at secret semantics.
- ``aggressive`` (Zero-Trust): the standard set + any 32+ char hex run, any 40+ char
  base64 run, and assignment-style for ANY uppercase-ish key. Will sometimes redact
  non-secrets; that is the intended trade-off.

Usage::

    from redact import redact_command, redact_text
    safe = redact_command(cmd, level="standard")

The replacement format is ``[REDACTED:<kind>]`` so downstream readers know what was
removed. Patterns and tests live alongside.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

REDACTION = "[REDACTED:{kind}]"

# (name, compiled pattern, replacement). Order matters; first match wins per char.
_STANDARD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws-temp-key", re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("github-pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-fine-grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("gitlab-pat", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe-live", re.compile(r"\b(?:sk|pk|rk)_live_[0-9a-zA-Z]{24,}\b")),
    ("stripe-test", re.compile(r"\b(?:sk|pk|rk)_test_[0-9a-zA-Z]{24,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{32,}\b")),
    ("openai-key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{40,}\b")),
    ("jwt", re.compile(r"\b(?:eyJ[A-Za-z0-9_-]{10,})\.(?:[A-Za-z0-9_-]{10,})\.(?:[A-Za-z0-9_-]{10,})\b")),
    ("bearer", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._\-+/=]{8,}")),
    ("basic-auth", re.compile(r"\b[Bb]asic\s+[A-Za-z0-9+/=]{12,}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----")),
    ("ssh-private", re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]*?-----END OPENSSH PRIVATE KEY-----")),
]

# Env-style assignment, standard set: KEY token suggests secrecy.
# Value can be bare (alphanumeric+symbols) or quoted (single/double).
_SECRET_KEY_HINT = re.compile(
    r"""(?ix)\b(
      (?:[A-Z][A-Z0-9_]*_)?(?:SECRET|TOKEN|PASSWORD|PASSWD|PWD|API[_-]?KEY|ACCESS[_-]?KEY|
      PRIVATE[_-]?KEY|AUTH|CREDENTIALS?|SESSION[_-]?KEY)
    )\s*[:=]\s*
    (?:"[^"]{1,}"|'[^']{1,}'|[A-Za-z0-9._\-+/=!@\#$%^&*~]{1,})
    """,
    re.VERBOSE,
)

# Aggressive extras
_HEX_BLOB = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_B64_BLOB = re.compile(r"\b[A-Za-z0-9+/=]{40,}\b")
# Aggressive mode redacts any uppercase env-style assignment, even short values.
# Trade-off: false positives like DEBUG=1 are intentional (the doc says so).
_ANY_UPPER_ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\s*=\s*([^\s'\"`]+)")


def _replace_with_kind(text: str, pattern: re.Pattern[str], kind: str) -> str:
    return pattern.sub(REDACTION.format(kind=kind), text)


def redact_text(text: str, level: str = "standard") -> str:
    """Return ``text`` with secrets replaced. Always returns a str; never raises."""
    if not text:
        return text
    out = text
    try:
        for kind, pat in _STANDARD_PATTERNS:
            out = _replace_with_kind(out, pat, kind)
        out = _SECRET_KEY_HINT.sub(lambda m: f"{m.group(1)}={REDACTION.format(kind='env-secret')}", out)
        if level == "aggressive":
            out = _replace_with_kind(out, _HEX_BLOB, "hex-blob")
            out = _replace_with_kind(out, _B64_BLOB, "b64-blob")
            out = _ANY_UPPER_ASSIGN.sub(lambda m: f"{m.group(1)}={REDACTION.format(kind='upper-assign')}", out)
    except re.error:
        return text
    return out


def redact_command(cmd: str, level: str = "standard") -> str:
    """Redact a shell command. Same as redact_text but kept for call-site clarity."""
    return redact_text(cmd, level=level)


def redact_iter(items: Iterable[str], level: str = "standard") -> list[str]:
    return [redact_text(s, level=level) for s in items]


__all__ = ["redact_text", "redact_command", "redact_iter", "REDACTION"]
