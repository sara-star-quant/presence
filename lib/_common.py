"""Shared utilities for presence hooks. No external deps; stdlib only.

Every hook entry point should call ``safe_main(fn)`` so any internal failure logs and
exits 0 so Claude Code never sees a presence-induced error. ``safe_main`` increments
an error counter that the next ``SessionStart`` surfaces to the user, so failures are
recoverable from the in-product UI without the user grepping log files.

Module never raises at import time on any platform: ``fcntl`` is lazily imported.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path

# Public env vars
STATE_DIR = Path(os.environ.get("PRESENCE_STATE") or (Path.home() / ".claude" / "presence"))
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent))

DEFAULT_GIT_TIMEOUT = 15  # seconds; overridable via settings: git.timeout_seconds


# ---------------------------------------------------------------------------
# State directory bootstrap with strict perms
# ---------------------------------------------------------------------------

def _ensure_dir(p: Path, mode: int = 0o700) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    try:
        current = stat.S_IMODE(p.stat().st_mode)
        if current != mode:
            p.chmod(mode)
    except (OSError, NotImplementedError):
        # Windows, network FS, exotic permission models; best effort.
        pass
    return p


def state_dir() -> Path:
    return _ensure_dir(STATE_DIR)


def project_dir(cwd: str | os.PathLike[str] | None = None) -> Path:
    return _ensure_dir(state_dir() / "projects" / repo_id(cwd))


def events_dir(cwd: str | os.PathLike[str] | None = None) -> Path:
    return _ensure_dir(state_dir() / "events" / repo_id(cwd))


def telemetry_dir() -> Path:
    return _ensure_dir(state_dir() / "telemetry")


def logs_dir() -> Path:
    return _ensure_dir(state_dir() / "logs")


# ---------------------------------------------------------------------------
# Git helpers: distinguish missing-binary / timeout / nonzero-exit so the
# warnings system can surface each correctly.
# ---------------------------------------------------------------------------

class GitError(Exception):
    """Base for git invocation problems."""


class GitNotInstalled(GitError):
    pass


class GitTimeout(GitError):
    pass


class GitFailed(GitError):
    pass


def git_run(cwd: str | os.PathLike[str], *args: str, timeout: int | None = None) -> str:
    """Run ``git -C cwd <args>``; return stdout (stripped). Raise typed GitError subclass on failure."""
    timeout = timeout or DEFAULT_GIT_TIMEOUT
    try:
        out = subprocess.check_output(
            ["git", "-C", str(cwd), *args],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise GitNotInstalled("git binary not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitTimeout(f"git {' '.join(args)} timed out after {timeout}s") from exc
    except subprocess.CalledProcessError as exc:
        raise GitFailed(f"git {' '.join(args)} exited {exc.returncode}") from exc
    return out.strip()


def git_run_safe(cwd: str | os.PathLike[str], *args: str, timeout: int | None = None) -> str | None:
    """Convenience wrapper: return None on any git failure, warn appropriately."""
    from warnings_log import warn  # local import to avoid cycle at module load

    try:
        return git_run(cwd, *args, timeout=timeout)
    except GitNotInstalled:
        warn("git_missing", "git binary not found on PATH; commit telemetry disabled")
        return None
    except GitTimeout as exc:
        warn("git_timeout", str(exc), cmd=list(args))
        return None
    except GitFailed:
        # Common case: not a git repo. Don't warn (too noisy).
        return None


async def async_git_run(cwd: str | os.PathLike[str], *args: str, timeout: int | None = None) -> str:
    """Async variant of git_run."""
    timeout = timeout or DEFAULT_GIT_TIMEOUT
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(cwd), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise GitTimeout(f"git {' '.join(args)} timed out after {timeout}s") from exc

        if proc.returncode != 0:
            raise GitFailed(f"git {' '.join(args)} exited {proc.returncode}")

        return stdout.decode("utf-8", errors="replace").strip()
    except FileNotFoundError as exc:
        raise GitNotInstalled("git binary not on PATH") from exc


async def async_git_run_safe(cwd: str | os.PathLike[str], *args: str, timeout: int | None = None) -> str | None:
    """Async variant of git_run_safe."""
    from warnings_log import warn  # local import to avoid cycle at module load

    try:
        return await async_git_run(cwd, *args, timeout=timeout)
    except GitNotInstalled:
        warn("git_missing", "git binary not found on PATH; commit telemetry disabled")
        return None
    except GitTimeout as exc:
        warn("git_timeout", str(exc), cmd=list(args))
        return None
    except GitFailed:
        return None


# ---------------------------------------------------------------------------
# Project identity
# ---------------------------------------------------------------------------

def repo_id(cwd: str | os.PathLike[str] | None = None) -> str:
    """Stable id for the current project. Prefers git remote URL; falls back to cwd path."""
    base = Path(cwd or os.getcwd()).resolve()
    # Use git itself to find toplevel; avoids the .git-walk-into-parent-tree footgun
    top = git_run_safe(base, "rev-parse", "--show-toplevel")
    if top:
        repo_root_path = Path(top)
        remote = git_run_safe(repo_root_path, "config", "--get", "remote.origin.url")
        seed = remote if remote else str(repo_root_path)
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return hashlib.sha256(str(base).encode("utf-8")).hexdigest()[:12]


def repo_root(cwd: str | os.PathLike[str] | None = None) -> Path:
    base = Path(cwd or os.getcwd()).resolve()
    top = git_run_safe(base, "rev-parse", "--show-toplevel")
    return Path(top) if top else base


# ---------------------------------------------------------------------------
# File I/O: atomic, locked where needed, encoding always utf-8
# ---------------------------------------------------------------------------

def _flock(fd: int, exclusive: bool = True) -> Callable[[], None]:
    """Best-effort file lock. Returns a noop-on-unlock callable on platforms without fcntl."""
    try:
        import fcntl
    except ImportError:
        return lambda: None
    fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    return lambda: fcntl.flock(fd, fcntl.LOCK_UN)


def atomic_write(path: str | os.PathLike[str], content: str, mode: int = 0o600) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    try:
        tmp.chmod(mode)
    except OSError:
        pass
    tmp.replace(p)


def append_jsonl(path: str | os.PathLike[str], obj: dict, mode: int = 0o600) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        unlock = _flock(f.fileno(), exclusive=True)
        try:
            f.write(line)
        finally:
            unlock()
    try:
        os.chmod(p, mode)
    except OSError:
        pass


def append_jsonl_rotating(
    path: str | os.PathLike[str],
    obj: dict,
    max_bytes: int = 1_000_000,
    mode: int = 0o600,
) -> None:
    """append_jsonl + size-based rotation. Once the file exceeds ``max_bytes``,
    rename it to ``<path>.1`` (overwriting any prior rotation). Single generation
    only; older history beyond that point is intentionally dropped.

    Used for telemetry files (claims/outcomes/confidence) where unbounded growth
    becomes a perf and storage problem but historical data beyond a rotation cycle
    has limited value (we only care about recent claims for revert detection).
    """
    p = Path(path)
    append_jsonl(p, obj, mode=mode)
    try:
        if p.stat().st_size > max_bytes:
            rotated = p.with_suffix(p.suffix + ".1")
            p.replace(rotated)  # atomic move; next append re-creates the file
    except OSError:
        pass


def read_jsonl(path: str | os.PathLike[str]) -> list[dict]:
    """Return parsed lines. Missing file -> []. Corrupt lines -> warn + skip."""
    from warnings_log import warn

    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    corrupt = 0
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    out.append(json.loads(s))
                except json.JSONDecodeError:
                    corrupt += 1
    except OSError as exc:
        warn("io_read_failed", f"could not read {p}: {exc}")
        return []
    if corrupt:
        warn(
            "jsonl_corrupt",
            f"{corrupt} corrupt line(s) skipped in {p.name}",
            path=str(p),
            count=corrupt,
        )
    return out


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def now_ts() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Hook protocol
# ---------------------------------------------------------------------------

def hook_input() -> dict:
    """Read JSON from stdin. Empty -> {}. Malformed -> warn + {}. Never raises."""
    from warnings_log import warn

    try:
        data = sys.stdin.read()
    except OSError as exc:
        warn("hook_stdin_io", f"failed to read hook stdin: {exc}")
        return {}
    if not data:
        return {}
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as exc:
        warn(
            "hook_input_malformed",
            f"malformed hook JSON: {exc.msg} at pos {exc.pos}",
            head=data[:200],
        )
        return {}
    return obj if isinstance(obj, dict) else {}


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def emit_context(event_name: str, text: str) -> None:
    if not text:
        return
    emit({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    })


def safe_main(fn: Callable[[], None]) -> None:
    """Run a hook entry point. On exception: log + count + fall back to stderr + exit 0."""
    try:
        fn()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001  outermost guard; never propagate
        tb = traceback.format_exc()
        wrote = False
        try:
            log_path = logs_dir() / "errors.log"
            _rotate_if_large(log_path, max_bytes=1_000_000)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {sys.argv[0]}\n{tb}\n")
            wrote = True
            _bump_counter("error")
        except OSError:
            pass
        if not wrote:
            try:
                sys.stderr.write(f"presence: hook {sys.argv[0]} failed and could not log: {tb[:200]}\n")
            except OSError:
                pass
    sys.exit(0)


def _rotate_if_large(path: Path, max_bytes: int) -> None:
    try:
        if path.exists() and path.stat().st_size >= max_bytes:
            path.replace(path.with_suffix(path.suffix + ".old"))
    except OSError:
        pass


def _bump_counter(name: str) -> None:
    """Increment a small int counter file. Used for error/warning surfacing."""
    p = logs_dir() / f"{name}_count"
    try:
        cur = int(p.read_text(encoding="utf-8").strip()) if p.exists() else 0
    except (OSError, ValueError):
        cur = 0
    try:
        atomic_write(p, str(cur + 1) + "\n")
    except OSError:
        pass


def read_counter(name: str) -> int:
    p = logs_dir() / f"{name}_count"
    try:
        return int(p.read_text(encoding="utf-8").strip()) if p.exists() else 0
    except (OSError, ValueError):
        return 0


def reset_counter(name: str) -> None:
    p = logs_dir() / f"{name}_count"
    try:
        atomic_write(p, "0\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Settings: distinguish missing (silent default) from corrupt (loud warn)
# ---------------------------------------------------------------------------

class SettingsError(Exception):
    pass


def settings(strict: bool = False) -> dict:
    """Return merged active preset + user overrides.

    Missing files -> defaults silently.
    Corrupt files -> warn loudly via warnings channel (and raise SettingsError if strict).
    """
    from warnings_log import warn

    s_path = state_dir() / "settings.json"
    user_settings: dict = {}
    if s_path.exists():
        try:
            user_settings = json.loads(s_path.read_text(encoding="utf-8"))
            if not isinstance(user_settings, dict):
                raise ValueError("settings.json must be a JSON object")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            warn("settings_corrupt", f"settings.json unreadable: {exc}; using defaults")
            if strict:
                raise SettingsError(str(exc)) from exc
            user_settings = {}

    preset_name = user_settings.get("preset", "solo-dev")
    preset = _load_preset(preset_name)
    if preset is None:
        warn("preset_missing", f"preset '{preset_name}' not found; using empty preset")
        preset = {}

    overrides = user_settings.get("overrides") or {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            _apply_dotted(preset, str(k), v)
    return preset


def _load_preset(name: str) -> dict | None:
    from warnings_log import warn

    candidates = [
        state_dir() / "presets" / f"{name}.json",
        PLUGIN_ROOT / "presets" / f"{name}.json",
    ]
    for c in candidates:
        if not c.exists():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("preset must be a JSON object")
            return data
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            warn("preset_corrupt", f"preset '{name}' at {c} is corrupt: {exc}")
            return None
    return None


def _apply_dotted(target: dict, key: str, value) -> None:
    """Apply dotted-path override: 'a.b.c' = v walks/creates nested dicts."""
    parts = key.split(".")
    node = target
    for part in parts[:-1]:
        existing = node.get(part)
        if not isinstance(existing, dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
