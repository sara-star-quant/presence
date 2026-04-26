# presence: security and privacy

## Threat model

`presence` is a Claude Code plugin that runs hooks in your shell, reads transcript files Claude Code writes locally, and persists state under `~/.claude/presence/`. Threats it considers:

| # | Threat | Mitigation |
|---|---|---|
| T1 | A bug in a hook crashes Claude Code | All hook entry points wrapped in `safe_main`: any exception is logged and the hook exits 0. Claude Code never sees a failure. |
| T2 | A bug in a hook leaks private data to stdout (which becomes context Claude sees) | Hooks emit only structured `additionalContext` text. No raw env, no raw file contents, no auth headers. |
| T3 | Concurrent Claude sessions race on state files | Atomic writes (write-temp + rename); `fcntl.flock` on JSONL appends. Drain operations hold an exclusive lock. |
| T4 | Logged shell commands contain secrets (e.g. `git commit -m "TOKEN=..."`) | Every command stored in events/telemetry passes through `redact.py` before being written. Standard preset catches well-known token shapes; Zero-Trust preset is aggressive. |
| T5 | A malicious git repo's commit messages are stored verbatim | Same: messages pass through redaction before being written to telemetry. |
| T6 | State directory readable by other users on the machine | `~/.claude/presence/` is created with `0o700`; files written `0o600`. Verified at every SessionStart. |
| T7 | A tampered plugin executes hooks | `MANIFEST.lock` ships with each release. `/presence-doctor` verifies it on demand in v0.1. SessionStart fail-closed on mismatch is planned for v0.2. |
| T8 | Network exfiltration | `presence` makes no outbound network calls in v0.1. Optional `gh pr` check (in `team-oss`) is opt-in and goes directly to GitHub's API; disabled in Zero-Trust. |
| T9 | Untrusted Python code from the workspace gets imported | We never `eval`, `exec`, or import from outside our own `lib/`. `sys.path` (via `PYTHONPATH` in the bash wrappers) is only ever extended with `lib/`. |
| T10 | Symlink attack on read paths (transcript, plugin files) | Path resolution uses `Path.resolve()`. Zero-Trust mode refuses transcript paths outside `~/.claude/projects/`. |
| T11 | Subprocess injection | All `git` calls use list args, never `shell=True`. No user-controlled strings reach a shell. |
| T12 | State file size attack (transcript or event queue, leading to memory DoS) | Transcripts are tail-read with a max-bytes cap (262 KiB by default; same under Zero-Trust). The event queue is drained on every consumer call (truncates), with a hard 2 MB emergency cap. |

## What `presence` is **not** trying to defend against

- A compromised Claude Code binary itself. That is outside the trust boundary; if Claude Code is hostile, hooks are not your problem.
- A compromised local user account. Once an attacker has shell as you, they have your `~/.claude/` regardless of presence.
- Side-channel timing attacks on hook execution.

## Privacy posture

- **All state is local.** Nothing is uploaded by `presence`. Ever.
- **No analytics, no error reporting, no remote telemetry.**
- **The optional `gh pr` outcome check** (preset `team-oss` and above; off in Zero-Trust) calls GitHub's REST API directly via the user's own `gh` CLI auth. No third-party intermediary.
- **State retention.** Commits/claims/outcomes accumulate in `~/.claude/presence/telemetry/`. Run `/presence-reset --telemetry` to wipe; `--all` to wipe everything.

## Permissions

- `~/.claude/presence/` and subdirectories: `0o700` (owner only)
- All written state files: `0o600` (owner read/write only)
- Hook scripts in plugin: `0o755` (anyone can read+execute, only owner writes)

Verified at every SessionStart; corrected automatically if loosened.

## Reporting a vulnerability

Use the GitHub security advisory flow at `https://github.com/sara-star-quant/presence/security/advisories/new` (available after the repo is published). Until then, file a private issue or contact the maintainer via the GitHub profile contact link rather than disclosing publicly.

## See also

- [`docs/zerotrust.md`](zerotrust.md): the opt-in Zero-Trust profile and what additional controls it adds (with v0.1 vs v0.2 status markers).
- [`docs/architecture.md`](architecture.md): how the pieces fit together.
