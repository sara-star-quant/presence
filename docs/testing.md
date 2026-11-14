# How presence is tested

What runs, what each layer is meant to catch, and what is not covered. Numbers are from main after v0.11.1: 548 tests in `tests/`.

## Layers

| Layer | Where | Catches |
|---|---|---|
| Unit and integration tests | `tests/`, run by `pytest` | Behavior of hooks, presets, state, redaction, audit, snapshots, the MCP server |
| Contract test | `tests/test_contract.py`, `tests/contract_snapshot.json` | Any removal or rename of a preset key, hook event, or CLI command ([contract.md](contract.md)); a threat in [security.md](security.md) whose pinning test no longer exists |
| Host payloads | `tests/test_host_payloads.py`, `tests/fixtures/host/<version>/` | The real hooks disagreeing with what Claude Code actually sends |
| Upgrade fixtures | `tests/test_state_upgrade.py`, `tests/fixtures/state/<tag>/` | State written by an earlier release that the current code can no longer open |
| Property tests | `tests/test_fuzz.py` (Hypothesis) | Parsers raising or misbehaving on arbitrary input |
| Coverage-guided fuzzing | `fuzz/` (Atheris under ClusterFuzzLite) | The same, reaching branches that random input does not |
| Backend parity | `tests/test_crypto_backend_parity.py` | The Python and Rust backends disagreeing on the keychain entry |
| Supply chain | `tests/test_release_supply_chain.py` | A GitHub Action referenced by tag instead of commit SHA |
| Performance gate | `bench/`, CI `bench` job | Hook latency regressions (cold start median 300 ms, aggregate session 12000 ms, both CI-runner thresholds) |

## Contract and upgrade tests

The compatibility promise is a test, not a paragraph. `contract_snapshot.json` records the frozen surface; `test_contract.py` fails if anything in it disappears. Additions pass.

Upgrade fixtures are state directories produced by each past release's own hooks, generated with `tests/fixtures/make_state_fixture.py <tag>` and committed. They are never regenerated from newer code, because that would test the new code against itself. The suite runs the current SessionStart hook and doctor against each one and checks that the model loads, doctor reports nothing, the audit chain verifies, and no old record is rewritten. There is one fixture per release from v0.7.1 on; a new one is added at each release.

## Fuzzing

Two tools cover the parsers that read bytes someone else could have written: the sealed and plain snapshot restore path, the audit-chain verifier, and the redaction engine.

- **Hypothesis** (`tests/test_fuzz.py`) runs on every PR with the normal suite. It asserts failure contracts: restore raises only `SnapshotError`, never writes outside the state dir, and never leaves it a non-directory; the verifier reports damage instead of raising; the redactor never raises. A bug the fuzzers found stays as an explicit `@example`, so it is replayed every run.
- **Atheris** (`fuzz/fuzz_snapshot.py`, `fuzz_audit.py`, `fuzz_redact.py`) runs under [ClusterFuzzLite](../.clusterfuzzlite/): 3 minutes on PRs that touch `lib/`, `fuzz/`, or the fuzz config, and a 30-minute batch nightly with the corpus kept between runs as workflow artifacts. The harnesses are structure-aware: they build well-formed tars, sealed archives, and audit chains, then damage them one way at a time, because raw bytes rarely get past a gzip header or an AES-GCM tag. The audit harness also checks the reverse property, that every damage it applies is reported. The redaction harness plants a known secret between separators and asserts it does not survive.

Atheris needs a Linux libFuzzer toolchain and does not build on macOS. To run it, trigger the `ClusterFuzzLite batch fuzzing` workflow from the Actions tab, or open a PR.

The first runs found real bugs, all fixed in v0.11.1 ([changelog](../CHANGELOG.md)): a snapshot member named `.` replaced the state directory with a file, an audit line holding U+2028 made the log read as corrupt, and several malformed-archive cases escaped as raw exceptions.

## CI

Every PR and every push to main runs:

- the test suite on Python 3.12, 3.13, and 3.14, on Linux x86_64, Linux arm64, and macOS arm64
- `ruff`, `bandit`, `shellcheck`, and an ASCII check that rejects non-ASCII outside the intentional test fixtures
- statement coverage with an 80% gate
- a check that `MANIFEST.lock` matches a fresh regeneration
- the two latency gates above, and a wheel build for the Rust client
- CodeQL and ClusterFuzzLite

## Not covered

- **The live Claude Code host in CI.** The host-payload tests replay payloads captured from a real Claude Code, but capturing needs a logged-in session, so a new Claude Code version stays unverified until someone re-runs `tests/fixtures/capture_host_payloads.py`. The README lists the tested versions. The first capture showed that every other hook test had been agreeing with our own assumptions: a successful Bash command carries no exit code, and failures arrive as a separate event.
- **A live keychain.** CI runners have none, so a round trip across the Python and Rust backends is manual.
- **macOS x86_64 and native Windows.** No runner for the first; unsupported on the second ([#9](https://github.com/sara-star-quant/presence/issues/9)).
- **Independent review.** The threat model, the code, and the tests have one author. No external security review has been done.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install --group dev
.venv/bin/python -m pytest -q
```

[CONTRIBUTING.md](../CONTRIBUTING.md) has the full development setup.
