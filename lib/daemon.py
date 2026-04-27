"""Ephemeral hook daemon.

Listens on a Unix socket at ``$PRESENCE_STATE/presence.sock`` and dispatches
hook invocations sent by the Rust client (``ext/src/client.rs``). Each
invocation reuses the warm Python interpreter, eliminating the bash + python
startup cost from every hook fire (the v0.4.0 perf headline).

Lifecycle:
  - Spawned on demand by the Rust client when no socket exists.
  - Auto-exits after IDLE_TIMEOUT seconds with no requests, freeing memory.
  - Re-spawned by the next client request.

Security:
  - Socket created mode 0o600; state dir is mode 0o700. Only the owning user
    can connect.
  - PID file written for stale-process cleanup by the client.
  - Daemon log written mode 0o600 (presence's "no readable secrets" stance).

Concurrency:
  - One asyncio loop, sequential hook execution. The hooks themselves are
    short (sub-100 ms in the slow path) so a queue depth > 1 is not
    a real-world bottleneck. If it becomes one, a future version can add
    bounded parallelism.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

# Setup paths
PRESENCE_STATE = Path(os.environ.get("PRESENCE_STATE", Path.home() / ".claude" / "presence"))
SOCKET_PATH = PRESENCE_STATE / "presence.sock"
PID_PATH = PRESENCE_STATE / "presence.pid"

IDLE_TIMEOUT = 300  # 5 minutes before auto-exit

# Lazy import; daemon imports _common.py on startup to load helpers.
_common = None  # populated in PresenceDaemon.__init__


class PresenceDaemon:
    def __init__(self):
        self.last_request_time = time.time()
        self.running = True

        # Pre-import all hook modules so dispatch is just a function call.
        # Without this, each request would pay the import cost on first fire
        # (defeats the daemon's reason for existing).
        import hook_post_tool_bash
        import hook_post_tool_edit
        import hook_pre_tool_bash
        import hook_session_start
        import hook_stop
        import hook_user_prompt_submit
        global _common  # noqa: PLW0603  module-level cache pattern; recognized
        import _common  # noqa: F811

        self.hooks = {
            "session-start": hook_session_start.main,
            "user-prompt-submit": hook_user_prompt_submit.main,
            "post-tool-bash": hook_post_tool_bash.main,
            "pre-tool-bash": hook_pre_tool_bash.main,
            "post-tool-edit": hook_post_tool_edit.main,
            "stop": hook_stop.main,
        }

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ):
        self.last_request_time = time.time()
        try:
            data = await reader.read()
            if not data:
                return

            try:
                req = _common._loads(data)
            except (json.JSONDecodeError, ValueError):
                writer.write(b"Malformed JSON request")
                await writer.drain()
                return

            hook_name = req.get("hook")
            stdin_data = req.get("stdin", "")

            if hook_name not in self.hooks:
                writer.write(b"Unknown hook")
                await writer.drain()
                return

            # Capture stdout by monkeypatching sys.stdout. The hook's
            # emit_context() writes to sys.stdout; we route that to our
            # buffer and ship it back to the client.
            class StdoutCapture:
                def __init__(self):
                    self.buffer = io.BytesIO()

                def write(self, s):
                    if isinstance(s, str):
                        self.buffer.write(s.encode("utf-8"))
                    else:
                        self.buffer.write(s)

                def flush(self):
                    pass

            capture = StdoutCapture()
            original_stdout = sys.stdout
            original_stdout_buffer = getattr(sys.stdout, "buffer", None)
            sys.stdout = capture  # type: ignore[assignment]
            # Some adapters write to sys.stdout.buffer for binary; route there too.
            sys.stdout.buffer = capture.buffer  # type: ignore[attr-defined]

            original_stdin = sys.stdin
            sys.stdin = io.StringIO(stdin_data)

            try:
                # Clear per-process caches so each request reads fresh state.
                # The daemon may live for minutes across many user actions;
                # a stale settings.json or encryption-state cache would mask
                # changes the user just made.
                _common._SETTINGS_CACHE = None
                _common._WRITE_STATE_CACHE = None
                _common._READ_KEY_CACHE = _common._UNSET

                self.hooks[hook_name]()
            except SystemExit:
                # safe_main calls sys.exit(0) on completion; that must not
                # kill the daemon process.
                pass
            except Exception:  # noqa: BLE001  outermost guard inside the daemon
                # The hook's own safe_main() should have caught everything;
                # if something escapes, swallow it here so the daemon stays up.
                pass
            finally:
                sys.stdout = original_stdout
                if original_stdout_buffer is not None:
                    try:
                        sys.stdout.buffer = original_stdout_buffer  # type: ignore[attr-defined]
                    except (AttributeError, TypeError):
                        pass
                sys.stdin = original_stdin

            writer.write(capture.buffer.getvalue())
            await writer.drain()

        except Exception:  # noqa: BLE001  daemon must never crash on a bad client
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self.last_request_time = time.time()

    async def _idle_watchdog(self):
        while self.running:
            await asyncio.sleep(10)
            if time.time() - self.last_request_time > IDLE_TIMEOUT:
                self.running = False
                try:
                    SOCKET_PATH.unlink(missing_ok=True)
                    PID_PATH.unlink(missing_ok=True)
                except OSError:
                    pass
                sys.exit(0)

    async def serve(self):
        # Enforce 0700 on the state dir.
        PRESENCE_STATE.mkdir(parents=True, exist_ok=True)
        try:
            PRESENCE_STATE.chmod(0o700)
        except OSError:
            pass

        # Clean up any stale socket from a prior crashed daemon.
        SOCKET_PATH.unlink(missing_ok=True)

        # Write PID for the client to find us by (and to kill stale instances).
        PID_PATH.write_text(str(os.getpid()))
        try:
            PID_PATH.chmod(0o600)
        except OSError:
            pass

        server = await asyncio.start_unix_server(self.handle_client, path=str(SOCKET_PATH))

        # Restrict socket permissions: only the owner can connect. This is
        # presence's primary cross-user isolation guarantee on the daemon path.
        try:
            SOCKET_PATH.chmod(0o600)
        except OSError:
            pass

        asyncio.create_task(self._idle_watchdog())

        async with server:
            await server.serve_forever()


def main():
    daemon = PresenceDaemon()
    try:
        asyncio.run(daemon.serve())
    except KeyboardInterrupt:
        pass
    finally:
        SOCKET_PATH.unlink(missing_ok=True)
        PID_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    # Redirect stderr to a log file for debugging daemon issues. The Rust
    # client spawns us detached (stdin/stdout already /dev/null).
    try:
        PRESENCE_STATE.mkdir(parents=True, exist_ok=True)
        log = PRESENCE_STATE / "daemon.log"
        sys.stderr = open(log, "a", encoding="utf-8")  # noqa: SIM115
        try:
            log.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass
    main()
