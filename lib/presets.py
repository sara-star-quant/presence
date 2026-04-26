"""Preset management: built-in bundles + user overrides + active selection.

API surface designed so the caller can distinguish:
  - preset not found (typo)
  - preset corrupt (parse error -> tell the user, don't silently swap)
  - preset OK
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from _common import PLUGIN_ROOT, atomic_write, state_dir

DEFAULT_PRESET = "solo-dev"


def builtin_dir() -> Path:
    return PLUGIN_ROOT / "presets"


def user_dir() -> Path:
    return state_dir() / "presets"


def settings_path() -> Path:
    return state_dir() / "settings.json"


@dataclass
class PresetResult:
    ok: bool
    data: dict | None = None
    error: str | None = None
    source: str | None = None  # "user" | "builtin"


def list_presets() -> dict[str, str]:
    out: dict[str, str] = {}
    for d, source in ((builtin_dir(), "builtin"), (user_dir(), "user")):
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            existing = out.get(f.stem)
            if existing is None:
                out[f.stem] = source
            elif existing == "builtin":
                out[f.stem] = "user (overrides builtin)"
    return out


def get_preset(name: str) -> PresetResult:
    """Look up a preset. User dir takes precedence over builtin."""
    for d, source in ((user_dir(), "user"), (builtin_dir(), "builtin")):
        p = d / f"{name}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return PresetResult(ok=False, error=f"parse error: {exc.msg} at line {exc.lineno}", source=source)
        except OSError as exc:
            return PresetResult(ok=False, error=f"read error: {exc}", source=source)
        if not isinstance(data, dict):
            return PresetResult(ok=False, error="preset must be a JSON object", source=source)
        return PresetResult(ok=True, data=data, source=source)
    return PresetResult(ok=False, error="not found")


def use_preset(name: str) -> PresetResult:
    """Activate a preset. Refuses on parse error to avoid silently picking the wrong one."""
    res = get_preset(name)
    if not res.ok:
        return res
    s_path = settings_path()
    s: dict = {}
    if s_path.exists():
        try:
            s = json.loads(s_path.read_text(encoding="utf-8"))
            if not isinstance(s, dict):
                s = {}
        except (json.JSONDecodeError, OSError) as exc:
            return PresetResult(ok=False, error=f"existing settings.json unreadable: {exc}")
    s["preset"] = name
    atomic_write(s_path, json.dumps(s, indent=2) + "\n")
    return res


def active_preset_name() -> str:
    p = settings_path()
    if not p.exists():
        return DEFAULT_PRESET
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DEFAULT_PRESET
    return data.get("preset", DEFAULT_PRESET) if isinstance(data, dict) else DEFAULT_PRESET
