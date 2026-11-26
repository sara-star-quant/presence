"""Can a claim in this repository ever be verified?

The gate counts a passing run of a test or build tool it recognises (lib/verify.py). In a repository that has no
such runner it can never be satisfied, so it would flag every code claim for good. This looks for the markers
of those runners, in the repository root, the working directory and one level below (a monorepo keeps its
package.json in a subfolder), and nothing else: it never runs anything and reads a marker file only up to 64 KB.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_SKIP = {"node_modules", "venv", ".venv", "target", "dist", "build", "__pycache__", "vendor", "site-packages"}
_MAX_SUBDIRS = 200
_READ = 65536
_PKG_READ = 1_000_000  # a package.json cut in the middle does not parse, so it gets more room than the other markers
_NPM_PLACEHOLDER = re.compile(r"no test specified")
_FILES = (
    "pytest.ini", "conftest.py", "tsconfig.json", "go.mod", "Cargo.toml", ".rspec", "phpunit.xml", "phpunit.xml.dist",
    "mix.exs", "Rakefile", "jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs",
    "vitest.config.js", "vitest.config.ts", "vitest.config.mjs",
)
_TEST_DIRS = ("tests", "test", "spec", "__tests__")
_JS_RUNNERS = ("jest", "vitest", "mocha")


def _text(p: Path, limit: int = _READ) -> str:
    if not p.is_file():  # a named pipe or device named like a marker would block the read for good
        return ""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _mapping(value) -> dict:
    """A field of an untrusted package.json as a dict, or an empty one: the file may hold any JSON."""
    return value if isinstance(value, dict) else {}


def _has_runner(d: Path) -> bool:
    if any((d / name).exists() for name in _FILES) or any((d / name).is_dir() for name in _TEST_DIRS):
        return True
    if any(re.search(r"\bpytest\b", _text(d / name)) for name in ("pyproject.toml", "setup.cfg")):
        return True
    if re.search(r"(?m)^build:", _text(d / "Makefile")):
        return True
    pkg = d / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(_text(pkg, _PKG_READ))
        except (ValueError, RecursionError):
            return False
        if not isinstance(data, dict):
            return False
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        test = scripts.get("test")
        if isinstance(test, str) and test.strip() and not _NPM_PLACEHOLDER.search(test):
            return True
        if scripts.get("build"):
            return True
        deps = {**_mapping(data.get("dependencies")), **_mapping(data.get("devDependencies"))}
        return any(name in deps for name in _JS_RUNNERS)
    return False


def _readable_runner(d: Path) -> bool:
    """_has_runner, treating a directory that cannot be read (permissions, a vanished folder) as having none."""
    try:
        return _has_runner(d)
    except OSError:
        return False


def can_be_verified(cwd) -> bool:
    """True when the repository (or the directory) holds a marker of a runner the gate recognises."""
    from _common import repo_root
    here = Path(cwd)
    roots = {here}
    try:
        roots.add(Path(repo_root(cwd)))
    except (OSError, ValueError):
        roots = {here}  # a repository we cannot resolve is judged by the directory alone
    seen: list[Path] = []
    for root in roots:
        seen.append(root)
        try:
            subs = [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".") and p.name not in _SKIP]
        except OSError:
            continue
        seen.extend(subs[:_MAX_SUBDIRS])
    return any(_readable_runner(d) for d in seen)
