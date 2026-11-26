"""Living project model: a per-repo markdown file appended by Claude across sessions."""
from __future__ import annotations

import time
from pathlib import Path

from _common import (
    _flock,
    _maybe_encrypt,
    _read_key_lazy,
    _refuse_plain_write,
    atomic_write,
    project_dir,
    settings,
)
from redact import redact_text

MODEL_HEADER = """# Project model: maintained by presence

This file is appended by Claude Code via the `presence` plugin. It captures Claude's
understanding of this codebase across sessions. Compressed periodically by the
model-curator agent. Do not commit to your repo unless you want a team-shared view.

"""


def model_path(cwd=None) -> Path:
    return project_dir(cwd) / "model.md"


def _decrypted(raw: str) -> str:
    """The file as text: each encrypted entry (one envelope per line) is replaced by its plaintext, plain lines pass
    through, and entries that cannot be decrypted (another key, a damaged line) become one placeholder line."""
    from crypto import decrypt_line, is_encrypted_line

    out: list[str] = []
    unreadable = 0
    key: object = _NO_KEY
    for line in raw.splitlines(keepends=True):
        if not is_encrypted_line(line):
            out.append(line)
            continue
        if key is _NO_KEY:
            key = _read_key_lazy()
        plain = decrypt_line(line.strip(), key) if key else None  # type: ignore[arg-type]
        if plain is None:
            unreadable += 1
        else:
            out.append(plain.decode("utf-8", errors="replace"))
    if unreadable:
        out.append(f"\n[{unreadable} encrypted entries unreadable: written under another key]\n")
    return "".join(out)


_NO_KEY = object()


def read_model(cwd=None, max_chars: int | None = None) -> str:
    p = model_path(cwd)
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if '{"_e":"' in text:
        try:
            text = _decrypted(text)
        except ImportError:  # no crypto library: the entries stay unreadable, the plain ones still read
            text = "".join(ln for ln in text.splitlines(keepends=True) if not ln.startswith('{"_e":"'))
    if max_chars and len(text) > max_chars:
        # Better truncation by structural chunks
        chunks = text.split("\n## ")
        head = chunks[0]
        tail = []
        budget = max(0, max_chars - len(head) - 100)

        for chunk in reversed(chunks[1:]):
            if len(chunk) <= budget:
                tail.insert(0, "\n## " + chunk)
                budget -= len(chunk) + 4
            else:
                break

        return head + "\n\n[...older entries elided; run /presence-doctor to compress...]\n" + "".join(tail)
    return text


def _on_disk(entry: str) -> str | None:
    """The entry as it goes to disk: encrypted when this store's own flag (`model.encrypted`) asks, plain otherwise.
    None when it asks and cannot, so the caller refuses instead of writing plain."""
    if not (settings().get("model") or {}).get("encrypted"):
        return entry
    return _maybe_encrypt(entry)


def _redacted(text: str) -> str:
    """The observation as the preset's redaction sees it. The model is the one store whose content Claude
    chooses, so a pasted token must not reach disk; the level and profiles are the preset's, as for events."""
    r = settings().get("redact") or {}
    if not r.get("enabled", True):
        return text
    profiles = [str(x) for x in (r.get("profiles") or []) if isinstance(x, str)]
    return redact_text(text, level=r.get("level") or "standard", profiles=profiles)


def append_observation(text: str, cwd=None) -> None:
    text = _redacted(text)
    timestamp = time.strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp}\n\n{text.strip()}\n"
    line = _on_disk(entry)
    if line is None:
        _refuse_plain_write()
        return
    if line != entry:  # an envelope is one line; plain entries carry their own newlines
        line += "\n"
    p = model_path(cwd)
    if not p.exists():
        atomic_write(p, MODEL_HEADER)
    with open(p, "a", encoding="utf-8") as f:
        unlock = _flock(f.fileno(), exclusive=True)
        try:
            f.write(line)
        finally:
            unlock()


MAX_MODEL_CHARS = 200_000


def replace_model(text: str, cwd=None) -> bool:
    """Replace the whole model with `text` (the curator's output), one envelope per entry when the preset asks for
    encryption. False, with the model untouched, when the text is empty or over the cap, or when encryption is required
    and impossible."""
    text = _redacted(text).strip()
    if not text or len(text) > MAX_MODEL_CHARS:
        return False
    head, *chunks = ("\n" + text).split("\n## ")
    parts = [(head.strip() + "\n\n") if head.strip() else MODEL_HEADER]
    for chunk in chunks:
        entry = f"\n## {chunk.strip()}\n"
        line = _on_disk(entry)
        if line is None:
            _refuse_plain_write()
            return False
        parts.append(line if line == entry else line + "\n")
    atomic_write(model_path(cwd), "".join(parts))
    return True


def drop_encrypted_entries() -> int:
    """Remove the encrypted entries from every project's model, keeping plain ones: what key rotation leaves
    unreadable. Returns how many were dropped."""
    from _common import state_dir

    dropped = 0
    for p in sorted((state_dir() / "projects").glob("*/model.md")):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            continue
        keep = [ln for ln in lines if not ln.startswith('{"_e":"')]
        if len(keep) != len(lines):
            dropped += len(lines) - len(keep)
            atomic_write(p, "".join(keep))
    return dropped


def model_chars(cwd=None) -> int:
    """Length of the model as it reads, which is what the curate threshold means; the file is larger when encrypted."""
    return len(read_model(cwd))


def model_size(cwd=None) -> int:
    p = model_path(cwd)
    return p.stat().st_size if p.exists() else 0
