#!/usr/bin/env python3
"""Fail when a commit in BASE..HEAD lacks a Developer Certificate of Origin sign-off.

Usage: check_dco.py BASE HEAD, run inside the checkout. A sign-off is a "Signed-off-by: Name <email>" line
whose email is the commit's author or committer. The maintainer and bots are exempt; merge commits are
skipped. Subjects are untrusted text, so what gets printed is plain ASCII with no workflow-command prefix.
"""
from __future__ import annotations

import re
import subprocess
import sys

EXEMPT = re.compile(
    r"(?:\d+\+)?pzverkov@users\.noreply\.github\.com|(?:\d+\+)?[A-Za-z0-9-]+\[bot\]@users\.noreply\.github\.com"
)
SIGN_OFF = re.compile(r"^Signed-off-by: .+ <([^<>\s@]+@[^<>\s@]+)>[ \t]*$", re.MULTILINE)
FIELD, RECORD = "\x1f", "\x1e"


def _plain(text: str) -> str:
    text = re.sub(r"[^\x20-\x7e]", "?", text)[:80]
    return re.sub(r":{2,}", ":", text)


def check(repo: str, base: str, head: str) -> list[str]:
    """One line per commit in base..head that needs a sign-off and has none."""
    if base.startswith("-") or head.startswith("-"):
        raise ValueError("revision looks like an option")
    out = subprocess.run(
        ["git", "log", "--no-merges", f"--format=%H{FIELD}%ae{FIELD}%ce{FIELD}%B{RECORD}", f"{base}..{head}"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    bad = []
    for record in out.split(RECORD):
        if not record.strip():
            continue
        sha, author, committer, body = record.strip().split(FIELD, 3)
        if EXEMPT.fullmatch(author):
            continue
        owners = {author.lower(), committer.lower()}
        if not any(e.lower() in owners for e in SIGN_OFF.findall(body)):
            bad.append(f"{sha[:12]} {_plain(body.splitlines()[0] if body.strip() else '')}")
    return bad


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: check_dco.py BASE HEAD\n")
        return 2
    try:
        bad = check(".", argv[0], argv[1])
    except (ValueError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"cannot read the commit range: {_plain(str(exc))}\n")
        return 2
    for line in bad:
        sys.stdout.write(f"missing sign-off: {line}\n")
    if bad:
        sys.stdout.write("Sign off with: git commit -s --amend (or git rebase --signoff). See CONTRIBUTING.md.\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
