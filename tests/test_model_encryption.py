"""Under a preset that requires encryption the project model is encrypted per entry, reads decrypt it, and a model that
cannot be encrypted is not written in plain text."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ZERO = {"preset": "zerotrust"}
KEY = b"k" * 32
NOTE = "the billing service retries on 503 and the retry budget lives in billing/retry.py"


@pytest.fixture
def model(isolated_state, fake_repo, monkeypatch):
    def load(preset=ZERO, available=True, key=KEY, import_error=False):
        (isolated_state / "settings.json").write_text(json.dumps(preset), encoding="utf-8")
        import crypto
        monkeypatch.setattr(crypto, "is_available", lambda: available)
        monkeypatch.setattr(crypto, "get_or_create_key", lambda: key)
        monkeypatch.setattr(crypto, "_backend_ops", lambda: ((lambda: key), None, None))
        if import_error:
            monkeypatch.setitem(sys.modules, "crypto", None)
        import _common
        import model as m
        importlib.reload(_common)
        return importlib.reload(m)
    return load


def _raw(m):
    p = m.model_path()
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_an_entry_written_under_zerotrust_is_not_on_disk_in_plain_text_and_reads_back(model):
    m = model()
    m.append_observation(NOTE)
    raw = _raw(m)
    assert "billing" not in raw and "retry" not in raw
    assert NOTE in m.read_model()


def test_a_preset_that_does_not_ask_for_encryption_writes_plain_as_before(model):
    m = model(preset={"preset": "solo-dev"})
    m.append_observation(NOTE)
    assert NOTE in _raw(m)


@pytest.mark.parametrize("why", [dict(available=False), dict(key=None), dict(import_error=True)], ids=["no-keychain", "no-key", "no-library"])
def test_a_model_entry_that_cannot_be_encrypted_is_not_written(model, why):
    m = model(**why)
    m.append_observation(NOTE)
    assert "billing" not in _raw(m)
    assert not m.model_path().exists() or "## " not in _raw(m)


def test_plain_entries_from_before_and_encrypted_entries_read_together(model):
    plain = model(preset={"preset": "solo-dev"})
    plain.append_observation("older plain note")
    m = model()
    m.append_observation(NOTE)
    text = m.read_model()
    assert "older plain note" in text and NOTE in text
    assert text.index("older plain note") < text.index(NOTE)


def test_truncation_applies_to_the_decrypted_text_and_keeps_the_newest_entries(model):
    m = model()
    for i in range(30):
        m.append_observation(f"entry number {i} " + "the queue drains in order. " * 8)
    text = m.read_model(max_chars=1500)
    assert "entry number 29" in text and "entry number 0 " not in text and "older entries elided" in text
    assert len(text) < 2500


def test_an_envelope_that_cannot_be_decrypted_reads_as_one_placeholder_not_an_error(model):
    m = model()
    m.append_observation("first")
    m.append_observation("second")
    other = model(key=b"z" * 32)
    text = other.read_model()
    assert "billing" not in text and "first" not in text
    assert text.count("encrypted entries unreadable") == 1 and "2 encrypted entries unreadable" in text


def test_model_chars_counts_the_decrypted_text_not_the_envelopes(model):
    m = model()
    m.append_observation("a" * 100)
    assert m.model_chars() == len(m.read_model())
    assert m.model_size() > m.model_chars()


def test_the_hostile_file_is_bounded(model):
    import time
    m = model()
    m.append_observation("real")
    with open(m.model_path(), "a", encoding="utf-8") as f:
        f.write('{"_e":"aes-gcm-v1","n":"AAAA","c":"AAAA"}\n' * 50_000)
    start = time.monotonic()
    text = m.read_model(max_chars=2000)
    assert time.monotonic() - start < 5.0 and "real" in text


def test_the_mcp_model_resource_serves_text_not_envelopes(model):
    m = model()
    m.append_observation(NOTE)
    import mcp_server
    importlib.reload(mcp_server)
    uri = next(r["uri"] for r in mcp_server.handle_resources_list({})["resources"] if r["uri"].endswith("/model"))
    served = mcp_server.handle_resources_read({"uri": uri})["contents"][0]["text"]
    assert NOTE in served and '"_e"' not in served


def test_the_curate_hint_measures_the_decrypted_model(model):
    import asyncio

    import hook_session_start as h
    m = model()
    for _ in range(12):
        m.append_observation(("the cache is keyed by tenant and region. " * 12).strip())
    importlib.reload(h)
    hint = asyncio.run(h.gather_curate_hint(os.getcwd(), {"model": {"enabled": True, "curate_threshold": 4000}}))
    assert "<curate_hint>" in hint
    shown = int(hint.split("model.md is ")[1].split(" chars")[0])
    assert shown == m.model_chars() and shown < m.model_size()


# --- replacing the model (what the curator does) -------------------------------------------------------------


CONSOLIDATED = "# Project model: maintained by presence\n\nheader line\n\n## Stable facts (consolidated 2026-11-26)\n\n- billing retries on 503\n\n## 2026-11-26 10:00\n\nrecent note\n"


def test_replacing_the_model_under_zerotrust_keeps_it_encrypted_and_readable(model):
    m = model()
    m.append_observation("old one")
    assert m.replace_model(CONSOLIDATED) is True
    raw = _raw(m)
    assert "billing" not in raw and "recent note" not in raw and "old one" not in raw
    text = m.read_model()
    assert "billing retries on 503" in text and "recent note" in text and "old one" not in text


def test_replacing_the_model_where_encryption_is_not_asked_for_writes_plain(model):
    m = model(preset={"preset": "solo-dev"})
    assert m.replace_model(CONSOLIDATED) is True
    assert "billing retries on 503" in _raw(m)


def test_a_replacement_that_cannot_be_encrypted_leaves_the_model_untouched(model):
    m = model()
    m.append_observation("keep me")
    before = _raw(m)
    broken = model(available=False)
    assert broken.replace_model(CONSOLIDATED) is False
    assert _raw(broken) == before and "billing" not in _raw(broken)


def test_a_replacement_is_redacted_and_bounded(model):
    m = model()
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789AB"
    assert m.replace_model(CONSOLIDATED + f"\n## 2026-11-26 11:00\n\ntoken {secret}\n") is True
    assert secret not in m.read_model()
    assert m.replace_model("x " * 400_000) is False  # over the cap: refused, the model is as it was
    assert "billing retries on 503" in m.read_model()


def _cli(args, stdin=""):
    import subprocess
    cli = os.path.join(os.path.dirname(__file__), "..", "lib", "cli.py")
    env = {**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "lib")}
    return subprocess.run([sys.executable, cli, *args], input=stdin, capture_output=True, text=True, env=env, check=False, cwd=os.getcwd())


def test_model_show_prints_the_decrypted_model_and_writes_nothing(model, isolated_state):
    m = model(preset={"preset": "solo-dev"})
    m.append_observation(NOTE)
    before = _raw(m)
    out = _cli(["model", "show"])
    assert out.returncode == 0 and NOTE in out.stdout
    assert _raw(m) == before


def test_model_replace_reads_the_new_body_from_stdin(model, isolated_state):
    m = model(preset={"preset": "solo-dev"})
    m.append_observation("old")
    out = _cli(["model", "replace"], stdin=CONSOLIDATED)
    assert out.returncode == 0
    assert "billing retries on 503" in m.read_model() and "old" not in m.read_model()


def test_model_replace_refuses_an_empty_body(model, isolated_state):
    m = model(preset={"preset": "solo-dev"})
    m.append_observation("keep")
    out = _cli(["model", "replace"], stdin="  \n")
    assert out.returncode != 0 and "keep" in m.read_model()


def test_the_curator_prompts_use_only_the_cli_and_never_edit_the_file_directly():
    root = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("agents/model-curator.md", "commands/presence-curate.md"):
        text = Path(root, rel).read_text(encoding="utf-8")
        assert "model show" in text and "model replace" in text
        assert "Use the Write tool" not in text and "Use the Read tool" not in text
        assert "model_path" not in text


def test_key_rotation_drops_the_encrypted_entries_of_every_project_and_keeps_the_plain_ones(model, isolated_state):
    plain = model(preset={"preset": "solo-dev"})
    plain.append_observation("older plain note")
    m = model()
    m.append_observation(NOTE)
    other = isolated_state / "projects" / "other" / "model.md"
    other.parent.mkdir(parents=True)
    other.write_text(_raw(m).splitlines()[-1] + "\n")
    assert m.drop_encrypted_entries() == 2
    text = m.read_model()
    assert "older plain note" in text and "unreadable" not in text and NOTE not in text
    assert other.read_text() == ""
    assert m.drop_encrypted_entries() == 0


def test_the_model_follows_its_own_encrypted_flag_not_the_other_sections(model):
    m = model(preset={"preset": "solo-dev", "overrides": {"telemetry.encrypted": True, "events.encrypted": True}})
    m.append_observation(NOTE)
    assert NOTE in _raw(m)
    assert m.replace_model(CONSOLIDATED) is True and "billing retries on 503" in _raw(m)
    m2 = model(preset={"preset": "solo-dev", "overrides": {"model.encrypted": True}})
    m2.append_observation("second")
    assert "second" not in _raw(m2) and "second" in m2.read_model()
