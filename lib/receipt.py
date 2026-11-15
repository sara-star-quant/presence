"""Verification receipts: a portable statement of what was run before a commit.

The Bash hook records one at commit time from the session's event queue, which is
gone after the next SessionStart. ``attach`` copies it into a git note
(``refs/notes/presence``) so it travels with the repo; ``verify`` needs nothing but
the repo. A receipt binds a commit and its tree to the redacted commands that
passed after the last edit and to a digest over all of it.

Format 1 is unsigned. The digest catches a note edited after the fact and a note
copied onto another commit. It does not stop someone with write access to the repo
from forging a whole receipt; signing and an externally witnessed head are the next
steps (docs/roadmap.md).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from _common import append_jsonl_rotating, now_ts, read_jsonl, telemetry_dir
from events import peek_events

FORMAT = 1
NOTES_REF = "presence"
MAX_EVIDENCE = 5


def receipts_path() -> Path:
    return telemetry_dir() / "receipts.jsonl"


def _digest(body: dict) -> str:
    rest = {k: v for k, v in body.items() if k != "digest"}
    return hashlib.sha256(json.dumps(rest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _git(cwd, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _git_try(cwd, *args: str) -> str | None:
    try:
        return _git(cwd, *args)
    except (subprocess.CalledProcessError, OSError):
        return None


def build(cwd, sha: str) -> dict:
    """Receipt for ``sha`` from the events queued in this session.

    An edit or a failed run marks the work unverified until a later pass; a pass
    clears that and becomes the evidence.
    """
    from __init__ import __version__

    dirty = False
    evidence: list[dict] = []
    for ev in peek_events(cwd):
        kind = ev.get("kind")
        if kind in ("edit", "test_fail", "build_fail"):
            dirty, evidence = True, []
        elif kind in ("test_pass", "build_pass"):
            dirty = False
            evidence.append({"kind": kind, "cmd": ev.get("cmd", ""), "ts": ev.get("ts", 0)})
    body = {
        "v": FORMAT,
        "commit": sha,
        "tree": _git(cwd, "rev-parse", f"{sha}^{{tree}}"),
        "ts": now_ts(),
        "verified_since_edit": not dirty,
        "evidence": evidence[-MAX_EVIDENCE:],
        "tool": f"presence {__version__}",
    }
    body["digest"] = _digest(body)
    return body


def record(cwd, sha: str) -> dict:
    """Build the receipt and keep it in local telemetry until it is attached."""
    r = build(cwd, sha)
    append_jsonl_rotating(receipts_path(), r)
    return r


def find(cwd, rev: str) -> dict:
    """The receipt recorded on this machine for ``rev``. LookupError if there is none."""
    sha = _git(cwd, "rev-parse", "--verify", f"{rev}^{{commit}}")
    found = [r for r in read_jsonl(receipts_path()) if r.get("commit") == sha]
    if not found:
        raise LookupError(f"no receipt recorded for {sha[:12]} on this machine")
    return found[-1]


def attach(cwd, rev: str) -> dict:
    """Write the recorded receipt for ``rev`` into its git note."""
    r = find(cwd, rev)
    _git(cwd, "notes", f"--ref={NOTES_REF}", "add", "-f", "-m", json.dumps(r, sort_keys=True), r["commit"])
    return r


def verify(cwd, rev: str) -> dict:
    """Check the git note on ``rev``. Needs only the repo, never presence state.

    status: verified | unverified (an edit or failure after the last pass) |
    no_evidence (nothing was observed running) | tampered (digest) | mismatch
    (note belongs to another commit or tree) | invalid | none.
    """
    sha = _git_try(cwd, "rev-parse", "--verify", f"{rev}^{{commit}}")
    if sha is None:
        return {"status": "invalid", "reason": f"{rev} is not a commit"}
    raw = _git_try(cwd, "notes", f"--ref={NOTES_REF}", "show", sha)
    if raw is None:
        return {"status": "none", "commit": sha}
    try:
        note = json.loads(raw)
        if not isinstance(note, dict) or note.get("v") != FORMAT:
            raise ValueError
    except ValueError:
        return {"status": "invalid", "commit": sha, "reason": "note is not a format 1 receipt"}
    if note.get("digest") != _digest(note):
        return {"status": "tampered", "commit": sha}
    if note.get("commit") != sha or note.get("tree") != _git_try(cwd, "rev-parse", f"{sha}^{{tree}}"):
        return {"status": "mismatch", "commit": sha}
    if not note.get("verified_since_edit"):
        status = "unverified"
    elif not note.get("evidence"):
        status = "no_evidence"
    else:
        status = "verified"
    return {"status": status, "commit": sha, "evidence": note.get("evidence", []), "tool": note.get("tool")}
