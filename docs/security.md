# presence: security and privacy

## Threat model

`presence` is a Claude Code plugin that runs hooks in your shell, reads transcript files Claude Code writes locally, and persists state under `~/.claude/presence/`. Threats it considers:

| # | Threat | Mitigation |
|---|---|---|
| T1 | A bug in a hook crashes Claude Code | All hook entry points wrapped in `safe_main`: any exception is logged and the hook exits 0. Claude Code never sees a failure. |
| T2 | A bug in a hook leaks private data to stdout (which becomes context Claude sees) | Hooks emit only structured `additionalContext` text. No raw env, no raw file contents, no auth headers. |
| T3 | Concurrent Claude sessions race on state files | Atomic writes (write-temp + rename); `fcntl.flock` on JSONL appends. Drain operations hold an exclusive lock. |
| T4 | Logged shell commands contain secrets (e.g. `git commit -m "TOKEN=..."`) | Every command stored in events or the outcome log, and every project-model entry, passes through `redact.py` before being written. Standard preset catches well-known token shapes plus the common command-line shapes: secret-named variables and flags, credentials inside a URL, `mysql -p` and `sshpass -p`. It matches known shapes only and cannot promise to catch every secret; Zero-Trust preset is aggressive. |
| T5 | A malicious git repo's commit messages are stored verbatim | Same: messages pass through redaction before being written to telemetry. |
| T6 | State directory readable by other users on the machine | `~/.claude/presence/` is created with `0o700`; files written `0o600`. Drift is re-tightened automatically at every SessionStart and on demand via `/presence-doctor --fix`. |
| T7 | A tampered plugin executes hooks | `MANIFEST.lock` ships with each release. `/presence-doctor` verifies it on demand in v0.1. SessionStart fail-closed on mismatch shipped in v0.2 (active under any preset with `integrity.fail_closed=true`; default in `zerotrust`). |
| T8 | Network exfiltration | `presence` makes no outbound network calls by default. The release-freshness check and the webhook notifier both read `network.egress_allowed` before doing anything; Zero-Trust sets that to `false`, which hard-disables both regardless of their own per-feature toggle. The `gh pr` check (`team-oss`+) is disabled in Zero-Trust via its own `telemetry.gh_pr_check` flag, off separately from `network.egress_allowed`. The webhook notifier additionally runs its payload through `redact.py` before the request leaves the machine, and never fires the network call from inside the hook itself (a detached subprocess does it, so a slow or dead endpoint can't stall a hook). |
| T9 | Untrusted Python code from the workspace gets imported | We never `eval`, `exec`, or import from outside our own `lib/`. `sys.path` (via `PYTHONPATH` in the bash wrappers) is only ever extended with `lib/`. |
| T10 | Symlink attack on read paths (transcript, plugin files) | Path resolution uses `Path.resolve()`. Zero-Trust mode refuses transcript paths outside `~/.claude/projects/`. |
| T11 | Subprocess injection | All `git` calls use list args, never `shell=True`. No user-controlled strings reach a shell. |
| T12 | State file size attack (transcript or event queue, leading to memory DoS) | Transcripts are tail-read with a max-bytes cap (262 KiB by default; same under Zero-Trust). The event queue is drained on every consumer call (truncates), with a hard 2 MB emergency cap. |
| T13 | An on-path attacker alters what presence downloads or sends | `install.sh` pins every download to https and TLS 1.2 across redirects, requires the binary to match `SHA256SUMS` (a missing file fails closed, never a warning), and checks the build attestation with `gh attestation verify`, pinned to the release workflow, when `gh` is present: by default a failure only warns, and `--require-attestation` (or `PRESENCE_REQUIRE_ATTESTATION=1`) makes it mandatory, also through a mirror, and refuses a binary that does not verify. The checksum file comes from the same release as the binary, so it protects against corruption and tampering in transit, not against a malicious release; the attestation is what ties the binary to our workflow. The webhook takes https, or http to loopback only. The update check reads at most 1 MB and keeps a response only if its tag looks like a version. |
| T14 | A hostile git note or release tag reaches the terminal or an agent's context | `verify-receipt` caps the note (16 KiB, five evidence entries), requires well-formed fields, prints one line of printable ASCII, and labels the receipt unsigned. Revisions that look like options are refused. With `--allowed-signers`, only a receipt signed by a pinned SSH key passes, so write access to the repo does not let anyone forge one. |
| T15 | The webhook URL, usually a bearer secret, is readable by other local users | The detached sender takes the URL on stdin with the payload, never in argv. |
| T16 | The tree check copies file content or names into state or the repository | `snapshot` hashes through a throwaway index and object directory, so the repository gains no objects and its index is untouched; the state file holds hashed paths, git object ids and scopes only, never content or names |
| T17 | A repository's own git config makes the tree check run a program, or a hostile base tree is read as an option | The tree check ignores the repository's fsmonitor setting, passes revisions so an option-like name is never read as one, and gives each snapshot one time budget. |
| T18 | The agent quiets the gate by making its own edits look like pulled or merged work | Only a pull, merge, checkout or clean rebase recorded in the HEAD log on an otherwise clean tree counts as incoming. Anything unknown, dirty, expired or ambiguous stays as loud as before, and a quieted turn leaves an `incoming` mark in the confidence log. A forged HEAD log is listed below as not defended. |
| T19 | A hostile repository stalls or redirects a hook through the files it contains | Marker and context files are read only when they are regular files, so a named pipe called `Makefile` cannot block a hook. Every read is bounded, and malformed `package.json` content gets an answer, not an exception. The AGENTS.md adapter writes only a regular file inside the repository and reports a refusal once. |
| T20 | presence copies project context into the repository, where it can be committed | The AGENTS.md adapter refuses under any preset with `settings.immutable` (Zero-Trust) and says so where `/presence-doctor` looks. Other presets write only the block the adapter owns. |
| T21 | State sits on disk in plain text under Zero-Trust | Records and project-model entries are AES-GCM encrypted with the keychain-held key. If encryption is unavailable nothing is written, never plain text. Sealed snapshots carry the model between machines and re-encrypt it under the destination key, and key rotation drops the encrypted entries. The tree state and the audit chain are plain by design, and the model still reaches Claude's context in plain text. |

## Which tests pin each claim

A claim is only as good as the test that fails when it breaks. This table lists the pinning test per threat; `tests/test_contract.py` fails if a listed test no longer exists. Rows marked "design property" have no dedicated test: they hold because the code path does not exist (no `shell=True`, no `eval`), which a test cannot meaningfully pin.

| Claim | Pinned by |
|---|---|
| T1 hooks never crash the host | `tests/test_hardening.py::test_run_hook_fallback_is_guarded` |
| T2, T5, T9, T11 | design property |
| T3 concurrent writers do not corrupt state | `tests/test_audit.py::test_concurrent_appends_chain_safely`, `tests/test_common.py::test_atomic_write_overwrites` |
| T4 secrets redacted before storage | `tests/test_redact.py::test_standard_known_token_shapes`, `tests/test_redact.py::test_secrets_in_command_shapes_are_redacted`, `tests/test_model_redaction.py::test_a_secret_in_an_observation_never_reaches_the_file` |
| T6 perms re-tightened at SessionStart | `tests/test_hardening.py::test_reverify_state_perms_retightens` |
| T7 plugin tamper and extra files fail closed | `tests/test_hardening.py::test_extra_file_fails_integrity`, `tests/test_hardening.py::test_integrity_gate_blocks_on_extra` |
| T8 egress blocked under zerotrust, payload redacted | `tests/test_notify.py::test_zerotrust_egress_block_wins_even_if_notify_is_enabled`, `tests/test_notify.py::test_final_excerpt_is_redacted_before_dispatch` |
| T12 transcript size cap | `tests/test_hook_stop.py::test_transcript_max_bytes_override_and_invalid` |
| T13 downloads pinned to https, missing checksums fail closed | `tests/test_release_supply_chain.py::test_install_pins_https_for_every_github_download`, `tests/test_release_supply_chain.py::test_download_without_sums_refuses_to_install` |
| T13 an unverifiable build is refused when asked | `tests/test_release_supply_chain.py::test_the_switch_refuses_a_binary_whose_attestation_does_not_verify`, `tests/test_release_supply_chain.py::test_the_switch_refuses_when_gh_is_not_there_to_verify` |
| T13 plain-http webhook refused except to loopback | `tests/test_notify.py::test_plain_http_to_a_remote_host_never_dispatches`, `tests/test_notify.py::test_loopback_http_and_remote_https_still_dispatch` |
| T13 update response bounded and tag validated | `tests/test_update_check.py::test_fetch_reads_a_bounded_body`, `tests/test_update_check.py::test_fetch_rejects_a_tag_that_is_not_a_version` |
| T14 receipt notes are untrusted input | `tests/test_receipt.py::test_an_oversized_note_is_invalid_not_parsed`, `tests/test_receipt.py::test_malformed_evidence_is_invalid`, `tests/test_receipt.py::test_cli_output_strips_terminal_escapes_and_labels_the_receipt_unsigned`, `tests/test_receipt.py::test_an_option_like_rev_is_refused` |
| T14 forged, relabelled or relocated receipts fail under pinned signers | `tests/test_receipt.py::test_a_forged_receipt_signed_with_the_attackers_own_key_is_untrusted`, `tests/test_receipt.py::test_an_unsigned_forgery_is_untrusted_once_signers_are_pinned`, `tests/test_receipt.py::test_a_signature_cannot_be_moved_onto_a_different_claim` |
| T14 CI evidence is accepted only from the repository's own main-branch workflow | `tests/test_ci_evidence.py::test_a_signed_ci_run_on_this_tree_verifies`, `tests/test_ci_evidence.py::test_a_predicate_for_another_tree_is_a_mismatch`, `tests/test_ci_evidence.py::test_unreadable_gh_output_is_never_a_pass` |
| T15 webhook URL stays out of argv | `tests/test_notify.py::test_webhook_url_never_appears_in_the_child_argv` |
| T16 snapshot leaves the repository untouched, state holds no content | `tests/test_worktree.py::test_computing_a_snapshot_adds_nothing_to_the_repository`, `tests/test_worktree.py::test_the_diff_lists_paths_against_the_base_tree_with_blob_ids_only` |
| T17 a repository's config cannot choose what the snapshot runs, and one snapshot has one time budget | `tests/test_worktree.py::test_a_repository_configured_fsmonitor_program_is_not_run`, `tests/test_worktree.py::test_the_git_calls_of_one_snapshot_share_one_budget`, `tests/test_worktree.py::test_a_base_tree_that_looks_like_an_option_is_never_passed_to_git` |
| T18 only provably incoming work quiets the gate; anything unknown, dirty or ambiguous stays as loud as before | `tests/test_incoming_changes.py::test_an_uncommitted_edit_next_to_a_pull_is_still_flagged`, `tests/test_incoming_changes.py::test_a_conflict_resolved_by_hand_is_still_flagged`, `tests/test_incoming_changes.py::test_a_round_trip_between_branches_is_ambiguous_and_stays_loud`, `tests/test_incoming_changes.py::test_an_expired_reflog_stays_loud`, `tests/test_incoming_changes.py::test_the_commit_gate_still_sees_pulled_code_in_the_session`, `tests/test_incoming_changes.py::test_a_huge_hostile_message_is_matched_in_linear_time` |
| T19 hostile repository files cannot stall or redirect a hook | `tests/test_testinfra.py::test_a_marker_that_is_a_named_pipe_does_not_hang_the_check`, `tests/test_testinfra.py::test_a_malformed_package_json_is_judged_without_raising`, `tests/test_testinfra.py::test_a_directory_that_cannot_be_read_is_skipped_not_fatal`, `tests/test_agents_md_zerotrust.py::test_an_agents_md_that_points_outside_the_repository_is_not_written_through`, `tests/test_agents_md_zerotrust.py::test_an_agents_md_that_is_a_named_pipe_does_not_hang_the_hook` |
| T20 Zero-Trust never writes project context into the repo through the AGENTS.md adapter | `tests/test_agents_md_zerotrust.py::test_zerotrust_writes_nothing_into_the_repo` |
| T21 Zero-Trust never falls back to plain text when encryption is unavailable | `tests/test_zerotrust_fail_closed.py::test_a_record_that_cannot_be_encrypted_is_not_written` |
| T21 the project model is encrypted per entry, refused when it cannot be, and travels sealed | `tests/test_model_encryption.py::test_an_entry_written_under_zerotrust_is_not_on_disk_in_plain_text_and_reads_back`, `tests/test_model_encryption.py::test_a_model_entry_that_cannot_be_encrypted_is_not_written`, `tests/test_snapshot_sealed.py::test_an_encrypted_project_model_travels_sealed_and_is_re_encrypted_for_the_destination` |
| audit line edit detected | `tests/test_audit.py::test_tampered_line_detected` |
| audit broken link detected | `tests/test_audit.py::test_broken_link_detected` |
| audit tail truncation detected, not laundered by later appends | `tests/test_audit.py::test_tail_truncation_detected`, `tests/test_audit.py::test_append_does_not_launder_truncation` |
| broken audit chain keeps hooks inert under zerotrust | `tests/test_audit.py::test_session_start_gate_blocks_on_broken_chain` |
| full audit rewrite by the account owner | not defended (see below) |

## What `presence` is **not** trying to defend against

- A compromised Claude Code binary itself. That is outside the trust boundary; if Claude Code is hostile, hooks are not your problem.
- A compromised local user account. Once an attacker has shell as you, they have your `~/.claude/` regardless of presence. In particular the Zero-Trust audit log is tamper-evident against in-place edits of individual lines (the SHA-256 hash chain detects a modified line or a broken link), but its genesis hash is a public constant and the chain carries no secret key, so rewriting the whole file with a fresh valid chain is not detectable. Tail truncation is caught by a sidecar head (`audit.head`), but a writer who edits both files defeats it. Use it to catch accidental or process-level corruption, not to bind the account owner.
- An agent that forges the HEAD log. The gate treats a pull, merge, checkout or clean rebase in that log as work that arrived and not as the agent's, and git writes whatever message `git update-ref -m` is given. The confidence gate is a nudge for honest mistakes, like the edit log it replaced, not a barrier; a quieted turn leaves a record (`incoming` in the confidence log) so it can be checked.
- A local attacker observing process arguments. On macOS, creating or rotating the keychain data key shells out to `security add-generic-password -w <hex>`, so the key is briefly visible in `ps` for the lifetime of that one subprocess (`security` has no stdin path for the value). The Linux `secret-tool` path passes the key over stdin and does not.
- The opt-in `--bootstrap` path, which pipes the uv installer from astral.sh into `sh` over TLS. Nothing pins or checksums that script; skip the flag and install Python 3.12 yourself if that matters.
- A forged receipt when the verifier does not pin signers: anyone who can write to the repo can write a consistent one, and `verify-receipt` says "unsigned" for that reason. Pinned signers close that; nothing defends against whoever holds the signing key and the verifier's policy.
- Side-channel timing attacks on hook execution.

The PreToolUse commit/push confidence gate is an advisory nudge, not an access control: it is trivially bypassable (rename the command, split it, run git directly) and is meant to prompt verification, not to enforce it.

## Privacy posture

- **All state is local.** Nothing is uploaded by `presence`. Ever.
- **No analytics, no error reporting, no remote telemetry.**
- **The optional `gh pr` outcome check** (preset `team-oss` and above; off in Zero-Trust) calls GitHub's REST API directly via the user's own `gh` CLI auth. No third-party intermediary.
- **The optional release-freshness check** (`update_check.enabled`; off in Zero-Trust) calls GitHub's public releases API on a 24h cache TTL.
- **The optional webhook notifier** (`notify.enabled`; off by default, hard-disabled in Zero-Trust) POSTs confidence-gate verdicts to a URL the user configures themselves in their own `settings.json` -- presence ships no default endpoint. This is the one feature in presence that sends non-metadata content (a short excerpt of the assistant's final message) off the machine, and only when a user explicitly opts in and supplies their own destination. See `docs/recipes.md` for setup and `lib/notify.py`'s module docstring for the exact payload shape and redaction behavior.
- **State retention.** Commits/claims/outcomes accumulate in `~/.claude/presence/telemetry/`. Run `/presence-reset --telemetry` to wipe; `--all` to wipe everything.

## Permissions

- `~/.claude/presence/` and subdirectories: `0o700` (owner only)
- All written state files: `0o600` (owner read/write only)
- Hook scripts in plugin: `0o755` (anyone can read+execute, only owner writes)

Re-tightened automatically at every SessionStart, and on demand via `/presence-doctor --fix`.

## Assurance case

This section is the project's assurance case: the argument that presence's security requirements are met. It ties the threat model above to the trust boundaries, the secure-design principles applied, and the common implementation weaknesses countered.

**Claim.** presence does not weaken the security of a developer's machine or Claude Code session: it never crashes the host, never leaks private data into model context or to the network, keeps its state owner-only, and (under Zero-Trust) encrypts state at rest with an audit log that is tamper-evident against in-place edits (see the scope note above for what the chain does and does not bind).

**Trust boundaries.**

- Claude Code <-> hooks (stdin/stdout): hook input (cwd, tool input/response, transcript path) is untrusted and validated; output is only structured `additionalContext` / decision JSON (T2); a hook failure is contained and exits 0 (T1).
- Workspace/repo <-> presence: repo content (commit messages, command strings, paths) is untrusted - redacted before storage (T4, T5), path-resolved and scope-checked (T10), never evaluated or imported (T9).
- presence state <-> other local users: state is owner-only `0o700`/`0o600`, set on write and re-tightened every SessionStart (T6); integrity is verifiable and fail-closed under Zero-Trust (T7).
- presence <-> network: no outbound calls by default; every opt-in network feature (`gh pr` check, release-freshness check, webhook notifier, `--bootstrap`) is explicit, documented, HTTPS, and disabled under Zero-Trust -- release-freshness check and webhook notifier via `network.egress_allowed`, `gh pr` check via its own `telemetry.gh_pr_check` flag (T8).
- Out of scope (outside the boundary): a hostile Claude Code binary, a compromised local account, side-channel timing.

**Secure-design principles applied.**

- Fail-safe defaults: hooks never break the session (`safe_main`, T1); under Zero-Trust, integrity mismatch fails closed (T7).
- Least privilege / least exposure: owner-only permissions (T6), zero network by default (T8), no shell execution (T11), no untrusted import/eval (T9).
- Complete mediation: permissions and (under Zero-Trust) integrity are re-checked every SessionStart, not once; every stored command passes through redaction (T4).
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
