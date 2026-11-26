"""Documentation reads like an engineer wrote it: no filler words, buzzwords or template phrases.

The commit-msg checker and the PR-body checker apply a longer list to commits and PR text; this pins the part that
belongs in the repository, so a doc edit that brings one back fails CI.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# `unlock` is a feature name (/presence-unlock), so it is not in the list.
TELLS = [
    "stale", "drift", "span", "spans", "leverage", "leveraging", "seamless", "seamlessly", "robust", "comprehensive", "streamline", "holistic",
    "cutting-edge", "state-of-the-art", "production-ready", "game-changer", "empower", "delve", "moreover", "furthermore",
    "in conclusion", "important to note", "worth noting", "rapidly evolving", "fast-paced", "plays a crucial",
    "on the other hand", "there are many factors", "by embracing", "thrilled", "humbled", "excited to share",
    "this repository provides", "modern, scalable", "feel free to", "best-in-class",
]


def _docs() -> list[Path]:
    names = ["README.md", "SECURITY.md", "CONTRIBUTING.md", "GOVERNANCE.md", "llms.txt"]
    paths = [ROOT / n for n in names]
    for folder in ("docs", "commands", "agents", "skills"):
        paths += sorted((ROOT / folder).rglob("*.md"))
    return [p for p in paths if p.exists()]


def _prose(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)  # code blocks hold commands and code, not prose
    return re.sub(r"`[^`\n]+`", "", text)  # a word in inline code is quoted as an example or a name


@pytest.mark.parametrize("path", _docs(), ids=lambda p: str(p.relative_to(ROOT)))
def test_a_document_has_none_of_the_filler_words_or_template_phrases(path):
    text = _prose(path).lower()
    hits = [t for t in TELLS if re.search(rf"\b{re.escape(t)}\b", text)]
    assert not hits, f"{path.relative_to(ROOT)} uses: {hits}"


def test_the_current_changelog_entry_has_none_either():
    entry = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("\n## v", 2)[1].lower()
    hits = [t for t in TELLS if re.search(rf"\b{re.escape(t)}\b", entry)]
    assert not hits, f"the newest CHANGELOG entry uses: {hits}"
