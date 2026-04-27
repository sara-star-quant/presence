"""Secret redaction for any user-controllable strings before they hit logs/state.

Two levels:
- ``standard``: catches well-known token shapes (AWS, GitHub, Slack, Stripe, JWT, Bearer)
  and ``KEY=value`` env-style assignments where KEY hints at secret semantics.
- ``aggressive`` (Zero-Trust): the standard set + any 32+ char hex run, any 40+ char
  base64 run, and assignment-style for ANY uppercase-ish key. Will sometimes redact
  non-secrets; that is the intended trade-off.

Composable redaction profiles (v0.5.0+) live under ``presets/redaction/`` and add
jurisdiction-specific patterns (PII-EU, PII-US, PCI-DSS, ...). Pass ``profiles=``
to opt in. Each pattern can declare an optional ``validator`` (e.g. ``luhn``) that
gates the redaction after the regex matches; the registry is in ``_VALIDATORS``.

Usage::

    from redact import redact_command, redact_text
    safe = redact_command(cmd, level="standard")
    safer = redact_text(text, level="standard", profiles=["pii-eu", "pci-dss"])

The replacement format is ``[REDACTED:<kind>]`` so downstream readers know what was
removed. Patterns and tests live alongside.
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

REDACTION = "[REDACTED:{kind}]"

# Profile schema version this build of presence understands. Profile files
# declaring a higher version load in compatibility mode (patterns still apply;
# unknown top-level keys ignored).
SCHEMA_VERSION = 1

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


# Validator registry: pluggable post-match checks for structured patterns
# (Luhn for credit cards, mod-97 for IBANs in a future profile, ISIN check
# digits, etc.). A pattern with ``validator: "luhn"`` matches the regex AND
# must pass the registered callable on the matched text to be redacted.
def _check_luhn(s: str) -> bool:
    """Standard mod-10 (Luhn) check on the digits in ``s``.

    Strips non-digit characters first since PANs commonly appear with spaces or
    dashes inside the matched span.
    """
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    return total % 10 == 0


_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "luhn": _check_luhn,
}


class ProfilePattern(NamedTuple):
    kind: str
    pattern: re.Pattern[str]
    validator: str | None  # key into _VALIDATORS, or None for regex-only


class ProfileLoadResult(NamedTuple):
    name: str
    status: str  # ok | not_found | parse_error | compile_error | unknown_validator | partial
    error: str | None  # human-readable detail when status != ok
    patterns: list[ProfilePattern]
    schema_version: int | None
    last_reviewed: str | None
    description: str | None
    disclaimer: str | None
    source_path: Path | None


_PROFILE_CACHE: dict[str, ProfileLoadResult] = {}


def _profile_search_paths(name: str) -> list[Path]:
    """User override first, built-in second.

    Lazy import of ``_common`` so this module is usable in contexts where the
    state directory is not yet initialized (CLI --list-profiles on a fresh
    machine, for instance).
    """
    from _common import PLUGIN_ROOT, state_dir
    return [
        state_dir() / "presets" / "redaction" / f"{name}.json",
        PLUGIN_ROOT / "presets" / "redaction" / f"{name}.json",
    ]


def _load_profile(name: str) -> ProfileLoadResult:
    """Load a profile by name (process-cached). Failures return an empty pattern list."""
    cached = _PROFILE_CACHE.get(name)
    if cached is not None:
        return cached

    found_path: Path | None = None
    for candidate in _profile_search_paths(name):
        if candidate.exists():
            found_path = candidate
            break
    if found_path is None:
        result = ProfileLoadResult(
            name=name, status="not_found",
            error=f"profile '{name}' not found in user or built-in redaction paths",
            patterns=[], schema_version=None, last_reviewed=None,
            description=None, disclaimer=None, source_path=None,
        )
        _PROFILE_CACHE[name] = result
        return result

    try:
        data = json.loads(found_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = ProfileLoadResult(
            name=name, status="parse_error",
            error=f"{found_path}: {exc}",
            patterns=[], schema_version=None, last_reviewed=None,
            description=None, disclaimer=None, source_path=found_path,
        )
        _PROFILE_CACHE[name] = result
        return result

    if not isinstance(data, dict):
        result = ProfileLoadResult(
            name=name, status="parse_error",
            error=f"{found_path}: top-level JSON must be an object",
            patterns=[], schema_version=None, last_reviewed=None,
            description=None, disclaimer=None, source_path=found_path,
        )
        _PROFILE_CACHE[name] = result
        return result

    raw_patterns = data.get("patterns") if isinstance(data.get("patterns"), list) else []
    patterns: list[ProfilePattern] = []
    issues: list[str] = []
    for i, entry in enumerate(raw_patterns):
        if not isinstance(entry, dict):
            issues.append(f"pattern[{i}]: not an object")
            continue
        kind = entry.get("kind") or entry.get("name") or f"unknown-{i}"
        pat_src = entry.get("pattern")
        validator = entry.get("validator")
        if not isinstance(pat_src, str):
            issues.append(f"pattern '{kind}': missing 'pattern' field")
            continue
        try:
            compiled = re.compile(pat_src)
        except re.error as exc:
            issues.append(f"pattern '{kind}': regex compile failed: {exc}")
            continue
        if validator is not None and validator not in _VALIDATORS:
            issues.append(f"pattern '{kind}': unknown validator '{validator}'")
            continue
        patterns.append(ProfilePattern(kind=str(kind), pattern=compiled, validator=validator))

    schema_version_raw = data.get("_schema_version")
    schema_version = schema_version_raw if isinstance(schema_version_raw, int) else None
    compat_warning: str | None = None
    if isinstance(schema_version, int) and schema_version > SCHEMA_VERSION:
        compat_warning = (
            f"schema_version={schema_version} > supported {SCHEMA_VERSION}; "
            "loading in compatibility mode (unknown keys ignored)"
        )

    if patterns and not issues:
        status = "ok"
        error = compat_warning
    elif patterns and issues:
        status = "partial"
        msg = "; ".join(issues)
        error = f"{compat_warning}; {msg}" if compat_warning else msg
    elif not patterns and issues:
        if any("regex compile" in e for e in issues):
            status = "compile_error"
        elif any("unknown validator" in e for e in issues):
            status = "unknown_validator"
        else:
            status = "parse_error"
        msg = "; ".join(issues)
        error = f"{compat_warning}; {msg}" if compat_warning else msg
    else:
        # No patterns, no errors. Empty profile - treat as ok.
        status = "ok"
        error = compat_warning

    result = ProfileLoadResult(
        name=name,
        status=status,
        error=error,
        patterns=patterns,
        schema_version=schema_version,
        last_reviewed=data.get("_last_reviewed") if isinstance(data.get("_last_reviewed"), str) else None,
        description=data.get("_description") if isinstance(data.get("_description"), str) else None,
        disclaimer=data.get("_disclaimer") if isinstance(data.get("_disclaimer"), str) else None,
        source_path=found_path,
    )
    _PROFILE_CACHE[name] = result
    return result


def _clear_profile_cache() -> None:
    """Test hook: drop the process-wide profile cache."""
    _PROFILE_CACHE.clear()


def _replace_with_kind(text: str, pattern: re.Pattern[str], kind: str) -> str:
    return pattern.sub(REDACTION.format(kind=kind), text)


def _apply_profile_pattern(text: str, pp: ProfilePattern) -> str:
    if pp.validator is None:
        return pp.pattern.sub(REDACTION.format(kind=pp.kind), text)
    validator_fn = _VALIDATORS[pp.validator]  # presence checked at load
    replacement = REDACTION.format(kind=pp.kind)

    def _sub(m: re.Match[str]) -> str:
        return replacement if validator_fn(m.group(0)) else m.group(0)

    return pp.pattern.sub(_sub, text)


def redact_text(text: str, level: str = "standard", profiles: list[str] | None = None) -> str:
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
        if profiles:
            for prof_name in profiles:
                result = _load_profile(prof_name)
                for pp in result.patterns:
                    out = _apply_profile_pattern(out, pp)
    except re.error:
        return text
    return out


def redact_command(cmd: str, level: str = "standard", profiles: list[str] | None = None) -> str:
    """Redact a shell command. Same as redact_text but kept for call-site clarity."""
    return redact_text(cmd, level=level, profiles=profiles)


def redact_iter(items: Iterable[str], level: str = "standard", profiles: list[str] | None = None) -> list[str]:
    return [redact_text(s, level=level, profiles=profiles) for s in items]


def list_available_profiles() -> list[tuple[str, Path]]:
    """Return ``(name, path)`` for every discoverable profile.

    User-override profiles shadow built-ins of the same name; the override path
    wins in the returned list.
    """
    from _common import PLUGIN_ROOT, state_dir
    seen: dict[str, Path] = {}
    for root in (state_dir() / "presets" / "redaction", PLUGIN_ROOT / "presets" / "redaction"):
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.json")):
            seen.setdefault(p.stem, p)
    return sorted(seen.items())


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="redact",
        description="presence redaction profile inspector / tester (read-only).",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list-profiles", action="store_true",
                   help="list all discoverable redaction profiles and their load status")
    g.add_argument("--show-profile", metavar="NAME",
                   help="print profile metadata + pattern names + kinds")
    g.add_argument("--test-profile", metavar="NAME",
                   help="redact --input/--stdin against the named profile and print the result")
    ap.add_argument("--input", metavar="FILE", help="input file for --test-profile")
    ap.add_argument("--stdin", action="store_true", help="read input from stdin for --test-profile")
    ap.add_argument("--level", default="standard", choices=("standard", "aggressive"),
                    help="redaction level for --test-profile (default: standard)")
    args = ap.parse_args(argv)

    if args.list_profiles:
        rows = list_available_profiles()
        if not rows:
            print("(no profiles found)")
            return 0
        print(f"{'name':<20} {'status':<18} {'last_reviewed':<13} {'patterns':<8} source")
        any_failed = False
        for name, _ in rows:
            r = _load_profile(name)
            if r.status not in ("ok",):
                any_failed = True
            print(f"{name:<20} {r.status:<18} {r.last_reviewed or '(none)':<13} "
                  f"{len(r.patterns):<8} {r.source_path}")
            if r.error:
                print(f"  {r.error}")
        return 2 if any_failed else 0

    if args.show_profile:
        r = _load_profile(args.show_profile)
        if r.status == "not_found":
            print(f"profile '{args.show_profile}' not found", file=sys.stderr)
            return 2
        print(f"name           : {r.name}")
        print(f"source         : {r.source_path}")
        print(f"schema_version : {r.schema_version}")
        print(f"last_reviewed  : {r.last_reviewed}")
        print(f"status         : {r.status}")
        if r.error:
            print(f"error          : {r.error}")
        print(f"description    : {r.description}")
        print(f"disclaimer     : {r.disclaimer}")
        print(f"patterns ({len(r.patterns)}):")
        for pp in r.patterns:
            v = f" validator={pp.validator}" if pp.validator else ""
            print(f"  - {pp.kind:<24} {pp.pattern.pattern}{v}")
        return 0 if r.status == "ok" else 2

    if args.test_profile:
        if args.input and args.stdin:
            print("--input and --stdin are mutually exclusive", file=sys.stderr)
            return 2
        if args.input:
            text = Path(args.input).read_text(encoding="utf-8")
        elif args.stdin:
            text = sys.stdin.read()
        else:
            print("--test-profile requires --input FILE or --stdin", file=sys.stderr)
            return 2
        r = _load_profile(args.test_profile)
        if r.status in ("not_found", "parse_error"):
            print(f"profile load failed: {r.status}: {r.error}", file=sys.stderr)
            return 2
        out = redact_text(text, level=args.level, profiles=[args.test_profile])
        sys.stdout.write(out)
        return 0

    return 0


__all__ = [
    "redact_text", "redact_command", "redact_iter", "REDACTION",
    "ProfilePattern", "ProfileLoadResult",
    "list_available_profiles", "_load_profile", "_clear_profile_cache",
    "SCHEMA_VERSION",
]


if __name__ == "__main__":
    sys.exit(_cli())
