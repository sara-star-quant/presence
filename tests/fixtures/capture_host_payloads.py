"""Capture real hook payloads from the installed Claude Code into tests/fixtures/host/.

    python tests/fixtures/capture_host_payloads.py

Builds a throwaway plugin whose hooks write their stdin to disk, then drives a few
short headless sessions (the cheapest model, a scratch repo) that exercise every event
and matcher presence subscribes to. It uses your logged-in Claude Code, so it spends a
few cents. Session ids, paths and ids are replaced with fixed values; everything else is
kept as the host sent it. Output goes to tests/fixtures/host/<claude --version>/. Add a
new directory when the host changes; do not edit an old one.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "fixtures" / "host"
EVENTS = {  # name -> (event, matcher)
    "session_start": ("SessionStart", None),
    "user_prompt_submit": ("UserPromptSubmit", None),
    "pre_tool_bash": ("PreToolUse", "Bash"),
    "post_tool_bash": ("PostToolUse", "Bash"),
    "post_tool_edit": ("PostToolUse", "Edit|Write|MultiEdit"),
    "post_tool_bash_failure": ("PostToolUseFailure", "Bash"),
    "stop": ("Stop", None),
}
SESSIONS = [
    "Use the Write tool to create a.txt containing the word hi, then use the Bash tool to run: echo ok. Reply with the single word done.",
    "Using the Bash tool, run these commands one at a time, in order, and do not retry any: "
    "(1) git commit --allow-empty -m probe  (2) python -m pytest --version  "
    "(3) python -m pytest no_such_test.py -q  (4) git push origin main . Reply with the single word done.",
]


def main() -> None:
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=True).stdout.split()[0]
    tmp = Path(tempfile.mkdtemp(prefix="presence-host-capture-"))
    plugin, raw, repo = tmp / "plugin", tmp / "raw", tmp / "repo"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / "hooks").mkdir()
    raw.mkdir()
    repo.mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "capture", "version": "0.0.1", "description": "dump hook payloads"}))
    hooks: dict = {}
    for name, (event, matcher) in EVENTS.items():
        entry = {"hooks": [{"type": "command", "command": f'f=$(mktemp "$CAPTURE_DIR/{name}.XXXXXX") && cat > "$f"', "timeout": 10}]}
        if matcher:
            entry["matcher"] = matcher
        hooks.setdefault(event, []).append(entry)
    (plugin / "hooks" / "hooks.json").write_text(json.dumps({"hooks": hooks}))
    for cmd in (["init", "-q"], ["remote", "add", "origin", "https://example.invalid/presence-fixture.git"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    env = {**os.environ, "CAPTURE_DIR": str(raw), "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]}
    for prompt in SESSIONS:
        subprocess.run(
            ["claude", "-p", prompt, "--plugin-dir", str(plugin), "--setting-sources", "project", "--model", "haiku",
             "--permission-mode", "acceptEdits", "--allowedTools", "Write", "Bash", "Edit", "--max-turns", "10",
             "--no-session-persistence", "--output-format", "json"],
            cwd=repo, env=env, check=True, capture_output=True, text=True, timeout=300,
        )
    dest = OUT / version
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    count = {}
    for f in sorted(raw.iterdir()):
        name = f.name.rsplit(".", 1)[0]
        d = json.loads(f.read_text())
        d["session_id"] = "00000000-0000-0000-0000-000000000000"
        d["transcript_path"] = "/home/user/.claude/projects/fixture/00000000.jsonl"
        d["cwd"] = "/work/repo"
        for key in ("prompt_id", "tool_use_id"):
            if key in d:
                d[key] = "fixture-" + key
        text = json.dumps(d, indent=1, sort_keys=True)
        text = re.sub(r"/(?:private/)?(?:var|tmp)/[^\s\"\\]*presence-host-capture-[^\s\"\\]*", "/work/repo", text)
        hint = (d.get("tool_input") or {}).get("command") or d.get("tool_name") or ""
        slug = re.sub(r"[^a-z0-9]+", "-", hint.lower()).strip("-")[:32]
        stem = f"{name}.{slug}" if slug else name
        count[stem] = count.get(stem, 0) + 1
        suffix = "" if count[stem] == 1 else f".{count[stem]}"
        (dest / f"{stem}{suffix}.json").write_text(text + "\n")
    (dest / "VERSION").write_text(version + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"claude {version}: {sum(count.values())} payloads -> {dest}")


if __name__ == "__main__":
    main()
