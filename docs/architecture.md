# presence: architecture

## Pillars and mechanisms

| Pillar | Hook / component | Behavior |
|---|---|---|
| Living project model | `SessionStart` | Loads `~/.claude/presence/projects/<repo-id>/model.md` into context at session start, truncated to a token budget. The `model-curator` agent compresses raw observations on demand via `/presence-curate`. |
| Outcome telemetry | `PostToolUse(Bash)` + `SessionStart` | Detects `git commit`, `git push`, `gh pr create` via `cmdparse` (shlex-based, not regex) and records SHA + Claude's stated intent into `~/.claude/presence/telemetry/claims.jsonl`. On the next session start, scans `git log` since `last_seen` for revert commits touching tracked SHAs and surfaces a digest. |
| Event digest | `PostToolUse(Edit/Write)` + `PostToolUse(Bash)` + `UserPromptSubmit` | Edits and bash command results (with classification: `test_pass`/`test_fail`/`build_pass`/`build_fail` for ~17 known commands) are appended to `~/.claude/presence/events/<repo-id>/pending.jsonl`. `SessionStart` and `UserPromptSubmit` drain (read + truncate) and inject a digest as `additionalContext`. |
| Calibrated confidence | `Stop` + `PreToolUse(Bash)` | `Stop` parses the final assistant message for unhedged success claims and cross-references the event log. If no test/build pass since the most recent edit, logs to `confidence.jsonl`. In strict presets (`enterprise-strict`, `zerotrust`), emits `{"decision":"block","reason":...}` to re-prompt the model; in default presets, just records and surfaces via the warning counter at the next `SessionStart`. `PreToolUse(Bash)` on `git commit`/`push` consults the same evidence, with mode determined by `confidence.commit_gate` (`off`/`warn`/`ask`/`block`). |

## State layout

State lives **outside** the project repo to avoid polluting team workspaces:

```
~/.claude/presence/
|-- settings.json                       # active preset name + overrides
|-- presets/                            # user-defined presets (optional)
|-- projects/<repo-id>/
|   |-- model.md                        # living architecture + conventions notes
|   `-- last_seen                       # unix ts of last SessionStart in this repo
|-- telemetry/
|   |-- claims.jsonl                    # what Claude committed, per SHA
|   |-- outcomes.jsonl                  # detected reverts touching tracked SHAs
|   `-- confidence.jsonl                # stated confidence vs verification evidence
|-- events/<repo-id>/
|   `-- pending.jsonl                   # events accumulated since last drain
`-- logs/
    |-- errors.log                      # tracebacks from safe_main wrapper
    |-- warnings.log                    # structured non-fatal warnings
    |-- error_count                     # counter (read + reset by SessionStart)
    `-- warning_count                   # counter (read + reset by SessionStart)
```

`<repo-id>` is `sha256(git_remote_url || abspath(repo_root))[:12]`. Computed via `git rev-parse --show-toplevel`, falling back to the cwd hash for non-git directories.

## Hook flow per session

```
SessionStart
  |-- surface error/warning counters (if non-zero) and reset them
  |-- load model.md (truncated to model.max_tokens * 4 chars)
  |-- scan git log since last_seen for revert commits touching tracked SHAs
  |-- drain pending events into a digest
  `-- emit additionalContext with the assembled summary

[user types prompt]
  UserPromptSubmit
    |-- drain pending events (if any accumulated since SessionStart)
    `-- emit additionalContext with the digest (if non-empty)

[Claude works ...]
  PostToolUse(Edit|Write|MultiEdit)
    `-- append {ts, kind: "edit", tool, path} to pending.jsonl

  PostToolUse(Bash)
    |-- append {ts, kind: "bash", cmd (redacted), exit} to pending.jsonl
    |-- classify cmd via verify.classify_command (returns test_pass/build_fail/...)
    |       and append a typed event if it matched
    |-- if cmd parses as `git commit` (via cmdparse, not regex):
    |       parse SHA from tool_response.stdout, record claim
    `-- if cmd parses as `git push` or `gh pr create`: record push claim

  PreToolUse(Bash)
    `-- if cmd parses as `git commit` or `git push`:
         |-- check: any test_pass/build_pass since the most recent edit?
         `-- if no, behavior depends on confidence.commit_gate:
              - "off"   : do nothing
              - "warn"  : emit additionalContext advisory; allow
              - "ask"   : emit permissionDecision="ask" with reason
              - "block" : emit permissionDecision="deny" with reason

Stop
  |-- tail-read transcript (last 256 KiB) for the last assistant message
  |-- if it contains an unhedged success claim AND there's been a recent edit:
  |       - log to confidence.jsonl
  |       - if confidence.stop_action == "block": emit {"decision":"block","reason":...}
  |       - else: warn(unverified_success_claim) and let SessionStart surface it
  `-- update last_seen for next session
```

## Customization

`~/.claude/presence/settings.json`:

```json
{
  "preset": "solo-dev",
  "overrides": {
    "model.max_tokens": 4000,
    "telemetry.gh_pr_check": false,
    "confidence.commit_gate": "warn"
  }
}
```

Dotted-path overrides walk N levels (`a.b.c = v` creates nested dicts). Built-in presets live in the plugin at `presets/*.json`. User presets live in `~/.claude/presence/presets/*.json` and override built-ins by name.

## Failure modes

Every hook entry point is wrapped in `safe_main`. On any exception:

- The traceback is appended to `logs/errors.log` (size-rotated at 1 MB).
- An error counter is incremented; `SessionStart` surfaces the count to the user as `additionalContext` and resets it.
- The hook exits 0 so Claude Code never sees the failure.

State writes are atomic (write-temp + rename). State reads on missing files return empty. Reads on corrupt files emit a structured warning (via `warnings_log.warn`) and skip the bad lines.

## What presence does NOT do

- Does not modify your repo (all state lives outside it)
- Does not upload anything (no analytics, no error reporting)
- Does not call external services except optional `gh` for PR status (off by default; opt-in per preset; disabled in `zerotrust`)
- Does not change Claude's tools or auto-approve any actions
- Does not import or execute any code from the user's workspace
