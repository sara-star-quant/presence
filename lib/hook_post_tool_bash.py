"""PostToolUse(Bash) hook: log commands, capture commit SHAs from stdout, classify test/build runs."""
from __future__ import annotations

import os

from _common import hook_input, safe_main, settings
from cmdparse import (
    extract_cd_target,
    extract_git_C_target,
    is_gh_pr_create,
    is_git_commit,
    is_git_push,
)
from events import append_event
from redact import redact_command
from telemetry import (
    get_head_commit,
    parse_commit_sha_from_stdout,
    record_commit_claim,
    record_push_claim,
)
from verify import classify_command


def _redact_level(cfg: dict) -> str:
    return ((cfg.get("redact") or {}).get("level")) or "standard"


def _resolve_commit_cwd(session_cwd: str, cmd: str) -> str:
    """If the command runs in a different directory (cd X && git commit / git -C X commit),
    use that directory for SHA lookup so we don't record a SHA from the wrong repo."""
    git_C = extract_git_C_target(cmd)
    if git_C:
        return os.path.join(session_cwd, git_C) if not os.path.isabs(git_C) else git_C
    cd_target = extract_cd_target(cmd)
    if cd_target:
        return os.path.join(session_cwd, cd_target) if not os.path.isabs(cd_target) else cd_target
    return session_cwd


def main() -> None:
    inp = hook_input()
    cfg = settings()
    session_cwd = inp.get("cwd") or os.getcwd()

    tool_input = inp.get("tool_input") or {}
    tool_response = inp.get("tool_response") or {}
    cmd = tool_input.get("command") or ""

    raw_exit = tool_response.get("exit_code")
    try:
        exit_code: int | None = int(raw_exit) if raw_exit is not None else None
    except (TypeError, ValueError):
        exit_code = None

    level = _redact_level(cfg)

    if (cfg.get("events") or {}).get("enabled", True):
        append_event({
            "kind": "bash",
            "cmd": redact_command(cmd[:500], level=level),
            "exit": exit_code if exit_code is not None else "?",
        }, cwd=session_cwd)

        # Classify only when we know the exit code; never silently bless a failed test as a pass
        classified = classify_command(cmd, exit_code)
        if classified:
            append_event({"kind": classified, "cmd": redact_command(cmd[:500], level=level)}, cwd=session_cwd)

    if not (cfg.get("telemetry") or {}).get("enabled", True):
        return
    if exit_code is None:
        # Bash hook input lacked an exit_code we could parse. Could be schema drift
        # in Claude Code or a malformed tool_response. Don't record (we can't tell
        # if the command succeeded), but surface the gap so /presence-doctor shows it.
        from warnings_log import warn
        warn(
            "bash_exit_unknown",
            "tool_response missing parseable exit_code; commit/push claim not recorded",
            cmd=cmd[:100],
        )
        return
    if exit_code != 0:
        return

    if is_git_commit(cmd):
        commit_cwd = _resolve_commit_cwd(session_cwd, cmd)
        sha = parse_commit_sha_from_stdout(tool_response.get("stdout") or "")
        if sha:
            # We have the sha from stdout; resolve the full hash via git
            head = get_head_commit(commit_cwd)
            if head and head["sha"].startswith(sha):
                record_commit_claim(commit_cwd, head["sha"], head["message"], intent=cmd[:200])
            else:
                # Fallback: record the short sha we got; better partial than nothing
                record_commit_claim(commit_cwd, sha, "(message unavailable)", intent=cmd[:200])
        else:
            head = get_head_commit(commit_cwd)
            if head:
                record_commit_claim(commit_cwd, head["sha"], head["message"], intent=cmd[:200])
    elif is_git_push(cmd):
        record_push_claim(session_cwd, intent=cmd[:200])
    elif is_gh_pr_create(cmd):
        record_push_claim(session_cwd, intent="pr_create: " + cmd[:200])


if __name__ == "__main__":
    safe_main(main)
