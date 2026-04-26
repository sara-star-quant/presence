# presence

[![CI](https://github.com/sara-star-quant/presence/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sara-star-quant/presence/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/sara-star-quant/presence?sort=semver&cacheSeconds=60)](https://github.com/sara-star-quant/presence/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue)](.github/workflows/ci.yml)
[![Stdlib only](https://img.shields.io/badge/runtime-stdlib--only-success)](pyproject.toml)
[![Local only](https://img.shields.io/badge/state-local--only-success)](docs/security.md)

A Claude Code plugin that turns every session into part of a continuum.

`presence` adds four things to Claude Code, globally, with one install and zero per-project setup:

1. **Living project model.** Claude builds and reuses notes about each repo it touches. No more re-deriving the same architecture every session.
2. **Outcome telemetry.** Tracks what Claude committed, then watches for reverts, amends, and PR closes. Future sessions see "your last 3 changes here were reverted within 24h" instead of repeating the same mistake.
3. **Event digest.** File changes, test failures, and build results that happened between turns are surfaced at the next prompt instead of needing to be polled.
4. **Calibrated confidence.** The Stop hook checks whether success claims ("fixed", "done", "works") are backed by actual verification (tests run, build green) since the change. Warns when they're not. Optional hard gate on `git commit`/`push`.

State lives in `~/.claude/presence/`, fully local, never uploaded.

## By the numbers

| Metric | Value | Method |
|---|---|---|
| Cold hook startup | 80 ms median, 87 ms p95 | n=50, `bench/cold_startup.py` |
| SessionStart populated | 108 ms median | 10 KB model + 100 events + 50 claims; n=50 |
| Install + first /presence-status | 237 ms total median | n=25, `bench/install_to_working.py` |
| Aggregate session overhead | 6.4 s for 77 hook fires | n=10, `bench/aggregate_session.py` |
| Tests | 167 passing | Python 3.12 + 3.13 + 3.14 across Linux + macOS |
| Runtime deps | 0 (stdlib only) | one optional: `cryptography` for Zero-Trust at-rest encryption |
| Surface area | 4 presets, 6 hooks, 5 slash commands, 3 skills, 1 subagent | see directories at repo root |
| Network egress | 0 in default presets | optional `gh` PR-status call (skill `outcome-check`); disabled in `zerotrust` |

All measurements: macOS arm64, Python 3.14.4. Reproduce locally with `python3 bench/<name>.py --runs N`.

> **Recent changes**: see [`CHANGELOG.md`](CHANGELOG.md) for the full per-version diff.
> v0.3.x cut cold-hook latency by ~27% and fixed a latent v0.2 bug where Zero-Trust users had their event digest silently emptied.
> v0.2.0 shipped the Zero-Trust preset: AES-GCM at rest, tamper-evident audit log, fail-closed SessionStart integrity. See [`docs/zerotrust.md`](docs/zerotrust.md).

## Install

Pick one method.

### Via the Claude Code plugin marketplace flow

The repo ships its own `marketplace.json` so it can be added directly:

```
/plugin marketplace add github.com/sara-star-quant/presence
/plugin install presence
```

### Via curl

```bash
curl -fsSL https://raw.githubusercontent.com/sara-star-quant/presence/main/install.sh | bash
```

### Via git clone

```bash
git clone https://github.com/sara-star-quant/presence ~/code/presence
~/code/presence/install.sh
```

The installer symlinks the plugin into `~/.claude/plugins/presence`, creates the state directory at `~/.claude/presence/` with `0700` perms, generates `MANIFEST.lock`, and pre-compiles `lib/` to bytecode. It is idempotent.

For the Zero-Trust preset's at-rest encryption (opt-in), also install the `cryptography` library:

```bash
pip install --user cryptography
```

Other presets and the rest of the Zero-Trust controls (integrity check, redaction, gates, audit log) are stdlib-only.

## Update

For installs done via curl or git clone:

```bash
~/code/presence/install.sh --update
```

`--update` does `git fetch` + `git pull --ff-only` + a re-run of the installer. It refuses to proceed if the working tree has uncommitted changes (so it never clobbers WIP). For installs done via the `/plugin` flow, use Claude Code's native plugin update mechanism.

## Verify install

In any Claude Code session:

```
/presence-status
```

You should see your active preset, the project ID for the current repo, and the size of the model + telemetry stores. For a focused Zero-Trust checklist:

```
/presence-status --zerotrust
```

For a full diagnostic:

```
/presence-doctor
```

## Presets

`presence` ships with four preset bundles. Switch any time:

```
/presence-preset use solo-dev
/presence-preset use team-oss
/presence-preset use enterprise-strict
/presence-preset use zerotrust
```

| Preset | Model | Telemetry | Commit gate | Stop gate | At rest |
|---|---|---|---|---|---|
| `solo-dev` (default) | on, terse | on, no PR check | off (advisory only via Stop) | silent (logged, surfaced next session) | plain |
| `team-oss` | on, verbose | on, optional PR check | warn (advisory text injected) | silent | plain |
| `enterprise-strict` | on, verbose, audit | on, audit log | block (refuses commit) | block (re-prompts on unverified success) | plain |
| `zerotrust` | on, encrypted, audit | on, encrypted, audit, no PR check | block | block | AES-GCM + keychain |

Custom presets: drop a `<name>.json` in `~/.claude/presence/presets/` and switch to it.

See [`docs/zerotrust.md`](docs/zerotrust.md) for the Zero-Trust profile in detail and [`CHANGELOG.md`](CHANGELOG.md) for the per-version diff.

## Uninstall

```
/plugin uninstall presence
```

Or, for local install:

```bash
~/.claude/plugins/presence/install.sh --uninstall
```

State at `~/.claude/presence/` is preserved by default. Pass `--purge` to also remove state. Under the Zero-Trust preset, also use `/presence-reset --crypto` to rotate the keychain key and wipe encrypted state.

## Privacy

- All state is local. Nothing is ever uploaded.
- No analytics, no telemetry-to-vendor, no remote calls.
- The `outcome-check` skill makes one optional `gh` call to read PR status if `gh` is on `$PATH` and authenticated; this hits GitHub's API directly, not any third party. Disable in preset.
- Under `zerotrust`, even that optional call is disabled.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full design: what each hook does, how state is laid out, the XML context schema, and how to write a custom preset.

## Disclaimer

`presence` is provided **as is** under the [MIT License](LICENSE), without warranty of any kind, express or implied. The authors and copyright holders (Sara Star Quant LLC) and any contributors are **not responsible** for any damage, data loss, security incident, regression, lost productivity, or other adverse outcome arising from the installation or use of this plugin.

This project is **not advice** of any kind:

- **Not legal advice.** The security model documented in [`docs/security.md`](docs/security.md) and [`docs/zerotrust.md`](docs/zerotrust.md) is informational. It is not a compliance attestation, certification, or guarantee under any regulatory framework (GDPR, HIPAA, SOC 2, ISO 27001, etc.). If you operate in a regulated environment, consult qualified counsel before relying on this plugin's properties.
- **Not security advice.** The Zero-Trust preset reduces attack surface and adds layered controls (encryption at rest, audit log, fail-closed integrity, hard commit gates) but is **not** a substitute for proper threat modeling, penetration testing, or operational security review in your specific environment.
- **Not engineering advice.** The calibrated-confidence gate and the living project model are useful nudges, **not** proofs of correctness. They reduce one common failure mode (asserting completion without verification); they do not replace tests, code review, or your own judgment.

By installing or using `presence`, you accept full responsibility for:

- Reviewing the source before running it on your system or in any session that touches sensitive data.
- Verifying that the documented properties (no network egress, local-only state, redaction patterns, encryption format, etc.) actually match what your environment requires.
- Any downstream consequences of decisions made or claims accepted while presence was active in your sessions, including but not limited to: code committed, code reverted, settings changed, and inferences drawn from the project model or telemetry digest.

The full legal terms are in [LICENSE](LICENSE). This README's Disclaimer section is an informational summary of the spirit of those terms; in any conflict, the LICENSE controls.

## License

MIT, see [LICENSE](LICENSE).
