# Contributing to presence

Thanks for considering a contribution. The project favors small, focused changes with clear motivation, and the hard constraints below exist to keep the plugin install-once and predictable for end users.

## Hard constraints

These are non-negotiable; PRs that break them will be asked to revise:

1. **Stdlib-only runtime.** The hook and slash-command code path must work with a fresh CPython install, no `pip install` required. The single optional dep is `cryptography`, used only by the `zerotrust` preset's at-rest encryption.
2. **ASCII-only** in code, docs, commits, PRs, and release notes. Two intentional unicode test fixtures are exempt: `tests/test_model.py`, `tests/test_redact.py`, `tests/test_crypto.py`. Verify with `LC_ALL=C grep -nP '[^\x00-\x7F]' <files>`.
3. **No em-dashes anywhere.** Use `--` or rephrase. Verify with `LC_ALL=C grep -nP '[\xe2\x80\x93\xe2\x80\x94]' <files>`.
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
.venv/bin/pip install pytest cryptography ruff
```

Python 3.12+ is required. CI runs against 3.12, 3.13, and 3.14 on both Linux and macOS.

## Local checks before opening a PR

All four must be green:

```bash
.venv/bin/python -m pytest -q                          # unit + integration tests
.venv/bin/python -m ruff check lib tests bench         # lint
shellcheck install.sh hooks/scripts/*.sh               # bash hygiene
PYTHONPATH=lib python3 lib/integrity.py --verify       # MANIFEST.lock matches lib/, hooks/, presets/, etc.
```

If you edited any file in `lib/integrity.py:_INCLUDE_GLOBS` (notably `lib/*.py`, `hooks/scripts/*.sh`, `presets/*.json`, `commands/*.md`, `agents/*.md`, `skills/**/*.md`, `.claude-plugin/*.json`), regenerate the manifest:

```bash
PYTHONPATH=lib python3 lib/integrity.py --write
```

Commit the regenerated `MANIFEST.lock` alongside the source change. CI's `manifest-integrity` job will fail otherwise.

## Adding a test

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

Drop a JSON under `presets/<name>.json`. The four shipped presets (`solo-dev`, `team-oss`, `enterprise-strict`, `zerotrust`) are the reference for valid keys. There is no formal schema yet (tracked under Issue E in the roadmap); a typo in a preset key is silently ignored.

## Release flow (maintainer notes)

1. Open a PR with the change (no version bump).
2. Merge after review.
3. On `main`: bump `.claude-plugin/plugin.json` and `lib/__init__.py` to the new version, regenerate `MANIFEST.lock`, commit as `v<X.Y.Z>: bump version`.
4. Tag: `git tag -a v<X.Y.Z> -m "v<X.Y.Z>"`.
5. Push: `git push origin main && git push origin v<X.Y.Z>`.
6. Create the GitHub release: `gh release create v<X.Y.Z> --target main --notes-file <CHANGELOG-extracted-section> --latest`.

## Performance work

The `bench/` harness is the source of truth for any "X is faster" claim. Reproduce numbers locally before claiming them in the CHANGELOG, and report median + p95 + n. See [`bench/README.md`](bench/README.md) for the convention.

## Code of conduct

Be polite, be specific, assume good faith. Disagreements are welcome; personal attacks are not. The maintainer reserves the right to lock or close threads that get unproductive.

## License

By contributing, you agree your contributions are licensed under the MIT License (see [`LICENSE`](LICENSE)).
