"""The license policy over ScanCode output: copyleft in code files fails, permissive and dual-licensed passes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "license_policy.py"


def _load():
    spec = importlib.util.spec_from_file_location("license_policy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scan(path, expression, score=100.0):
    """The part of ScanCode's JSON the policy reads."""
    match = {"license_expression_spdx": expression, "score": score, "start_line": 1, "end_line": 4}
    return {"files": [{"path": path, "type": "file", "license_detections": [{"matches": [match]}]}]}


@pytest.mark.parametrize("expression", [
    "GPL-3.0-or-later", "GPL-2.0-only", "LGPL-2.1-or-later", "AGPL-3.0-only", "SSPL-1.0", "BUSL-1.1",
    "MIT AND GPL-2.0-only", "GPL-2.0-only WITH Classpath-exception-2.0", "(MIT AND (GPL-3.0-only OR AGPL-3.0-only))",
    "LicenseRef-scancode-proprietary-license", "CC-BY-NC-4.0",
])
def test_copyleft_and_restricted_licenses_fail(expression):
    assert _load().violations(scan("lib/x.py", expression))


@pytest.mark.parametrize("expression", [
    "MIT", "Apache-2.0", "BSD-3-Clause", "Apache-2.0 WITH LLVM-exception", "MIT OR Apache-2.0",
    "MIT OR Apache-2.0 OR LGPL-2.1-or-later", "(MIT OR Apache-2.0) AND Unicode-3.0", "Zlib", "Unlicense OR MIT",
])
def test_permissive_and_dual_licensed_code_passes(expression):
    assert _load().violations(scan("lib/x.py", expression)) == []


def test_a_weak_match_is_ignored_and_the_floor_is_inclusive():
    mod = _load()
    assert mod.violations(scan("lib/x.py", "GPL-3.0-only", score=50.0)) == []
    assert mod.violations(scan("lib/x.py", "GPL-3.0-only", score=89.9)) == []
    assert mod.violations(scan("lib/x.py", "GPL-3.0-only", score=90.0))


@pytest.mark.parametrize("path", ["docs/notes.md", "docs/sbom.json", "LICENSE", "lib/data.txt"])
def test_only_code_files_are_judged(path):
    assert _load().violations(scan(path, "GPL-3.0-only")) == []


@pytest.mark.parametrize("path", ["lib/x.py", "ext/src/lib.rs", "install.sh", "pyproject.toml", ".github/workflows/ci.yml"])
def test_code_files_are_judged(path):
    assert _load().violations(scan(path, "GPL-3.0-only"))


def test_an_expression_it_cannot_read_fails_closed():
    assert _load().violations(scan("lib/x.py", "MIT AND ("))
    assert _load().violations(scan("lib/x.py", "MIT ??? Apache-2.0"))


def test_the_report_is_one_plain_ascii_line_per_finding():
    out = _load().violations(scan("lib/" + chr(0x202E) + "x.py", "GPL-3.0-only"))
    assert len(out) == 1 and out[0].isascii() and "\n" not in out[0]


def test_the_command_exits_nonzero_on_a_planted_gpl_header_and_zero_when_clean(tmp_path):
    mod = _load()
    bad, good = tmp_path / "bad.json", tmp_path / "good.json"
    bad.write_text(json.dumps(scan("planted.py", "GPL-3.0-or-later")))
    good.write_text(json.dumps(scan("lib/x.py", "MIT")))
    assert mod.main([str(bad)]) == 1
    assert mod.main([str(good)]) == 0
    assert mod.main([str(tmp_path / "missing.json")]) == 2


def test_an_entry_with_no_type_is_still_judged():
    """ScanCode only writes type with --info; dropping that flag must not turn the policy into a no-op."""
    data = scan("lib/x.py", "GPL-3.0-only")
    del data["files"][0]["type"]
    assert _load().violations(data)


def test_a_directory_entry_is_not_a_file():
    data = scan("lib", "GPL-3.0-only")
    data["files"][0]["type"] = "directory"
    assert _load().violations(data) == []


def test_a_scan_that_found_no_files_is_an_error_not_a_pass(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"files": []}))
    assert _load().main([str(empty)]) == 2
