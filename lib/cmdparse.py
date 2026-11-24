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

import os
import shlex

# A command longer than this is not parsed: a shell lexer is a character loop in Python, and a hook that
# hangs on a hostile command is worse than a gate that misses one.
MAX_COMMAND_CHARS = 32_768
_PIPELINE_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")"}
_ASSIGN_TOKEN = lambda t: "=" in t and t.split("=", 1)[0].replace("_", "").isalnum() and t.split("=", 1)[0][:1].isalpha()  # noqa: E731


def _tokenize(cmd: str) -> list[str] | None:
    """Words and operators. Operators are split off even when glued to a word (``add .;git commit``,
    ``a&&b``, ``(git commit)``); quoted text stays one word."""
    if len(cmd) > MAX_COMMAND_CHARS:
        return None
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = "#"
        return list(lex)
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


# Wrappers that run the next word as the command, and shells whose -c argument is a command line.
_WRAPPERS = {"env", "command", "exec", "time", "nohup"}
_SHELLS = {"bash", "sh", "zsh", "dash"}
_MAX_SHELL_DEPTH = 2
# git global options that take no value, and those that take the next word as their value.
_GIT_FLAGS = {"--no-pager", "--paginate", "-p", "-P", "--no-optional-locks", "--bare", "--literal-pathspecs",
              "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--no-replace-objects"}
_GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}


def _unwrap(rest: list[str]) -> list[str]:
    """Drop wrapper words (env, command, exec, time, nohup) so the command itself comes first."""
    while rest and os.path.basename(rest[0]) in _WRAPPERS:
        wrapper = os.path.basename(rest[0])
        rest = rest[1:]
        if wrapper == "env":
            while rest and (rest[0].startswith("-") or _ASSIGN_TOKEN(rest[0])):
                flag = rest[0]
                rest = rest[2:] if flag in ("-u", "-C", "-S") and len(rest) > 1 else rest[1:]
        rest = _strip_env_prefix(rest)
    return rest


def _shell_payload(rest: list[str]) -> str | None:
    """The command line handed to ``bash -c '...'`` (also -lc and friends), or None."""
    if not rest or os.path.basename(rest[0]) not in _SHELLS:
        return None
    for i, tok in enumerate(rest[1:], start=1):
        if tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:]:
            return rest[i + 1] if i + 1 < len(rest) else None
        if not tok.startswith("-"):
            return None  # a script path, not -c
    return None


def _command_clauses(cmd: str, depth: int = 0) -> list[list[str]]:
    """Every clause of ``cmd``, wrappers stripped, including those inside a shell -c argument."""
    tokens = _tokenize(cmd)
    if tokens is None:
        return []
    out: list[list[str]] = []
    for clause in _clauses(tokens):
        rest = _unwrap(_strip_env_prefix(clause))
        if not rest:
            continue
        out.append(rest)
        payload = _shell_payload(rest)
        if payload is not None and depth < _MAX_SHELL_DEPTH:
            out.extend(_command_clauses(payload, depth + 1))
    return out


def matches_subcommand(cmd: str, *, prog: str, sub: str) -> bool:
    """True iff any clause in ``cmd`` is ``[wrapper] [ENV=v ...] prog [global flags] sub ...``, also behind a
    path (/usr/bin/git) or inside ``bash -c '...'``."""
    for rest in _command_clauses(cmd):
        if os.path.basename(rest[0]) != prog:
            continue
        # Skip git's optional global flags before the subcommand: -C dir, -c k=v, --git-dir=..., --no-pager.
        i = 1
        while i < len(rest):
            tok = rest[i]
            if tok in _GIT_VALUE_FLAGS and i + 1 < len(rest):
                i += 2
                continue
            if tok in _GIT_FLAGS or tok.startswith(("--git-dir=", "--work-tree=", "--namespace=", "--config-env=", "-c=")):
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
    for rest in _command_clauses(cmd):
        if len(rest) >= 3 and os.path.basename(rest[0]) == "gh" and rest[1] == "pr" and rest[2] == "create":
            return True
    return False


def extract_cd_target(cmd: str) -> str | None:
    """For ``cd X && git commit ...`` style: return ``X`` if a cd clause precedes a relevant clause."""
    for rest in _command_clauses(cmd):
        if len(rest) >= 2 and rest[0] == "cd":
            return rest[1]
    return None


def extract_git_C_target(cmd: str) -> str | None:
    """For ``git -C X commit ...``: return X."""
    for rest in _command_clauses(cmd):
        if len(rest) >= 3 and os.path.basename(rest[0]) == "git" and rest[1] == "-C":
            return rest[2]
    return None


__all__ = [
    "is_git_commit", "is_git_push", "is_gh_pr_create",
    "extract_cd_target", "extract_git_C_target",
    "matches_subcommand",
]
