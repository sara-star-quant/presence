# presence

[![CI](https://github.com/sara-star-quant/presence/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sara-star-quant/presence/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/sara-star-quant/presence?sort=semver&cacheSeconds=60)](https://github.com/sara-star-quant/presence/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue)](.github/workflows/ci.yml)
[![Stdlib only](https://img.shields.io/badge/runtime-stdlib--only-success)](pyproject.toml)
[![Local only](https://img.shields.io/badge/state-local--only-success)](docs/security.md)

A Claude Code plugin with read-only projections (MCP server, AGENTS.md adapter) so MCP-aware clients (Cursor, Claude Desktop, Continue) and AGENTS.md-aware tools (Codex, Gemini CLI, Windsurf, GitHub Copilot) can also read its accumulated context. Turns every session into part of a continuum.

`presence` adds four things to Claude Code, globally, with one install and zero per-project setup:

1. **Living project model.** Claude builds and reuses notes about each repo it touches. No more re-deriving the same architecture every session.
2. **Outcome telemetry.** Tracks what Claude committed, then watches for reverts, amends, and PR closes. Future sessions see "your last 3 changes here were reverted within 24h" instead of repeating the same mistake.
3. **Event digest.** File changes, test failures, and build results that happened between turns are surfaced at the next prompt instead of needing to be polled.
4. **Calibrated confidence.** The Stop hook checks whether success claims ("fixed", "done", "works") are backed by actual verification (tests run, build green) since the change. Warns when they're not. Optional hard gate on `git commit`/`push`.

State lives in `~/.claude/presence/`, fully local, never uploaded.

## Install (30 seconds)

```bash
curl -fsSL https://raw.githubusercontent.com/sara-star-quant/presence/main/install.sh | bash
```

That's the whole thing. Idempotent installer, makes no outbound network calls beyond fetching itself, applies globally to every Claude Code project. Restart Claude Code and run `/presence-status` to confirm. For options (`--bootstrap` to auto-install Python, `--verify`, `--build-ext` for the native fast path), see [Quickstart](#quickstart) below.

## By the numbers

| Metric | Default (stdlib) | With `--build-ext` | Method |
|---|---|---|---|
| Cold hook startup | 82 ms median | **8.9 ms median** | n=50 / n=30, `bench/cold_startup.py` |
| SessionStart populated | 112 ms median | **9.1 ms median** | 10 KB model + 100 events + 50 claims |
| Aggregate session (77 fires) | 6.4 s | **770 ms** | n=10 / n=5, `bench/aggregate_session.py` |
| Install + first /presence-status | 245 ms total | 245 ms total | n=25, `bench/install_to_working.py` |
| Tests | 291 passing | | Python 3.12 + 3.13 + 3.14 across Linux + macOS |
| Runtime deps (default) | 0 (stdlib only) | | one optional: `cryptography` for Zero-Trust at-rest encryption |
| Optional with `--build-ext` | | Rust toolchain at install time | binary then runs without Rust |
| Surface area | 4 presets, 6 hooks, 6 slash commands, 3 skills, 1 subagent, 1 MCP server, 1 cross-tool adapter, 3 redaction profiles | | redaction profiles opt-in for regulated workloads |
| Network egress | 0 in default presets | | opt-in `gh` PR-status call; opt-in `--bootstrap` / `--download-ext`; all disabled by default |
| Platforms | macOS arm64 + Linux x86_64 (CI) | | Windows: install in WSL2 |

The `--build-ext` column reflects optional native acceleration via the Rust daemon client (`./install.sh --build-ext` to compile locally, or `--download-ext` to fetch a pre-built binary from the latest release). Without it, hooks run on the stdlib-only path. See [`bench/HISTORY.md`](bench/HISTORY.md) for the full version-by-version benchmark history.

All measurements: macOS arm64, Python 3.14.4. Reproduce locally with `python3 bench/<name>.py --runs N`. See [`bench/README.md`](bench/README.md) for the full convention.

> **Recent changes**: see [`CHANGELOG.md`](CHANGELOG.md) for the full per-version diff.
> v0.5.0 ships composable redaction profiles for jurisdiction-aware sensitive data. Opt-in via `redact.profiles` in settings: `pii-eu`, `pii-us`, `pci-dss` (PAN matches gated by Luhn). New `docs/compliance.md` says exactly what presence does and does not do for regulated workloads. No certification framing: profile names describe data classes, not compliance frameworks.
> v0.4.2 ships the cross-tool AGENTS.md adapter. Set `PRESENCE_HOST=agents-md` and presence refreshes `<repo>/AGENTS.md` on every Claude Code SessionStart, picked up automatically by Codex, Cursor, Gemini CLI, Windsurf, GitHub Copilot, and others reading the open AGENTS.md standard. See [`docs/multi-host.md`](docs/multi-host.md).
> v0.4.1 shipped the MCP server: any MCP-aware client (Claude Desktop, Cursor, Continue, custom agents) can read presence's living model + outcome telemetry over JSON-RPC stdio. See [`docs/mcp.md`](docs/mcp.md).
> v0.4.0 shipped the Rust daemon client + warm Python daemon + adapter seam. Optional via `--build-ext` / `--download-ext`. Cuts hot-path latency from 82 ms to 8.9 ms (-89%).
> v0.3.x cut cold-hook latency by ~27% and fixed a latent v0.2 bug where Zero-Trust users had their event digest silently emptied.
> v0.2.0 shipped the Zero-Trust preset: AES-GCM at rest, tamper-evident audit log, fail-closed SessionStart integrity. See [`docs/zerotrust.md`](docs/zerotrust.md).

## Quickstart

If this is your first Claude Code plugin: just run these two commands.

### 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/sara-star-quant/presence/main/install.sh | bash
```

The installer is idempotent. It checks for Python 3.12+, symlinks the plugin into `~/.claude/plugins/presence`, creates the state directory at `~/.claude/presence/` with `0700` perms, generates `MANIFEST.lock`, and pre-compiles `lib/` to bytecode.

If you don't have Python 3.12+, the installer prints a warning and continues; presence is installed but stays inactive until a 3.12+ Python is on `PATH`. This is intentional so you can install on a machine that will get Python later (or run `--bootstrap`). To auto-install Python 3.13 via [uv](https://github.com/astral-sh/uv) (single binary, no sudo, ~5 MB), pass `--bootstrap`:

```bash
curl -fsSL https://raw.githubusercontent.com/sara-star-quant/presence/main/install.sh | bash -s -- --bootstrap
```

`--bootstrap` is opt-in because it makes one network call to `astral.sh`. The default install path makes no outbound calls.

### 2. Verify it works

```bash
~/.claude/plugins/presence/install.sh --verify
```

Checks the symlink, plugin registration in `settings.json`, perms, Python, the `MANIFEST.lock` integrity, and synthetically fires all 6 hooks against the real lib/ tree. Exit 0 means ready. `FAIL` lines tell you exactly what is missing. For machine-readable output: `--verify --json`.

### 3. Use it

Restart Claude Code (or open a new session) in any repo and run `/presence-status`.

## Other install methods

### Via the Claude Code plugin marketplace flow

The repo ships its own `marketplace.json` so it can be added directly:

```
/plugin marketplace add github.com/sara-star-quant/presence
/plugin install presence
```

### Via git clone

```bash
git clone https://github.com/sara-star-quant/presence ~/code/presence
~/code/presence/install.sh
```

For the Zero-Trust preset's at-rest encryption (opt-in), also install the `cryptography` library into the same Python presence uses. On modern macOS / Linux this matters because Homebrew and most distros mark the system Python as PEP 668 externally-managed; a bare `pip install` exits with `error: externally-managed-environment`.

Pick the path that matches how you got Python:

```bash
# A. You used --bootstrap (presence has its own uv-managed Python).
#    pip works directly there, no PEP 668 wall.
"$(cat ~/.claude/presence/.python_bin)" -m pip install cryptography

# B. You're on Homebrew / a system Python and want to override PEP 668
#    (installs into your user site, not system; safe in practice).
python3 -m pip install --user --break-system-packages cryptography

# C. You want isolation (cleanest): create a venv and pin presence at it.
python3 -m venv ~/.claude/presence-venv
~/.claude/presence-venv/bin/pip install cryptography
echo "$HOME/.claude/presence-venv/bin/python3" > ~/.claude/presence/.python_bin
```

If unsure which Python presence is using, run `/presence-doctor` and look at the `pinned python` / `python` lines, then use that interpreter's `-m pip install cryptography`.

Other presets and the rest of the Zero-Trust controls (integrity check, redaction, gates, audit log) are stdlib-only.

## Update

For installs done via curl or git clone:

```bash
~/.claude/plugins/presence/install.sh --update
```

`--update` does `git fetch` + `git pull --ff-only` + a re-run of the installer. It refuses to proceed if the working tree has uncommitted changes (so it never clobbers WIP). For installs done via the `/plugin` flow, use Claude Code's native plugin update mechanism.

### Get notified of new releases (opt-in)

`/presence-doctor` can surface the latest released tag against your installed version. Off by default; enable by adding the following to `~/.claude/presence/settings.json`:

```json
{ "update_check": { "enabled": true } }
```

The next SessionStart pre-warms a 24 h cache (one anonymous HTTPS GET to `api.github.com`); the doctor then renders one line, e.g. `latest       : v0.6.0 (you have v0.5.4) [checked 12h ago]`. Forced off under the `zerotrust` preset (no network egress under that posture). Run `/presence-doctor --refresh` to bypass the TTL when verifying a fresh tag.

## Verify install

The fastest check is `./install.sh --verify` from the previous section. From inside Claude Code you can also run:

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

To auto-correct recoverable issues (perm drift, missing manifest, stale `.integrity-blocked` marker):

```bash
PYTHONPATH=~/.claude/plugins/presence/lib python3 ~/.claude/plugins/presence/lib/doctor.py --fix
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
- Composable redaction profiles for jurisdiction-relevant patterns (EU PII, US PII, PCI-DSS) ship in [`presets/redaction/`](presets/redaction/). See [`docs/compliance.md`](docs/compliance.md) for the honest scope (presence has no formal certification).

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full design: what each hook does, how state is laid out, the XML context schema, and how to write a custom preset.

## Documentation

Start at [`docs/index.md`](docs/index.md) for a map. Highlights:

- [`docs/architecture.md`](docs/architecture.md) - how the pieces fit together
- [`docs/security.md`](docs/security.md) - threat model (T1 through T12)
- [`docs/zerotrust.md`](docs/zerotrust.md) - the opt-in Zero-Trust profile
- [`docs/compliance.md`](docs/compliance.md) - what presence does / does not do for regulated workloads (no certification framing)
- [`docs/glossary.md`](docs/glossary.md) - definitions for project-specific terms
- [`docs/recipes.md`](docs/recipes.md) - common preset customizations
- [`docs/roadmap.md`](docs/roadmap.md) - what we've deferred and why
- [`SECURITY.md`](SECURITY.md), [`CONTRIBUTING.md`](CONTRIBUTING.md), [`bench/README.md`](bench/README.md), [`llms.txt`](llms.txt)

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
