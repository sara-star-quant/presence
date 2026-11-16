"""Calibrated-confidence checker: parse success claims; check evidence."""
from __future__ import annotations

import os
import re
import shlex

from _common import now_ts
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


def scan_recent(cwd=None, since_ts: int | None = None, window_seconds: int = 1800) -> dict:
    """Single peek_events pass returning the recency facts callers need.

    Replaces N independent `for ev in peek_events(cwd)` loops with one. The
    Stop hook and PreToolUse(Bash) hook each used to call peek_events twice
    per fire (once for last-edit, once for last-pass) which doubled the cold
    JSONL parse cost.
    """
    if since_ts is None:
        since_ts = now_ts() - window_seconds
    return scan_events(peek_events(cwd), since_ts)


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


def scan_events(events, since_ts: int) -> dict:
    """The recency facts from an ordered event list. Pure, so tests and the transcript replay
    in bench/gate_replay.py run exactly the logic the hooks run."""
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
    return {
        "last_edit_ts": last_edit,
        "last_pass_ts": last_pass,
        "has_recent_edit": last_edit > 0,
        "has_recent_test_evidence": last_pass > 0,
        # Event order, not clock seconds: events are appended as they happen, and an edit
        # and the test that follows it routinely land in the same second.
        "verified_since_edit": last_edit == 0 or passed_since_edit,
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
_INFO_ONLY = {"--version", "--help", "-h", "--collect-only", "--co", "--dry-run"}


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


def _find_run(cmd: str, patterns: list[re.Pattern], need_status: bool = True) -> list[str] | None:
    """True iff ``cmd`` runs one of ``patterns`` *and* its exit status describes that run.

    The tool must sit in command position (not an argument to grep or echo), must not be
    an info-only call (``--version``), and the shell must report its status: not on either
    side of ``||`` or ``|`` (``pytest | tail`` exits 0 when the tests fail), not followed
    by ``;`` or ``&`` and more work. A chain of ``&&`` is fine: exit 0 means every link
    passed. Multi-line commands are skipped; heredocs make clause splitting a guess.
    """
    if "\n" in cmd.strip():
        return None
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    clauses: list[tuple[list[str], str | None, str | None]] = []  # words, separator before, after
    cur: list[str] = []
    before: str | None = None
    for tok in tokens:
        if tok in _SEPARATORS:
            clauses.append((cur, before, tok))
            cur, before = [], tok
        else:
            cur.append(tok)
    clauses.append((cur, before, None))
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
    if is_test or is_build:
        kind = "test" if is_test else "build"
        return f"{kind}_{'pass' if code == 0 else 'fail'}"
    if output and code == 0:
        run = _find_run(cmd, _TEST_PATTERNS, need_status=False)
        verdict = _summary_verdict(output, run) if run else None
        if verdict:
            return f"test_{verdict}"
    return None
