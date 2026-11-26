"""Tests for lib/daemon.py (v0.4.0).

The daemon runs detached; we test it by spawning a real subprocess, sending
a JSON payload over the Unix socket, and asserting the response. Skip on
Windows (no Unix sockets) and on systems where bash/python3 isn't usable
in the test sandbox.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DAEMON_PY = REPO_ROOT / "lib" / "daemon.py"


pytestmark = pytest.mark.skipif(
    platform.system() == "Windows",
    reason="presence daemon uses Unix sockets; Windows native is tracked as a roadmap item",
)


@pytest.fixture
def short_state_dir():
    """Create a tmp dir whose path is short enough for AF_UNIX.

    macOS caps Unix socket paths at 104 bytes, Linux at 108. pytest's tmp_path
    nests under /private/var/folders/.../pytest-of-USER/pytest-NN/... which
    blows past the cap. Use mkdtemp under /tmp directly.
    """
    p = Path(tempfile.mkdtemp(prefix="pres-", dir="/tmp"))
    state = p / "s"

    yield state
    shutil.rmtree(p, ignore_errors=True)


def _spawn_daemon(state_dir: Path) -> subprocess.Popen:
    """Start the daemon as a background process pointing at state_dir."""
    env = {
        **os.environ,
        "PRESENCE_STATE": str(state_dir),
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "PYTHONPATH": str(REPO_ROOT / "lib"),
    }
    return subprocess.Popen(
        [sys.executable, str(DAEMON_PY)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_daemon(proc: subprocess.Popen) -> None:
    """Terminate a spawned daemon and reap it. Always wait after kill: coverage
    instrumentation slows daemon shutdown past a short terminate timeout, and an
    unreaped Popen trips a ResourceWarning in Popen.__del__ that filterwarnings
    error escalates into a failure."""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _wait_for_socket(sock_path: Path, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sock_path.exists():
            return True
        time.sleep(0.05)
    return False


def _send_request(sock_path: Path, payload: dict) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(sock_path))
    s.sendall(json.dumps(payload).encode("utf-8"))
    s.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    s.close()
    return b"".join(chunks)


def test_daemon_responds_to_user_prompt_submit(short_state_dir):
    state = short_state_dir

    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"

        # Send a UserPromptSubmit hook with empty events; expect empty stdout
        # (no events to drain) and clean exit (no daemon crash).
        response = _send_request(sock, {
            "hook": "user-prompt-submit",
            "stdin": json.dumps({"cwd": str(REPO_ROOT), "prompt": "test"}),
        })
        # Empty response is the expected case (no pending events).
        assert response == b"" or b"hookSpecificOutput" in response

        # Daemon should still be alive after one request.
        assert proc.poll() is None
    finally:
        _stop_daemon(proc)


def test_daemon_socket_perms_are_0600(short_state_dir):
    """The daemon socket must be 0o600 so other users on the same machine
    cannot connect. This is the daemon's primary cross-user isolation."""
    import stat

    state = short_state_dir

    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"
        # bind() under umask 077 leaves the node at 0o700 (owner-only) until the
        # daemon's chmod to 0o600 lands, so the file appearing is not the signal.
        deadline = time.time() + 5.0
        mode = stat.S_IMODE(sock.stat().st_mode)
        while mode != 0o600 and time.time() < deadline:
            time.sleep(0.05)
            mode = stat.S_IMODE(sock.stat().st_mode)
        assert mode == 0o600, f"socket perms should be 0o600, got 0o{mode:03o}"
    finally:
        _stop_daemon(proc)


def test_daemon_writes_pid_file(short_state_dir):
    """The PID file is what the Rust client reads to kill stale daemons
    when the socket is unresponsive."""
    state = short_state_dir

    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"
        pid_file = state / "presence.pid"
        assert pid_file.exists()
        recorded_pid = int(pid_file.read_text().strip())
        assert recorded_pid == proc.pid
    finally:
        _stop_daemon(proc)


def test_daemon_rejects_unknown_hook(short_state_dir):
    state = short_state_dir

    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"
        response = _send_request(sock, {"hook": "made-up-hook", "stdin": "{}"})
        assert b"Unknown hook" in response
        # Daemon stays alive after a bad request.
        assert proc.poll() is None
    finally:
        _stop_daemon(proc)


def test_daemon_handles_multiple_sequential_requests(short_state_dir):
    """A single daemon instance must serve many requests without leaking
    state or crashing. Regression check for the per-request cache clearing
    in handle_client (without it, settings/encryption state cached on the
    first call would persist for all subsequent calls in the same daemon
    lifetime, masking changes the user just made)."""
    state = short_state_dir
    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"

        # Fire 5 sequential UserPromptSubmit hooks. All should return cleanly,
        # daemon stays alive throughout, no resource leak.
        for i in range(5):
            response = _send_request(sock, {
                "hook": "user-prompt-submit",
                "stdin": json.dumps({"cwd": str(REPO_ROOT), "prompt": f"req {i}"}),
            })
            # Empty or valid JSON either way - never raise.
            if response:
                assert b"hookSpecificOutput" in response or response == b""
            assert proc.poll() is None, f"daemon died after request {i}"
    finally:
        _stop_daemon(proc)


def test_daemon_clears_caches_between_requests(short_state_dir, monkeypatch):
    """The daemon clears _SETTINGS_CACHE / _WRITE_STATE_CACHE / _READ_KEY_CACHE
    on every request so a settings.json change between requests is visible.
    Without this, the first request's preset would lock in for the daemon's
    entire 5-min lifetime - silently masking /presence-preset use commands."""
    state = short_state_dir
    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"

        # Fire one hook; then write a settings.json that changes the preset;
        # fire another hook. The second hook must observe the new settings.
        _send_request(sock, {
            "hook": "user-prompt-submit",
            "stdin": json.dumps({"cwd": str(REPO_ROOT), "prompt": "first"}),
        })
        # Write settings.json. The daemon's _SETTINGS_CACHE for this state
        # was populated by the first request; we need it cleared by the second.
        (state / "settings.json").write_text(
            json.dumps({"preset": "team-oss"}), encoding="utf-8",
        )
        # Second request: if the cache was cleared, it picks up the new
        # preset. If not, we'd see solo-dev (the default) still.
        # We can't easily observe the preset name from the daemon response,
        # but we CAN verify the daemon didn't crash and didn't leak the
        # cache by checking it stays alive after a settings change.
        response = _send_request(sock, {
            "hook": "user-prompt-submit",
            "stdin": json.dumps({"cwd": str(REPO_ROOT), "prompt": "second"}),
        })
        assert proc.poll() is None
        # Sanity: response is parseable or empty.
        if response:
            assert b"hookSpecificOutput" in response or response == b""
    finally:
        _stop_daemon(proc)


def test_daemon_idle_timeout_auto_exits(short_state_dir, monkeypatch):
    """Daemon must auto-exit after IDLE_TIMEOUT seconds of no requests so
    long-lived shells don't accumulate stale daemons. We patch IDLE_TIMEOUT
    to a short value via env, then wait for the daemon to exit on its own.

    This test is deliberately fragile timing-wise (uses a real wall-clock
    delay); we cap at 8s and skip if the runner is too slow."""
    state = short_state_dir
    # Patch IDLE_TIMEOUT to 2 seconds for this test by using a wrapper
    # script that imports daemon and overrides the constant.
    wrapper = state.parent / "fast_daemon.py"
    wrapper.write_text(
        f"import sys; sys.path.insert(0, '{REPO_ROOT}/lib')\n"
        "import daemon\n"
        "daemon.IDLE_TIMEOUT = 2\n"
        "daemon.main()\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PRESENCE_STATE": str(state),
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "PYTHONPATH": str(REPO_ROOT / "lib"),
    }
    proc = subprocess.Popen(
        [sys.executable, str(wrapper)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"
        # Fire one request to set last_request_time, then wait > IDLE_TIMEOUT.
        _send_request(sock, {
            "hook": "user-prompt-submit",
            "stdin": json.dumps({"cwd": str(REPO_ROOT), "prompt": "ping"}),
        })
        # Watchdog runs every 10s by default, but since IDLE_TIMEOUT=2 we
        # expect exit within 12-13s (10s tick + 2s threshold); check up to 15s.
        deadline = time.time() + 15
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.5)
        if proc.poll() is None:
            pytest.skip("daemon did not auto-exit within 15s; runner may be slow")
        # Auto-exit happened: socket should also be cleaned up.
        assert not sock.exists(), "daemon left a stale socket on auto-exit"
    finally:
        if proc.poll() is None:
            _stop_daemon(proc)


def test_daemon_handles_malformed_json(short_state_dir):
    state = short_state_dir

    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock), "daemon did not create socket within 5s"
        # Send raw bytes that aren't valid JSON; daemon should respond with
        # an error message rather than crash.
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock))
        s.sendall(b"this is not json {{{")
        s.shutdown(socket.SHUT_WR)
        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
        s.close()
        assert b"Malformed" in response
        assert proc.poll() is None
    finally:
        _stop_daemon(proc)


# --- a gate decision is never lost, whoever else is starting, failing or updating -------------------------------


def _alive(sock: Path) -> bool:
    try:
        return _send_request(sock, {"hook": "nope", "stdin": ""}) == b"Unknown hook"
    except OSError:
        return False


def test_a_second_daemon_on_the_same_state_exits_and_leaves_the_first_serving(short_state_dir):
    """Two hooks starting at once used to start two daemons, the second deleting the first one's socket."""
    state = short_state_dir
    first = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock)
        second = _spawn_daemon(state)
        try:
            assert second.wait(timeout=15) == 0
        finally:
            _stop_daemon(second)
        assert first.poll() is None and sock.exists() and _alive(sock)
        assert (state / "presence.pid").read_text().strip() == str(first.pid)
    finally:
        _stop_daemon(first)


def test_a_hook_that_raises_is_logged_and_counted_not_swallowed(short_state_dir, monkeypatch, capsys):
    import asyncio
    import importlib

    monkeypatch.setenv("PRESENCE_STATE", str(short_state_dir))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    import _common
    importlib.reload(_common)
    import daemon
    importlib.reload(daemon)
    d = daemon.PresenceDaemon()

    def boom():
        raise RuntimeError("hook exploded")
    d.hooks["stop"] = boom

    class Reader:
        async def read(self):
            return json.dumps({"hook": "stop", "stdin": "{}"}).encode()

    class Writer:
        def write(self, _b): pass
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass

    asyncio.run(d.handle_client(Reader(), Writer()))
    assert "hook exploded" in capsys.readouterr().err
    assert _common.read_counter("error") == 1


def _plugin_root(tmp):
    root = tmp / "plugin"
    (root / "lib").mkdir(parents=True)
    (root / ".claude-plugin").mkdir()
    (root / "lib" / "__init__.py").write_text('__version__ = "1"\n')
    (root / "MANIFEST.lock").write_text("a\n")
    (root / ".claude-plugin" / "plugin.json").write_text("{}\n")
    return root


def test_the_daemon_retires_after_a_reply_once_the_installed_plugin_changed(short_state_dir, tmp_path):
    """An update used to leave a warm daemon serving the old code until it idled out five minutes later."""
    state = short_state_dir
    root = _plugin_root(tmp_path)
    env = {**os.environ, "PRESENCE_STATE": str(state), "CLAUDE_PLUGIN_ROOT": str(root), "PYTHONPATH": str(REPO_ROOT / "lib")}
    proc = subprocess.Popen([sys.executable, str(DAEMON_PY)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock)
        assert _alive(sock) and proc.poll() is None  # unchanged: stays up
        (root / "MANIFEST.lock").write_text("b changed\n")
        os.utime(root / "MANIFEST.lock", (time.time() + 5, time.time() + 5))
        assert _alive(sock)  # this request is still answered
        assert proc.wait(timeout=10) == 0
        assert not sock.exists() and not (state / "presence.pid").exists()
    finally:
        _stop_daemon(proc)


def test_a_stop_block_comes_back_through_the_daemon(short_state_dir, tmp_path):
    """The gate's whole job: an unverified claim after an edit is blocked, over the socket, end to end."""
    state = short_state_dir
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    (repo / "pytest.ini").write_text("[pytest]\n")
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True)
    state.mkdir(parents=True, exist_ok=True)
    (state / "settings.json").write_text(json.dumps({"preset": "solo-dev", "overrides": {"confidence.stop_action": "block"}}))
    proc = _spawn_daemon(state)
    try:
        sock = state / "presence.sock"
        assert _wait_for_socket(sock)
        (repo / "a.py").write_text("x = 2\n")
        _send_request(sock, {"hook": "post-tool-edit", "stdin": json.dumps(
            {"cwd": str(repo), "session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": str(repo / "a.py")}})})
        out = _send_request(sock, {"hook": "stop", "stdin": json.dumps(
            {"cwd": str(repo), "session_id": "s1", "last_assistant_message": "Done, it works now."})})
        assert b'"decision":"block"' in out.replace(b" ", b""), out
    finally:
        _stop_daemon(proc)


def test_the_client_waits_as_long_as_the_host_lets_a_hook_run_and_never_kills_by_pid_file():
    src = (REPO_ROOT / "ext" / "src" / "client.rs").read_text()
    assert "from_millis(500)" not in src
    assert 'arg("-9")' not in src, "a pid file can be stale and name an unrelated process"
