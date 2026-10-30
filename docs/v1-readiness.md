# What stands between presence and 1.0

An honest gap analysis. 1.0 is a promise to people who depend on presence that the surface in [contract.md](contract.md) will not break within 1.x. This page lists what has to be true before making that promise, with the evidence for where we are today. It is not a schedule, and several items need decisions only the maintainer can make.

## Where we are

Facts as of v0.11.0 (2026-10-30):

| Signal | Value |
|---|---|
| Age | first commit 2026-04-26, about six months |
| Releases | 28 tags; v0.9.0, v0.9.1, v0.9.2 and v0.10.0 all shipped on the same day |
| Contributors | one author (85 commits), one contributor on GitHub, bus factor 1 |
| Outside signal | 8 stars, 0 forks, one open issue (#9, the Windows roadmap item), no user-filed bugs |
| Tests | 488 passing, 83% statement coverage (gate: 80%) |
| Platforms in CI | Linux (x86_64 and arm64) and macOS, Python 3.12 to 3.14; no Windows |

What the numbers say: the code is well tested against itself, and almost nothing has tested it against anyone else. A frozen contract is only worth freezing once real use has shown where it is wrong. Today every design decision has been validated by the one person who made it.

## What is already in place

- The contract is written down ([contract.md](contract.md)) and enforced: `tests/test_contract.py` fails if a preset key, hook event, or CLI subcommand is removed or narrowed.
- Zero-Trust integrity is complete in design: manifest gate and audit-chain gate fail closed, tail truncation is detected, sealed snapshots move encrypted state between machines.
- Each threat in [security.md](security.md) names the test that pins it.
- Coverage gate at 80%, signed tags, reproducible release workflow, perf bench gate.

These are necessary for 1.0. They are not sufficient, and having them is why the list below is about the outside world rather than the code.

## Gaps

Each gap lists the evidence, why it blocks, and an exit criterion. Thresholds marked "proposed" are mine to start the conversation, not decisions.

### 1. No real-world validation

- **Evidence**: no external bug reports, no forks, one contributor. The new fail-closed audit gate and sealed snapshot format are days old.
- **Why it blocks**: fail-closed behavior makes hooks go inert on a false positive. Only real machines (odd filesystems, restored backups, clock skew, crashed sessions mid-append) find those. We found one such bug ourselves (stale `audit.head` after restore) only because we were reading the code.
- **Exit criterion (proposed)**: at least 8 weeks since the last change to the contract surface, at least a handful of installs the maintainer does not control, and every issue they file triaged. Without a feedback channel there is nothing to wait for, so add one: an issue template for "it went inert" reports and a documented way to ask for help.

### 2. Host compatibility is unstated and untested against the real host

- **Evidence**: presence runs inside Claude Code, but no document names a minimum or tested Claude Code version, and no test runs the real host. Hook payloads are simulated by our own fixtures.
- **Why it blocks**: the hook contract belongs to Claude Code, not to us. A 1.0 that cannot say "works with Claude Code X through Y" promises something it cannot check.
- **Exit criterion**: a compatibility table in the README (tested versions), recorded real hook payloads from those versions as fixtures in the tests, and a documented policy for what happens when the host changes (warn, degrade, stay inert). A CI job against the real host is the stronger form but may need credentials; capture fixtures first.

### 3. Platform coverage (mostly addressed in 0.11.0)

- **Done**: the README carries a support matrix, and releases now ship a Linux arm64 binary alongside Linux x86_64 and macOS x86_64 and arm64. CI tests Linux arm64.
- **Still open**: native Windows is unsupported (WSL2 only, issue #9) and stays post-1.0 unless a real user asks. Nobody measures how much slower the Python fallback is than the Rust client.

### 4. Supply chain of the release artifacts (addressed in 0.11.0)

- **Done**: each release publishes `SHA256SUMS`, a CycloneDX SBOM, and a GitHub build provenance attestation for the binaries. Third-party Actions are pinned by commit SHA, and the runner image is pinned to `ubuntu-24.04` so the Linux binary's glibc floor does not move silently. `install.sh --download-ext` verifies the checksum and, when `gh` is present, the attestation. See [SECURITY.md](../SECURITY.md).
- **Still open**: nothing blocking. Revisit if the attestation or SBOM format changes.

### 5. Upgrade and migration paths are barely tested

- **Evidence**: only the snapshot format carries a version number. State files (JSONL records, `model.md`, `settings.json`, the audit chain) have no format version, and the only cross-version test is the `audit.head` case we added after the fact. No test loads state written by an older release.
- **Why it blocks**: 1.0 promises state keeps its meaning across 1.x. Without fixtures from older releases we cannot show it holds even across the 0.x series.
- **Exit criterion**: committed state-directory fixtures from at least the last five minor releases (generated by those releases), a test that the current code opens each and `/presence-doctor` reports healthy, and a decision on whether state files need an explicit format marker before 1.0 (adding one later is a breaking change; adding it now is cheap).

### 6. Security assurance rests on one reviewer

- **Evidence**: the threat model, the implementation, and the tests were all written by the same author. The new parsers (sealed snapshot, tar restore) have example-based tests only. No fuzzing, no external review.
- **Why it blocks**: the Zero-Trust preset sells a security posture. Claims of "tamper-evident" and "fail closed" deserve a second pair of eyes, and parsers of untrusted input deserve fuzzing.
- **Exit criterion**: property or fuzz tests for the sealed-snapshot parser, the tar restore path, the redaction engine, and the audit verifier; a written self-audit against the threat table; and ideally one external review (even a paid single-engineer review of `lib/crypto.py`, `lib/audit.py`, `lib/snapshot.py`).

### 7. Python and Rust key storage must agree (guarded since 0.11.x)

- **Evidence**: the Rust extension (`ext/src/crypto.rs`) only reads and writes the data key in the OS keychain. The AES-GCM line format lives in Python alone, so there is no second cipher to diverge. What can diverge is the keychain entry: service, account, attribute names and hex encoding.
- **Why it matters**: if the two backends disagree, a key written with the extension installed becomes invisible without it, and Zero-Trust state turns unreadable.
- **Guard**: `tests/test_crypto_backend_parity.py` reads the Rust source and fails on any drift in those four values, and fails if line encryption ever appears in Rust. A live keychain round trip across both backends stays manual, because CI runners have no keychain.

### 8. Governance and bus factor

- **Evidence**: single maintainer. Every merge needs an admin override because branch protection requires a review nobody else can give. The GPG signing key, PyPI account, and repository admin sit with one person. [GOVERNANCE.md](../GOVERNANCE.md) documents the continuity plan.
- **Why it blocks**: 1.0 implies someone will still answer security reports and ship fixes next year. That is a people question more than a code one.
- **Exit criterion**: a second maintainer with merge and release rights, or an explicit statement in the 1.0 notes that this is a single-maintainer project and what that means for response times. OpenSSF Silver also needs this, but Silver itself is not a 1.0 requirement.

### 9. Operational limits are tuned, not characterised

- **Evidence**: a perf bench gate exists and guards cold-hook latency. Nothing measures behavior with a very large audit log, hundreds of projects, a full event queue, or a slow filesystem (network home directories). The SessionStart audit check re-reads the whole log each time.
- **Why it blocks**: fail-closed plus unbounded growth is the combination that turns a slow day into an inert plugin.
- **Exit criterion**: documented limits with tests at the edge (log of 100k lines, 500 projects, an event queue at the emergency cap), and the incremental audit verification we deferred, if the numbers say it is needed.

## What 1.0 does not need

- ACP, universal install, and native Windows are post-1.0 and stay trigger-gated in the [roadmap](roadmap.md). 1.0 can say plainly that they are not supported.
- The OpenSSF Silver badge.
- A larger user base for its own sake. Evidence of use is the need, not the count.

## Suggested order

1. **0.11: trust the artifacts (shipped).** Checksums, attestations, SBOM, SHA-pinned Actions, Linux arm64 build, support matrix.
2. **0.12: prove the boundaries.** Host compatibility table and recorded payload fixtures, old-state fixtures with the state-format-marker decision. The Python/Rust key-storage guard is already in.
3. **0.13: harden.** Fuzz and property tests, operational-limit tests, self-audit document, external review request.
4. **Soak, then a release candidate.** Run 1.0-rc for several weeks with the feedback channel open; fix what comes in as rc.N.
5. **1.0** when the gaps above are closed or explicitly accepted in the release notes.

None of this is fast. Weeks to months of calendar time is realistic, mostly in the soak and the outside review, not in the code.

## What would change this assessment

Real users reporting real problems would move gap 1 in either direction. A second maintainer closes gap 8 immediately. A change in how Claude Code versions or documents its hook contract would reorder gap 2 to the top.
