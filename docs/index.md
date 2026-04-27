# presence docs

Quick map of what lives where. If you're a new user start with the README; this index is for when you're looking for something specific.

## Pages

- **[architecture.md](architecture.md)** - how the pieces fit together: hooks, state layout, the XML context schema, how presets compose. Read this if you want to understand or extend the runtime.
- **[security.md](security.md)** - threat model (T1 through T12), what presence defends against, what is explicitly out of scope. Read this before relying on the Zero-Trust properties for anything serious.
- **[zerotrust.md](zerotrust.md)** - the opt-in `zerotrust` preset: AES-GCM at rest, audit log with hash chain, fail-closed integrity, settings-immutability. Read this if you're considering enabling Zero-Trust.
- **[glossary.md](glossary.md)** - definitions for the terms presence uses (living model, calibrated confidence, integrity manifest, etc.). Read this if a term you saw in the README isn't obvious.
- **[recipes.md](recipes.md)** - common preset customizations as copy-paste snippets ("warn-only commit gate", "longer transcript scan", "back up my state", etc.).
- **[mcp.md](mcp.md)** - Model Context Protocol integration. Exposes presence's living model + telemetry as MCP resources for Claude Desktop, Cursor, Continue, and any other MCP-aware client.
- **[multi-host.md](multi-host.md)** - cross-tool AGENTS.md adapter (v0.4.2+). One env var lets Codex, Cursor, Gemini CLI, Windsurf, GitHub Copilot, and others read presence's accumulated context.
- **[roadmap.md](roadmap.md)** - what we've decided to defer and why (multi-tool, native Windows, release automation, snapshots, schema validation, side-by-side installs). Each item has a tracking issue with the same title.

## See also

- **[../README.md](../README.md)** - install + Quickstart + presets table.
- **[../CHANGELOG.md](../CHANGELOG.md)** - per-version diff.
- **[../SECURITY.md](../SECURITY.md)** - vulnerability disclosure policy (use GitHub Security Advisory).
- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** - dev environment, test matrix, hard constraints.
- **[../bench/README.md](../bench/README.md)** - the perf bench harness.
- **[../llms.txt](../llms.txt)** - structured project summary for AI tool indexing.
