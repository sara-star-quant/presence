# Verification receipts (experimental)

A receipt is a small JSON statement, stored as a git note, saying what presence saw run before a commit. It lets a reviewer, CI job or another tool check "did the agent run the tests after its last edit?" without installing presence or trusting the agent's summary.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" receipt --attach      # write the note for HEAD
git push origin refs/notes/presence                              # share it
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" verify-receipt HEAD   # anyone with the repo
```

The Bash hook records a receipt locally on every successful `git commit`. Nothing touches your repo until you run `--attach`.

## What is in one

`v`, `commit`, `tree`, `ts`, `verified_since_edit`, up to five `evidence` entries (kind, redacted command, time), `tool`, and a SHA-256 `digest` over the rest. Evidence is the test or build commands that passed after the last edit or failed run; see [testing](testing.md) for how a command qualifies (the tool must be in command position and its exit code must describe the run).

`verify-receipt` exits 0 only for `verified`. Other results: `unverified` (an edit or failure came after the last pass), `no_evidence` (presence saw nothing run), `tampered` (digest mismatch), `mismatch` (the note belongs to another commit or tree), `invalid`, `none`.

## What it does not prove

- **Not signed.** The digest catches a note edited afterwards and a note copied onto another commit. Anyone who can write to the repo can still forge a whole receipt. A receipt is the machine's own claim, not an independent witness. Signing and a witnessed audit head are on the [roadmap](roadmap.md).
- **Only what the hooks saw.** Edits made through shell redirection, MCP tools or subagents are invisible, so `verified_since_edit` can be wrong in both directions.
- **Any passing test counts.** There is no link yet between the edited files and the tests that ran.
- **Notes are public once pushed.** Commands are redacted, but they still show what you ran (paths, test selectors). Review `git notes --ref=presence show <rev>` before pushing the notes ref to a public remote.
- **Amend and rebase** change the commit hash, so the old receipt stops matching. That is the safe direction.

The format is experimental and not part of the frozen [contract](contract.md); the two CLI commands may change before 1.0.
