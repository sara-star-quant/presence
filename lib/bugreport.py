"""Bundle install --verify --json + doctor --json + recent warnings + state sizes
into one paste-friendly blob for filing GitHub issues.

Two output modes:
  - default JSON (machine-parseable; CI scripts can ingest)
  - --md (markdown-fenced; human pastes into the bug template)

Used via /presence-bugreport. The slash command is what end users actually see.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys

from _common import PLUGIN_ROOT, state_dir
from doctor import report
from warnings_log import read_warnings


def _read_version() -> str:
    """Read presence version from .claude-plugin/plugin.json (the source of truth).

    lib/__init__.py also has __version__ but that's been out of sync historically.
    plugin.json is what the marketplace + Claude Code read.
    """
    p = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, json.JSONDecodeError):
        return "unknown"


def _run_verify_json(cwd: str) -> dict | None:
    """Invoke install.sh --verify --json against the working tree. Returns the
    parsed JSON, or None if verify isn't available or fails to emit JSON.

    We don't fail the whole bugreport on a verify error; the doctor block is
    independent and still useful.
    """
    install_sh = PLUGIN_ROOT / "install.sh"
    if not install_sh.exists():
        return None
    try:
        env = os.environ.copy()
        # If we're invoked from inside Claude Code, CLAUDE_PLUGIN_ROOT is set;
        # otherwise install.sh resolves SCRIPT_DIR from its own location.
        env.setdefault("CLAUDE_PLUGIN_ROOT", str(PLUGIN_ROOT))
        env.setdefault("PRESENCE_STATE", str(state_dir()))
        result = subprocess.run(  # noqa: S603
            ["bash", str(install_sh), "--verify", "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
            cwd=cwd,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def assemble(cwd: str | None = None) -> dict:
    """Bundle the diagnostic surface for a bug report. Read-only; no side effects."""
    cwd = cwd or "."
    rep = report(cwd)
    return {
        "presence_version": _read_version(),
        "platform": f"{platform.system()} {platform.machine()} {platform.release()}",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "active_preset": rep.get("active_preset"),
        "verify": _run_verify_json(cwd),
        "doctor": rep,
        "recent_warnings": read_warnings(limit=20),
        "state_sizes": {
            "model_md_bytes": rep.get("model_size_bytes", 0),
            "pending_events_bytes": rep.get("pending_events_bytes", 0),
            "claims_bytes": rep.get("claims_bytes", 0),
            "outcomes_bytes": rep.get("outcomes_bytes", 0),
            "confidence_bytes": rep.get("confidence_bytes", 0),
            "errors_log_bytes": rep.get("errors_log_bytes", 0),
            "warnings_log_bytes": rep.get("warnings_log_bytes", 0),
        },
    }


def to_markdown(bundle: dict) -> str:
    """Render the bundle as a paste-friendly markdown block. The structure
    mirrors the bug.yml issue template fields so the user can copy sections
    into the right slots."""
    lines = [
        "## presence bug report",
        "",
        f"- **Version**: `{bundle['presence_version']}`",
        f"- **Platform**: {bundle['platform']}",
        f"- **Python**: {bundle['python']}",
        f"- **Active preset**: `{bundle['active_preset']}`",
        "",
    ]

    verify = bundle.get("verify")
    if verify is not None:
        lines.append("### `install.sh --verify --json`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(verify, indent=2))
        lines.append("```")
        lines.append("")
    else:
        lines.append("### `install.sh --verify --json`")
        lines.append("")
        lines.append("(could not run; install.sh missing or verify failed)")
        lines.append("")

    lines.append("### `lib/doctor.py --json`")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(bundle["doctor"], indent=2, default=str))
    lines.append("```")
    lines.append("")

    warnings_list = bundle.get("recent_warnings", [])
    if warnings_list:
        lines.append("### Recent warnings")
        lines.append("")
        for w in warnings_list:
            lines.append(f"- `[{w.get('category', '?')}]` {w.get('message', '')}")
            if w.get("fix"):
                lines.append(f"  - fix: {w['fix']}")
        lines.append("")
    else:
        lines.append("### Recent warnings")
        lines.append("")
        lines.append("(none)")
        lines.append("")

    lines.append("### State sizes (bytes)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(bundle["state_sizes"], indent=2))
    lines.append("```")

    return "\n".join(lines)


def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="presence: bundle diagnostic surface for a GitHub bug report",
    )
    ap.add_argument("--cwd", default=".", help="project directory to inspect")
    ap.add_argument("--md", action="store_true",
                    help="emit markdown for pasting into a GitHub issue")
    args = ap.parse_args()
    bundle = assemble(args.cwd)
    if args.md:
        print(to_markdown(bundle))
    else:
        print(json.dumps(bundle, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
