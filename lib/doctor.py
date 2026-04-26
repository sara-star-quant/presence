"""/presence-doctor support: diagnostic snapshot of presence's local state."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from _common import (
    PLUGIN_ROOT,
    logs_dir,
    read_counter,
    repo_id,
    state_dir,
)
from events import event_path, peek_events
from model import model_size
from telemetry import claims_path, confidence_path, outcomes_path
from warnings_log import read_warnings

from presets import active_preset_name, list_presets


def python_version_ok() -> tuple[bool, str]:
    v = sys.version_info
    return ((v.major, v.minor) >= (3, 12), f"{v.major}.{v.minor}.{v.micro}")


def has_git() -> bool:
    return shutil.which("git") is not None


def integrity_status() -> str:
    try:
        from integrity import load_manifest, verify_manifest

        if load_manifest() is None:
            return "no MANIFEST.lock present (skipped)"
        missing, mismatched, _extra = verify_manifest()
        if missing or mismatched:
            return f"FAILED: {len(missing)} missing, {len(mismatched)} mismatched"
        return "OK"
    except Exception as exc:  # noqa: BLE001
        return f"check error: {exc}"


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def report(cwd: str | None = None) -> dict:
    cwd = cwd or "."
    rid = repo_id(cwd)
    py_ok, py_ver = python_version_ok()
    return {
        "presence_root": str(PLUGIN_ROOT),
        "state_dir": str(state_dir()),
        "active_preset": active_preset_name(),
        "available_presets": list_presets(),
        "current_repo_id": rid,
        "errors_since_last_session": read_counter("error"),
        "warnings_since_last_session": read_counter("warning"),
        "recent_warnings": read_warnings(limit=10),
        "model_size_bytes": model_size(cwd),
        "pending_events_bytes": _file_size(event_path(cwd)),
        "pending_event_count": len(peek_events(cwd)),
        "claims_bytes": _file_size(claims_path()),
        "outcomes_bytes": _file_size(outcomes_path()),
        "confidence_bytes": _file_size(confidence_path()),
        "errors_log_bytes": _file_size(logs_dir() / "errors.log"),
        "warnings_log_bytes": _file_size(logs_dir() / "warnings.log"),
        "python_ok": py_ok,
        "python_version": py_ver,
        "git_available": has_git(),
        "integrity": integrity_status(),
    }


def render(rep: dict) -> str:
    lines = [
        "presence: doctor report",
        "-" * 40,
        f"plugin root  : {rep['presence_root']}",
        f"state dir    : {rep['state_dir']}",
        f"active preset: {rep['active_preset']}",
        f"presets      : {', '.join(rep['available_presets']) or '(none)'}",
        f"repo id      : {rep['current_repo_id']}",
        "",
        f"python       : {rep['python_version']} {'OK' if rep['python_ok'] else 'FAIL (need 3.12+)'}",
        f"git on PATH  : {'OK' if rep['git_available'] else 'FAIL (telemetry disabled)'}",
        f"integrity    : {rep['integrity']}",
        "",
        f"errors since last session   : {rep['errors_since_last_session']}",
        f"warnings since last session : {rep['warnings_since_last_session']}",
        "",
        "state sizes",
        f"  model.md            : {rep['model_size_bytes']:>10} bytes",
        f"  pending events      : {rep['pending_events_bytes']:>10} bytes ({rep['pending_event_count']} entries)",
        f"  telemetry/claims    : {rep['claims_bytes']:>10} bytes",
        f"  telemetry/outcomes  : {rep['outcomes_bytes']:>10} bytes",
        f"  telemetry/confidence: {rep['confidence_bytes']:>10} bytes",
        f"  logs/errors         : {rep['errors_log_bytes']:>10} bytes",
        f"  logs/warnings       : {rep['warnings_log_bytes']:>10} bytes",
    ]
    if rep["recent_warnings"]:
        lines.append("")
        lines.append("recent warnings (newest last):")
        for w in rep["recent_warnings"]:
            lines.append(f"  [{w.get('category', '?'):30}] {w.get('message', '')[:80]}")
    return "\n".join(lines)


def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="presence diagnostic report")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    ap.add_argument("--cwd", default=".", help="project directory to inspect")
    args = ap.parse_args()
    rep = report(args.cwd)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = ["report", "render"]
