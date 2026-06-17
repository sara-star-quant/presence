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
| T6 | State directory readable by other users on the machine | `~/.claude/presence/` is created with `0o700`; files written `0o600`. Drift is re-tightened on demand via `/presence-doctor --fix`; automatic SessionStart reverification is tracked in the integrity-hardening issue. |
| T7 | A tampered plugin executes hooks | `MANIFEST.lock` ships with each release. `/presence-doctor` verifies it on demand in v0.1. SessionStart fail-closed on mismatch shipped in v0.2 (active under any preset with `integrity.fail_closed=true`; default in `zerotrust`). |
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

Drift is corrected on demand via `/presence-doctor --fix`; automatic SessionStart reverification is tracked in the integrity-hardening issue.

## Assurance case

This section is the project's assurance case: the argument that presence's security requirements are met. It ties the threat model above to the trust boundaries, the secure-design principles applied, and the common implementation weaknesses countered.

**Claim.** presence does not weaken the security of a developer's machine or Claude Code session: it never crashes the host, never leaks private data into model context or to the network, keeps its state owner-only, and (under Zero-Trust) encrypts state at rest with a tamper-evident audit log.

**Trust boundaries.**

- Claude Code <-> hooks (stdin/stdout): hook input (cwd, tool input/response, transcript path) is untrusted and validated; output is only structured `additionalContext` / decision JSON (T2); a hook failure is contained and exits 0 (T1).
- Workspace/repo <-> presence: repo content (commit messages, command strings, paths) is untrusted - redacted before storage (T4, T5), path-resolved and scope-checked (T10), never evaluated or imported (T9).
- presence state <-> other local users: state is owner-only `0o700`/`0o600`, set on write and re-tightened on demand via `/presence-doctor --fix` (T6); integrity is verifiable and fail-closed under Zero-Trust (T7).
- presence <-> network: no outbound calls by default; the only calls (opt-in `gh pr` check, opt-in `--bootstrap`) are explicit, documented, HTTPS, and disabled under Zero-Trust (T8).
- Out of scope (outside the boundary): a hostile Claude Code binary, a compromised local account, side-channel timing.

**Secure-design principles applied.**

- Fail-safe defaults: hooks never break the session (`safe_main`, T1); under Zero-Trust, integrity mismatch fails closed (T7).
- Least privilege / least exposure: owner-only permissions (T6), zero network by default (T8), no shell execution (T11), no untrusted import/eval (T9).
- Complete mediation: the integrity gate runs every SessionStart under Zero-Trust, not once; every stored command passes through redaction (T4); permissions are re-tightened on demand via `/presence-doctor --fix`.
- Economy of mechanism: stdlib-only runtime, local files, no service in the default path.
- Defense in depth: redaction + permissions + integrity + (Zero-Trust) at-rest encryption and a SHA-256 audit chain.

**Common implementation weaknesses countered.**

- OS command injection (CWE-78): subprocess calls use list args, never `shell=True` (T11).
- Path traversal / link following (CWE-22/59): `Path.resolve()` plus a Zero-Trust allowlist for transcript paths (T10).
- Sensitive data exposure (CWE-200/532): no private data to stdout (T2); redaction before any log/telemetry write (T4, T5).
- Unsafe deserialization / code execution (CWE-502/94): JSON only via the standard library; no `eval`/`exec`; `sys.path` extended only with `lib/` (T9).
- Uncontrolled resource consumption (CWE-400): tail-read caps and event-queue truncation with a hard emergency cap (T12).
- Incorrect permissions (CWE-276): owner-only perms enforced and re-verified (T6).

Static analysis (ruff including its security `S` rules, plus bandit) runs on every push and gates merges, providing ongoing evidence that these classes stay countered.

## Reporting a vulnerability

Use the GitHub security advisory flow at `https://github.com/sara-star-quant/presence/security/advisories/new`. See [`SECURITY.md`](../SECURITY.md) for the full reporting and response process.

## See also

- [`docs/zerotrust.md`](zerotrust.md): the opt-in Zero-Trust profile and what additional controls it adds (with v0.1 vs v0.2 status markers).
- [`docs/architecture.md`](architecture.md): how the pieces fit together.
