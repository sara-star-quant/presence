# Third-party components

The `presence` plugin itself (Python under `lib/`, hooks, commands, skills,
presets, docs) is licensed under Apache-2.0 (see LICENSE).

The components below are NOT covered by that license. They are third-party
dependencies that retain their own upstream licenses. presence does not
relicense them; this file records them for attribution and to scope the
project license to first-party code.

## Optional native extension (`ext/`, Rust)

Built only when installed with `--build-ext` / `--download-ext`. Crates and
their upstream licenses (as published on crates.io):

| Crate | Upstream license |
| ----- | ---------------- |
| pyo3 | Apache-2.0 OR MIT |
| serde_json | Apache-2.0 OR MIT |
| hex | Apache-2.0 OR MIT |
| git2 | Apache-2.0 OR MIT |
| security-framework (macOS) | Apache-2.0 OR MIT |
| secret-service (Linux) | Apache-2.0 OR MIT |

Transitive dependencies retain their own licenses; see `ext/Cargo.lock` and
each crate's listing on crates.io for the authoritative terms.

## Optional Python dependency

| Package | Used by | Upstream license |
| ------- | ------- | ---------------- |
| cryptography | Zero-Trust at-rest encryption (opt-in) | Apache-2.0 OR BSD-3-Clause |

The default stdlib-only runtime pulls in none of the above.
