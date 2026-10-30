"""Release artifact trust: pinned Actions, installer checksum verification, asset-name agreement."""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
INSTALL_SH = ROOT / "install.sh"


def test_every_action_is_pinned_to_a_commit_sha():
    unpinned = []
    for wf in WORKFLOWS:
        for n, line in enumerate(wf.read_text().splitlines(), 1):
            m = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
            if m and not m.group(1).startswith("./") and not re.search(r"@[0-9a-f]{40}$", m.group(1)):
                unpinned.append(f"{wf.name}:{n}: {m.group(1)}")
    assert not unpinned, "pin by 40-char commit SHA (keep the tag in a trailing comment):\n" + "\n".join(unpinned)


def _installer_assets() -> set[str]:
    return set(re.findall(r'asset="(presence-client-[\w-]+)"', INSTALL_SH.read_text()))


def _workflow_assets() -> set[str]:
    return set(re.findall(r"artifact:\s*(presence-client-[\w-]+)", (ROOT / ".github/workflows/release.yml").read_text()))


def test_installer_only_asks_for_assets_the_release_builds():
    assert _installer_assets() and _installer_assets() <= _workflow_assets()


def test_every_built_asset_is_reachable_from_the_installer():
    assert _workflow_assets() <= _installer_assets()


def test_release_workflow_publishes_checksums_attestations_and_sbom():
    text = (ROOT / ".github/workflows/release.yml").read_text()
    assert "SHA256SUMS" in text
    assert "attest-build-provenance" in text and "id-token: write" in text and "attestations: write" in text
    assert "sbom-action" in text


# --- installer checksum verification ---------------------------------------

def _host_asset() -> str | None:
    s, m = platform.system(), platform.machine()
    return {
        ("Darwin", "arm64"): "presence-client-macos-arm64",
        ("Darwin", "x86_64"): "presence-client-macos-x86_64",
        ("Linux", "x86_64"): "presence-client-linux-x86_64",
        ("Linux", "aarch64"): "presence-client-linux-arm64",
    }.get((s, m))


needs_asset = pytest.mark.skipif(_host_asset() is None, reason="no pre-built client for this host")


@pytest.fixture
def clone(tmp_path):
    c = tmp_path / "clone"
    (c / "lib").mkdir(parents=True)
    (c / ".claude-plugin").mkdir()
    (c / ".claude-plugin" / "plugin.json").write_text('{"name":"presence","version":"9.9.9"}')
    shutil.copy2(INSTALL_SH, c / "install.sh")
    return c


def _release(tmp_path, content=b"binary-bytes", sums="auto", name=None):
    rel = tmp_path / "release"
    rel.mkdir(exist_ok=True)
    asset = name or _host_asset()
    if content is not None:
        (rel / asset).write_bytes(content)
    if sums == "auto":
        sums = f"{hashlib.sha256(content).hexdigest()}  {asset}\n"
    if sums is not None:
        (rel / "SHA256SUMS").write_text(sums)
    return rel


def _download(clone, rel):
    env = {**os.environ, "CLAUDE_HOME": str(clone.parent / "home"), "PRESENCE_RELEASE_BASE": rel.as_uri()}
    return subprocess.run(
        ["bash", str(clone / "install.sh"), "--download-ext"],
        capture_output=True, text=True, check=False, env=env, cwd=clone,
    )


@needs_asset
def test_download_verifies_checksum_and_installs(clone, tmp_path):
    r = _download(clone, _release(tmp_path))
    assert r.returncode == 0, r.stderr
    target = clone / "lib" / "presence-client"
    assert target.read_bytes() == b"binary-bytes" and os.access(target, os.X_OK)
    assert "checksum verified" in r.stdout


@needs_asset
def test_download_rejects_a_tampered_binary_and_leaves_nothing(clone, tmp_path):
    rel = _release(tmp_path)
    (rel / _host_asset()).write_bytes(b"evil-bytes")
    r = _download(clone, rel)
    assert r.returncode != 0 and "checksum mismatch" in r.stderr
    assert not (clone / "lib" / "presence-client").exists()


@needs_asset
def test_download_rejects_sums_without_an_entry_for_the_asset(clone, tmp_path):
    rel = _release(tmp_path, sums=f"{'0' * 64}  some-other-file\n")
    r = _download(clone, rel)
    assert r.returncode != 0 and "no entry" in r.stderr
    assert not (clone / "lib" / "presence-client").exists()


@needs_asset
def test_download_accepts_binary_mode_and_uppercase_hashes(clone, tmp_path):
    h = hashlib.sha256(b"binary-bytes").hexdigest().upper()
    r = _download(clone, _release(tmp_path, sums=f"{h} *{_host_asset()}\n"))
    assert r.returncode == 0, r.stderr


@needs_asset
def test_download_without_sums_warns_but_installs_older_releases(clone, tmp_path):
    r = _download(clone, _release(tmp_path, sums=None))
    assert r.returncode == 0 and "not verified" in r.stderr
    assert (clone / "lib" / "presence-client").exists()


@needs_asset
def test_download_fails_cleanly_when_the_asset_is_missing(clone, tmp_path):
    r = _download(clone, _release(tmp_path, content=None, sums=None))
    assert r.returncode != 0
    assert not (clone / "lib" / "presence-client").exists()


@needs_asset
def test_download_keeps_an_existing_client_when_verification_fails(clone, tmp_path):
    existing = clone / "lib" / "presence-client"
    existing.write_bytes(b"known-good")
    rel = _release(tmp_path)
    (rel / _host_asset()).write_bytes(b"evil-bytes")
    assert _download(clone, rel).returncode != 0
    assert existing.read_bytes() == b"known-good"
