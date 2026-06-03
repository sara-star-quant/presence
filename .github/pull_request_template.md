<!-- Thanks for opening a PR. Please fill out everything below; it makes review faster. -->

## Summary

<!-- One or two sentences. What changed and why. -->

## What changed

<!-- Bulleted list of the actual diff highlights. Reference file paths. -->

## Test plan

<!-- Tick what you ran locally. CI will re-run them on push. -->

- [ ] `.venv/bin/python -m pytest -q` (all green)
- [ ] `.venv/bin/python -m ruff check lib tests bench`
- [ ] `.venv/bin/python -m bandit -c pyproject.toml -r lib`
- [ ] `shellcheck install.sh hooks/scripts/*.sh`
- [ ] `PYTHONPATH=lib python3 lib/integrity.py --verify`
- [ ] New/changed behavior is covered by tests (required for behavior changes)
- [ ] `bash install.sh --verify` (if you touched install/runtime paths)
- [ ] Bench numbers (if you made a perf-relevant change): `python3 bench/<relevant>.py --runs 50`

## Backward compat

<!-- Does this break any v0.3.x state file (settings.json, encrypted/plain telemetry, audit log, model.md, MANIFEST.lock)? If so, document the migration path. -->

- [ ] No state-file format changes
- [ ] No CLI flag removals or behavior changes for existing flags

## Constraints checklist

- [ ] ASCII-only outside the two intentional unicode test fixtures (`tests/test_model.py`, `tests/test_redact.py`, `tests/test_crypto.py`)
- [ ] No em-dashes anywhere
- [ ] Stdlib-only runtime preserved (one optional dep `cryptography` only for zerotrust)
- [ ] CHANGELOG.md updated under the unreleased section (if user-visible)
- [ ] MANIFEST.lock regenerated (if you edited any file in `lib/integrity.py:_INCLUDE_GLOBS`)
