"""Check that CI re-ran the tests on a tree and signed the result.

A receipt (lib/receipt.py) is the developer machine's claim about what ran. This is the
independent half: the repository's CI workflow runs every required job on the pushed commit
and, only if all passed, attests a subject derived from the commit's tree hash. Anyone can
rebuild that subject from the tree, so there is no artifact to fetch, and the same tree
matches a receipt even after a rebase merge changed the commit hash.

The verifier pins who may sign: the ci.yml workflow of the named repository, on the main
branch, on GitHub-hosted runners. Without those pins a writer could point a workflow of their
own at any ref and attest whatever they like. Admin merges skip review, so what lands on main
is only as trustworthy as the people allowed to merge there (docs/receipts.md).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from receipt import _git, _rev

PREDICATE_TYPE = "https://github.com/sara-star-quant/presence/attestations/test-evidence/v1"
SIGNER_WORKFLOW = ".github/workflows/ci.yml"
SOURCE_REF = "refs/heads/main"
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def subject_text(tree: str) -> str:
    """The attested subject: derived from the tree alone, byte for byte what ci.yml writes."""
    return f"presence test evidence v1\ntree {tree}\n"


def verify(cwd, rev: str, repo: str) -> dict:
    """status: verified | not_attested (no signed run for this tree, or gh could not say) |
    mismatch (attested predicate names another tree) | failed_jobs (a job in the run did not pass).

    Needs the GitHub CLI and network. A missing ``gh`` is an error, never a pass.
    """
    if not _REPO.fullmatch(repo) or repo.startswith("-"):
        raise ValueError(f"repo must look like owner/name: {repo!r}")
    tree = _git(cwd, "rev-parse", f"{_rev(rev)}^{{tree}}")
    with tempfile.TemporaryDirectory() as tmp:
        subject = Path(tmp) / "subject.txt"
        subject.write_text(subject_text(tree))
        try:
            r = subprocess.run(
                ["gh", "attestation", "verify", str(subject), "--repo", repo,
                 "--predicate-type", PREDICATE_TYPE,
                 "--signer-workflow", f"{repo}/{SIGNER_WORKFLOW}",
                 "--source-ref", SOURCE_REF, "--deny-self-hosted-runners", "--format", "json"],
                capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"gh unavailable: {exc}") from exc
    predicate = _predicate(r.stdout) if r.returncode == 0 else None
    if predicate is None:
        return {"status": "not_attested", "tree": tree}
    jobs = predicate.get("jobs")
    if predicate.get("tree") != tree:
        return {"status": "mismatch", "tree": tree}
    if not isinstance(jobs, dict) or not jobs or any(v != "success" for v in jobs.values()):
        return {"status": "failed_jobs", "tree": tree}
    return {"status": "verified", "tree": tree, "commit": str(predicate.get("commit", ""))[:40],
            "run": str(predicate.get("run_url", ""))[:200], "jobs": sorted(jobs)}


def _predicate(out: str) -> dict | None:
    try:
        entries = json.loads(out)
        for e in entries:
            pred = e["verificationResult"]["statement"]["predicate"]
            if isinstance(pred, dict):
                return pred
    except (ValueError, KeyError, TypeError):
        pass
    return None
