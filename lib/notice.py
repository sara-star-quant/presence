"""One plain line for the agent at its next prompt (stop_action "warn").

The Stop hook cannot add context to the next turn, so an unverified claim leaves a small file under the
project's state and the UserPromptSubmit hook reads it once. The text is fixed: nothing from the claim is
copied into it, so a message cannot steer the agent through its own notice. One slot, so two claims before
a prompt make one notice; it is kept for the session that made the claim and dropped after six hours.
"""
from __future__ import annotations

import json

from _common import atomic_write, now_ts, project_dir

NOTICE_TEXT = ("presence: your last message claimed success, but no passing test or build was recorded since your "
               "last edit. Run the tests, or say plainly that the work is untested.")
MAX_AGE = 6 * 3600


def _path(cwd):
    return project_dir(cwd) / "notice.json"


def queue_notice(cwd, session_id) -> None:
    atomic_write(_path(cwd), json.dumps({"ts": now_ts(), "sid": str(session_id or "")}))


def take_notice(cwd, session_id) -> str | None:
    """The notice text once, or None. A file for another session is left for that session."""
    path = _path(cwd)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts, sid = int(data["ts"]), str(data.get("sid") or "")
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    if now_ts() - ts > MAX_AGE:
        path.unlink(missing_ok=True)
        return None
    if sid and sid != str(session_id or ""):
        return None
    path.unlink(missing_ok=True)
    return NOTICE_TEXT
