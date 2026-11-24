"""Calibrated-confidence checker: parse success claims; check evidence."""
from __future__ import annotations

import os
import re
import shlex

from _common import now_ts
from cmdparse import MAX_COMMAND_CHARS
from events import peek_events

SUCCESS_CLAIMS = [
    re.compile(r"\b(?:fixed|resolved|done|works?|working|complete|completed|all set)\b", re.IGNORECASE),
    re.compile(r"\b(?:passes|passing) (?:all )?tests?\b", re.IGNORECASE),
    re.compile(r"\bready to (?:ship|merge|deploy|land)\b", re.IGNORECASE),
    # NOTE: "should X" is intentionally NOT a SUCCESS_CLAIM. "should" is itself a hedge.
]

HEDGES = [
    re.compile(r"\b(?:probably|likely|possibly|may|might|i think|i believe)\b", re.IGNORECASE),
    re.compile(r"\b(?:untested|not (?:yet )?tested|haven['']t (?:run|tested|verified))\b", re.IGNORECASE),
    re.compile(r"\bneeds? (?:verification|testing|review|to be (?:tested|verified))\b", re.IGNORECASE),
    re.compile(r"\bcan't (?:test|verify|run)\b", re.IGNORECASE),
]


def has_unhedged_success_claim(text: str) -> bool:
    if not text:
        return False
    if not any(p.search(text) for p in SUCCESS_CLAIMS):
        return False
    return not any(p.search(text) for p in HEDGES)


def scan_recent(cwd=None, since_ts: int | None = None, window_seconds: int = 1800, tree_view: dict | None = None) -> dict:
    """Single peek_events pass returning the recency facts callers need.

    Replaces N independent `for ev in peek_events(cwd)` loops with one. The
    Stop hook and PreToolUse(Bash) hook each used to call peek_events twice
    per fire (once for last-edit, once for last-pass) which doubled the cold
    JSONL parse cost.
    """
    if since_ts is None:
        since_ts = now_ts() - window_seconds
    return scan_events(peek_events(cwd), since_ts, tree_view)


DOC_EXT = {".md", ".txt", ".rst"}


def edit_scope(path: str, root: str) -> str:
    """Whether an edit is something a test run could verify: ``code`` inside the project,
    ``docs`` (prose files), or ``outside`` the project (notes, config in the home directory)."""
    if not path:
        return "code"  # unknown path: keep asking for evidence
    base = os.path.normpath(root)
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))
    if full != base and not full.startswith(base + os.sep):
        return "outside"
    return "docs" if os.path.splitext(full)[1].lower() in DOC_EXT else "code"


def scan_events(events, since_ts: int, tree_view: dict | None = None) -> dict:
    """The recency facts from an ordered event list. Pure, so tests and the transcript replay
    in bench/gate_replay.py run exactly the logic the hooks run.

    ``tree_view`` (lib/worktree.py ``view``) comes from looking at the working copy, so it sees
    edits made by a shell command, an MCP tool or a checkout that no hook reported. When given,
    it decides whether code changed; and, when a passing run was recorded with its tree, whether
    that run covered exactly this tree. Without a recorded pass tree the event order still decides
    verification.
    """
    last_edit = 0
    last_pass = 0
    passed_since_edit = False
    for ev in events:
        ts = ev.get("ts", 0)
        if ts < since_ts:
            continue
        kind = ev.get("kind")
        if kind == "edit":
            if ev.get("scope", "code") != "code":
                continue  # events from older releases carry no scope and count as code
            last_edit = max(last_edit, ts)
            passed_since_edit = False
        elif kind in ("test_pass", "build_pass"):
            last_pass = max(last_pass, ts)
            passed_since_edit = True
        elif kind in ("test_fail", "build_fail"):
            passed_since_edit = False  # the latest run is red: an earlier pass no longer stands
    has_edit = last_edit > 0
    verified = last_edit == 0 or passed_since_edit
    if tree_view is not None:
        has_edit = bool(tree_view["code_changed"])
        exact = tree_view.get("verified_exact")
        verified = (not has_edit) or (exact if exact is not None else passed_since_edit)
    return {
        "last_edit_ts": last_edit,
        "last_pass_ts": last_pass,
        "has_recent_edit": has_edit,
        "has_recent_test_evidence": last_pass > 0,
        # Event order, not clock seconds: events are appended as they happen, and an edit
        # and the test that follows it routinely land in the same second.
        "verified_since_edit": verified,
    }


def has_recent_test_evidence(cwd=None, since_ts: int | None = None, window_seconds: int = 600) -> bool:
    """True iff a passing test/build event was logged since ``since_ts`` (default last 10 min)."""
    return scan_recent(cwd, since_ts=since_ts, window_seconds=window_seconds)["has_recent_test_evidence"]


def has_recent_edit(cwd=None, since_ts: int | None = None, window_seconds: int = 1800) -> bool:
    return scan_recent(cwd, since_ts=since_ts, window_seconds=window_seconds)["has_recent_edit"]


# Test/build classifiers: proper word boundaries, no cargo-culted "\n"/"$" tokens
_TEST_PATTERNS = [
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\bjest\b", re.IGNORECASE),
    re.compile(r"\bvitest\b", re.IGNORECASE),
    re.compile(r"\bgo\s+test\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+test\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+(?:run\s+)?test\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+t\b", re.IGNORECASE),
    re.compile(r"\byarn\s+(?:run\s+)?test\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(?:run\s+)?test\b", re.IGNORECASE),
    re.compile(r"\bbun\s+test\b", re.IGNORECASE),
    re.compile(r"\brspec\b", re.IGNORECASE),
    re.compile(r"\bmocha\b", re.IGNORECASE),
    re.compile(r"\bphpunit\b", re.IGNORECASE),
    re.compile(r"\bmix\s+test\b", re.IGNORECASE),
    re.compile(r"\brake\s+test\b", re.IGNORECASE),
    re.compile(r"\bginkgo\b", re.IGNORECASE),
    re.compile(r"\bnpx\s+(?:jest|vitest|mocha)\b", re.IGNORECASE),
]
_BUILD_PATTERNS = [
    re.compile(r"\bnpm\s+run\s+build\b", re.IGNORECASE),
    re.compile(r"\byarn\s+build\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(?:run\s+)?build\b", re.IGNORECASE),
    re.compile(r"\bbun\s+(?:run\s+)?build\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+build\b", re.IGNORECASE),
    re.compile(r"\bgo\s+build\b", re.IGNORECASE),
    re.compile(r"\bmake\s+build\b", re.IGNORECASE),
    re.compile(r"\btsc\b", re.IGNORECASE),
    re.compile(r"\b(?:next|vite|webpack)\s+build\b", re.IGNORECASE),
]


_SEPARATORS = {";", "&&", "||", "|", "&"}
_WRAPPERS = {"time", "env", "nice", "nohup", "command", "npx", "bunx"}
_RUN_WRAPPERS = {"uv", "poetry", "pipenv", "pdm", "hatch"}  # `<tool> run <cmd>`
_INFO_ONLY = {"--version", "--help", "-h", "--collect-only", "--co", "--dry-run", "--no-run", "--listTests", "--list-tests", "-list", "--list"}


def _command_start(words: list[str]) -> list[str]:
    """Drop env assignments and runner wrappers so the first word is the tool itself."""
    i = 0
    while i < len(words):
        w = os.path.basename(words[i])
        if "=" in words[i] and not words[i].startswith("-") and words[i].split("=", 1)[0].isidentifier():
            i += 1
        elif w in _WRAPPERS:
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 1
        elif (
            (w == "timeout" and i + 1 < len(words))
            or (w.startswith("python") and words[i + 1 : i + 2] == ["-m"])
            or (w in _RUN_WRAPPERS and words[i + 1 : i + 2] == ["run"])
        ):
            i += 2
        else:
            break
    rest = words[i:]
    return [os.path.basename(rest[0]), *rest[1:]] if rest else rest


def _split_clauses(cmd: str) -> list[tuple[list[str], str | None, str | None]] | None:
    """Clauses of a one-line command as (words, separator before, separator after), or None when the
    command is multi-line, too big to judge, or does not tokenise."""
    if "\n" in cmd.strip() or len(cmd) > MAX_COMMAND_CHARS:
        return None
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    clauses: list[tuple[list[str], str | None, str | None]] = []
    cur: list[str] = []
    before: str | None = None
    for tok in tokens:
        if tok in ("(", ")"):
            continue  # a subshell does not change which clause runs or what its status says
        if tok in _SEPARATORS:
            clauses.append((cur, before, tok))
            cur, before = [], tok
        else:
            cur.append(tok)
    clauses.append((cur, before, None))
    return clauses


# Clauses that may sit between a test and the commit it guards without touching what was tested.
_TREE_NEUTRAL_PROGS = {"cd", "echo", "printf", "true", ":", "pwd", "ls", "cat", "test", "["}
_TREE_NEUTRAL_GIT = ("add", "status", "diff", "log")


def _leaves_tree_alone(words: list[str]) -> bool:
    start = _command_start(words)
    if not start:
        return True
    if start[0] in _TREE_NEUTRAL_PROGS:
        return True
    if start[0] == "git":
        from cmdparse import matches_subcommand
        text = shlex.join(words)
        return any(matches_subcommand(text, prog="git", sub=sub) for sub in _TREE_NEUTRAL_GIT)
    return False


def run_guards_target(cmd: str, is_target) -> bool:
    """True iff ``cmd`` runs a test or build and then a target clause (git commit or push) linked only by
    ``&&``: the target runs only when the run exited 0, so asking for evidence first is a false alarm.
    ``;``, ``||``, a pipe, a background ``&``, a run that comes after the target, a run that may be
    skipped (``false || pytest && ...``) and info-only runs do not count. Anything between the run and the
    target that could change the tested files (``sed -i``, a script, ``make fmt``, ``git stash pop``) ends the
    guard: only cd, echo, git add, status, diff and log and the like may sit there."""
    clauses = _split_clauses(cmd)
    if clauses is None:
        return False
    for t, (words, _, _) in enumerate(clauses):
        if not words or not is_target(shlex.join(words)):
            continue
        j = t
        while j > 0 and clauses[j][1] == "&&":
            j -= 1
            start = _command_start(clauses[j][0])
            if (start and not _INFO_ONLY.intersection(start) and clauses[j][1] in (None, ";", "&&")
                    and any(p.match(" ".join(start)) for p in _TEST_PATTERNS + _BUILD_PATTERNS)):
                return True
            if not _leaves_tree_alone(clauses[j][0]):
                break  # something between the run and the target may have changed what was tested
    return False


def _find_run(cmd: str, patterns: list[re.Pattern], need_status: bool = True) -> list[str] | None:
    """True iff ``cmd`` runs one of ``patterns`` *and* its exit status describes that run.

    The tool must sit in command position (not an argument to grep or echo), must not be
    an info-only call (``--version``), and the shell must report its status: not on either
    side of ``||`` or ``|`` (``pytest | tail`` exits 0 when the tests fail), not followed
    by ``;`` or ``&`` and more work. A chain of ``&&`` is fine: exit 0 means every link
    passed. Multi-line commands are skipped; heredocs make clause splitting a guess.
    """
    clauses = _split_clauses(cmd)
    if clauses is None:
        return None
    for i, (words, sep_before, _) in enumerate(clauses):
        if need_status and sep_before not in (None, ";", "&&"):
            continue
        if need_status and any(sep != "&&" for _, _, sep in clauses[i:] if sep is not None):
            continue
        start = _command_start(words)
        if start and not _INFO_ONLY.intersection(start) and any(p.match(" ".join(start)) for p in patterns):
            return start
    return None


def _runs(cmd: str, patterns: list[re.Pattern]) -> bool:
    return _find_run(cmd, patterns) is not None


_TAIL_BYTES = 8192
# Patterns here run on text a test can print, so each one must be unambiguous (no nested or
# overlapping repetition): `\w+` would also match the digits of the next item.
_PYTEST = re.compile(r"(?m)^[= ]*(\d+ [a-z]+(?:, \d+ [a-z]+)*) in [\d.]+s")
_CARGO = re.compile(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed")
_JEST = re.compile(r"(?m)^[ \t]*Tests:?[ \t]+(.*)$")
_SUMMARY_TOOLS = {"pytest": "pytest", "cargo": "cargo", "go": "go", "jest": "jest", "vitest": "jest"}


# A run that exits 0 without running a test is not evidence: go test with no test files, cargo test with zero
# tests, jest --passWithNoTests, an empty rspec or mocha run. Words in a log do not decide it: any count of
# tests that did run wins. Single pass over the output tail, no nested repetition.
_NOTHING_RAN = re.compile(
    r"(?im)no tests? found|no test files found|no tests executed|no tests to run|no tests ran|running 0 tests"
    r"|^[ \t]*0 examples, 0 failures|^[ \t]*0 passing\b|\[no test files\]")
_SOMETHING_RAN = re.compile(
    r"(?m)\b[1-9]\d* (?:passed|passing|examples?)\b|^ok[ \t]+\S+[ \t]+(?:[\d.]+s|\(cached\))(?:[ \t]*\(cached\))?[ \t]*$"
    r"|test result: ok\. [1-9]\d* passed")


def _nothing_ran(output: str) -> bool:
    tail = output[-_TAIL_BYTES:]
    return bool(_NOTHING_RAN.search(tail)) and not _SOMETHING_RAN.search(tail)


def _summary_verdict(output: str, start: list[str]) -> str | None:
    """``pass`` or ``fail`` from the runner's own closing summary, else None. Only the tail of
    the output is read, and only tools whose summary format is known."""
    tool = _SUMMARY_TOOLS.get(start[0].lower())
    tail = output[-_TAIL_BYTES:]
    if tool == "pytest":
        found = _PYTEST.findall(tail)
        counts = {w: int(n) for n, w in re.findall(r"(\d+) (\w+)", found[-1])} if found else {}
        if counts.get("failed") or counts.get("error") or counts.get("errors"):
            return "fail"
        return "pass" if counts.get("passed") else None
    if tool == "cargo":
        results = _CARGO.findall(tail)
        if any(r[0] == "FAILED" or int(r[2]) for r in results):
            return "fail"
        return "pass" if any(int(r[1]) for r in results) else None
    if tool == "go":
        lines = tail.splitlines()
        if any(ln.startswith(("FAIL", "--- FAIL")) for ln in lines):
            return "fail"
        return "pass" if any(ln.startswith("ok") for ln in lines) else None
    if tool == "jest":
        found = _JEST.findall(tail)
        if not found:
            return None
        return "fail" if "failed" in found[-1] else "pass" if "passed" in found[-1] else None
    return None


def classify_command(cmd: str | None, exit_code, output: str | None = None) -> str | None:
    """Return ``test_pass``/``test_fail``/``build_pass``/``build_fail`` or ``None``.

    If ``exit_code`` is missing/unparseable, returns ``None`` and refuses to classify
    (so a failed test cannot be silently logged as a pass).

    When the exit status cannot describe the run (``pytest | tail``, ``pytest || true``) but a
    test tool is in command position and the command exited 0, the runner's own summary line in
    ``output`` decides. A summary that is missing or unreadable leaves the run unclassified.
    """
    if not cmd:
        return None
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        return None
    is_test = _runs(cmd, _TEST_PATTERNS)
    is_build = _runs(cmd, _BUILD_PATTERNS)
    if is_test and code == 0 and output and _nothing_ran(output):
        return None  # exit 0, but no test ran: neither a pass nor a failure
    if is_test or is_build:
        kind = "test" if is_test else "build"
        return f"{kind}_{'pass' if code == 0 else 'fail'}"
    if output and code == 0:
        run = _find_run(cmd, _TEST_PATTERNS, need_status=False)
        verdict = _summary_verdict(output, run) if run else None
        if verdict:
            return f"test_{verdict}"
    return None
