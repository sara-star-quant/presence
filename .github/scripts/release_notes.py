"""Turn a CHANGELOG entry into release-page text: relative file links pinned to the tag, plus a link to the full diff.

The release page is not the repository, so `[doc](docs/a.md)` goes nowhere there. Pinned to the tag, the link opens
the file as it was shipped, and keeps doing so when main moves on.

    python3 release_notes.py OWNER/REPO vX.Y.Z [vPREVIOUS] < entry.md > notes.md
"""
from __future__ import annotations

import re
import sys

_TAG = re.compile(r"v\d+\.\d+\.\d+\Z")
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_ABSOLUTE = ("http://", "https://", "mailto:", "#", "/")


def _check(tag: str) -> None:
    if not _TAG.match(tag):
        raise ValueError(f"not a release tag: {tag!r}")


def pin_links(body: str, repo: str, tag: str) -> str:
    _check(tag)

    def pin(m: re.Match) -> str:
        target = m.group(1)
        if target.startswith(_ABSOLUTE):
            return m.group(0)
        path = target[2:] if target.startswith("./") else target
        kind = "tree" if path.split("#")[0].endswith("/") else "blob"
        if kind == "tree":
            path = path.split("#")[0].rstrip("/")
        return f"](https://github.com/{repo}/{kind}/{tag}/{path})"

    return _LINK.sub(pin, body)


def footer(repo: str, tag: str, previous: str) -> str:
    _check(tag)
    if not previous:
        return ""
    _check(previous)
    return f"Full diff: [{previous}...{tag}](https://github.com/{repo}/compare/{previous}...{tag})"


def main() -> None:
    repo, tag = sys.argv[1], sys.argv[2]
    previous = sys.argv[3] if len(sys.argv) > 3 else ""
    out = pin_links(sys.stdin.read().rstrip(), repo, tag)
    tail = footer(repo, tag, previous)
    sys.stdout.write(out + ("\n\n" + tail if tail else "") + "\n")


if __name__ == "__main__":
    main()
