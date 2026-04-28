# presence vs Obsidian, MCP-memory servers, and other context tools

This page exists because the same question keeps coming up: *"Should I use presence, or just wire Claude into my Obsidian vault?"*

Short answer: they do different jobs, they compose well, and the reliability tradeoffs are not where most people expect.

## What presence is (and is not)

presence is a **headless context-continuity layer** for Claude Code. It runs as plugin hooks inside Claude Code itself, auto-captures what Claude actually did during a session (post-tool-use, post-edit, post-bash), and feeds a compact summary back into the next session via the SessionStart hook. There is no UI for browsing the captured state — the surface is the next conversation.

presence is not a knowledge vault, not a notes app, not a sync service. There is no editor, no graph view, no mobile client, no shared-team mode. The state lives in `~/.claude/presence/` as plain files (`model.md`, `events.jsonl`, telemetry JSONL, optional encrypted-at-rest under the zerotrust preset). See [architecture.md](architecture.md) for the data-flow diagram.

## How "Claude + Obsidian" usually works

There are several distinct integration paths, each with different reliability and capture properties:

| Setup | What it is |
|---|---|
| **Obsidian-only, no Claude** | The vault is plain `.md` files in a folder. Local-first; no service in the request path. |
| **Obsidian Sync (paid)** | Hosted service that syncs the vault between machines. The local files remain readable when the sync service is down. |
| **Obsidian + hosted MCP server** (e.g. via Smithery) | Claude calls a remote MCP server which reads/writes your vault contents. The MCP host sees vault contents. |
| **Obsidian + local MCP server** | A process on your machine exposes the vault as MCP tools. No remote service, but the process must stay running. |
| **"Claude reads my vault folder directly"** | No MCP layer; the user manually pastes or references notes in conversation. |

## Comparison axes

These are the axes that actually differ. Rows are the candidate setups; cells are what each path gives you.

| | presence | Obsidian + hosted MCP | Obsidian + local MCP | Vault-with-manual-capture |
|---|---|---|---|---|
| **Backend service in request path** | None | Hosted MCP host | Local MCP process | None |
| **Failure mode when service is down** | N/A — no service | Tool error mid-conversation | Tool error if process not running | None |
| **Capture model** | Auto via PostToolUse hooks | Depends on the MCP server's tools | Depends on the server | Manual: user writes notes |
| **Default network egress** | Zero in v0.5.x; opt-in GitHub release check at v0.6.0+ (off by default; forced off under zerotrust) | Every tool call hits the MCP host | None to MCP, but MCP server may make its own | None |
| **State location** | `~/.claude/presence/` local files | Depends on host | Vault folder (local) | Vault folder (local) |
| **UI for browsing the captured memory** | None (headless) | Typically none | Typically none | Obsidian itself (rich) |
| **Multi-device sync** | Out of scope | Depends on vault sync | Depends on vault sync | Depends on vault sync |
| **Mobile** | No | If MCP host is reachable | No (local process pinned to a machine) | Obsidian Mobile reads the vault |

## Where presence shines

- **No service in the request path.** Hooks run inside Claude Code itself; there is no presence backend to go down. This is the load-bearing claim. Compare to a hosted MCP host — when it is degraded, Claude sees tool errors mid-conversation.
- **Fail-open everywhere.** Every hook is wrapped by `safe_main` (`lib/_common.py`). Any internal failure logs to `~/.claude/presence/logs/errors.log`, increments an error counter that the next SessionStart surfaces, and exits 0 so Claude Code never sees a presence-induced error. Even when presence itself breaks, your conversation continues.
- **Subprocess fallback for the Rust ext.** When the compiled `presence_ext` wheel is missing or stale, `lib/telemetry.py::get_head_commit` and `lib/crypto.py` fall through to plain `git`/`subprocess` paths. Slower, identical behavior. The v0.6.0 doctor cross-check warns once when the wheel is stale; it never blocks.
- **Stdlib-only Python core.** The runtime path has no pip dependencies. `cryptography` is opt-in for the zerotrust at-rest encryption. No MCP server, no daemon, no socket.
- **Auto-capture beats manual-capture for reliability of *what you actually did.*** A manual notes flow only contains what the user remembered to write down. presence's `model.md` and `events.jsonl` accumulate from PostToolUse hooks regardless of whether the user thinks to record anything. This is a coverage win that is independent of the reliability axis above.

See [security.md](security.md) for the threat model and [zerotrust.md](zerotrust.md) for the encrypted-at-rest opt-in.

## Where Obsidian wins

- **Rich UI.** Backlinks, graph view, plugin ecosystem, custom CSS, full-text search across the whole vault. presence has none of those — it is not in that job category.
- **Multi-device sync.** Obsidian Sync (or iCloud/Syncthing/git over the vault) is a solved problem. presence's state is per-machine; cross-machine state is an explicit out-of-scope item in [roadmap.md](roadmap.md).
- **Mobile.** Obsidian Mobile is real and the vault is browseable from a phone. presence does not run on mobile.
- **Long-form note editing and linking.** That is what Obsidian was built for. presence's `model.md` is a working file shaped by automatic compaction — it is not a place to write your knowledge base.

## They compose

Nothing in presence prevents you from also using Obsidian. presence's `model.md` is a plain markdown file at `~/.claude/presence/<repo-id>/model.md`. If you want to surface it inside your vault, you can symlink or include it from a vault file — your call, your vault, no presence-side feature involved.

This page intentionally stops short of recommending a specific integration. The doc establishes the comparison; the integration choice is yours and depends on how your vault is laid out.

## What this doc does NOT do

- Compare against every memory plugin in the ecosystem. The categories above (hosted-MCP, local-MCP, vault-with-manual-capture) capture the reliability shape; vendor-by-vendor comparisons rot fast and invite "you got our feature wrong" issues.
- Mark presence as a "replacement for" anything. It is a different job category from Obsidian.
- Cite specific outage incidents of competitor services. Reliability claims are made structurally — service-in-path vs not — not by counting incidents.
- Recommend a specific Obsidian-presence wiring. Out of scope; that is a user decision.

## See also

- [architecture.md](architecture.md) — data flow that grounds the "no service in path" claim.
- [security.md](security.md) — threat model and zerotrust posture, the substrate for the "default network egress" axis.
- [mcp.md](mcp.md) — presence does ship a read-only MCP server that exposes the captured state to *other* MCP-aware clients (Claude Desktop, Cursor, Continue). That is the one place presence touches the MCP ecosystem; it is read-only and consumes presence's own state, not the other way around.
