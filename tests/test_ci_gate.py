"""CI routing: a documentation-only change gets the docs checks, everything else gets the full run, and a routing
bug cannot let code merge without its tests."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
import ci_gate as g  # noqa: E402


@pytest.mark.parametrize(
    "paths",
    [["README.md"], ["docs/security.md", "docs/img/a.png"], ["CHANGELOG.md", "llms.txt"], ["diagrams/presence-repo.svg"], ["CONTRIBUTING.md", "docs/index.md"]],
)
def test_only_documentation_is_a_documentation_change(paths):
    assert g.classify(paths) == "docs"


@pytest.mark.parametrize(
    "paths",
    [
        ["lib/cli.py"], ["README.md", "lib/cli.py"], ["skills/confidence-gate/SKILL.md"], ["agents/model-curator.md"],
        ["commands/presence-doctor.md"], ["hooks/hooks.json"], [".github/workflows/ci.yml"], [".github/scripts/ci_gate.py"],
        ["tests/test_model.py"], ["MANIFEST.lock"], ["THIRD-PARTY.md"], ["pyproject.toml"], ["install.sh"],
        [],  # an empty diff is unknown, so it runs everything
        ["docs/../lib/cli.py"], ["docsx/readme.md"], ["README.md.py"], ["notes/README.md"],
    ],
)
def test_anything_else_unknown_or_empty_runs_the_full_ci(paths):
    assert g.classify(paths) == "code"


def _needs(code, **results):
    base = {"changes": {"result": "success", "outputs": {"code": "true" if code else "false"}}}
    for job in g.HEAVY + ["docs"]:
        base[job] = {"result": "skipped" if (job == "docs") == code else "success"}
    for job, r in results.items():
        base[job] = {"result": r}
    return base


def test_a_green_code_change_passes():
    assert g.verdict(_needs(True))[0] is True


def test_a_green_documentation_change_passes_with_the_heavy_jobs_skipped():
    ok, message = g.verdict(_needs(False))
    assert ok is True and "documentation" in message


@pytest.mark.parametrize("job", g.HEAVY)
def test_a_code_change_fails_when_any_heavy_job_was_skipped(job):
    ok, message = g.verdict(_needs(True, **{job: "skipped"}))
    assert ok is False and job in message


@pytest.mark.parametrize("result", ["failure", "cancelled"])
def test_a_failed_or_cancelled_job_fails_the_run(result):
    assert g.verdict(_needs(True, test=result))[0] is False
    assert g.verdict(_needs(False, docs=result))[0] is False


def test_a_documentation_change_fails_when_the_docs_job_did_not_pass():
    assert g.verdict(_needs(False, docs="skipped"))[0] is False


def test_a_broken_classifier_fails_the_run():
    needs = _needs(False)
    needs["changes"]["result"] = "failure"
    assert g.verdict(needs)[0] is False


def test_a_push_or_an_unknown_event_classifies_as_code(monkeypatch, tmp_path, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("EVENT_NAME", "push")
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.setattr(sys, "argv", ["ci_gate.py", "classify"])
    assert g.main() == 0 and out.read_text() == "code=true\n"


def test_a_git_error_classifies_as_code(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("EVENT_NAME", "pull_request")
    monkeypatch.setenv("BASE_REF", "no-such-branch")
    monkeypatch.chdir(tmp_path)  # not a repository: git fails
    monkeypatch.setattr(sys, "argv", ["ci_gate.py", "classify"])
    assert g.main() == 0 and out.read_text() == "code=true\n"


# --- the workflow wiring ---------------------------------------------------------------------------------------


def _workflow():
    import yaml
    return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def test_every_heavy_job_waits_for_the_classifier_and_skips_on_a_documentation_change():
    jobs = _workflow()["jobs"]
    for name in g.HEAVY:
        assert jobs[name].get("needs") == "changes", name
        assert jobs[name].get("if") == "needs.changes.outputs.code == 'true'", name


def test_the_gate_waits_for_every_job_and_runs_even_when_they_fail():
    jobs = _workflow()["jobs"]
    gate = jobs["ci-result"]
    assert gate["name"] == "CI result" and gate["if"] == "always()"
    assert set(gate["needs"]) == {"changes", "docs", *g.HEAVY}


def test_the_attestation_still_waits_for_the_full_set_of_jobs_on_a_push():
    attest = _workflow()["jobs"]["attest-tests"]
    assert attest["if"] == "github.event_name == 'push'" and set(g.HEAVY) - {"wheel-build"} <= set(attest["needs"])


def test_the_docs_job_runs_exactly_the_tests_marked_as_reading_documents():
    steps = " ".join(str(s.get("run", "")) for s in _workflow()["jobs"]["docs"]["steps"])
    assert "-m docs_facts" in steps


# A test that reads a document but is not marked would be skipped on a documentation-only change, so a doc edit could
# break it and merge. Every test file that opens one of these paths must carry the marker.
READS = re.compile(r"""(?:ROOT|REPO)\s*/\s*["'](?:docs|README\.md|CHANGELOG\.md|llms\.txt|CONTRIBUTING\.md|SECURITY\.md|GOVERNANCE\.md)""")


def test_every_test_that_reads_a_document_carries_the_docs_marker():
    unmarked = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name != "test_ci_gate.py" and READS.search(text) and "pytestmark = pytest.mark.docs_facts" not in text:
            unmarked.append(path.name)
    assert not unmarked, f"these read documents but are not marked docs_facts: {unmarked}"
