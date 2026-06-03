"""presence: continuous-collaboration layer for Claude Code."""
__version__ = "0.6.2"

# Lower bound on the compiled presence_ext crate version that this Python
# plugin expects. Bumped manually whenever a Python-side change requires a
# new ext API surface. lib/_common.py::check_ext_compat() compares this
# to presence_ext.__version__ at SessionStart and surfaces a warning via
# the standard warnings_log channel on mismatch. Fail-open: the subprocess
# fallback in lib/telemetry.py + lib/crypto.py runs unaffected even if
# the wheel is stale or absent.
_MIN_EXT_VERSION = "0.2.0"
