"""doctor.py CLI paths (--json, text, --fix) and the Zero-Trust report lines."""
from __future__ import annotations

import importlib
import json
import sys

import _common
import doctor


def _reload(state_dir, monkeypatch):
    monkeypatch.setenv("PRESENCE_STATE", str(state_dir))
    importlib.reload(_common)
    importlib.reload(doctor)
    return doctor


def _run(d, monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["doctor", *argv])
    rc = d._cli()
    return rc, capsys.readouterr().out


def test_cli_text_report(isolated_state, monkeypatch, capsys):
    d = _reload(isolated_state, monkeypatch)
    rc, out = _run(d, monkeypatch, capsys)
    assert rc == 0 and out.strip()


def test_cli_json_report(isolated_state, monkeypatch, capsys):
    d = _reload(isolated_state, monkeypatch)
    rc, out = _run(d, monkeypatch, capsys, "--json")
    assert rc == 0 and "notify" in json.loads(out)


def test_cli_fix_reports_actions_and_remaining(isolated_state, monkeypatch, capsys):
    d = _reload(isolated_state, monkeypatch)
    monkeypatch.setattr(d, "fix", lambda: (["chmod 0o700 x"], ["still broken"]))
    rc, out = _run(d, monkeypatch, capsys, "--fix")
    assert rc == 1
    assert "fixed: chmod 0o700 x" in out and "still broken" in out
    monkeypatch.setattr(d, "fix", lambda: ([], []))
    rc, out = _run(d, monkeypatch, capsys, "--fix")
    assert rc == 0 and "nothing to do" in out
    monkeypatch.setattr(d, "fix", lambda: (["a"], []))
    rc, out = _run(d, monkeypatch, capsys, "--fix", "--json")
    assert rc == 0 and json.loads(out) == {"actions": ["a"], "remaining": []}


def test_cli_refresh_disabled(isolated_state, monkeypatch, capsys):
    import update_check

    d = _reload(isolated_state, monkeypatch)
    monkeypatch.setattr(update_check, "is_enabled", lambda cfg: False)
    rc, out = _run(d, monkeypatch, capsys, "--refresh")
    assert rc == 1 and "disabled" in out


def test_zerotrust_report_audit_chain_states(isolated_state, monkeypatch):
    import audit

    d = _reload(isolated_state, monkeypatch)
    importlib.reload(audit)
    assert any("no audit log yet" in ln for ln in d.zerotrust_report())
    for i in range(3):
        audit.append("step", {"i": i})
    assert any("audit chain" in ln and "OK (3 line(s)" in ln for ln in d.zerotrust_report())
    lines = audit.audit_path().read_text().splitlines()
    audit.audit_path().write_text("\n".join(lines[:2]) + "\n")
    fail = [ln for ln in d.zerotrust_report() if ln.startswith("audit chain")]
    assert "FAIL" in fail[0] and "truncated" in fail[0] and "--audit-rotate" in fail[0]
