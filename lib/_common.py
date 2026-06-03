"""Shared utilities for presence hooks. No external deps; stdlib only.

Every hook entry point should call ``safe_main(fn)`` so any internal failure logs and
exits 0 so Claude Code never sees a presence-induced error. ``safe_main`` increments
an error counter that the next ``SessionStart`` surfaces to the user, so failures are
recoverable from the in-product UI without the user grepping log files.

Module never raises at import time on any platform: ``fcntl`` is lazily imported.
``asyncio`` is also lazy: only ``async_git_run`` / ``async_git_run_safe`` import it,
so the 5 sync hooks (UserPromptSubmit, PostToolUse(Bash|Edit), PreToolUse(Bash), Stop)
do not pay the ~30 ms asyncio import cost on cold start.
"""
from __future__ import annotations

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
# JSON helpers (v0.4.0): prefer orjson when available, fall back to stdlib
# json. Centralized so callers don't need to repeat the try/except pattern.
# orjson is a fully optional dep; presence remains stdlib-only by default.
# ---------------------------------------------------------------------------

try:
    import orjson as _orjson
    _HAS_ORJSON = True
except ImportError:
    _orjson = None
    _HAS_ORJSON = False


def _dumps(obj: dict) -> str:
    """Serialize ``obj`` to a single-line JSON string."""
    if _HAS_ORJSON:
        return _orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _loads(data: str | bytes) -> dict:
    """Parse a JSON document from str or bytes. Raises on malformed input."""
    if _HAS_ORJSON:
        return _orjson.loads(data)
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data)


# ---------------------------------------------------------------------------
# State directory bootstrap with strict perms
# ---------------------------------------------------------------------------

# Per-process: paths that have already been mkdir+stat+chmod'd. Subsequent
# calls return the Path immediately. Hooks are short-lived so a process-local
# cache cannot drift; if a test or external process changes perms mid-fire
# we accept the staleness in exchange for the ~3 syscalls saved per call.
_ENSURED_DIRS: set[str] = set()


def _ensure_dir(p: Path, mode: int = 0o700) -> Path:
    key = str(p)
    if key in _ENSURED_DIRS:
        return p
    p.mkdir(parents=True, exist_ok=True)
    try:
        current = stat.S_IMODE(p.stat().st_mode)
        if current != mode:
            p.chmod(mode)
    except (OSError, NotImplementedError):
        # Windows, network FS, exotic permission models; best effort.
        pass
    _ENSURED_DIRS.add(key)
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
        warn("git_missing", "git binary not found on PATH; commit telemetry disabled",
             fix="install git from https://git-scm.com or your package manager")
        return None
    except GitTimeout as exc:
        warn("git_timeout", str(exc), cmd=list(args))
        return None
    except GitFailed:
        # Common case: not a git repo. Don't warn (too noisy).
        return None


async def async_git_run(cwd: str | os.PathLike[str], *args: str, timeout: int | None = None) -> str:
    """Async variant of git_run."""
    import asyncio  # lazy: only async hooks pay the asyncio import cost
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
        warn("git_missing", "git binary not found on PATH; commit telemetry disabled",
             fix="install git from https://git-scm.com or your package manager")
        return None
    except GitTimeout as exc:
        warn("git_timeout", str(exc), cmd=list(args))
        return None
    except GitFailed:
        return None


# ---------------------------------------------------------------------------
# Project identity
# ---------------------------------------------------------------------------

# Per-process cache. Each repo_id() call costs up to 2 git subprocesses
# (rev-parse --show-toplevel, then config --get remote.origin.url); the
# SessionStart asyncio.gather fan-out alone calls it 4+ times per fire across
# project_dir / events_dir / telemetry helpers. Caching saves 6+ subprocess
# spawns per fire on the heaviest hook. Key is the resolved cwd string.
_REPO_ID_CACHE: dict[str, str] = {}


def repo_id(cwd: str | os.PathLike[str] | None = None) -> str:
    """Stable id for the current project. Prefers git remote URL; falls back to cwd path."""
    base = Path(cwd or os.getcwd()).resolve()
    key = str(base)
    cached = _REPO_ID_CACHE.get(key)
    if cached is not None:
        return cached
    # Use git itself to find toplevel; avoids the .git-walk-into-parent-tree footgun
    top = git_run_safe(base, "rev-parse", "--show-toplevel")
    if top:
        repo_root_path = Path(top)
        remote = git_run_safe(repo_root_path, "config", "--get", "remote.origin.url")
        seed = remote if remote else str(repo_root_path)
        rid = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    else:
        rid = hashlib.sha256(str(base).encode("utf-8")).hexdigest()[:12]
    _REPO_ID_CACHE[key] = rid
    return rid


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
    """Append a JSON object as a single line. Encrypts the line if the active preset
    requests encryption AND ``crypto`` is available; otherwise writes plain.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    plain = _dumps(obj)
    line = _maybe_encrypt(plain) + "\n"
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


def _maybe_encrypt(plain_json_line: str) -> str:
    """Encrypt the line iff the active preset wants encryption AND key is available.
    Otherwise return the plain line unchanged. Best-effort; on any failure, returns plain.
    """
    enabled, key = _encryption_write_state()
    if not enabled or key is None:
        return plain_json_line
    try:
        from crypto import encrypt_line
        return encrypt_line(plain_json_line.encode("utf-8"), key)
    except Exception:  # noqa: BLE001  never let encryption failure break a write
        return plain_json_line


# Per-process caches. Hooks are short-lived so a process-local cache is safe.
# Two separate caches:
#   _WRITE_STATE_CACHE: only populated on the write path; never touches the
#       keychain in presets that don't request encryption.
#   _READ_KEY_CACHE:    populated lazily on the read path the first time
#       read_jsonl encounters an encrypted-looking line. Sentinel _UNSET means
#       "not yet looked"; None means "looked, no key available".
# Splitting them removes the v0.3.0-and-earlier behavior where read_jsonl
# called _try_existing_key_only() (a `security` subprocess on macOS) on every
# cold hook even under solo-dev / team-oss / enterprise-strict, dominating the
# cold-hook latency budget.
_WRITE_STATE_CACHE: tuple[bool, bytes | None] | None = None
_UNSET = object()
_READ_KEY_CACHE: object = _UNSET


def _encryption_write_state() -> tuple[bool, bytes | None]:
    """Return (wants_encrypt, key_or_None) for the write path.

    Returns (False, None) without ever invoking the keychain when the active
    preset has no storage section flagged ``encrypted``.
    """
    global _WRITE_STATE_CACHE
    if _WRITE_STATE_CACHE is not None:
        return _WRITE_STATE_CACHE

    cfg = settings()
    wants_encrypt = any(
        bool((cfg.get(section) or {}).get("encrypted"))
        for section in ("model", "telemetry", "events")
    )
    if not wants_encrypt:
        _WRITE_STATE_CACHE = (False, None)
        return _WRITE_STATE_CACHE

    try:
        from crypto import get_or_create_key, is_available
    except ImportError:
        from warnings_log import warn_once
        warn_once(
            "crypto_lib_missing",
            "preset wants encryption but `cryptography` is not installed; falling back to plain",
            fix="pip install --user cryptography",
        )
        _WRITE_STATE_CACHE = (False, None)
        return _WRITE_STATE_CACHE

    if not is_available():
        from warnings_log import warn_once
        warn_once(
            "crypto_keychain_missing",
            "preset wants encryption but no OS keychain backend (security/secret-tool) found",
            fix="on macOS the keychain is built in; on Linux install secret-tool (apt install libsecret-tools)",
        )
        _WRITE_STATE_CACHE = (False, None)
        return _WRITE_STATE_CACHE

    key = get_or_create_key()
    if key is None:
        from warnings_log import warn_once
        warn_once(
            "crypto_key_failed",
            "could not retrieve or create the data key from the keychain",
            fix="run /presence-reset --crypto to rotate the data key",
        )
        _WRITE_STATE_CACHE = (False, None)
        return _WRITE_STATE_CACHE

    _WRITE_STATE_CACHE = (True, key)
    return _WRITE_STATE_CACHE


def _read_key_lazy() -> bytes | None:
    """Return a key for the read path, fetched lazily on first encrypted line.

    Reuses the write-state key when encryption is on for writes; otherwise
    tries to fetch an existing key without creating one (so historical
    encrypted lines remain readable after a preset switch). Either way, the
    keychain is only touched once per process and only if the reader has
    actually seen an encrypted line.
    """
    global _READ_KEY_CACHE
    if _READ_KEY_CACHE is not _UNSET:
        return _READ_KEY_CACHE  # type: ignore[return-value]
    _enabled, key = _encryption_write_state()
    if key is not None:
        _READ_KEY_CACHE = key
        return key
    _READ_KEY_CACHE = _try_existing_key_only()
    return _READ_KEY_CACHE  # type: ignore[return-value]


def _try_existing_key_only() -> bytes | None:
    """Fetch an existing data key without creating a new one. For read-only paths
    when encryption is off (so we can still decrypt historical encrypted lines)."""
    try:
        from crypto import KEY_BYTES, _backend_ops  # noqa: PLC2701  internal crypto helper
    except ImportError:
        return None
    get, _set, _del = _backend_ops()
    if get is None:
        return None
    key = get()
    if key and len(key) == KEY_BYTES:
        return key
    return None


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
    """Return parsed lines. Missing file -> []. Corrupt lines -> warn + skip.

    Auto-decrypts lines that look encrypted, when the data key is available in the
    keychain. Mixed files (some encrypted, some plain) are handled per-line. Lines
    that look encrypted but cannot be decrypted are skipped and counted as corrupt.
    """
    from warnings_log import warn

    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    corrupt = 0
    # Defer crypto import + keychain probe to first encrypted line. In the
    # common case (solo-dev / team-oss / enterprise-strict reading a plain
    # file) neither happens at all, eliminating the keychain subprocess that
    # used to dominate cold-hook latency on macOS.
    decrypt_line = None
    is_encrypted_line = None
    crypto_imported = False
    key: object = _UNSET
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if not crypto_imported:
                    try:
                        from crypto import decrypt_line as _dl
                        from crypto import is_encrypted_line as _iel
                        decrypt_line, is_encrypted_line = _dl, _iel
                    except ImportError:
                        is_encrypted_line = lambda _s: False  # noqa: E731
                    crypto_imported = True
                if is_encrypted_line(s):
                    if key is _UNSET:
                        key = _read_key_lazy()
                    if key is None:
                        corrupt += 1
                        continue
                    plain = decrypt_line(s, key)  # type: ignore[misc]
                    if plain is None:
                        corrupt += 1
                        continue
                    try:
                        out.append(_loads(plain))
                    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                        corrupt += 1
                else:
                    try:
                        out.append(_loads(s))
                    except (json.JSONDecodeError, ValueError):
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
# Integrity block (set by SessionStart's fail-closed check; honored by every hook)
# ---------------------------------------------------------------------------

def integrity_block_path() -> Path:
    """Return the marker path WITHOUT calling state_dir().

    integrity_blocked() is the first line of every sync hook's main(), so a
    mkdir + stat + chmod here costs ~3 syscalls per cold fire just to ask "does
    the marker exist?". If STATE_DIR doesn't exist the marker can't either, so
    a missing-dir read returns False correctly with zero extra work. Writers
    (set_integrity_block) go through atomic_write, which creates the parent.
    """
    return STATE_DIR / ".integrity-blocked"


def integrity_blocked() -> bool:
    """True iff SessionStart's fail-closed integrity check left a block marker.

    Hooks should call this at the top of their main() and exit silently if True.
    Only SessionStart has the authority to set or clear the marker.
    """
    return integrity_block_path().exists()


def set_integrity_block(reason: str) -> None:
    try:
        atomic_write(integrity_block_path(), reason + "\n")
    except OSError:
        pass


def clear_integrity_block() -> None:
    p = integrity_block_path()
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


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
        obj = _loads(data)
    except (json.JSONDecodeError, ValueError) as exc:
        warn(
            "hook_input_malformed",
            f"malformed hook JSON: {exc}",
            head=data[:200],
        )
        return {}
    return obj if isinstance(obj, dict) else {}


def emit(payload: dict) -> None:
    # Retain raw emit for non-context JSON needs (e.g., telemetry flush or doctor JSON)
    if _HAS_ORJSON:
        sys.stdout.buffer.write(_orjson.dumps(payload))
    else:
        sys.stdout.write(_dumps(payload))
    sys.stdout.flush()


def emit_context(event_name: str, text: str) -> None:
    from adapters import get_adapter
    adapter = get_adapter()
    adapter.emit_context(event_name, text)


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


_SETTINGS_CACHE: dict | None = None


def settings(strict: bool = False) -> dict:
    """Return merged active preset + user overrides.

    Missing files -> defaults silently.
    Corrupt files -> warn loudly via warnings channel (and raise SettingsError if strict).

    Result is cached per process (hook lifetime). ``strict=True`` callers
    bypass the cache so validation paths always re-parse and re-raise.
    """
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None and not strict:
        return _SETTINGS_CACHE

    from warnings_log import warn

    s_path = state_dir() / "settings.json"
    user_settings: dict = {}
    if s_path.exists():
        try:
            user_settings = _loads(s_path.read_bytes())
            if not isinstance(user_settings, dict):
                raise ValueError("settings.json must be a JSON object")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            warn("settings_corrupt", f"settings.json unreadable: {exc}; using defaults",
                 fix="inspect ~/.claude/presence/settings.json (it is JSON; fix syntax) or run /presence-reset --all")
            if strict:
                raise SettingsError(str(exc)) from exc
            user_settings = {}

    preset_name = user_settings.get("preset", "solo-dev")
    preset = _load_preset(preset_name)
    if preset is None:
        warn("preset_missing", f"preset '{preset_name}' not found; using empty preset")
        preset = {}
    # Stamp the active preset name into the merged dict so callers (notably
    # hook_session_start.fail_closed_integrity_check) can report it without a
    # second settings round-trip.
    preset["__active_preset__"] = preset_name

    overrides = user_settings.get("overrides") or {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            _apply_dotted(preset, str(k), v)
    if not strict:
        _SETTINGS_CACHE = preset
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
            data = _loads(c.read_bytes())
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


def _parse_semver(s: str) -> tuple[int, int, int]:
    """Parse 'X.Y.Z' or 'X.Y.Z-suffix' into a comparable (major, minor, patch).

    Raises ValueError/IndexError on unparseable input. Callers that need fail-open
    semantics (currently only check_ext_compat) must catch explicitly -- returning
    a (0,0,0) sentinel here would silently compare as "older than" any real version
    and produce false-stale warnings, which violates the roadmap fail-open contract.
    """
    core = s.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    return (
        int(parts[0]),
        int(parts[1]) if len(parts) > 1 else 0,
        int(parts[2]) if len(parts) > 2 else 0,
    )


def check_ext_compat() -> tuple[bool, str | None, str | None]:
    """Cross-check the loaded presence_ext crate version against _MIN_EXT_VERSION.

    Returns ``(ok, ext_version, message)``:
      - ``(True, version, None)``  ext loaded and meets the bound.
      - ``(True, None, None)``     ext not installed; subprocess fallback path
                                   (lib/telemetry.py, lib/crypto.py) runs unchanged.
      - ``(False, version, msg)``  ext loaded but is older than _MIN_EXT_VERSION.

    Fail-open in every error path: import errors, missing __version__ attribute,
    and unparseable version strings all return ``(True, ...)``. A broken ext
    must never block hooks; the subprocess fallback already covers ext absence.
    """
    try:
        import presence_ext
        ext_version = getattr(presence_ext, "__version__", None)
    except ImportError:
        return (True, None, None)
    if not isinstance(ext_version, str) or not ext_version.strip():
        return (True, None, None)

    try:
        from __init__ import _MIN_EXT_VERSION
    except ImportError:
        return (True, ext_version, None)

    try:
        ext_parsed = _parse_semver(ext_version)
        min_parsed = _parse_semver(_MIN_EXT_VERSION)
    except (ValueError, IndexError):
        return (True, ext_version, None)

    if ext_parsed >= min_parsed:
        return (True, ext_version, None)
    return (
        False,
        ext_version,
        f"presence_ext {ext_version} is older than required {_MIN_EXT_VERSION}; "
        f"run install.sh --update --build-ext to refresh",
    )
