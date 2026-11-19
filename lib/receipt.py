"""Verification receipts: a portable statement of what was run before a commit.

The Bash hook records one at commit time from the session's event queue, which is
gone after the next SessionStart. ``attach`` copies it into a git note
(``refs/notes/presence``) so it travels with the repo; ``verify`` needs nothing but
the repo. A receipt binds a commit and its tree to the redacted commands that
passed after the last edit and to a digest over all of it.

The digest catches a note edited after the fact and a note copied onto another commit.
It does not stop someone with write access to the repo from writing a whole new one.
That takes a signature: ``attach(sign_key=...)`` signs the digest with an SSH key, and
``verify(allowed_signers=...)`` trusts only keys the verifier pinned itself, outside the
repo. A signature cannot help against whoever holds the key (including an agent that can
use it silently); a hardware key that needs a touch, or a CI-issued attestation, covers
that case (docs/receipts.md).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from _common import append_jsonl_rotating, now_ts, read_jsonl, telemetry_dir
from events import peek_events

FORMAT = 1
NOTES_REF = "presence"
MAX_EVIDENCE = 5
MAX_NOTE_BYTES = 16_384  # five 500-character commands fit in about 4 KB
MAX_CMD = 500
SIG_NAMESPACE = "presence-receipt"
MAX_SIG = 2048
_KINDS = {"test_pass", "build_pass"}

# The in-toto Statement form of a receipt (docs/receipts.md). The type URI is an identifier that signed
# data may carry, so it never changes once published.
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://github.com/sara-star-quant/presence/blob/main/docs/receipts.md#as-an-in-toto-statement"
_OID = {40: "sha1", 64: "sha256"}
_HEX = re.compile(r"[0-9a-f]+\Z")
# What settles a verdict and who writes it, in words a reviewer can check against the receipt.
CLAIM_CARD = {
    "policy": "A commit is verified when a passing test or build command ran on exactly this git tree after the last change.",
    "scope": "The commit's working tree and the commands the hooks saw run on it; nothing about the machine, the environment or the test output.",
    "records": "The hooks' record of passing commands, each tied to the git tree it ran on, kept in this receipt's evidence list.",
    "writer": "The presence hooks on the machine that ran the agent, not the agent. Unsigned, anyone who can write to the repo can write one; a pinned SSH signature or a CI attestation says who vouches.",
    "rule": "verified only when verified_since_edit is true and at least one passing command is recorded; otherwise unverified or no_evidence.",
}


def receipts_path() -> Path:
    return telemetry_dir() / "receipts.jsonl"


def _digest(body: dict) -> str:
    rest = {k: v for k, v in body.items() if k not in ("digest", "signature")}
    return hashlib.sha256(json.dumps(rest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _rev(rev: str) -> str:
    """A revision from the command line must not be able to pose as a git option."""
    if not isinstance(rev, str) or not rev or rev.startswith("-") or "\0" in rev:
        raise ValueError(f"not a usable revision: {rev!r}")
    return rev


def safe_text(text: object, limit: int = 80) -> str:
    """One printable ASCII line. A note comes from a repo anyone may have written to, and its
    text can reach a terminal or an agent's context: no escapes, no newlines, bounded."""
    return "".join(c if " " <= c <= "~" else "?" for c in str(text)[:limit])


def _well_formed(note: dict) -> bool:
    ev = note.get("evidence")
    return (
        isinstance(note.get("commit"), str)
        and isinstance(note.get("tree"), str)
        and isinstance(note.get("verified_since_edit"), bool)
        and isinstance(note.get("exact", False), bool)
        and (note.get("signature") is None or (isinstance(note["signature"], str) and len(note["signature"]) <= MAX_SIG))
        and isinstance(ev, list)
        and len(ev) <= MAX_EVIDENCE
        and all(
            isinstance(e, dict)
            and e.get("kind") in _KINDS
            and isinstance(e.get("cmd"), str)
            and len(e["cmd"]) <= MAX_CMD
            and isinstance(e.get("ts"), int)
            for e in ev
        )
    )


def _oid_digest(oid: object) -> dict:
    """A git object id as an in-toto digest, keyed by the repository's real hash format."""
    if not isinstance(oid, str) or _OID.get(len(oid)) is None or not _HEX.match(oid):
        raise ValueError(f"not a git object id: {safe_text(oid)!r}")
    return {_OID[len(oid)]: oid}


def to_statement(note: dict) -> dict:
    """The receipt as an in-toto Statement (v1): the tree and the commit as subjects, the claim card and
    the evidence as the predicate. Pure: no signing and no I/O. It adds no hash of test output, no
    executable and nothing about the machine, so a reader learns exactly what the receipt already says."""
    return {
        "_type": STATEMENT_TYPE,
        "subject": [
            {"name": "git-tree", "digest": _oid_digest(note.get("tree"))},
            {"name": "git-commit", "digest": _oid_digest(note.get("commit"))},
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            **CLAIM_CARD,
            "verified_since_edit": bool(note.get("verified_since_edit")),
            "exact": bool(note.get("exact", False)),
            "evidence": [{"kind": e.get("kind"), "cmd": e.get("cmd"), "ts": e.get("ts")}
                         for e in (note.get("evidence") or [])[:MAX_EVIDENCE]],
            "tool": note.get("tool"),
            "ts": note.get("ts"),
            "receipt_digest": note.get("digest"),
        },
    }


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

    events = peek_events(cwd)
    tree = _git(cwd, "rev-parse", f"{sha}^{{tree}}")
    # When the passing runs recorded the tree they ran on, that tree is the evidence: it matches the
    # commit's tree or it does not, whoever edited what and however. Without trees (older state, or
    # a repository git could not hash) fall back to the order of edit and run events.
    exact = any(ev.get("tree") for ev in events if ev.get("kind") in ("test_pass", "build_pass"))
    dirty = False
    evidence: list[dict] = []
    for ev in events:
        kind = ev.get("kind")
        if kind == "edit" and (exact or ev.get("scope", "code") != "code"):
            continue  # exact mode ignores edit events; otherwise notes and docs cannot be verified by a test
        if kind in ("edit", "test_fail", "build_fail"):
            dirty, evidence = True, []
        elif kind in ("test_pass", "build_pass"):
            if exact and ev.get("tree") != tree:
                continue
            dirty = False
            evidence.append({"kind": kind, "cmd": ev.get("cmd", ""), "ts": ev.get("ts", 0)})
    if exact:
        dirty = not evidence
    body = {
        "v": FORMAT,
        "commit": sha,
        "tree": tree,
        "ts": now_ts(),
        "verified_since_edit": not dirty,
        "exact": exact,
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


def _ssh_keygen(*args: str, data: bytes = b"") -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["ssh-keygen", *args], input=data, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"ssh-keygen unavailable: {exc}") from exc


def sign_digest(digest: str, key: str | Path) -> str:
    """SSH signature over the receipt digest. A ``.pub`` path signs through ssh-agent, so a
    hardware key that needs a touch per signature works."""
    r = _ssh_keygen("-Y", "sign", "-f", str(key), "-n", SIG_NAMESPACE, data=digest.encode())
    if r.returncode != 0 or not r.stdout:
        raise ValueError(f"signing failed: {safe_text(r.stderr.decode(errors='replace'), 200)}")
    return r.stdout.decode()


def _signer(note: dict, allowed_signers: Path) -> str | None:
    """The pinned principal whose key signed this receipt's digest, or None."""
    sig = note.get("signature")
    if not sig:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        sigfile = Path(tmp) / "sig"
        sigfile.write_text(sig)
        found = _ssh_keygen("-Y", "find-principals", "-f", str(allowed_signers), "-s", str(sigfile))
        for principal in found.stdout.decode(errors="replace").split():
            ok = _ssh_keygen("-Y", "verify", "-f", str(allowed_signers), "-I", principal,
                             "-n", SIG_NAMESPACE, "-s", str(sigfile), data=note["digest"].encode())
            if ok.returncode == 0:
                return principal
    return None


def find(cwd, rev: str) -> dict:
    """The receipt recorded on this machine for ``rev``. LookupError if there is none."""
    sha = _git(cwd, "rev-parse", "--verify", f"{_rev(rev)}^{{commit}}")
    found = [r for r in read_jsonl(receipts_path()) if r.get("commit") == sha]
    if not found:
        raise LookupError(f"no receipt recorded for {sha[:12]} on this machine")
    return found[-1]


def attach(cwd, rev: str, sign_key: str | Path | None = None) -> dict:
    """Write the recorded receipt for ``rev`` into its git note, signed when a key is given."""
    r = find(cwd, rev)
    if sign_key is not None:
        r = {**r, "signature": sign_digest(r["digest"], sign_key)}
    _git(cwd, "notes", f"--ref={NOTES_REF}", "add", "-f", "-m", json.dumps(r, sort_keys=True), r["commit"])
    return r


def verify(cwd, rev: str, allowed_signers: str | Path | None = None) -> dict:
    """Check the git note on ``rev``. Needs only the repo, never presence state.

    status: verified (consistent, complete, unsigned) | unverified (an edit or failure after the last pass) |
    no_evidence (nothing was observed running) | tampered (digest) | mismatch
    (note belongs to another commit or tree) | untrusted (``allowed_signers`` given and no
    pinned key signed it) | invalid | none.

    ``allowed_signers`` is an ssh-keygen allowed_signers file the verifier supplies itself. Never
    read it from the repo under test: whoever can write a note can write that file too.
    """
    signers = None
    if allowed_signers is not None:
        signers = Path(allowed_signers)
        if not signers.is_file():
            raise ValueError(f"allowed signers file not found: {signers}")
    sha = _git_try(cwd, "rev-parse", "--verify", f"{_rev(rev)}^{{commit}}")
    if sha is None:
        return {"status": "invalid", "reason": f"{rev} is not a commit"}
    raw = _git_try(cwd, "notes", f"--ref={NOTES_REF}", "show", sha)
    if raw is None:
        return {"status": "none", "commit": sha}
    try:
        if len(raw.encode()) > MAX_NOTE_BYTES:
            raise ValueError
        note = json.loads(raw)
        if not isinstance(note, dict) or note.get("v") != FORMAT or not _well_formed(note):
            raise ValueError
    except (ValueError, RecursionError):
        return {"status": "invalid", "commit": sha, "reason": "note is not a well-formed format 1 receipt"}
    if note.get("digest") != _digest(note):
        return {"status": "tampered", "commit": sha}
    if note.get("commit") != sha or note.get("tree") != _git_try(cwd, "rev-parse", f"{sha}^{{tree}}"):
        return {"status": "mismatch", "commit": sha}
    signer = None
    if signers is not None:
        signer = _signer(note, signers)
        if signer is None:
            return {"status": "untrusted", "commit": sha}
    if not note.get("verified_since_edit"):
        status = "unverified"
    elif not note.get("evidence"):
        status = "no_evidence"
    else:
        status = "verified"
    # Without pinned signers "verified" means consistent and complete only: anyone who can write
    # to the repo can write a receipt that passes.
    return {"status": status, "commit": sha, "evidence": note["evidence"], "exact": note.get("exact", False),
            "signed": signer is not None, "signer": signer}
