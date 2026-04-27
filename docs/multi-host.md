# Multi-host: AGENTS.md adapter (v0.4.2+)

presence runs as a Claude Code plugin. v0.4.2 lets it project its accumulated knowledge into other AI coding tools without porting the whole hook system to each one.

The mechanism: when Claude Code's `SessionStart` hook fires, presence refreshes a delimited section of `<repo_root>/AGENTS.md`. The next time the user opens **any AGENTS.md-aware tool** in the same repo (Codex, Cursor, Gemini CLI, Windsurf, GitHub Copilot, etc.), that tool reads the refreshed AGENTS.md as part of its first-turn context.

## Hosts that read AGENTS.md (verified 2026-04)

Per the [OpenAI Codex AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md) and [agents.md](https://agents.md/), AGENTS.md is now an **open standard** under the Agentic AI Foundation (Linux Foundation directed fund). Tools that read it:

- **OpenAI Codex CLI** (the format's origin)
- **Cursor** (legacy `.cursorrules` is being replaced; `.cursor/rules/*.mdc` is the new way; AGENTS.md works as a fallback)
- **Gemini CLI** (also reads its preferred `GEMINI.md`; AGENTS.md works as a fallback per Google's docs)
- **Windsurf** (Cascade)
- **GitHub Copilot** (in IDEs that support it)
- **Many community tools** following the open standard

This is why v0.4.2 ships **one** adapter rather than five.

## Quickstart

In your shell, when running a Claude Code session in a repo:

```bash
PRESENCE_HOST=agents-md
```

Set this env var before opening Claude Code. From then on, every Claude Code session refreshes `<repo>/AGENTS.md` with presence's living model + telemetry digest. When you later open Codex / Cursor / Gemini / Windsurf in the same repo, they pick it up automatically.

To make it permanent in your shell:

```bash
echo 'export PRESENCE_HOST=agents-md' >> ~/.zshrc   # or ~/.bashrc
```

## Filename override

Some tools prefer their own filename (`GEMINI.md` for Gemini CLI's primary file, `.cursor/rules/presence.mdc` for Cursor's new rules format). Override:

```bash
PRESENCE_AGENTS_MD_FILENAME=GEMINI.md
# or
PRESENCE_AGENTS_MD_FILENAME=.cursor/rules/presence.mdc
```

Subdirectory paths work; the adapter creates the parent directories. Defaults to `AGENTS.md` when unset.

## File contract: how presence behaves inside YOUR file

presence is a guest in `AGENTS.md`. It writes only to a delimited section:

```markdown
<!-- presence:start -->
<!-- This block is managed by presence (https://github.com/sara-star-quant/presence). -->
<!-- It refreshes at the start of each Claude Code session. Edit outside the markers. -->

<presence_context>
<project_model>
... (presence's living model)
</project_model>
<telemetry_digest>
... (recent commits, reverts, verification claims)
</telemetry_digest>
</presence_context>

<!-- presence:end -->
```

Everything outside the markers is **left exactly as you wrote it**. The adapter is idempotent: refreshing twice with the same content produces the same file. Refreshing with new content replaces only the section between the markers.

If `AGENTS.md` does not exist, the adapter creates it containing only the presence section. If you'd rather not have presence write the file at all, just don't set `PRESENCE_HOST=agents-md`.

## When does the refresh happen?

Only on Claude Code's `SessionStart` event. Other hooks (`UserPromptSubmit`, `PostToolUse`, `Stop`) are ignored by this adapter to avoid writing-on-every-keystroke noise. The freshest model + telemetry digest is assembled at SessionStart anyway.

If you want manual control, run `/presence-status` (no auto-refresh) or `/presence-doctor` (diagnostic only). Neither writes to AGENTS.md.

## Should I commit AGENTS.md?

That's a workflow choice, not a presence opinion:

- **Commit it**: your team gets the same AI context. Each team member's presence will refresh the section on their own machine, so the section's *content* will diff between commits (presence-managed). User-authored content stays stable across machines.
- **`.gitignore` it**: AGENTS.md becomes per-developer. Useful when each contributor's presence-tracked telemetry differs and you don't want diff noise.
- **Hybrid**: commit a hand-authored AGENTS.md with your team's conventions outside the markers; `.gitignore` is wrong here, but consider using `git update-index --skip-worktree AGENTS.md` to track the user-content version while ignoring the presence-managed section's churn.

The tradeoffs are the same as for any auto-generated file in version control. presence has no preference.

## Recognized PRESENCE_HOST values

| Value | Adapter | What it does |
|---|---|---|
| `claude` (default) | `ClaudeAdapter` | Emits Claude Code's `hookSpecificOutput` JSON. The hook protocol presence has used since v0.1. |
| `agents-md` (and `agents_md`, `agents`) | `AgentsMdAdapter` | Refresh `<repo>/AGENTS.md` (or `$PRESENCE_AGENTS_MD_FILENAME`) on SessionStart. v0.4.2+. |
| `generic` | `GenericAdapter` | Plain-text stdout. Useful for debugging presence outside Claude Code. |
| anything else | falls through to `ClaudeAdapter` | Safe default; presence's "never break a hook" stance. |

## What's NOT shipping in v0.4.2

- **Per-tool adapters** (Cursor / Gemini / Codex separate classes): unnecessary because AGENTS.md serves all of them. The single override `PRESENCE_AGENTS_MD_FILENAME` covers users who want the tool-specific filename.
- **Live MCP integration**: that's v0.4.1 (`docs/mcp.md`). MCP-aware tools (Claude Desktop, Cursor, Continue) can use the MCP server for live reads instead of, or in addition to, the AGENTS.md refresh.
- **ACP** (Agent Client Protocol from Zed): chat-session control, distinct from AGENTS.md's "give me context." Tracked as v0.4.3 / v0.5.0.
- **`clawbot` adapter**: this tool is not publicly documented in any source verified at the time of v0.4.2; if support is needed, file an issue with a pointer to the spec and we'll add a v0.4.3 patch.

## Compared to MCP (v0.4.1)

| | MCP server (v0.4.1) | AGENTS.md adapter (v0.4.2) |
|---|---|---|
| **Direction** | Client pulls from presence | presence pushes to file |
| **Freshness** | Live (read on each MCP request) | Refreshed on Claude Code SessionStart |
| **Tool support** | Claude Desktop, Cursor, Continue, others with MCP support | Codex, Cursor, Gemini, Windsurf, Copilot, others reading AGENTS.md |
| **Setup** | Per-client MCP config (one entry per tool) | One env var (`PRESENCE_HOST=agents-md`) |
| **Disk writes** | None | One file per repo, only on SessionStart |
| **Use both?** | Yes, they're independent and serve different tools |

Most users will pick one or the other. Power users with multiple AI tools open simultaneously can run both.

## See also

- [`mcp.md`](mcp.md) - MCP server (v0.4.1)
- [`recipes.md`](recipes.md) - common preset customizations
- [`architecture.md`](architecture.md) - the adapter seam in context
