# Model Context Protocol (MCP) integration

v0.4.1+ exposes presence's living project model and outcome telemetry as MCP resources. Any MCP-aware client (Claude Desktop, Cursor, Continue, custom agents) can connect and read presence's accumulated context without going through Claude Code-specific hook plumbing.

## What's exposed

Two read-only resources, one per repository the user has touched:

| URI | Content | MIME type |
|---|---|---|
| `presence://<repo_id>/model` | The living `model.md` (Markdown) | `text/markdown` |
| `presence://<repo_id>/telemetry` | Recent commit / revert / verification claims (JSON array) | `application/json` |

`<repo_id>` is the 12-char SHA-256 prefix presence uses to identify the current repo (same as `/presence-status` shows). The MCP server returns whichever repo's state matches the current working directory at the time the client sends the JSON-RPC request.

## How to start the server

```bash
python3 ~/.claude/plugins/presence/lib/cli.py mcp
```

The server reads JSON-RPC messages from stdin, one per line, and writes responses to stdout. It exits when stdin closes. No daemon is involved on the MCP path; the MCP client owns the lifecycle.

### Alternative: PyPI launcher

[`presence-mcp`](https://github.com/sara-star-quant/presence-mcp) is a thin PyPI package that locates the local presence install and runs the command above for you. Install it once, then point every per-client config at a single command name:

```bash
pip install presence-mcp   # or `pipx install presence-mcp`, `uv tool install presence-mcp`
presence-mcp               # equivalent to `python3 ~/.claude/plugins/presence/lib/cli.py mcp`
```

Listed in the official MCP Registry as `io.github.sara-star-quant/presence-mcp`.

## Per-client config

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the equivalent on Windows / Linux:

```json
{
  "mcpServers": {
    "presence": {
      "command": "python3",
      "args": [
        "/Users/<you>/.claude/plugins/presence/lib/cli.py",
        "mcp"
      ]
    }
  }
}
```

Restart Claude Desktop. The two presence resources will appear in the resource picker.

Or with the PyPI launcher installed:

```json
{
  "mcpServers": {
    "presence": {
      "command": "presence-mcp"
    }
  }
}
```

### Cursor

Add to your project's `.cursor/mcp.json` (or the global Cursor MCP settings, depending on your version):

```json
{
  "mcpServers": {
    "presence": {
      "command": "python3",
      "args": ["~/.claude/plugins/presence/lib/cli.py", "mcp"]
    }
  }
}
```

Cursor expands `~` itself; if it doesn't, use the absolute path.

Or with the PyPI launcher installed:

```json
{
  "mcpServers": {
    "presence": {
      "command": "presence-mcp"
    }
  }
}
```

### Continue

In `~/.continue/config.json`:

```json
{
  "models": [...],
  "mcpServers": [
    {
      "name": "presence",
      "command": "python3",
      "args": ["/path/to/presence/lib/cli.py", "mcp"]
    }
  ]
}
```

Or with the PyPI launcher installed:

```json
{
  "mcpServers": [
    {
      "name": "presence",
      "command": "presence-mcp"
    }
  ]
}
```

### Custom JSON-RPC client

The server is a vanilla MCP `2024-11-05` implementation. Send `initialize`, then `resources/list`, then `resources/read` per the [MCP spec](https://modelcontextprotocol.io). Methods other than those three return JSON-RPC error -32601 (method not found).

Example session:

```
> {"jsonrpc":"2.0","id":1,"method":"initialize"}
< {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"resources":{}},"serverInfo":{"name":"presence-mcp","version":"0.1.0"}}}
> {"jsonrpc":"2.0","id":2,"method":"resources/list"}
< {"jsonrpc":"2.0","id":2,"result":{"resources":[...]}}
> {"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"presence://abc123/model"}}
< {"jsonrpc":"2.0","id":3,"result":{"contents":[{"uri":"...","mimeType":"text/markdown","text":"..."}]}}
```

## Working directory matters

The server resolves `<repo_id>` from the current working directory at the time of the request, via `git rev-parse --show-toplevel`. If your MCP client launches the server from a fixed directory (typical for desktop apps), the server only sees that one repo. To see other repos, either:

1. Launch a separate instance per project (set the working directory in the MCP client config), or
2. Pass `cwd` via the MCP client's per-server config field if it has one.

This is a known limitation of the v0.4.1 implementation. A future minor may add an explicit `repo_id` parameter to `resources/read` for clients that want to switch repos without restarting the server.

## What's NOT exposed

- The audit log (`audit.jsonl`). MCP clients shouldn't be able to read or modify presence's tamper-evident chain.
- The events queue (`pending.jsonl`). It's drained on every `UserPromptSubmit` hook fire; reading it through MCP would race the hook system.
- Settings, presets, `MANIFEST.lock`. Read those directly if needed.

## Security posture

- The MCP server runs with the user's own privileges and reads only files under `~/.claude/presence/`. It writes nothing.
- It does not connect to any network. The transport is stdin/stdout.
- Under the `zerotrust` preset, encrypted state files are decrypted on read using the user's keychain key. The MCP client receives plaintext over the local stdio pipe; it never sees the key. Consider this when choosing which clients to grant access.
- The server has no authentication beyond "the calling process can spawn me." If you don't want a particular MCP client to see presence state, don't add presence to that client's MCP config.

## Roadmap

- Future: explicit `repo_id` parameter for cross-repo reads (so a single MCP server instance can serve multiple projects without restart).
- Future: `resources/subscribe` so MCP clients can watch for new commits / revert detections in real time.
