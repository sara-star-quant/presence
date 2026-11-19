"""A receipt rendered as an in-toto Statement: a published format other tools can read."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import receipt
from events import append_event

TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
COMMIT = "a" * 40
CARD = ("policy", "scope", "records", "writer", "rule")


def _note(**over):
    body = {"v": 1, "commit": COMMIT, "tree": TREE, "ts": 1_700_000_000, "verified_since_edit": True, "exact": True,
            "evidence": [{"kind": "test_pass", "cmd": "pytest -q", "ts": 1_699_999_990}], "tool": "presence 0.13.1"}
    body.update(over)
    body["digest"] = receipt._digest(body)
    return body


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_a_receipt_renders_as_an_in_toto_statement_over_the_tree_and_the_commit():
    s = receipt.to_statement(_note())
    assert s["_type"] == "https://in-toto.io/Statement/v1"
    assert s["predicateType"] == receipt.PREDICATE_TYPE
    assert s["subject"] == [{"name": "git-tree", "digest": {"sha1": TREE}},
                            {"name": "git-commit", "digest": {"sha1": COMMIT}}]


def test_a_sha256_repository_keys_the_digest_by_its_real_format():
    tree, commit = "b" * 64, "c" * 64
    s = receipt.to_statement(_note(tree=tree, commit=commit))
    assert [x["digest"] for x in s["subject"]] == [{"sha256": tree}, {"sha256": commit}]


@pytest.mark.parametrize("bad", ["", "xyz", "A" * 40, "a" * 41, "a" * 39, "g" * 40, None, 7])
def test_an_id_that_is_not_a_git_object_id_is_refused_not_mislabelled(bad):
    with pytest.raises(ValueError):
        receipt.to_statement(_note(tree=bad))


def test_the_predicate_names_what_settles_the_claim_and_who_writes_it():
    p = receipt.to_statement(_note())["predicate"]
    for field in CARD:
        assert isinstance(p[field], str) and p[field].strip(), field
    assert "hook" in p["writer"].lower() and "agent" in p["writer"].lower()


def test_the_predicate_keeps_the_verdict_the_evidence_and_the_old_digest():
    note = _note()
    p = receipt.to_statement(note)["predicate"]
    assert p["verified_since_edit"] is True and p["exact"] is True and p["tool"] == "presence 0.13.1"
    assert p["ts"] == note["ts"] and p["receipt_digest"] == note["digest"]
    assert p["evidence"] == note["evidence"]


def test_the_statement_never_carries_test_results_executables_or_environments():
    """Pinned on purpose: the receipt says a passing command ran on this tree. It does not hash
    results, ship an executable or describe the machine, and a field like that must not creep in."""
    banned = {"results", "result", "test_results", "passedTests", "failedTests", "executable", "environment",
              "env", "credential", "credentials", "user", "host", "hostname"}
    assert not banned & set(_keys(receipt.to_statement(_note())))


def test_rendering_is_pure_and_deterministic():
    note = _note()
    before = json.dumps(note, sort_keys=True)
    a = json.dumps(receipt.to_statement(note), sort_keys=True)
    b = json.dumps(receipt.to_statement(note), sort_keys=True)
    assert a == b and json.dumps(note, sort_keys=True) == before


def test_an_unverified_receipt_stays_unverified_in_statement_form():
    p = receipt.to_statement(_note(verified_since_edit=False, evidence=[]))["predicate"]
    assert p["verified_since_edit"] is False and p["evidence"] == []


def test_an_oversized_evidence_list_is_cut_to_the_receipt_limit():
    many = [{"kind": "test_pass", "cmd": f"c{i}", "ts": i} for i in range(20)]
    p = receipt.to_statement(_note(evidence=many))["predicate"]
    assert len(p["evidence"]) == receipt.MAX_EVIDENCE


def test_the_cli_prints_the_statement_for_a_recorded_receipt(isolated_state, fake_repo):
    (fake_repo / "a.txt").write_text("x")
    subprocess.run(["git", "add", "a.txt"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add a"], cwd=fake_repo, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=fake_repo, check=True, capture_output=True, text=True).stdout.strip()
    append_event({"kind": "test_pass", "cmd": "pytest -q"}, cwd=fake_repo)
    receipt.record(fake_repo, sha)
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PRESENCE_STATE": str(isolated_state), "PYTHONPATH": str(root / "lib")}
    out = subprocess.run([sys.executable, str(root / "lib" / "cli.py"), "receipt", "--statement"], cwd=fake_repo, env=env,
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    s = json.loads(out.stdout)
    assert s["_type"] == "https://in-toto.io/Statement/v1"
    assert s["subject"][1]["digest"]["sha1"] == sha
