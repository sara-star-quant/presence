# The 1.x contract

What presence promises not to break within a major version, and what it does not. `tests/test_contract.py` enforces the first list against `tests/contract_snapshot.json`: additions pass, removing or narrowing anything on it fails.

## Covered (additive-only within 1.x)

| Surface | Promise |
|---|---|
| Preset keys (`presets/_schema.json`) | A key is never removed or renamed, its type never changes, an enum never loses a value. New keys and new enum values may appear. |
| `schema_version` in a preset | Optional integer, default 1. A preset with a newer version than the plugin supports still loads and warns once (`preset_schema_newer`). The number changes only for a breaking preset change, which a major release alone may make. |
| Hook events (`hooks/hooks.json`) | The events and tool matchers listed in the snapshot keep firing the same script. New events may be added. |
| Hook names (`lib/cli.py hook <name>`) | The names in the snapshot keep working. |
| CLI subcommands (`lib/cli.py`) | `hook` and `mcp` keep working. |
| Hook failure behavior | A hook never fails the host: an unhandled error is logged and the hook exits 0. |
| State layout | `~/.claude/presence/` file names and the JSONL line-per-record format keep their meaning. The audit chain format is anchored by the genesis constant `presence-audit-v1`; the snapshot archive carries its own `format` number and restore refuses a mismatch. |

## Removal policy

A preset key, hook name, or CLI subcommand slated for removal is first deprecated: it keeps working and logs a warning for at least one minor release, the CHANGELOG names it, and only the next major release removes it.

## Not covered

- Python module internals under `lib/` (function names, signatures).
- Wording of warnings, doctor output, and injected context text.
- The Rust extension's internal API (`ext/` has its own version).
- The content of preset files shipped with the plugin (values may be retuned; the keys they use stay valid).

## Where this is checked

- Key, type, and enum stability: `tests/test_contract.py::test_schema_keys_are_superset_of_frozen`, `::test_schema_leaf_types_not_narrowed`.
- Hook and CLI surface: `::test_hooks_json_matches_frozen_events`, `::test_cli_hook_names_superset`, `::test_cli_subcommands_superset`.
- Every shipped preset validates without a warning: `::test_bundled_presets_validate_clean`.
- Threat-model claims each point at a pinning test: `::test_security_table_references_existing_tests`.

To add to the contract deliberately, regenerate the new entries into `tests/contract_snapshot.json` in the same change; never delete entries to make a test pass.
