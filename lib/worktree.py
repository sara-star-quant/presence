"""Verify by tree: say exactly what a test run covered, whoever made the edits.

The gate used to learn about edits from the Edit and Write tool hooks. Edits made by a shell
command, an MCP tool, a subagent or a ``git checkout`` never reached it, so "no edit seen since
the last passing run" was often wrong. This module looks at the working copy instead.

``snapshot`` hashes the working copy (tracked changes and untracked, not ignored, files) into a
git tree, using a throwaway index and a throwaway object directory, so the repository gains no
objects and its own index is untouched. A clean copy hashes to ``HEAD^{tree}``, which is also
what a commit records, so a tree that passed its tests can be matched to the commit and to CI.

Per session the state file keeps a baseline (the working copy when the session started), the tree
of the last passing run, and, per changed path, a blob id and a scope. Paths are stored hashed:
state is encrypted at rest under zerotrust, and no file content ever lands in it. Any failure
returns None and the caller falls back to watching edit events.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import _common
from verify import edit_scope

# Files tools leave behind when a test or build runs. Hidden only while untracked, so a run cannot
# change the tree it just verified; anything the project tracks still counts.
ARTIFACTS = (
    "__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", ".hypothesis/", ".tox/", ".nox/",
    ".venv/", "venv/", "*.egg-info/", ".coverage", ".coverage.*", "htmlcov/", "node_modules/", "target/", ".DS_Store",
)
MAX_DIFF = 500
BUDGET = 3.0  # seconds a snapshot may take before the session falls back to watching edit events
_HEX = frozenset("0123456789abcdef")


def _git(cwd, *args: str, env: dict | None = None, timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout, check=False)


def _is_oid(value: str) -> bool:
    return len(value) in (40, 64) and set(value) <= _HEX


def head_tree(cwd) -> str | None:
    try:
        r = _git(cwd, "rev-parse", "HEAD^{tree}")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 and _is_oid(r.stdout.strip()) else None


def snapshot(cwd, base_head_tree: str | None = None, timeout: float = 5.0) -> dict | None:
    """``{"tree": hash, "diff": {path: blob_id} | None}`` for the working copy, or None.

    ``diff`` lists the paths whose content differs from ``base_head_tree`` (None when there are
    more than MAX_DIFF of them, or no base was given). Deleted paths map to the null id.
    """
    try:
        r = _git(cwd, "rev-parse", "--git-dir", "--git-path", "objects", "--git-path", "index", timeout=timeout)
        if r.returncode != 0 or len(r.stdout.split("\n")) < 3:
            return None
        _, objects, index = (os.path.join(str(cwd), p) for p in r.stdout.split("\n")[:3])
        with tempfile.TemporaryDirectory() as tmp:
            if os.path.exists(index):
                # copy2, not copy: git re-reads an entry as new as the index itself (the racy-clean rule), and a
                # copy stamped "now" would hide a quick same-size edit. The copy also keeps the stat cache,
                # so only changed files are hashed.
                shutil.copy2(index, os.path.join(tmp, "index"))
            os.makedirs(os.path.join(tmp, "objects"))
            env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index"),
                   "GIT_OBJECT_DIRECTORY": os.path.join(tmp, "objects"),
                   "GIT_ALTERNATE_OBJECT_DIRECTORIES": objects}
            exclude = os.path.join(tmp, "exclude")
            with open(exclude, "w", encoding="utf-8") as f:
                f.write("\n".join(ARTIFACTS) + "\n")
            if _git(cwd, "-c", f"core.excludesFile={exclude}", "add", "-A", env=env, timeout=timeout).returncode != 0:
                return None
            w = _git(cwd, "write-tree", env=env, timeout=timeout)
            tree = w.stdout.strip()
            if w.returncode != 0 or not _is_oid(tree):
                return None
            diff = None
            if base_head_tree:
                d = _git(cwd, "diff-tree", "-r", "--no-renames", "--raw", "-z", "--no-abbrev", base_head_tree, tree,
                         env=env, timeout=timeout)
                if d.returncode == 0:
                    parts = d.stdout.split("\0")
                    entries = {parts[i + 1]: parts[i].split()[3] for i in range(0, len(parts) - 1, 2) if parts[i]}
                    diff = entries if len(entries) <= MAX_DIFF else None
            return {"tree": tree, "diff": diff}
    except (OSError, subprocess.TimeoutExpired):
        return None


def _pack(diff: dict[str, str] | None, root: str) -> dict[str, str] | None:
    """Hashed path -> "blob_id:scope". No path or content is kept."""
    if diff is None:
        return None
    return {hashlib.sha256(p.encode()).hexdigest()[:16]: f"{oid}:{edit_scope(p, root)}" for p, oid in diff.items()}


def _state_path(cwd) -> Path:
    return _common.project_dir(cwd) / "worktree.json"


def _load(cwd) -> dict:
    try:
        data = json.loads(_state_path(cwd).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(cwd, state: dict) -> None:
    _common.atomic_write(_state_path(cwd), json.dumps(state, sort_keys=True))


def _timed(cwd, state: dict, fn):
    """Run a snapshot; if it fails or overruns BUDGET, switch tree checks off for the session. A slow
    answer is still returned this once."""
    start = time.monotonic()
    result = fn()
    if result is None or time.monotonic() - start > BUDGET:
        _save(cwd, {**state, "slow": True})
    return result


def ensure_base(cwd, session_id: str) -> None:
    """Record the working copy as it is when the session starts, once per session."""
    if _load(cwd).get("session") == session_id:
        return
    head = head_tree(cwd)
    start = time.monotonic()
    snap = snapshot(cwd, head, timeout=BUDGET) if head else None
    if snap is None or time.monotonic() - start > BUDGET:
        _save(cwd, {"session": session_id, "slow": True})  # tree checks are off for this session
        return
    _save(cwd, {"session": session_id, "head_tree": head, "base_tree": snap["tree"],
                "base_diff": _pack(snap["diff"], str(_common.repo_root(cwd))), "verified": None})


def record_pass(cwd, session_id: str) -> str | None:
    """A test or build run passed: remember the exact tree it passed on, and return it."""
    ensure_base(cwd, session_id)
    state = _load(cwd)
    if state.get("session") != session_id or state.get("slow"):
        return None
    snap = _timed(cwd, state, lambda: snapshot(cwd, timeout=BUDGET))
    if snap is None:
        return None
    _save(cwd, {**_load(cwd), "verified": snap["tree"]})
    return snap["tree"]


def record_fail(cwd, session_id: str) -> None:
    state = _load(cwd)
    if state.get("session") == session_id and state.get("verified") is not None:
        _save(cwd, {**state, "verified": None})


def view(cwd, session_id: str) -> dict | None:
    """What the gate needs: did code change since the session started, and did the last passing
    run cover exactly this tree (True, False, or None when no pass was recorded). None overall
    when there is no baseline or the working copy cannot be read."""
    state = _load(cwd)
    if state.get("session") != session_id or not state.get("base_tree") or state.get("slow"):
        return None
    snap = _timed(cwd, state, lambda: snapshot(cwd, state.get("head_tree"), timeout=BUDGET))
    if snap is None:
        return None
    now = _pack(snap["diff"], str(_common.repo_root(cwd)))
    base = state.get("base_diff")
    if now is None or base is None:
        changed = snap["tree"] != state["base_tree"]  # too many paths to compare: assume code
    else:
        touched = {k for k in set(now) | set(base) if now.get(k) != base.get(k)}
        changed = any((now.get(k) or base.get(k) or "").endswith(":code") for k in touched)
    verified = state.get("verified")
    return {"code_changed": changed, "verified_exact": None if verified is None else verified == snap["tree"]}
