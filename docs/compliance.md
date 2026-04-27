# Compliance: honest scope

This document is a written-down map of what `presence` does and does not do that's
relevant to deployments in regulated environments (EU GDPR, US healthcare, US gov
contractors, payment processors). It exists because users have asked, and because
the wrong answer here would be misleading.

**Read this if you operate in a regulated environment and want to know what
presence helps with versus what you still have to build yourself.**

## What presence does

Local technical primitives that exist today (v0.5.0+):

- **Local-only state.** Default presets make zero outbound network calls. State
  lives at `~/.claude/presence/` with `0o700` directory perms / `0o600` file
  perms. See `docs/security.md` (T2: data exfiltration).
- **AES-GCM encryption at rest under `zerotrust`.** The data key is wrapped by
  an OS-keychain-stored key (macOS Keychain or Linux Secret Service). See
  `docs/zerotrust.md`.
- **Tamper-evident audit log.** Every state-mutating operation under `zerotrust`
  appends to `audit.jsonl` with a per-line SHA-256 hash chain. Mutation, removal,
  or reordering is detectable via `python3 lib/integrity.py --audit-verify`.
- **Fail-closed integrity check at SessionStart.** A missing or mutated plugin
  file (against `MANIFEST.lock`) blocks all hooks for the session and writes the
  blocking event to the audit log.
- **Composable redaction profiles.** Jurisdiction-relevant patterns (PII-EU,
  PII-US, PCI-DSS) opt-in via `redact.profiles` in settings. PCI-DSS gates PAN
  matches with a Luhn validator so non-PAN 16-digit strings pass through.

## What presence does NOT do

- **No certification.** presence is not FedRAMP-authorized. Not FIPS 140-3
  validated. Not ISO 27001 certified. Not SOC 2 attested. Not PCI DSS assessed.
  Not HIPAA "compliant" (compliance is an organizational property, not a
  software property).
- **No ATO.** No Authority To Operate from any agency, public or private.
- **Not legal, security, or compliance advice.** This document does not
  substitute for review by your own counsel, security team, or compliance
  officer.
- **A redaction profile name does NOT imply compliance with a framework.**
  `pii-eu.json` does not mean "GDPR-compliant." `pci-dss.json` does not mean
  "PCI-compliant." Each profile only redacts patterns commonly considered
  sensitive in the named jurisdiction. The profile JSON files themselves carry a
  `_disclaimer` field stating this, repeated so that anyone reading the raw JSON
  sees it.
- **No "compliance dashboard" or "audit report" feature.** The combination of
  `audit.jsonl` + `lib/integrity.py --audit-verify` produces tamper-evident
  records. Use those as one input to your own attestation tooling, not as a
  substitute.

## Recommended posture for regulated workloads

1. **Use the `zerotrust` preset.** This is the strict-by-default option:
   AES-GCM at rest, audit log, fail-closed integrity, aggressive secret
   redaction, no network egress.
2. **Add the redaction profiles relevant to your jurisdiction(s).** Edit
   `~/.claude/presence/settings.json`:

   ```json
   {
     "preset": "zerotrust",
     "overrides": {
       "redact": {
         "profiles": ["pii-eu", "pci-dss"]
       }
     }
   }
   ```

   Verify with `/presence-doctor` (the report shows active profiles + load
   status) or `python3 -m redact --list-profiles`.

3. **Have your own security team review presence's source.** It's stdlib-only
   Python 3.12+ (a few thousand lines). Reviewable. The Rust extension under
   `ext/` is optional and provides a perf optimization only.
4. **Treat the audit log as one input to your own attestation tooling.** It is
   not a finished compliance artifact.
5. **Add custom redaction patterns for anything jurisdiction-specific that the
   shipped profiles miss.** Drop a JSON file into
   `~/.claude/presence/presets/redaction/<your-name>.json` and add it to the
   `redact.profiles` list. See `presets/redaction/README.md` for the schema.

## Profiles shipped in v0.5.0

- `pii-eu.json`: EU IBAN, Dutch BSN (with prefix), Italian codice fiscale,
  French INSEE/NIR (with prefix).
- `pii-us.json`: US SSN (with hyphens), US EIN (with prefix), US bank routing
  (with prefix).
- `pci-dss.json`: PAN candidates 13-19 digits gated by Luhn validator.

## Profiles deliberately NOT shipped

- `phi-hipaa.json` (NPI, MRN, ICD codes near patient identifiers): defers until
  domain validation by a healthcare contributor.
- `cui-us-gov.json` (CUI markings, classification handling): defers until
  validation by a federal-contractor contributor.
- Any profile named after a compliance framework (`fedramp`, `hipaa`, `us-gov`,
  `cmmc`, etc.). Such names imply certification we do not have.

## Pointers

- `docs/security.md`: T1-T12 threat model.
- `docs/zerotrust.md`: zerotrust preset internals.
- `presets/redaction/README.md`: how to author custom profiles.
- `lib/integrity.py --audit-verify`: walk the audit chain.
- `lib/redact.py` (or `python3 -m redact --help`): inspect / test profiles.
