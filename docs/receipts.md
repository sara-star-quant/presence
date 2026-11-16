# Verification receipts (experimental)

A receipt is a small JSON statement, stored as a git note, saying what presence saw run before a commit. It lets a reviewer, CI job or another tool check "did the agent run the tests after its last edit?" without installing presence or trusting the agent's summary.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" receipt --attach      # write the note for HEAD
git push origin refs/notes/presence                              # share it
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" verify-receipt HEAD   # anyone with the repo
```

Sign it so write access to the repo is not enough to forge one:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" receipt --sign-key ~/.ssh/id_ed25519      # attaches and signs
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" verify-receipt HEAD --allowed-signers ~/ci/allowed_signers
```

`allowed_signers` is the ordinary `ssh-keygen` file (`name@example.org ssh-ed25519 AAAA...`). The verifier must supply it from somewhere the repo's writers cannot change: a CI secret, a file on the runner, never a path inside the checkout under test.

The Bash hook records a receipt locally on every successful `git commit`. Nothing touches your repo until you run `--attach`.

## What is in one

`v`, `commit`, `tree`, `ts`, `verified_since_edit`, up to five `evidence` entries (kind, redacted command, time), `tool`, and a SHA-256 `digest` over the rest. Evidence is the test or build commands that passed after the last edit or failed run; see [testing](testing.md) for how a command qualifies (the tool must be in command position and its exit code must describe the run).

`verify-receipt` exits 0 only for `verified`. Other results: `unverified` (an edit or failure came after the last pass), `no_evidence` (presence saw nothing run), `tampered` (digest mismatch), `mismatch` (the note belongs to another commit or tree), `invalid`, `none`.

## Who can forge one

| Attacker | Unsigned | Signed and pinned |
|---|---|---|
| Can write to the repo (stolen token, rogue collaborator) | Forges any receipt | Cannot: needs a pinned key. Editing a note, copying one to another commit, or signing with their own key all end in `untrusted` |
| Deletes the note | `none`, exit 1 | `none`, exit 1; CI should treat a missing receipt as a failure |
| Runs as you on your machine, including the agent | Forges any receipt | Can sign if the key works silently. A hardware key (`ssh-keygen -t ed25519-sk`, signing through `ssh-agent` with a `.pub` path) needs a touch per signature |
| Holds the signing key and the verifier's policy | Forges any receipt | Forges any receipt. No scheme survives this |

A signature proves who vouched for the claim, not that the claim is true: it is still the machine that ran the agent saying what it saw. For proof, have CI re-run the tests on the commit's tree and sign that; the receipt's `tree` field is what lets CI match them up.

## Proof from CI

A signature says who vouched; it does not say the tests passed. For that, CI re-runs them. After every required job passes on a push to main, `ci.yml` signs a subject derived from the commit's tree hash. Anyone with the GitHub CLI can check it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" verify-evidence HEAD --repo sara-star-quant/presence
```

The subject is rebuilt from the tree, so there is nothing to download, and the tree (not the commit hash) is what links this to a receipt: a rebase merge changes the hash and keeps the tree. The verifier insists on the repository's own `ci.yml`, on `refs/heads/main`, on GitHub-hosted runners; without those pins a writer could attest anything from a workflow of their own. What it cannot cover: whoever may merge to main controls what main's workflow does, and an admin merge skips review. It needs network and `gh`.

## What it does not prove

- **It is the working copy's tree, not a record of edits.** Each passing run records the git tree of the working copy it ran on (tracked changes and untracked files, minus ignored ones), and a receipt is `exact` when that tree is the commit's tree. Edits made by a shell command, an MCP tool or a subagent therefore count. A file the tests saw but the commit left out, or an ignored file the tests depended on, makes the tree differ, so the receipt says unverified.
- **Big repositories fall back.** Hashing a working copy takes about 0.1 s for a few thousand files and seconds for tens of thousands. Past a 3 second budget the session stops using trees and the receipt reverts to the order of edit and run events (`exact: false`).
- **Notes are public once pushed.** Commands are redacted, but they still show what you ran (paths, test selectors). Review `git notes --ref=presence show <rev>` before pushing the notes ref to a public remote.
- **Amend and rebase** change the commit hash, so the old receipt stops matching. That is the safe direction.

The format is experimental and not part of the frozen [contract](contract.md); the two CLI commands may change before 1.0.
