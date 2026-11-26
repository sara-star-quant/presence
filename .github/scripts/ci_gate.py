"""CI routing: which jobs a change needs, and one verdict for the whole run.

classify  reads the pull request diff and prints code=true or code=false to GITHUB_OUTPUT.
          code=false only when EVERY changed file is documentation. Anything else, any git error, an empty diff,
          a push to main: code=true, the full run. Failing toward the full run is the point.
result    reads the needs of the last job (NEEDS_JSON) and exits 1 unless the run is green. A skipped job is fine
          for a documentation change and a failure for a code change, so a bug in the routing cannot merge code
          that skipped its tests.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

DOCS = [
    r"README\.md", r"CHANGELOG\.md", r"CONTRIBUTING\.md", r"SECURITY\.md", r"GOVERNANCE\.md", r"CODE_OF_CONDUCT\.md",
    r"llms\.txt", r"docs/.+", r"diagrams/.+",
]
HEAVY = ["test", "shellcheck", "ascii", "ruff", "bandit", "coverage", "manifest-integrity", "bench", "wheel-build"]


def is_docs(path: str) -> bool:
    if path.startswith("/") or ".." in path.split("/"):
        return False
    return any(re.fullmatch(p, path) for p in DOCS)


def classify(paths: list[str]) -> str:
    paths = [p for p in paths if p]
    if not paths:
        return "code"
    return "docs" if all(is_docs(p) for p in paths) else "code"


def verdict(needs: dict) -> tuple[bool, str]:
    changes = needs.get("changes") or {}
    if changes.get("result") != "success":
        return False, "the change classifier did not succeed"
    bad = sorted(k for k, v in needs.items() if v.get("result") in ("failure", "cancelled"))
    if bad:
        return False, f"failed or cancelled: {', '.join(bad)}"
    if (changes.get("outputs") or {}).get("code") == "true":
        missing = [k for k in HEAVY if (needs.get(k) or {}).get("result") != "success"]
        if missing:
            return False, f"a code change must pass every job, but these did not run green: {', '.join(missing)}"
        return True, "code change: every job passed"
    if (needs.get("docs") or {}).get("result") != "success":
        return False, "a documentation change must pass the docs job"
    return True, "documentation change: docs job passed"


def _changed_files(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", f"origin/{base}...HEAD"], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "classify":
        kind = "code"
        if os.environ.get("EVENT_NAME") == "pull_request" and os.environ.get("BASE_REF"):
            try:
                kind = classify(_changed_files(os.environ["BASE_REF"]))
            except (subprocess.CalledProcessError, OSError):
                kind = "code"
        line = f"code={'false' if kind == 'docs' else 'true'}"
        print(line)
        with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return 0
    if cmd == "result":
        ok, message = verdict(json.loads(os.environ["NEEDS_JSON"]))
        print(("ok: " if ok else "FAIL: ") + message)
        return 0 if ok else 1
    print("usage: ci_gate.py classify|result", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
