"""The README preset table is what a user chooses from, so it must say what the preset files do."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs_facts

ROOT = Path(__file__).resolve().parent.parent
PRESETS = ["solo-dev", "team-oss", "enterprise-strict", "zerotrust"]


def _table() -> dict[str, list[str]]:
    rows = {}
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        name = cells[0].replace("`", "").split(" ")[0]
        if name in PRESETS and len(cells) == 6:
            rows[name] = cells
    return rows


def _preset(name: str) -> dict:
    return json.loads((ROOT / "presets" / f"{name}.json").read_text(encoding="utf-8"))


def test_every_preset_has_a_row():
    assert sorted(_table()) == sorted(PRESETS)


@pytest.mark.parametrize("name", PRESETS)
def test_the_outcome_log_cell_matches_the_pr_check_encryption_and_audit_flags(name):
    cell = _table()[name][2]
    t = _preset(name)["telemetry"]
    assert ("no PR check" in cell) == (not t.get("gh_pr_check")), cell
    assert ("PR check" in cell.replace("no PR check", "")) == bool(t.get("gh_pr_check")), cell
    assert ("encrypted" in cell) == bool(t.get("encrypted")), cell
    assert ("audit" in cell) == bool(t.get("audit_log")), cell
    assert "optional" not in cell, cell  # the flag is on or off in a preset, never optional


@pytest.mark.parametrize("name", PRESETS)
def test_the_model_cell_matches_the_model_flags(name):
    cell = _table()[name][1]
    m = _preset(name)["model"]
    assert ("verbose" in cell) == bool(m.get("verbose")), cell
    assert ("terse" in cell) == (not m.get("verbose")), cell
    assert ("encrypted" in cell) == bool(m.get("encrypted")), cell
    assert ("audit" in cell) == bool(m.get("audit_log")), cell


@pytest.mark.parametrize("name", PRESETS)
def test_the_gate_cells_match_the_confidence_settings(name):
    cells = _table()[name]
    c = _preset(name)["confidence"]
    assert cells[3].split(" ")[0] == c["commit_gate"], cells[3]
    assert cells[4].split(" ")[0] == c["stop_action"], cells[4]


@pytest.mark.parametrize("name", PRESETS)
def test_the_at_rest_cell_matches_encryption(name):
    cell = _table()[name][5]
    encrypted = any(bool((_preset(name).get(s) or {}).get("encrypted")) for s in ("model", "telemetry", "events"))
    assert ("AES-GCM" in cell) == encrypted, cell


# --- the rest of the README's checkable facts ---------------------------------------------------------------


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_status_line_names_the_current_minor_version():
    import re
    version = re.search(r'__version__ = "(\d+\.\d+)\.\d+"', (ROOT / "lib" / "__init__.py").read_text(encoding="utf-8")).group(1)
    assert f"Pre-1.0 ({version}.x)" in _readme()


def test_the_surface_counts_match_the_files():
    import re
    text = _readme()
    surface = re.search(r"Surface: (.+?)\.\n", text).group(1)
    counts = {
        "slash commands": len(list((ROOT / "commands").glob("*.md"))),
        "skills": len([p for p in (ROOT / "skills").iterdir() if p.is_dir()]),
        "subagent": len(list((ROOT / "agents").glob("*.md"))),
        "redaction profiles": len([p for p in (ROOT / "presets" / "redaction").glob("*.json") if not p.name.startswith("_")]),
        "presets": len(PRESETS),
    }
    for label, n in counts.items():
        assert f"{n} {label}" in surface, f"{label}: README says {surface!r}, files say {n}"


def test_the_newest_captured_host_version_is_in_the_compatibility_table():
    newest = sorted((p.name for p in (ROOT / "tests" / "fixtures" / "host").iterdir() if p.is_dir()), key=lambda v: tuple(map(int, v.split("."))))[-1]
    assert f"| {newest} |" in _readme()


def test_every_relative_link_in_the_readme_points_at_something_that_exists():
    import re
    for target in re.findall(r"\]\(([^)\s]+)\)", _readme()):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        assert (ROOT / target.split("#")[0]).exists(), f"README links to a path that does not exist: {target}"


def test_the_threat_count_quoted_in_the_readme_and_the_index_is_the_real_one():
    import re
    threats = [int(m) for m in re.findall(r"^\| T(\d+) \|", (ROOT / "docs" / "security.md").read_text(encoding="utf-8"), re.MULTILINE)]
    assert threats == list(range(1, max(threats) + 1)), "threat ids must be consecutive"
    for doc in (_readme(), (ROOT / "docs" / "index.md").read_text(encoding="utf-8")):
        assert f"T1 to T{max(threats)}" in doc


def test_every_threat_has_a_row_in_the_pinning_table():
    import re
    text = (ROOT / "docs" / "security.md").read_text(encoding="utf-8")
    pins = text.split("| Claim | Pinned by |", 1)[1]
    for n in re.findall(r"^\| T(\d+) \|", text.split("## Which tests pin", 1)[0], re.MULTILINE):
        assert re.search(rf"\bT{n}\b", pins), f"T{n} has no row in the pinning table"


def _schema_keys() -> set[str]:
    schema = json.loads((ROOT / "presets" / "_schema.json").read_text(encoding="utf-8"))
    keys: set[str] = set()

    def walk(node, prefix=""):
        for k, v in node.items():
            if k.startswith("$") or k in ("description", "type"):
                continue
            keys.add(prefix + k)
            if isinstance(v, dict):
                walk(v, prefix + k + ".")
    walk(schema)
    return keys


def test_every_override_key_in_the_docs_is_a_real_setting():
    """A recipe with a misspelt key does nothing, silently: the user thinks a network call is off and it is not."""
    import re
    keys = _schema_keys()
    text = "".join((ROOT / "docs" / name).read_text(encoding="utf-8") for name in ("recipes.md", "architecture.md"))
    found = re.findall(r'"([a-z_]+\.[a-z_.]+)":', text)
    assert found, "no override keys found in the docs"
    unknown = sorted({k for k in found if k not in keys})
    assert not unknown, f"recipes use settings that do not exist: {unknown}"
