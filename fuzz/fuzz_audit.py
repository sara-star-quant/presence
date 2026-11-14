"""Coverage-guided, structure-aware fuzzer for the audit hash chain.

Builds a genuine chain with audit.append, damages it in one specific way, and
checks the verifier's contract: an intact chain verifies, and every damage that
changes the chain is reported. A mode that feeds raw bytes checks it never raises.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
STATE = Path(tempfile.mkdtemp(prefix="presence-fuzz-audit-"))
os.environ["PRESENCE_STATE"] = str(STATE)

import atheris

with atheris.instrument_imports():
    import audit


def _reset() -> None:
    audit.audit_path().unlink(missing_ok=True)
    audit.head_path().unlink(missing_ok=True)


def _build(fdp) -> list[str]:
    for _ in range(fdp.ConsumeIntInRange(1, 6)):
        details = {fdp.ConsumeUnicodeNoSurrogates(8): fdp.ConsumeUnicodeNoSurrogates(24)}
        audit.append(fdp.ConsumeUnicodeNoSurrogates(16) or "event", details)
    return audit.audit_path().read_text(encoding="utf-8").splitlines(keepends=True)


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    _reset()
    path = audit.audit_path()
    if fdp.ConsumeBool():
        path.write_bytes(fdp.ConsumeBytes(4096))
        assert isinstance(audit.verify_chain()["ok"], bool)
        return

    lines = _build(fdp)
    assert audit.verify_chain()["ok"], "an untouched chain must verify"
    n = len(lines)
    op = fdp.ConsumeIntInRange(0, 4)
    i = fdp.ConsumeIntInRange(0, n - 1)
    if op == 0:  # delete a line
        del lines[i]
    elif op == 1:  # duplicate a line
        lines.insert(i, lines[i])
    elif op == 2:  # swap two different lines
        j = fdp.ConsumeIntInRange(0, n - 1)
        if lines[i] == lines[j]:
            return
        lines[i], lines[j] = lines[j], lines[i]
    elif op == 3:  # flip one printable ASCII byte inside a line
        raw = bytearray(lines[i].encode("utf-8"))
        k = fdp.ConsumeIntInRange(0, len(raw) - 1)
        if not 0x20 <= raw[k] < 0x7F:
            return
        raw[k] ^= 0x01
        lines[i] = raw.decode("utf-8", errors="replace")
    else:  # splice in a foreign line
        junk = fdp.ConsumeUnicodeNoSurrogates(64)
        if not junk.strip():
            return
        lines.insert(i, junk + "\n")
    path.write_text("".join(lines), encoding="utf-8")
    assert not audit.verify_chain()["ok"], f"damage went unreported (op={op})"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
