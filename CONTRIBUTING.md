# Contributing to presence

Thanks for considering a contribution. The project favors small, focused changes with clear motivation, and the hard constraints below exist to keep the plugin install-once and predictable for end users.

## Hard constraints

These are non-negotiable; PRs that break them will be asked to revise:

1. **Stdlib-only runtime.** The hook and slash-command code path must work with a fresh CPython install, no `pip install` required. The single optional dep is `cryptography`, used only by the `zerotrust` preset's at-rest encryption.
2. **ASCII-only** in code, docs, commits, PRs, and release notes. Two intentional unicode test fixtures are exempt: `tests/test_model.py`, `tests/test_redact.py`, `tests/test_crypto.py`. Verify with `LC_ALL=C grep -nP '[^\x00-\x7F]' <files>`. CI's `ascii` job enforces this on every push.
3. **No em-dashes anywhere.** Use `--` or rephrase. Em-dashes are non-ASCII, so the ASCII-only check above flags them (a byte-class grep like `[\xe2...]` does not -- use the `[^\x00-\x7F]` form, or `grep -nP '\x{2014}'` without `LC_ALL=C`).
4. **Branch -> PR -> wait for human merge.** No direct commits to `main`, no auto-merge, no force-push to shared branches.
5. **Author commits as your own git identity.** No synthetic identity (no `Co-Authored-By: <bot>` lines unless the project explicitly asks).

## Dev environment setup

The project uses PEP 735 dependency groups for dev tooling:

```bash
python3 -m venv .venv
.venv/bin/pip install --group dev    # pytest + cryptography + ruff
```

Requires pip 25.1 or later. If your pip is older, the equivalent is:

```bash
.venv/bin/pip install pytest cryptography ruff bandit
```

Python 3.12+ is required. CI runs against 3.12, 3.13, and 3.14 on both Linux and macOS.

## Coding standards

- **Python** follows PEP 8, enforced by ruff (configuration in `pyproject.toml [tool.ruff]`); ruff also applies bugbear, pyupgrade, security (flake8-bandit), and other rule sets.
- **Shell** scripts follow shellcheck's recommendations.
- **Rust** (the optional `ext/` extension) follows rustfmt formatting and clippy lints.

These run in CI and must pass before merge. Style exceptions are rare and annotated inline at their location (e.g. `# noqa`, `# nosec`).

## Local checks before opening a PR

All five must be green:

```bash
.venv/bin/python -m pytest -q                          # unit + integration tests
.venv/bin/python -m ruff check lib tests bench         # lint
.venv/bin/python -m bandit -c pyproject.toml -r lib    # security scan
shellcheck install.sh hooks/scripts/*.sh               # bash hygiene
PYTHONPATH=lib python3 lib/integrity.py --verify       # MANIFEST.lock matches lib/, hooks/, presets/, etc.
```

If you edited any file in `lib/integrity.py:_INCLUDE_GLOBS` (notably `lib/*.py`, `hooks/scripts/*.sh`, `presets/*.json`, `commands/*.md`, `agents/*.md`, `skills/**/*.md`, `.claude-plugin/*.json`), regenerate the manifest:

```bash
PYTHONPATH=lib python3 lib/integrity.py --write
```

Commit the regenerated `MANIFEST.lock` alongside the source change. CI's `manifest-integrity` job will fail otherwise.

### Statement coverage

CI's `coverage` job gates statement coverage at 74% (the Silver-badge target is 80%, tracked in #39). Measurement is in-process and deterministic; `daemon.py` is omitted (it runs only as a subprocess and is behavior-tested by `tests/test_daemon.py`). To reproduce the CI number locally:

```bash
PYTHONPATH=lib .venv/bin/coverage run -m pytest -q
.venv/bin/coverage report
```

## Adding a test

**Policy:** changes that add or alter behavior MUST include tests covering the new or changed code paths. PRs that change behavior without tests will be asked to add them.

Test files live under `tests/` and are auto-collected. Use the `isolated_state` fixture from `tests/conftest.py` whenever you touch state. Use the `fake_repo` fixture when you need a stable `repo_id`. Examples:

- `tests/test_hooks_smoke.py` exercises every hook wrapper end-to-end.
- `tests/test_zerotrust_integration.py` uses an in-memory keychain stub so the suite never touches a real OS keychain.
- `tests/test_install_update.py` and `tests/test_doctor_fix.py` test the install.sh `--update` / `--verify` paths and `lib/doctor.py --fix`.

If your change adds a new code path that affects performance, add a bench script under `bench/` (see `bench/README.md`).

## Adding a slash command, skill, or agent

- Slash commands: drop a markdown file under `commands/` with the YAML frontmatter Claude Code expects (see `commands/presence-status.md` for shape).
- Skills: directory under `skills/<name>/SKILL.md`.
- Agents: markdown file under `agents/`.

All of these are integrity-tracked, so regenerate the manifest after.

## Adding a preset

Drop a JSON under `presets/<name>.json`. The four shipped presets (`solo-dev`, `team-oss`, `enterprise-strict`, `zerotrust`) are the reference for valid keys, and `presets/_schema.json` declares every recognized field. `_load_preset` validates against it on read: an unrecognized or wrong-typed key emits a warning (surfaced by `/presence-doctor` and the next SessionStart) instead of being silently ignored. Add new fields to `_schema.json` in the same change that starts reading them. Custom user presets belong in `~/.claude/presence/presets/`, which loads first and sits outside the integrity manifest.

## Release flow (maintainer notes)

1. Open a PR with the change (no version bump).
2. Merge after review.
3. On `main`: bump `.claude-plugin/plugin.json` and `lib/__init__.py` to the new version, regenerate `MANIFEST.lock`, commit as `v<X.Y.Z>: bump version`.
4. Tag (GPG-signed): `git tag -s v<X.Y.Z> -m "v<X.Y.Z>"`. The repo sets `user.signingkey`, so `-s` needs no extra flags (you will be prompted for the key passphrase; on macOS you may need `export GPG_TTY=$(tty)`). Verify locally with `git tag -v v<X.Y.Z>`. For the tag to show "Verified" on GitHub, upload the public key to your account and make sure the tagger email matches a verified account email.
5. Push: `git push origin main && git push origin v<X.Y.Z>`.
6. Create the GitHub release: `gh release create v<X.Y.Z> --target main --notes-file <CHANGELOG-extracted-section> --latest`.

## Performance work

The `bench/` harness is the source of truth for any "X is faster" claim. Reproduce numbers locally before claiming them in the CHANGELOG, and report median + p95 + n. See [`bench/README.md`](bench/README.md) for the convention.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). In short: be polite, be specific, assume good faith. See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for the expected behavior and how to report unacceptable conduct.

## License

By contributing, you agree your contributions are licensed under the Apache License 2.0 (see [`LICENSE`](LICENSE)). Sign off each commit with `git commit -s` to certify the [Developer Certificate of Origin](https://developercertificate.org/); the `Signed-off-by` line asserts you wrote the change or have the right to submit it under that license.
