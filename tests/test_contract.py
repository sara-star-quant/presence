"""The 1.x contract: additive-only changes to presets, hooks and CLI (docs/contract.md).

tests/contract_snapshot.json holds the frozen surface. Additions pass; removing or
narrowing anything listed there fails these tests, which is the point.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN = json.loads((Path(__file__).parent / "contract_snapshot.json").read_text())


def _schema_leaves() -> dict:
    sch = json.loads((ROOT / "presets" / "_schema.json").read_text())
    out: dict = {}

    def walk(node: dict, prefix: str) -> None:
        for k, v in node.items():
            if k.startswith("_") and not prefix:
                continue
            if isinstance(v, dict):
                walk(v, f"{prefix}{k}.")
            else:
                out[f"{prefix}{k}"] = v

    walk(sch, "")
    return out


def _reload():
    import _common
    import warnings_log

    importlib.reload(_common)
    importlib.reload(warnings_log)
    warnings_log.clear_warnings_state()
    return _common, warnings_log


def _cats(warnings_log) -> list[str]:
    return [w["category"] for w in warnings_log.read_warnings(limit=200)]


def test_schema_keys_are_superset_of_frozen():
    current = _schema_leaves()
    missing = sorted(set(FROZEN["preset_keys"]) - set(current))
    assert not missing, f"preset keys removed or renamed (breaks the 1.x contract): {missing}"


def test_schema_leaf_types_not_narrowed():
    current = _schema_leaves()
    for path, frozen in FROZEN["preset_keys"].items():
        now = current[path]
        if isinstance(frozen, list):
            assert isinstance(now, list) and set(frozen) <= set(now), f"{path}: enum lost values"
        else:
            assert now == frozen, f"{path}: type changed {frozen!r} -> {now!r}"


def test_hooks_json_matches_frozen_events():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    events = sorted([ev, g.get("matcher", "")] for ev, groups in hooks.items() for g in groups)
    assert events == FROZEN["hook_events"]
    for groups in hooks.values():
        for g in groups:
            for h in g["hooks"]:
                script = h["command"].split("${CLAUDE_PLUGIN_ROOT}/", 1)[1]
                assert (ROOT / script).is_file(), script


def test_cli_hook_names_superset():
    import cli

    assert set(FROZEN["hook_names"]) <= set(cli._HOOKS)


def test_cli_subcommands_superset(monkeypatch, capsys):
    import sys

    import cli

    for cmd in FROZEN["cli_commands"]:
        monkeypatch.setattr(sys, "argv", ["presence", cmd, "--help"])
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 0, f"subcommand {cmd!r} not accepted"
        capsys.readouterr()


def test_bundled_presets_validate_clean(isolated_state):
    _common, warnings_log = _reload()
    for p in sorted((ROOT / "presets").glob("*.json")):
        if p.name.startswith("_"):
            continue
        assert _common._load_preset(p.stem) is not None
    assert [c for c in _cats(warnings_log) if c.startswith("preset_")] == []


def _write_preset(state, name, body):
    (state / "presets").mkdir(exist_ok=True)
    (state / "presets" / f"{name}.json").write_text(json.dumps(body))


def test_schema_version_newer_than_supported_warns_and_loads(isolated_state):
    _common, warnings_log = _reload()
    _write_preset(isolated_state, "future", {"schema_version": 99, "notify": {"enabled": True}})
    data = _common._load_preset("future")
    assert data is not None and data["notify"]["enabled"] is True
    assert _cats(warnings_log).count("preset_schema_newer") == 1


def test_schema_version_current_or_absent_is_silent(isolated_state):
    _common, warnings_log = _reload()
    _write_preset(isolated_state, "cur", {"schema_version": _common.CURRENT_PRESET_SCHEMA_VERSION})
    _write_preset(isolated_state, "none", {"notify": {"enabled": False}})
    assert _common._load_preset("cur") is not None and _common._load_preset("none") is not None
    assert [c for c in _cats(warnings_log) if c.startswith("preset_")] == []


def test_schema_version_wrong_type_warns_bad_type_and_loads(isolated_state):
    _common, warnings_log = _reload()
    for name, bad in (("s", "1"), ("b", True), ("f", 1.5), ("n", None)):
        _write_preset(isolated_state, name, {"schema_version": bad})
        assert _common._load_preset(name) is not None
    cats = _cats(warnings_log)
    assert "preset_bad_type" in cats and "preset_schema_newer" not in cats


def test_every_commit_gate_mode_the_hook_handles_validates(isolated_state):
    """hook_pre_tool_bash documents off/warn/ask/block; the schema must accept all four."""
    _common, warnings_log = _reload()
    for mode in ("off", "warn", "ask", "block"):
        _write_preset(isolated_state, f"g-{mode}", {"confidence": {"commit_gate": mode}})
        assert _common._load_preset(f"g-{mode}") is not None
    assert "preset_bad_type" not in _cats(warnings_log)
    _write_preset(isolated_state, "g-bogus", {"confidence": {"commit_gate": "bogus"}})
    _common._load_preset("g-bogus")
    assert "preset_bad_type" in _cats(warnings_log)


def test_security_table_references_existing_tests():
    import re

    text = (ROOT / "docs" / "security.md").read_text()
    section = text.split("## Which tests pin each claim", 1)[1].split("\n## ", 1)[0]
    refs = re.findall(r"`(tests/[\w/]+\.py)::(test_\w+)`", section)
    assert len(refs) >= 10
    for path, name in refs:
        src = (ROOT / path).read_text()
        assert re.search(rf"^def {name}\(", src, re.M), f"{path}::{name} not found"
