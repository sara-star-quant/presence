# Governance

## Model

presence uses a single-maintainer ("benevolent dictator") model. The maintainer makes the final decisions on scope, design, releases, and dispute resolution. Anyone may propose changes via a pull request or open an issue to discuss direction; the maintainer reviews, requests changes, and decides what merges.

Because the project is FLOSS under the Apache-2.0 license, anyone may fork at any time if they disagree with the direction.

## Roles and responsibilities

- **Maintainer** (currently Peter Z., GitHub `@pzverkov`):
  - Triages issues and reviews/merges pull requests.
  - Owns the release process (version bump, signed tag, GitHub release) - see [CONTRIBUTING.md](CONTRIBUTING.md).
  - Holds the credentials needed to operate the project: GitHub repository admin, the GPG release signing key, the PyPI account for the `presence-mcp` launcher, and the OpenSSF Best Practices entry.
  - Sets and enforces the hard constraints in [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Contributors**: anyone who opens an issue or pull request. Contributions must meet the requirements in [CONTRIBUTING.md](CONTRIBUTING.md) (tests for behavior changes, lint, ASCII-only, branch -> PR -> review).

## Decision making

Routine changes: the maintainer reviews and merges. Larger or contentious changes are discussed in a GitHub issue first; the maintainer makes the final call and records the reasoning in the issue or PR thread.

## Continuity and succession

The project is currently single-maintainer (bus factor 1). To keep it recoverable if the maintainer becomes unavailable:

- The repository lives in the `sara-star-quant` GitHub organization, so another organization owner can be added and can administer the repository, issues, and releases.
- The credentials required to continue the project (GitHub org/repo admin, the GPG release signing key plus its revocation certificate, the PyPI launcher account) are kept by the maintainer in a personal secret store so they can be recovered or transferred.
- Adding a second maintainer - which raises the bus factor to 2 and enables two-person review - is an explicit near-term goal. Until then, this document records the recovery path.

Because the code is Apache-2.0-licensed, the project can also continue via a fork even without an access transfer.
