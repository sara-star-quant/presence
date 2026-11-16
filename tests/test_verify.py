"""Confidence-gate logic: claim parsing + command classification."""
import pytest
from verify import classify_command, has_unhedged_success_claim


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Fixed the bug.", True),
        ("It works now.", True),
        ("Done. Passing all tests.", True),
        ("Probably works.", False),
        ("I think this is done.", False),
        ("This should fix it.", False),
        ("Untested but should work.", False),
        ("Made the change. Needs testing.", False),
        ("", False),
        ("Refactored the auth flow.", False),
    ],
)
def test_has_unhedged_success_claim(text, expected):
    assert has_unhedged_success_claim(text) is expected


@pytest.mark.parametrize(
    "cmd, exit_code, expected",
    [
        ("pytest tests/", 0, "test_pass"),
        ("pytest tests/", 1, "test_fail"),
        ("npm test", 0, "test_pass"),
        ("npm run build", 0, "build_pass"),
        ("npm run build", 2, "build_fail"),
        ("cargo test", 0, "test_pass"),
        ("tsc --noEmit", 0, "build_pass"),
        ("ls -la", 0, None),
        ("git status", 0, None),
        ("npx jest", 0, "test_pass"),
        # Unparseable exit code -> refuse to classify (safe default)
        ("pytest", "weird", None),
        ("pytest", None, None),
    ],
)
def test_classify_command(cmd, exit_code, expected):
    assert classify_command(cmd, exit_code) == expected


@pytest.mark.parametrize(
    "cmd, expected",
    [
        # mentions the tool but does not run it
        ("grep -rn pytest docs", None),
        ("echo pytest", None),
        ("cat tests/test_pytest_plugin.py", None),
        ("git log --grep='npm test'", None),
        ("pip install pytest", None),
        ("sed -i 's/pytest/x/' a.py", None),
        ("python3 - <<'EOF'\nimport pytest\nEOF", None),
        # runs the tool but proves nothing
        ("pytest --version", None),
        ("pytest --help", None),
        ("pytest --collect-only", None),
        # exit code does not describe the test run
        ("pytest || true", None),
        ("pytest 2>&1 | tail -5", None),
        ("npm test | tee out.log", None),
        ("pytest; echo done", None),
        ("ls || pytest", None),
        ("pytest &", None),
        # real runs, through the wrappers and chains agents actually use
        ("cd repo && pytest -q", "test_pass"),
        ("ls; cargo test", "test_pass"),
        ("pytest -x && ruff check .", "test_pass"),
        ("FOO=1 pytest", "test_pass"),
        (".venv/bin/python -m pytest -q", "test_pass"),
        ("uv run pytest", "test_pass"),
        ("./node_modules/.bin/jest", "test_pass"),
        ("timeout 60 go test ./...", "test_pass"),
        ("pytest -n 4", "test_pass"),
    ],
)
def test_classify_requires_a_real_run(cmd, expected):
    assert classify_command(cmd, 0) == expected


def test_classify_chain_failure_is_a_fail():
    assert classify_command("cd repo && pytest", 1) == "test_fail"


def test_classify_empty_command():
    assert classify_command("", 0) is None
    assert classify_command(None, 0) is None


@pytest.mark.parametrize(
    ("kinds", "verified"),
    [
        ([], True),  # no edits: nothing to verify
        (["test_pass"], True),
        (["edit"], False),
        (["edit", "test_pass"], True),  # same clock second is fine: order decides
        (["test_pass", "edit"], False),  # a pass before the edit is not verification
        (["edit", "test_pass", "edit"], False),
        (["edit", "test_fail"], False),
        (["edit", "build_pass"], True),
    ],
)
def test_verified_since_edit_follows_event_order(isolated_state, fake_repo, kinds, verified):
    from events import append_event
    from verify import scan_recent

    for kind in kinds:
        append_event({"kind": kind}, cwd=str(fake_repo))
    assert scan_recent(str(fake_repo))["verified_since_edit"] is verified


# --- runner output as evidence when the exit status is not reliable ---------------------------

PYTEST_OK = "...........\n20 passed in 22.45s\n"
PYTEST_RED = "FAILED tests/test_a.py::test_x - assert 1 == 2\n1 failed, 13 passed in 1.22s\n"


@pytest.mark.parametrize(
    "cmd, output, expected",
    [
        ("pytest -q 2>&1 | tail -5", PYTEST_OK, "test_pass"),
        ("pytest -q 2>&1 | tail -5", PYTEST_RED, "test_fail"),  # pipe exits 0 on a red run
        ("python -m pytest || true", PYTEST_RED, "test_fail"),
        ("pytest -x; echo done", "1 error in 0.20s\n", "test_fail"),
        ("pytest | tee out.log", "== 630 passed, 13 skipped in 335.78s (0:05:35) ==\n", "test_pass"),
        ("cargo test 2>&1 | tail -20", "test result: ok. 3 passed; 0 failed; 0 ignored\n", "test_pass"),
        ("cargo test 2>&1 | tail -20", "test result: ok. 3 passed; 0 failed\ntest result: FAILED. 2 passed; 1 failed\n", "test_fail"),
        ("go test ./... | tail", "ok  \tpkg/a\t0.2s\nFAIL\tpkg/b\t0.1s\n", "test_fail"),
        ("go test ./... | tail", "ok  \tpkg/a\t0.2s\nok  \tpkg/b\t0.1s\n", "test_pass"),
        ("npx jest | tail", "Tests:       1 failed, 4 passed, 5 total\n", "test_fail"),
        ("npx vitest run | tail", " Tests  4 passed (4)\n", "test_pass"),
        # no usable summary, or nothing that proves a run
        ("pytest | tail -3", "", None),
        ("pytest | tail -3", "no tests ran in 0.10s\n", None),
        ("pytest | tail -3", "5 passed was my guess\n", None),
        # the output of something that is not the runner proves nothing
        ("echo '5 passed in 1.0s'", "5 passed in 1.0s\n", None),
        ("grep pytest docs | tail", "5 passed in 1.0s\n", None),
        ("pytest --version | cat", "20 passed in 1.0s\n", None),
    ],
)
def test_classify_reads_the_runner_summary_when_the_status_is_unreliable(cmd, output, expected):
    assert classify_command(cmd, 0, output) == expected


def test_a_reliable_status_still_beats_the_output():
    assert classify_command("pytest -q", 1, PYTEST_OK) == "test_fail"
    assert classify_command("pytest -q", 0, PYTEST_RED) == "test_pass"  # unchanged: the exit code is authoritative


def test_output_is_ignored_when_a_piped_command_did_not_exit_zero():
    """pytest | grep nothing exits 1 from grep; that is a disagreement, so unknown."""
    assert classify_command("pytest | grep nothing", 1, PYTEST_OK) is None


def test_only_the_tail_of_a_large_output_is_read():
    noisy = "5 failed in 1.0s\n" + "x" * 200_000 + "\n" + PYTEST_OK
    assert classify_command("pytest | tail -200", 0, noisy) == "test_pass"


# --- which edits need verification -------------------------------------------------------------

@pytest.mark.parametrize("path, expected", [
    ("/w/repo/lib/a.py", "code"),
    ("lib/a.py", "code"),
    ("/w/repo/README.md", "docs"),
    ("/w/repo/notes.txt", "docs"),
    ("/home/u/.claude/memory/x.md", "outside"),
    ("/w/other/a.py", "outside"),
    ("/w/repo-evil/a.py", "outside"),
])
def test_edit_scope(path, expected):
    from verify import edit_scope
    assert edit_scope(path, "/w/repo") == expected


def test_only_code_edits_make_work_unverified():
    from verify import scan_events
    docs = [{"kind": "edit", "ts": 10, "scope": "docs"}, {"kind": "edit", "ts": 11, "scope": "outside"}]
    assert scan_events(docs, 0)["has_recent_edit"] is False
    assert scan_events([{"kind": "edit", "ts": 10}], 0)["has_recent_edit"] is True  # events from older releases carry no scope
    code_then_docs = [{"kind": "edit", "ts": 10, "scope": "code"}, {"kind": "edit", "ts": 11, "scope": "docs"}]
    assert scan_events(code_then_docs, 0)["verified_since_edit"] is False
    assert scan_events(code_then_docs + [{"kind": "test_pass", "ts": 12}], 0)["verified_since_edit"] is True


@pytest.mark.parametrize("hostile", [
    "9 " + "009 " * 2000 + "x",                      # ambiguous repetition in the pytest summary pattern
    "1 passed, " * 800 + "x",
    "\n" * 8000 + "  " * 100,                        # whitespace runs before a jest "Tests:" line
    " " * 8000 + "\n" + " " * 8000,
    "test result: ok. " + "9" * 8000,
])
def test_hostile_runner_output_cannot_stall_the_hook(hostile):
    """Runner output is text a test can print, so every summary pattern must be linear on it."""
    import time
    start = time.perf_counter()
    for cmd in ("pytest | tail", "cargo test | tail", "go test ./... | tail", "npx jest | tail"):
        assert classify_command(cmd, 0, hostile) is None
    assert time.perf_counter() - start < 1.0


# --- the tree view overrides what edit events say ------------------------------------------------

@pytest.mark.parametrize("view, events, edited, verified", [
    ({"code_changed": True, "verified_exact": False}, [], True, False),                    # an edit no hook saw
    ({"code_changed": True, "verified_exact": True}, [{"kind": "edit", "ts": 5}], True, True),
    ({"code_changed": False, "verified_exact": None}, [{"kind": "edit", "ts": 5}], False, True),  # edited, then put back
    ({"code_changed": True, "verified_exact": None}, [{"kind": "edit", "ts": 5}], True, False),   # no tree recorded for any pass
    ({"code_changed": True, "verified_exact": None}, [{"kind": "edit", "ts": 5}, {"kind": "test_pass", "ts": 6}], True, True),
    ({"code_changed": True, "verified_exact": False}, [{"kind": "edit", "ts": 5}, {"kind": "test_pass", "ts": 6}], True, False),
])
def test_scan_events_trusts_the_tree_when_it_has_one(view, events, edited, verified):
    from verify import scan_events
    out = scan_events(events, 0, view)
    assert (out["has_recent_edit"], out["verified_since_edit"]) == (edited, verified)


def test_without_a_tree_view_the_event_logic_is_unchanged():
    from verify import scan_events
    assert scan_events([{"kind": "edit", "ts": 5}], 0)["verified_since_edit"] is False
    assert scan_events([{"kind": "edit", "ts": 5}, {"kind": "test_pass", "ts": 6}], 0, None)["verified_since_edit"] is True
