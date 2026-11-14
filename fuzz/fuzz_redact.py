"""Coverage-guided fuzzer for the redaction engine.

Two modes: arbitrary text must never raise, and text with a known secret
planted between separators must come back without that secret.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
os.environ.setdefault("PRESENCE_STATE", "/tmp/presence-fuzz-redact")  # noqa: S108

import atheris

with atheris.instrument_imports():
    from redact import redact_text

_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_ALNUM = _UPPER + "abcdefghijklmnopqrstuvwxyz"


def _chars(fdp, alphabet: str, n: int) -> str:
    return "".join(alphabet[fdp.ConsumeIntInRange(0, len(alphabet) - 1)] for _ in range(n))


def _secret(fdp) -> str:
    kind = fdp.ConsumeIntInRange(0, 3)
    if kind == 0:
        return "AKIA" + _chars(fdp, _UPPER, 16)
    if kind == 1:
        return "ghp_" + _chars(fdp, _ALNUM, 36)
    if kind == 2:
        return "glpat-" + _chars(fdp, _ALNUM, 20)
    return "sk_live_" + _chars(fdp, _ALNUM, 24)


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    level = "aggressive" if fdp.ConsumeBool() else "standard"
    if fdp.ConsumeBool():
        out = redact_text(fdp.ConsumeUnicodeNoSurrogates(2048), level=level)
        assert isinstance(out, str)
        return
    secret = _secret(fdp)
    before = fdp.ConsumeUnicodeNoSurrogates(256)
    after = fdp.ConsumeUnicodeNoSurrogates(256)
    out = redact_text(f"{before} {secret} {after}", level=level)
    assert secret not in out, f"secret survived redaction: {secret!r}"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
