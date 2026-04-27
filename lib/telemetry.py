"""Outcome telemetry: records what Claude committed; watches for reverts/amends."""
from __future__ import annotations

import re
from pathlib import Path

from _common import (
    DEFAULT_GIT_TIMEOUT,
    append_jsonl_rotating,
    async_git_run_safe,
    git_run_safe,
    now_ts,
    read_jsonl,
    repo_id,
    repo_root,
    settings,
    telemetry_dir,
)
from redact import redact_command


def claims_path() -> Path:
    return telemetry_dir() / "claims.jsonl"


def outcomes_path() -> Path:
    return telemetry_dir() / "outcomes.jsonl"


def confidence_path() -> Path:
    return telemetry_dir() / "confidence.jsonl"


def _redact_level() -> str:
    return ((settings().get("redact") or {}).get("level")) or "standard"


def _git_timeout() -> int:
    return int(((settings().get("git") or {}).get("timeout_seconds")) or DEFAULT_GIT_TIMEOUT)


# git-commit prints "[branch hash] message" on success. Capture the hash directly to
# avoid an extra `git log -1` call (which can race + costs a subprocess on big repos).
_COMMIT_OUT_RE = re.compile(r"^\[\S+\s+(?:\(root-commit\)\s+)?([0-9a-f]{7,40})\]", re.MULTILINE)


def parse_commit_sha_from_stdout(stdout: str | None) -> str | None:
    if not stdout:
        return None
    m = _COMMIT_OUT_RE.search(stdout)
    return m.group(1) if m else None


def get_head_commit(cwd) -> dict | None:
    try:
        import presence_ext.git as ext_git
        try:
            return ext_git.get_head_commit(str(cwd))
        except Exception:
            pass
    except ImportError:
        pass

    out = git_run_safe(cwd, "log", "-1", "--format=%H%x09%ct%x09%s", timeout=_git_timeout())
    if not out:
        return None
    try:
        sha, ct, msg = out.split("\t", 2)
        return {"sha": sha, "ct": int(ct), "message": msg}
    except ValueError:
        return None


def record_commit_claim(cwd, sha: str, message: str, intent: str | None = None) -> None:
    append_jsonl_rotating(claims_path(), {
        "ts": now_ts(),
        "kind": "commit",
        "repo": repo_id(cwd),
        "root": str(repo_root(cwd)),
        "sha": sha,
        "message": redact_command(message or "", level=_redact_level()),
        "intent": redact_command(intent or "", level=_redact_level()) if intent else None,
    })


def record_push_claim(cwd, intent: str | None = None) -> None:
    append_jsonl_rotating(claims_path(), {
        "ts": now_ts(),
        "kind": "push",
        "repo": repo_id(cwd),
        "intent": redact_command(intent or "", level=_redact_level()) if intent else None,
    })


def record_outcome(kind: str, sha: str, **details) -> None:
    append_jsonl_rotating(outcomes_path(), {
        "ts": now_ts(),
        "kind": kind,
        "sha": sha,
        **details,
    })


def record_confidence(claim: str, verified: bool, **details) -> None:
    append_jsonl_rotating(confidence_path(), {
        "ts": now_ts(),
        "claim": claim,
        "verified": bool(verified),
        **details,
    })


def scan_for_revert(cwd, since_ts: int) -> list[dict]:
    """Look at git log since ``since_ts`` for revert commits touching tracked SHAs."""
    if not since_ts:
        return []
    rid = repo_id(cwd)
    tracked = {c["sha"] for c in read_jsonl(claims_path()) if c.get("kind") == "commit" and c.get("repo") == rid}
    if not tracked:
        return []

    try:
        import presence_ext.git as ext_git
        try:
            return ext_git.scan_for_revert(str(cwd), since_ts, list(tracked))
        except Exception:
            pass
    except ImportError:
        pass

    out = git_run_safe(
        cwd, "log", f"--since=@{since_ts}", "--max-count=500", "--format=%H%x09%s%x09%ct",
        timeout=_git_timeout(),
    )
    if not out:
        return []
    findings: list[dict] = []
    for line in out.splitlines():
        if not line:
            continue
        try:
            sha, msg, ct = line.split("\t", 2)
        except ValueError:
            continue
        if not msg.lower().startswith("revert "):
            continue
        for tracked_sha in tracked:
            if tracked_sha[:7] in msg or tracked_sha in msg:
                findings.append({
                    "kind": "revert",
                    "tracked": tracked_sha,
                    "by": sha,
                    "ts": int(ct),
                    "message": msg,
                })
                break
    return findings


async def async_scan_for_revert(cwd, since_ts: int) -> list[dict]:
    """Look at git log since ``since_ts`` for revert commits touching tracked SHAs (async)."""
    import asyncio

    if not since_ts:
        return []
    rid = repo_id(cwd)
    # Read the claims log in a thread to keep the event loop responsive
    claims_rows = await asyncio.to_thread(read_jsonl, claims_path())
    tracked = {c["sha"] for c in claims_rows if c.get("kind") == "commit" and c.get("repo") == rid}
    if not tracked:
        return []

    try:
        import presence_ext.git as ext_git
        try:
            return await asyncio.to_thread(ext_git.scan_for_revert, str(cwd), since_ts, list(tracked))
        except Exception:
            pass
    except ImportError:
        pass

    out = await async_git_run_safe(
        cwd, "log", f"--since=@{since_ts}", "--max-count=500", "--format=%H%x09%s%x09%ct",
        timeout=_git_timeout(),
    )
    if not out:
        return []
    findings: list[dict] = []
    for line in out.splitlines():
        if not line:
            continue
        try:
            sha, msg, ct = line.split("\t", 2)
        except ValueError:
            continue
        if not msg.lower().startswith("revert "):
            continue
        for tracked_sha in tracked:
            if tracked_sha[:7] in msg or tracked_sha in msg:
                findings.append({
                    "kind": "revert",
                    "tracked": tracked_sha,
                    "by": sha,
                    "ts": int(ct),
                    "message": msg,
                })
                break
    return findings
