"""Tests for lib/snapshot.py.

Round-trip integrity: snapshot then restore reproduces the original state
byte-for-byte for the included files. Per-machine markers are excluded.
Refusals are deterministic and clearly worded.
"""
from __future__ import annotations

import datetime as dt
import importlib
import io
import json
import tarfile
from pathlib import Path

import _common
import pytest
import snapshot


def _seed(state_dir: Path) -> None:
    """Drop a representative slice of state into state_dir."""
    (state_dir / "projects" / "abc123def456").mkdir(parents=True, exist_ok=True)
    (state_dir / "projects" / "abc123def456" / "model.md").write_text(
        "# project model\n\nHello world.\n", encoding="utf-8",
    )
    (state_dir / "projects" / "abc123def456" / "last_seen").write_text("1700000000\n", encoding="utf-8")
    (state_dir / "events" / "abc123def456").mkdir(parents=True, exist_ok=True)
    (state_dir / "events" / "abc123def456" / "pending.jsonl").write_text(
        '{"ts":1,"kind":"edit","path":"x.py"}\n', encoding="utf-8",
    )
    (state_dir / "telemetry").mkdir(parents=True, exist_ok=True)
    (state_dir / "telemetry" / "claims.jsonl").write_text(
        '{"ts":2,"kind":"commit","sha":"deadbeef"}\n', encoding="utf-8",
    )
    (state_dir / "settings.json").write_text(
        json.dumps({"preset": "solo-dev"}), encoding="utf-8",
    )
    # Per-machine markers that MUST be excluded:
    (state_dir / ".python_bin").write_text("/usr/bin/python3", encoding="utf-8")
    (state_dir / ".python_version_ok").write_text("/usr/bin/python3", encoding="utf-8")
    (state_dir / ".integrity-blocked").write_text("from a stale session", encoding="utf-8")
    (state_dir / "logs").mkdir(parents=True, exist_ok=True)
    (state_dir / "logs" / ".warned-test_cat").write_text("1700000000", encoding="utf-8")


def test_snapshot_roundtrip(isolated_state, tmp_path):
    importlib.reload(_common)
    importlib.reload(snapshot)
    _seed(isolated_state)
    out = tmp_path / "snap.tar.gz"
    snapshot.snapshot(out)
    assert out.exists()

    # Restore into a fresh state dir and compare.
    new_state = tmp_path / "new-state"
    new_state.mkdir()
    import os
    os.environ["PRESENCE_STATE"] = str(new_state)
    importlib.reload(_common)
    importlib.reload(snapshot)
    snapshot.restore(out, overwrite=True)

    assert (new_state / "projects" / "abc123def456" / "model.md").read_text() == "# project model\n\nHello world.\n"
    assert (new_state / "events" / "abc123def456" / "pending.jsonl").exists()
    assert (new_state / "telemetry" / "claims.jsonl").exists()
    assert (new_state / "settings.json").exists()


def test_snapshot_excludes_per_machine_markers(isolated_state, tmp_path):
    importlib.reload(_common)
    importlib.reload(snapshot)
    _seed(isolated_state)
    out = tmp_path / "snap.tar.gz"
    snapshot.snapshot(out)
    with tarfile.open(out) as tf:
        names = {m.name for m in tf.getmembers()}
    assert ".python_bin" not in names
    assert ".python_version_ok" not in names
    assert ".integrity-blocked" not in names
    assert "logs/.warned-test_cat" not in names
    # And the included files are present.
    assert "projects/abc123def456/model.md" in names
    assert "settings.json" in names


def test_snapshot_includes_meta(isolated_state, tmp_path):
    importlib.reload(_common)
    importlib.reload(snapshot)
    _seed(isolated_state)
    out = tmp_path / "snap.tar.gz"
    snapshot.snapshot(out)
    with tarfile.open(out) as tf:
        member = tf.getmember(snapshot.META_FILENAME)
        meta = json.loads(tf.extractfile(member).read().decode("utf-8"))
    assert meta["format"] == snapshot.SCHEMA_FORMAT
    assert "presence_version" in meta
    assert "created_at" in meta


def test_snapshot_refused_under_zerotrust(isolated_state, tmp_path, monkeypatch):
    importlib.reload(_common)
    importlib.reload(snapshot)
    # Force settings to claim encryption is on.
    monkeypatch.setattr(snapshot, "settings", lambda: {"events": {"encrypted": True}})
    with pytest.raises(snapshot.SnapshotError, match="zerotrust"):
        snapshot.snapshot(tmp_path / "snap.tar.gz")


def test_restore_refuses_existing_state_without_overwrite(isolated_state, tmp_path):
    importlib.reload(_common)
    importlib.reload(snapshot)
    _seed(isolated_state)
    out = tmp_path / "snap.tar.gz"
    snapshot.snapshot(out)
    # Restore into the same (already-populated) state dir.
    with pytest.raises(snapshot.SnapshotError, match="non-empty"):
        snapshot.restore(out, overwrite=False)


def test_restore_rejects_format_mismatch(isolated_state, tmp_path):
    importlib.reload(_common)
    importlib.reload(snapshot)
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        body = json.dumps({"format": 999, "presence_version": "9.9.9"}).encode("utf-8")
        info = tarfile.TarInfo(snapshot.META_FILENAME)
        info.size = len(body)
        info.mtime = int(dt.datetime.now().timestamp())
        tf.addfile(info, io.BytesIO(body))
    with pytest.raises(snapshot.SnapshotError, match="format"):
        snapshot.restore(bad, overwrite=True)


def test_restore_rejects_missing_meta(isolated_state, tmp_path):
    importlib.reload(_common)
    importlib.reload(snapshot)
    bad = tmp_path / "no-meta.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        body = b"some content"
        info = tarfile.TarInfo("settings.json")
        info.size = len(body)
        info.mtime = int(dt.datetime.now().timestamp())
        tf.addfile(info, io.BytesIO(body))
    with pytest.raises(snapshot.SnapshotError, match="missing"):
        snapshot.restore(bad, overwrite=True)


def test_restore_rejects_path_traversal(isolated_state, tmp_path):
    """Snapshot tarballs from another user must not be able to write outside
    the state dir via .. or absolute paths."""
    importlib.reload(_common)
    importlib.reload(snapshot)
    bad = tmp_path / "traversal.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        meta_body = json.dumps({"format": snapshot.SCHEMA_FORMAT}).encode("utf-8")
        meta_info = tarfile.TarInfo(snapshot.META_FILENAME)
        meta_info.size = len(meta_body)
        meta_info.mtime = int(dt.datetime.now().timestamp())
        tf.addfile(meta_info, io.BytesIO(meta_body))
        body = b"malicious"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(body)
        info.mtime = int(dt.datetime.now().timestamp())
        tf.addfile(info, io.BytesIO(body))
    with pytest.raises(snapshot.SnapshotError, match="unsafe"):
        snapshot.restore(bad, overwrite=True)
