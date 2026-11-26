"""Can a claim in this repository ever be verified? Without a runner the gate recognises, it can only nag."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from testinfra import can_be_verified


def _w(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


POSITIVE = [
    ("pytest.ini", "[pytest]\n"),
    ("conftest.py", ""),
    ("tests/test_a.py", "def test_a(): pass\n"),
    ("pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-q'\n"),
    ("setup.cfg", "[tool:pytest]\n"),
    ("package.json", json.dumps({"scripts": {"test": "jest"}})),
    ("package.json", json.dumps({"scripts": {"build": "tsc"}})),
    ("package.json", json.dumps({"devDependencies": {"vitest": "^2"}})),
    ("jest.config.js", "module.exports = {}\n"),
    ("tsconfig.json", "{}"),
    ("go.mod", "module x\n"),
    ("Cargo.toml", "[package]\nname='x'\n"),
    (".rspec", ""),
    ("phpunit.xml", "<phpunit/>"),
    ("mix.exs", ""),
    ("Rakefile", ""),
    ("Makefile", "build:\n\tcc x.c\n"),
    ("web/package.json", json.dumps({"scripts": {"test": "vitest run"}})),
]


@pytest.mark.parametrize(("rel", "text"), POSITIVE, ids=[p[0] + ":" + p[1][:12] for p in POSITIVE])
def test_a_recognised_runner_makes_claims_verifiable(tmp_path, rel, text):
    _w(tmp_path, rel, text)
    assert can_be_verified(tmp_path) is True


NEGATIVE = [
    [("README.md", "# x\n")],
    [],
    [("package.json", json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))],
    [("package.json", json.dumps({"name": "x"}))],
    [("Makefile", "clean:\n\trm -f x\n")],
    [("build.gradle", ""), ("gradlew", "")],  # a runner presence does not recognise cannot produce evidence
    [("node_modules/pkg/package.json", json.dumps({"scripts": {"test": "jest"}}))],
    [(".git/hooks/pytest.ini", "")],
    [("docs/notes.md", "tests are discussed here\n"), ("src/main.c", "int main(){}\n")],
]


@pytest.mark.parametrize("files", NEGATIVE, ids=[str(i) for i in range(len(NEGATIVE))])
def test_without_a_recognised_runner_nothing_can_be_verified(tmp_path, files):
    for rel, text in files:
        _w(tmp_path, rel, text)
    assert can_be_verified(tmp_path) is False


def test_the_check_looks_at_the_repository_root_from_a_subdirectory(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _w(tmp_path, "pytest.ini", "[pytest]\n")
    (tmp_path / "src" / "deep").mkdir(parents=True)
    assert can_be_verified(tmp_path / "src" / "deep") is True


def test_a_broken_marker_file_does_not_raise(tmp_path):
    _w(tmp_path, "package.json", "{not json")
    assert can_be_verified(tmp_path) is False


def test_a_huge_marker_file_is_read_in_bounded_time(tmp_path):
    import time
    _w(tmp_path, "pyproject.toml", "x" * 20_000_000)
    start = time.monotonic()
    can_be_verified(tmp_path)
    assert time.monotonic() - start < 2.0


def test_many_subdirectories_are_checked_in_bounded_time(tmp_path):
    import time
    for i in range(3000):
        (tmp_path / f"d{i}").mkdir()
    start = time.monotonic()
    can_be_verified(tmp_path)
    assert time.monotonic() - start < 2.0


@pytest.mark.parametrize(
    "package",
    [
        {"dependencies": "x"}, {"devDependencies": 5}, {"dependencies": ["a"]}, {"dependencies": None, "devDependencies": None},
        {"scripts": []}, {"scripts": {"test": 5}}, {"scripts": "jest"}, [], "text", 5, None,
        {"dependencies": {"a": 1}, "devDependencies": "x"},
    ],
    ids=lambda p: json.dumps(p)[:30],
)
def test_a_malformed_package_json_is_judged_without_raising(tmp_path, package):
    """The repository is untrusted input: whatever its package.json holds, the check answers, never raises."""
    _w(tmp_path, "package.json", json.dumps(package))
    assert can_be_verified(tmp_path) is False


def test_a_runner_dependency_still_counts_next_to_a_malformed_sibling_field(tmp_path):
    _w(tmp_path, "package.json", json.dumps({"dependencies": "x", "devDependencies": {"vitest": "^2"}}))
    assert can_be_verified(tmp_path) is True


@pytest.mark.skipif(__import__("os").geteuid() == 0, reason="root can read a mode 000 directory")
def test_a_directory_that_cannot_be_read_is_skipped_not_fatal(tmp_path):
    """A root-owned data folder inside the repository must not make the check raise."""
    import os
    locked = tmp_path / "locked"
    locked.mkdir()
    _w(locked, "package.json", json.dumps({"scripts": {"test": "jest"}}))
    os.chmod(locked, 0)
    try:
        assert can_be_verified(tmp_path) is False
        _w(tmp_path, "pytest.ini", "[pytest]\n")
        assert can_be_verified(tmp_path) is True  # a readable marker elsewhere still counts
    finally:
        os.chmod(locked, 0o700)


def test_a_large_package_json_is_not_cut_in_the_middle_and_misjudged(tmp_path):
    big = {"scripts": {"test": "jest"}, "description": "x" * 300_000}
    _w(tmp_path, "package.json", json.dumps(big))
    assert can_be_verified(tmp_path) is True


def test_an_oversized_package_json_is_still_bounded(tmp_path):
    import time
    _w(tmp_path, "package.json", "[" * 5_000_000)
    start = time.monotonic()
    assert can_be_verified(tmp_path) is False
    assert time.monotonic() - start < 2.0


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
@pytest.mark.parametrize("name", ["Makefile", "pyproject.toml", "setup.cfg", "package.json"])
def test_a_marker_that_is_a_named_pipe_does_not_hang_the_check(tmp_path, name):
    """The repository is hostile input: reading a FIFO named like a marker would block the hook for good."""
    import subprocess
    import sys
    os.mkfifo(tmp_path / name)
    code = "import sys; sys.path.insert(0, sys.argv[1]); from testinfra import can_be_verified; print(can_be_verified(sys.argv[2]))"
    lib = str(Path(__file__).resolve().parent.parent / "lib")
    out = subprocess.run([sys.executable, "-c", code, lib, str(tmp_path)], capture_output=True, text=True, timeout=10, check=False)
    assert out.stdout.strip() == "False"
