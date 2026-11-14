# presence docs

A map of what lives where. New users start with the [README](../README.md); this index is for finding something specific.

## Understand it

- **[architecture.md](architecture.md)** - how the pieces fit together: hooks, state layout, the XML context schema, how presets compose. Read this to understand or extend the runtime.
- **[glossary.md](glossary.md)** - the terms presence uses (living model, calibrated confidence, integrity manifest, etc.).
- **[positioning.md](positioning.md)** - presence versus Obsidian, MCP-memory servers, and other context tools, and why they compose. Read this when evaluating it against an existing setup.

## Use it

- **[recipes.md](recipes.md)** - common preset customizations as copy-paste snippets ("warn-only commit gate", "longer transcript scan", "back up my state", etc.).
- **[mcp.md](mcp.md)** - exposes the living model and telemetry as MCP resources for Claude Desktop, Cursor, Continue, and other MCP clients.
- **[multi-host.md](multi-host.md)** - the AGENTS.md adapter: one env var lets Codex, Cursor, Gemini CLI, Windsurf, GitHub Copilot, and others read presence's accumulated context.

## Security and compliance

- **[security.md](security.md)** - threat model (T1 to T12), the test that pins each claim, and what is explicitly out of scope. Read this before relying on the Zero-Trust properties for anything serious.
- **[zerotrust.md](zerotrust.md)** - the opt-in `zerotrust` preset: AES-GCM at rest, hash-chained audit log, fail-closed integrity, settings immutability, and moving state between machines.
- **[compliance.md](compliance.md)** - honest scope for regulated workloads: what presence does, what it does not, the composable redaction profiles, and why no compliance-framework presets ship.

## Project status and quality

- **[contract.md](contract.md)** - the stability promise: what never breaks (preset keys, hook surface, CLI, state layout), the removal policy, and what is not covered.
- **[testing.md](testing.md)** - what runs, what each layer catches, how fuzzing works, and what is not covered.
- **[v1-readiness.md](v1-readiness.md)** - the gaps between presence and 1.0: evidence, why each blocks, exit criteria, and a suggested order.
- **[roadmap.md](roadmap.md)** - what we decided to defer and why (native Windows, ACP, universal install). Each item has a tracking issue with the same title.

## See also

- **[../README.md](../README.md)** - install, status, security model, presets.
- **[../CHANGELOG.md](../CHANGELOG.md)** - per-version diff.
- **[../SECURITY.md](../SECURITY.md)** - vulnerability disclosure policy (use GitHub Security Advisory) and how to verify release binaries.
- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** - dev environment, test matrix, hard constraints.
- **[../GOVERNANCE.md](../GOVERNANCE.md)** - maintainership and the continuity plan.
- **[../bench/README.md](../bench/README.md)** - the perf bench harness.
- **[../llms.txt](../llms.txt)** - structured project summary for AI tool indexing.
