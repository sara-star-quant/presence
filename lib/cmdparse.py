"""Robust shell-command parsing: distinguishes ``git commit`` (real) from ``grep "git commit"`` (false positive).

Approach:
- ``shlex.split`` the command (POSIX mode).
- Walk pipeline clauses by splitting on top-level ``;``, ``&&``, ``||``, ``|`` *outside*
  shlex tokens (we use the already-tokenized list so quoted ones are safe).
- For each clause, strip leading ``ENV=value`` assignments, then check the first
  remaining token pair.

This intentionally misses fancy shell constructs (subshells, command substitution,
xargs piping). Those are rare for the commands we care about (commit, push, gh pr
create, test runners). When parsing fails entirely, we conservatively return False;
better miss a gate than block the wrong thing.
"""
from __future__ import annotations

import shlex

_PIPELINE_SEPARATORS = {";", "&&", "||", "|", "&"}
_ASSIGN_TOKEN = lambda t: "=" in t and t.split("=", 1)[0].replace("_", "").isalnum() and t.split("=", 1)[0][:1].isalpha()  # noqa: E731


def _tokenize(cmd: str) -> list[str] | None:
    try:
        return shlex.split(cmd, comments=True, posix=True)
    except ValueError:
        return None


def _clauses(tokens: list[str]) -> list[list[str]]:
    out: list[list[str]] = []
    cur: list[str] = []
    for t in tokens:
        if t in _PIPELINE_SEPARATORS:
            if cur:
                out.append(cur)
                cur = []
            continue
        cur.append(t)
    if cur:
        out.append(cur)
    return out


def _strip_env_prefix(clause: list[str]) -> list[str]:
    i = 0
    while i < len(clause) and _ASSIGN_TOKEN(clause[i]):
        i += 1
    return clause[i:]


def matches_subcommand(cmd: str, *, prog: str, sub: str) -> bool:
    """True iff any clause in ``cmd`` is ``[ENV=v ...] prog [-C path] sub ...``."""
    tokens = _tokenize(cmd)
    if tokens is None:
        return False
    for clause in _clauses(tokens):
        rest = _strip_env_prefix(clause)
        if not rest or rest[0] != prog:
            continue
        # Skip git's optional global flags before the subcommand: -C dir, -c k=v, --git-dir=...
        i = 1
        while i < len(rest):
            tok = rest[i]
            if tok == "-C" and i + 1 < len(rest):
                i += 2
                continue
            if tok == "-c" and i + 1 < len(rest):
                i += 2
                continue
            if tok.startswith(("--git-dir=", "--work-tree=", "-c=")):
                i += 1
                continue
            break
        if i < len(rest) and rest[i] == sub:
            return True
    return False


def is_git_commit(cmd: str) -> bool:
    return matches_subcommand(cmd, prog="git", sub="commit")


def is_git_push(cmd: str) -> bool:
    return matches_subcommand(cmd, prog="git", sub="push")


def is_gh_pr_create(cmd: str) -> bool:
    """gh pr create. gh pulls don't have nested -C handling, so simpler form."""
    tokens = _tokenize(cmd)
    if tokens is None:
        return False
    for clause in _clauses(tokens):
        rest = _strip_env_prefix(clause)
        if len(rest) >= 3 and rest[0] == "gh" and rest[1] == "pr" and rest[2] == "create":
            return True
    return False


def extract_cd_target(cmd: str) -> str | None:
    """For ``cd X && git commit ...`` style: return ``X`` if a cd clause precedes a relevant clause."""
    tokens = _tokenize(cmd)
    if tokens is None:
        return None
    for clause in _clauses(tokens):
        rest = _strip_env_prefix(clause)
        if len(rest) >= 2 and rest[0] == "cd":
            return rest[1]
    return None


def extract_git_C_target(cmd: str) -> str | None:
    """For ``git -C X commit ...``: return X."""
    tokens = _tokenize(cmd)
    if tokens is None:
        return None
    for clause in _clauses(tokens):
        rest = _strip_env_prefix(clause)
        if len(rest) >= 3 and rest[0] == "git" and rest[1] == "-C":
            return rest[2]
    return None


__all__ = [
    "is_git_commit", "is_git_push", "is_gh_pr_create",
    "extract_cd_target", "extract_git_C_target",
    "matches_subcommand",
]
