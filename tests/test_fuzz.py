"""Property-based fuzzing of the parsers that read untrusted bytes.

Each test feeds arbitrary input to one entry point and asserts the failure
contract: the redactor never raises, the snapshot restore path raises only
SnapshotError and never writes outside the state dir, and the audit verifier
reports damage instead of crashing.
"""
from __future__ import annotations

import io
import json
import shutil
import tarfile

import audit
import pytest
import snapshot
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from redact import redact_text

pytestmark = pytest.mark.filterwarnings("ignore")

FUZZ = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _clear(path):
    for child in path.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()


@FUZZ
@given(st.text(), st.sampled_from(["standard", "aggressive"]))
def test_redact_text_never_raises(text, level):
    assert isinstance(redact_text(text, level=level), str)


@FUZZ
@given(st.binary(max_size=4096))
def test_restore_rejects_arbitrary_bytes_cleanly(isolated_state, blob):
    snap = isolated_state.parent / "in.snap"
    snap.write_bytes(blob)
    try:
        snapshot.restore(snap)
    except snapshot.SnapshotError:
        pass
    assert list(isolated_state.iterdir()) == []


@FUZZ
@given(st.binary(max_size=4096), st.integers(0, 255))
def test_unseal_rejects_arbitrary_sealed_bytes_cleanly(monkeypatch, tail, cost):
    monkeypatch.setattr(snapshot, "_derive", lambda *_a: bytes(32))
    blob = snapshot.SEAL_MAGIC + bytes([cost]) + tail
    try:
        snapshot._unseal(blob, "pw")
    except snapshot.SnapshotError:
        pass


def _archive(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        members = {snapshot.META_FILENAME: json.dumps({"format": snapshot.SCHEMA_FORMAT}).encode()}
        members.update({n: b"x" for n in names})
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


_NAME = st.one_of(
    st.text(alphabet="ab./\\\x00", min_size=1, max_size=12),
    st.sampled_from(["../x", "/etc/x", "a/../../x", "a//b", "./a", "..", "."]),
)


@FUZZ
@example(names=["."])  # used to replace the state dir with a file
@example(names=["a\x00b"])  # used to raise ValueError from the staging write
@given(st.lists(_NAME, max_size=4))
def test_restore_never_writes_outside_state_dir(isolated_state, names):
    parent = isolated_state.parent
    snap = parent / "in.snap"
    snap.write_bytes(_archive(names))
    before = {p.name for p in parent.iterdir()}
    try:
        snapshot.restore(snap)
    except snapshot.SnapshotError:
        pass
    assert {p.name for p in parent.iterdir()} == before
    _clear(isolated_state)


@FUZZ
@example(blob=b"0")  # valid JSON, not an object: used to raise AttributeError
@given(st.binary(max_size=4096))
def test_verify_chain_reports_instead_of_raising(isolated_state, blob):
    audit.audit_path().write_bytes(blob)
    report = audit.verify_chain()
    assert isinstance(report["ok"], bool)
    _clear(isolated_state)
