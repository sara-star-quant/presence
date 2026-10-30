# Security policy

## Reporting a vulnerability

Please use GitHub's private security advisory flow:

https://github.com/sara-star-quant/presence/security/advisories/new

Do **not** file a public issue for security-relevant findings. The maintainer will respond within a reasonable window and coordinate disclosure.

If GitHub Security Advisories is not available to you for any reason, contact the maintainer through the GitHub profile linked from the repo (`sara-star-quant`).

## Response process

Once a report arrives:

1. The maintainer acknowledges receipt within 14 days (usually sooner).
2. The report is triaged: reproduce, assess severity, and confirm whether it is in scope (see below).
3. A fix is developed privately in the GitHub Security Advisory. Medium and higher severity issues are patched within 60 days of confirmation; critical issues are prioritized.
4. A patched release is published, the advisory is disclosed, and the reporter is credited unless they request anonymity.

## Supported versions

Only the most recent minor release of `presence` is actively supported. Patch releases backport security fixes within the same minor line; older minors do not receive backports unless an issue is severe and the upgrade path is blocked.

| Version | Supported |
|---|---|
| latest minor (currently 0.6.x) | yes |
| earlier minor lines | no |

## Threat model in scope

The full threat model lives in [`docs/security.md`](docs/security.md) (T1 through T12) and the Zero-Trust profile is documented in [`docs/zerotrust.md`](docs/zerotrust.md). In summary:

- Hooks must never make Claude Code observe a presence-induced error (`safe_main` outermost guard).
- Hooks must never leak private data to stdout (only structured `additionalContext` text; no raw env, no raw file contents, no auth headers).
- State files must remain readable only by the owning user (`0o700` / `0o600`, set on write and re-tightened every SessionStart).
- Logged commands containing secrets must be redacted before write (`lib/redact.py`; aggressive redaction under the `zerotrust` preset).
- Plugin file integrity must be verifiable on demand (`/presence-doctor` in v0.1; SessionStart fail-closed in v0.2 under `zerotrust`).
- Under `zerotrust`: state at rest must be AES-GCM encrypted with the data key wrapped in the OS keychain; the audit log must be tamper-evident with a per-line SHA-256 hash chain; `presence-unlock` must gate any settings.json or preset write.

## Out of scope

The following are **not** considered vulnerabilities for the purposes of this policy:

- A compromised Claude Code binary itself. That is outside the trust boundary; if Claude Code is hostile, hooks are not your problem.
- A compromised local user account. Once an attacker has shell as you, they have your `~/.claude/` regardless of presence.
- Side-channel timing attacks on hook execution.
- The optional `gh pr` outcome check (in `team-oss`+ presets) reaching GitHub's API. This is a documented opt-in network call and is disabled in `zerotrust`.
- The opt-in `install.sh --bootstrap` flag fetching `https://astral.sh/uv/install.sh`. This is documented as an explicit network call requiring the user's `--bootstrap` flag; the default install path makes no outbound calls.

## Verifying a release

Release tags are GPG-signed from v0.6.2 onward (earlier tags predate the signing setup). To verify a signed tag you have checked out:

1. Import the maintainer's public signing key (GPG key `3D675B9061B2B930`), published on the maintainer's GitHub account at `https://github.com/pzverkov.gpg`.
2. Run `git tag -v v<X.Y.Z>` and confirm a "Good signature" from that key.

The private signing key is held only by the maintainer and is never stored on any distribution server.

### Release binaries

From v0.11.0 each release also carries `SHA256SUMS`, a CycloneDX SBOM (`presence-sbom.cdx.json`) for the Rust extension's dependencies, and a build provenance attestation for every binary and the SBOM.

- `./install.sh --download-ext` checks the downloaded binary against `SHA256SUMS` and refuses a mismatch or a missing entry. Releases before v0.11.0 have no `SHA256SUMS`; the installer warns that the binary is unverified.
- To verify provenance yourself (needs the GitHub CLI): `gh attestation verify presence-client-<platform> --repo sara-star-quant/presence`. This proves the binary came out of this repository's release workflow for that tag. The checksum alone only proves the download matches what the release published.
- Every GitHub Action in the workflows is pinned by commit SHA, so a moved tag upstream cannot change what the release job runs.

## See also

- [`README.md`](README.md) Disclaimer section for the legal positioning (Apache-2.0, no warranty, not legal/security/engineering advice).
- [`docs/security.md`](docs/security.md) for the full T1-T12 threat model.
- [`docs/zerotrust.md`](docs/zerotrust.md) for the Zero-Trust profile.
- [`CHANGELOG.md`](CHANGELOG.md) for security-relevant changes per release.
