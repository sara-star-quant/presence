"""Replay Claude Code session transcripts through the confidence gate and report how it does.

    python3 bench/gate_replay.py ~/.claude/projects [--sample N]

Local only. The output is counts and rates: no message text, paths or commands.

Definitions (fixed before any result was read; change them and the numbers are no longer
comparable, so bump this note and say why):

- Unit: a Stop turn, the assistant output between two real user prompts. Its final text is
  the last assistant text block.
- claim: ``verify.has_unhedged_success_claim`` on that text.
- eligible: a claim with an edit in the previous 30 minutes. The gate only acts on these.
- fired: eligible and ``verify.scan_events`` says not verified since the last edit. That is
  the Stop hook's own condition, run through the same function.
- Exit status: a tool result with ``is_error`` is a failure; a command runs through
  ``verify.classify_command`` with its output, exactly as the Bash hook does.
- Outcome: the first test or build run after the claim and before any later edit, same session.
  A failure is ``false_done``, a pass is ``true_done``, nothing is ``unresolved``. The tree has
  not changed since the claim, so a later failure means the work was not done when it was said.
- edit_class: the strongest ``verify.edit_scope`` among the edits in the window: ``code``, else
  ``docs`` (.md, .txt, .rst), else ``outside`` (not under the session cwd). Only ``code`` edits make
  the gate fire, so a class other than ``code`` has fired = 0 by construction.
- No rate is printed for a group with fewer than 30 resolved turns.

Revision note: the first run (shipped v0.11.3 logic: strict exit-status rules, any edit counts)
found 0 of 131 eligible turns ever verified, because 318 of 400 genuine test runs were piped and
dropped, and 111 of 131 eligible turns were edits to docs or outside the project. The runner-summary
rule and edit scope came from that finding, and these definitions follow the shipped gate. The first
run's numbers are the baseline; later runs are not comparable with it by design.

Threats to validity, stated so a reader can discount the numbers: agents test after a claim
mostly when unsure (selection), a later failure can be flaky or unrelated, sessions run with
``stop_action=block`` include the gate's own nudge, and the 30-minute window is the live one.
The bounds columns assume every unresolved turn went one way, then the other.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from verify import classify_command, edit_scope, has_unhedged_success_claim, scan_events  # noqa: E402

WINDOW = 1800
MIN_RESOLVED = 30
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CLASSES = ("code", "docs", "outside")


def _epoch(entry: dict) -> float:
    try:
        return datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return 0.0


def _is_prompt(entry: dict) -> bool:
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and any(b.get("type") == "text" for b in content) and not any(
        b.get("type") == "tool_result" for b in content)


def _read(path: Path) -> tuple[list[dict], int]:
    entries, skipped = [], 0
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if not isinstance(obj, dict):
            skipped += 1
        elif not obj.get("isSidechain"):
            entries.append(obj)
    return entries, skipped


def _events(entries: list[dict]) -> list[dict]:
    """Edits, classified runs and one ``final`` per turn, in transcript order."""
    failed: dict[str, bool] = {}
    output: dict[str, str] = {}
    for e in entries:
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "user" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tid = b.get("tool_use_id", "")
                    failed[tid] = bool(b.get("is_error"))
                    body = b.get("content")
                    output[tid] = body if isinstance(body, str) else "\n".join(
                        x.get("text", "") for x in body if isinstance(x, dict)) if isinstance(body, list) else ""

    events: list[dict] = []
    final: dict | None = None
    for e in entries:
        ts = _epoch(e)
        if _is_prompt(e):
            if final:
                events.append(final)
            final = None
            continue
        content = (e.get("message") or {}).get("content")
        if e.get("type") != "assistant" or not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and str(b.get("text", "")).strip():
                final = {"kind": "final", "ts": ts, "text": b["text"], "cwd": e.get("cwd") or ""}
            elif b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS:
                inp = b.get("input") or {}
                path = inp.get("file_path") or inp.get("notebook_path") or ""
                events.append({"kind": "edit", "ts": ts, "path": path, "scope": edit_scope(path, e.get("cwd") or "/")})
            elif b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = (b.get("input") or {}).get("command", "")
                kind = classify_command(cmd, 1 if failed.get(b.get("id", "")) else 0, output.get(b.get("id", "")))
                if kind:
                    events.append({"kind": kind, "ts": ts})
    if final:
        events.append(final)
    return events


def _outcome(later: list[dict]) -> str:
    for ev in later:
        if ev["kind"] == "edit":
            break
        if ev["kind"] in ("test_pass", "build_pass"):
            return "true_done"
        if ev["kind"] in ("test_fail", "build_fail"):
            return "false_done"
    return "unresolved"


def replay(path: Path) -> tuple[list[dict], int]:
    """Turns for one transcript, and the number of lines that could not be read."""
    entries, skipped = _read(path)
    events = _events(entries)
    sid = hashlib.sha256(str(path).encode()).hexdigest()[:8]
    turns = []
    for i, ev in enumerate(events):
        if ev["kind"] != "final":
            continue
        history = [x for x in events[:i] if x["kind"] != "final"]
        scan = scan_events(history, ev["ts"] - WINDOW)
        claim = has_unhedged_success_claim(ev["text"])
        scopes = {x["scope"] for x in history if x["kind"] == "edit" and x["ts"] >= ev["ts"] - WINDOW}
        turns.append({
            "id": f"{sid}:{i}", "session": sid, "claim": claim,
            "eligible": claim and bool(scopes),
            "fired": claim and scan["has_recent_edit"] and not scan["verified_since_edit"],
            "edit_class": "code" if "code" in scopes else "docs" if "docs" in scopes else "outside" if scopes else "none",
            "outcome": _outcome(events[i + 1:]),
        })
    return turns, skipped


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k of n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def _counts(rows: list[dict]) -> dict:
    c = {"false_done": 0, "true_done": 0, "unresolved": 0}
    for r in rows:
        c[r["outcome"]] += 1
    return c


def _risk_ratio(rows: list[dict], resamples: int = 2000) -> tuple[float, float, float] | None:
    """False-done rate among fired over the rate among not fired, with a bootstrap over sessions."""
    def rr(sample: list[dict]) -> float | None:
        f = [r for r in sample if r["fired"] and r["outcome"] != "unresolved"]
        n = [r for r in sample if not r["fired"] and r["outcome"] != "unresolved"]
        if not f or not n:
            return None
        pn = sum(r["outcome"] == "false_done" for r in n) / len(n)
        return None if pn == 0 else (sum(r["outcome"] == "false_done" for r in f) / len(f)) / pn

    point = rr(rows)
    if point is None:
        return None
    by_session: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_session[r["session"]].append(r)
    keys, rng, draws = list(by_session), random.Random(0), []  # noqa: S311  seeded: reproducible, not security
    for _ in range(resamples):
        v = rr([r for k in (rng.choice(keys) for _ in keys) for r in by_session[k]])
        if v is not None:
            draws.append(v)
    if len(draws) < resamples // 2:
        return None
    draws.sort()
    return point, draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]


def summarize(turns: list[dict]) -> str:
    out = ["Gate replay summary", "",
           "Eligible turns: a success claim with an edit in the previous 30 minutes.", "",
           "| class | eligible | fired | fire rate | fired: false / true / unresolved | not fired: false / true / unresolved | false-done rate, fired | not fired |",
           "|---|---|---|---|---|---|---|---|"]
    for cls in CLASSES:
        rows = [t for t in turns if t["eligible"] and t["edit_class"] == cls]
        fired = [t for t in rows if t["fired"]]
        quiet = [t for t in rows if not t["fired"]]
        fc, qc = _counts(fired), _counts(quiet)

        def rate(c: dict) -> str:
            n = c["false_done"] + c["true_done"]
            if n < MIN_RESOLVED:
                return f"not enough evidence ({n} resolved)"
            lo, hi = wilson(c["false_done"], n)
            return f"{c['false_done'] / n:.0%} ({lo:.0%} to {hi:.0%}, n={n})"

        fire = f"{len(fired) / len(rows):.0%}" if rows else "n/a"
        out.append(f"| {cls} | {len(rows)} | {len(fired)} | {fire} | {fc['false_done']} / {fc['true_done']} / {fc['unresolved']} "
                   f"| {qc['false_done']} / {qc['true_done']} / {qc['unresolved']} | {rate(fc)} | {rate(qc)} |")
    code = [t for t in turns if t["eligible"] and t["edit_class"] == "code"]
    rr = _risk_ratio(code) if sum(t["outcome"] != "unresolved" for t in code) >= MIN_RESOLVED else None
    out += ["", "Risk ratio, code edits (false-done rate when fired over when not; 95% bootstrap over sessions): "
            + (f"{rr[0]:.2f} ({rr[1]:.2f} to {rr[2]:.2f})" if rr else "not enough evidence")]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("projects", type=Path)
    ap.add_argument("--sample", type=int, default=0, help="print this many ids of fired code turns for hand labelling")
    args = ap.parse_args()
    files = sorted(args.projects.glob("*/*.jsonl"))
    turns, skipped = [], 0
    for f in files:
        t, s = replay(f)
        turns += t
        skipped += s
    print(summarize(turns))
    print(f"\nTranscripts: {len(files)}; turns: {len(turns)}; claims: {sum(t['claim'] for t in turns)}; unreadable lines skipped: {skipped}")
    if args.sample:
        pool = [t["id"] for t in turns if t["fired"] and t["edit_class"] == "code"]
        print("Sample for hand labelling:", ", ".join(random.Random(0).sample(pool, min(args.sample, len(pool)))))  # noqa: S311


if __name__ == "__main__":
    main()
