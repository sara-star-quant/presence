"""State snapshot + restore for cross-machine continuity (non-zerotrust only).

v0.3.4 ships the non-encrypted path. Roadmap issue #11 tracks the
zerotrust case: snapshotting encrypted state requires a key-rewrap so the
destination machine can decrypt with its own keychain key, which is its own
design call.

Excluded from snapshots (per-machine cache only):
  .python_bin, .python_version_ok, .integrity-blocked, .unlock-*, logs/.warned-*

Included:
  projects/<repo_id>/{model.md,last_seen}, events/<repo_id>/pending.jsonl,
  telemetry/{claims,outcomes,confidence}.jsonl, logs/{errors,warnings}.log,
  settings.json, presets/<custom>.json, audit.jsonl

Schema versioned via _snapshot_meta.json at the tarball root.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import io
import json
import tarfile
from pathlib import Path

from _common import PLUGIN_ROOT, settings, state_dir

SCHEMA_FORMAT = 1
META_FILENAME = "_snapshot_meta.json"

# Path patterns excluded from snapshots. Matched against POSIX paths relative
# to the state dir. The first three are markers that should never travel
# across machines (they describe the source host's interpreter / session
# state); the warned-* family is per-process counter state.
_EXCLUDE_PATTERNS = (
    ".python_bin",
    ".python_version_ok",
    ".integrity-blocked",
    "unlock-*",
    ".unlock-*",
    "logs/.warned-*",
)


class SnapshotError(Exception):
    """Snapshot or restore refused or failed."""


def _is_excluded(rel_posix: str) -> bool:
    """Return True iff rel_posix matches any exclusion pattern."""
    for pat in _EXCLUDE_PATTERNS:
        # Match either the full path or just the basename.
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(Path(rel_posix).name, pat):
            return True
    return False


def _zerotrust_active() -> bool:
    """True iff the current settings request encryption on any storage section.

    We check the merged preset, not just the preset name, because a user could
    pick zerotrust and then disable encryption via overrides (the schema allows
    this). What matters is whether anything currently on disk would be encrypted.
    """
    cfg = settings()
    return any(
        bool((cfg.get(section) or {}).get("encrypted"))
        for section in ("model", "telemetry", "events")
    )


def _read_version() -> str:
    p = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, json.JSONDecodeError):
        return "unknown"


def snapshot(out_path: str | Path) -> Path:
    """Write a tar.gz of the (non-zerotrust) state dir.

    Raises SnapshotError if the active preset wants encryption (the user must
    snapshot before switching to zerotrust, or wait for v0.3.5 for ZT support).
    """
    if _zerotrust_active():
        raise SnapshotError(
            "snapshot of zerotrust state is not yet supported (issue #11); "
            "switch to a non-zerotrust preset first or wait for v0.3.5"
        )

    sd = state_dir()
    if not sd.exists():
        raise SnapshotError(f"state directory does not exist: {sd}")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    meta = {
        "format": SCHEMA_FORMAT,
        "presence_version": _read_version(),
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds") + "Z",
    }

    with tarfile.open(out, "w:gz") as tf:
        # Write meta first so restore can validate without scanning the whole tar.
        meta_bytes = json.dumps(meta, indent=2).encode("utf-8")
        meta_info = tarfile.TarInfo(META_FILENAME)
        meta_info.size = len(meta_bytes)
        meta_info.mtime = int(dt.datetime.now().timestamp())
        meta_info.mode = 0o600
        tf.addfile(meta_info, io.BytesIO(meta_bytes))

        # Walk state dir in sorted order so the tar is deterministic.
        for path in sorted(sd.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(sd).as_posix()
            if _is_excluded(rel):
                continue
            tf.add(path, arcname=rel, recursive=False)

    return out


def restore(in_path: str | Path, overwrite: bool = False) -> None:
    """Extract a snapshot tar.gz over the state dir.

    Refuses if state already exists and overwrite=False (the safe default;
    the user must explicitly opt in to clobbering existing memory).
    Refuses on schema version mismatch.
    """
    p = Path(in_path)
    if not p.exists():
        raise SnapshotError(f"snapshot not found: {p}")

    sd = state_dir()
    if any(sd.iterdir()) and not overwrite:
        raise SnapshotError(
            f"state directory is non-empty: {sd}\n"
            "pass --overwrite to clobber existing state, "
            "or remove ~/.claude/presence/ first"
        )

    with tarfile.open(p, "r:gz") as tf:
        # Validate meta first.
        try:
            meta_member = tf.getmember(META_FILENAME)
        except KeyError as exc:
            raise SnapshotError(f"snapshot missing {META_FILENAME}; not a presence snapshot") from exc
        meta_file = tf.extractfile(meta_member)
        if meta_file is None:
            raise SnapshotError("snapshot meta unreadable")
        try:
            meta = json.loads(meta_file.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SnapshotError(f"snapshot meta is not valid JSON: {exc}") from exc
        if meta.get("format") != SCHEMA_FORMAT:
            raise SnapshotError(
                f"snapshot format {meta.get('format')!r} != supported {SCHEMA_FORMAT!r}; "
                "this snapshot was made by a different version of presence"
            )

        # Refuse any member with absolute path or .. traversal.
        for member in tf.getmembers():
            if member.name == META_FILENAME:
                continue
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise SnapshotError(f"refusing unsafe tar member: {member.name!r}")

        # Extract everything except the meta file (already consumed).
        for member in tf.getmembers():
            if member.name == META_FILENAME:
                continue
            target = sd / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            tf.extract(member, sd, filter="data")
            try:
                target.chmod(0o600)
            except OSError:
                pass


def _cli() -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="presence: state snapshot / restore (non-zerotrust)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot", help="write a tar.gz of the state dir")
    snap.add_argument("out_path")
    rest = sub.add_parser("restore", help="extract a tar.gz over the state dir")
    rest.add_argument("in_path")
    rest.add_argument("--overwrite", action="store_true",
                      help="clobber existing state instead of refusing")
    args = ap.parse_args()

    try:
        if args.cmd == "snapshot":
            out = snapshot(args.out_path)
            print(f"wrote {out}")
        else:
            restore(args.in_path, overwrite=args.overwrite)
            print(f"restored from {args.in_path} to {state_dir()}")
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
