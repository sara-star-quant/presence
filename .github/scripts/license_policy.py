#!/usr/bin/env python3
"""Fail when ScanCode finds copyleft or restricted licenses in code files.

Usage: license_policy.py scancode.json. Only code files are judged (prose and data mention licenses without
being under them), only matches scoring at least 90, and SPDX expressions are evaluated: an OR passes when any
branch is permissive, an AND needs every branch to be. An expression it cannot read fails.
"""
from __future__ import annotations

import json
import re
import sys

SCORE_FLOOR = 90.0
CODE = (".py", ".rs", ".sh", ".bash", ".toml", ".yml", ".yaml", ".js", ".ts", ".c", ".h", ".go")
DENIED = re.compile(
    r"(?:A?L?GPL-|SSPL-|BUSL-|Commons-Clause|CC-BY-N[CD]|LicenseRef-scancode-(?:proprietary|commercial|commons-clause))",
    re.IGNORECASE,
)
TOKEN = re.compile(r"\(|\)|[A-Za-z0-9.+:-]+")


class _Unreadable(ValueError):
    pass


def _tokens(expression: str) -> list[str]:
    stripped = TOKEN.sub(" ", expression)
    if stripped.strip():
        raise _Unreadable(expression)
    return TOKEN.findall(expression)


def denied(expression: str) -> bool:
    """True when no permissive way of satisfying the expression exists."""
    toks = _tokens(expression)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def atom() -> bool:
        if peek() is None:
            raise _Unreadable(expression)
        tok = take()
        if tok == "(":
            value = either()
            if peek() != ")":
                raise _Unreadable(expression)
            take()
            return value
        if tok in (")", "AND", "OR", "WITH"):
            raise _Unreadable(expression)
        value = bool(DENIED.match(tok))
        if peek() == "WITH":
            take()
            if peek() is None or take() in ("(", ")", "AND", "OR", "WITH"):
                raise _Unreadable(expression)
        return value

    def both() -> bool:
        value = atom()
        while peek() == "AND":
            take()
            value = atom() or value
        return value

    def either() -> bool:
        value = both()
        while peek() == "OR":
            take()
            value = both() and value
        return value

    result = either()
    if peek() is not None:
        raise _Unreadable(expression)
    return result


def _plain(text: str) -> str:
    return re.sub(r"[^\x20-\x7e]", "?", str(text))[:160]


def violations(data: dict) -> list[str]:
    found = []
    for entry in data.get("files", []):
        path = str(entry.get("path", ""))
        if entry.get("type") == "directory" or not path.endswith(CODE):
            continue
        for detection in entry.get("license_detections") or []:
            for match in detection.get("matches") or []:
                score = match.get("score") or 0
                if score < SCORE_FLOOR:
                    continue
                expression = match.get("license_expression_spdx") or ""
                try:
                    bad = denied(expression)
                except _Unreadable:
                    bad = True
                if bad:
                    found.append(f"{_plain(path)}:{match.get('start_line')}-{match.get('end_line')} "
                                 f"{_plain(expression)} (score {score})")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: license_policy.py scancode.json\n")
        return 2
    try:
        with open(argv[0], encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"cannot read the scan: {_plain(exc)}\n")
        return 2
    if not data.get("files"):
        sys.stderr.write("the scan lists no files; nothing was checked\n")
        return 2
    found = violations(data)
    for line in found:
        sys.stdout.write(f"license policy: {line}\n")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
