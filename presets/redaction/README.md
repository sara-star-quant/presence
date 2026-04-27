# presets/redaction/

Composable redaction profiles. Each file is a static set of regex patterns that
extends the base secret redactor (`lib/redact.py`) when opted into via
`redact.profiles` in settings.

## Profile JSON schema

```json
{
  "_schema_version": 1,
  "_description": "human-readable description",
  "_disclaimer": "Using this profile does not constitute compliance with ...",
  "_last_reviewed": "YYYY-MM-DD",
  "_review_owner": "name or team (optional)",
  "patterns": [
    {
      "name": "pattern-slug",
      "pattern": "<Python regex source>",
      "kind": "label-used-in-[REDACTED:<kind>]",
      "validator": "luhn",
      "notes": "why this pattern shape was chosen (optional)"
    }
  ]
}
```

Required: `_schema_version`, `_description`, `_disclaimer`, `_last_reviewed`,
`patterns`. Each pattern requires `name`, `pattern`, `kind`. `validator` and
`notes` are optional.

`validator` is a registered post-match check (currently only `luhn` for credit
card numbers). The pattern's regex must match AND the validator must return
`true` for the redaction to fire. Add new validators in `lib/redact.py` under
`_VALIDATORS`.

Unknown top-level keys and unknown pattern keys are ignored. `_schema_version`
greater than the supported version (`SCHEMA_VERSION` in `lib/redact.py`) loads
in compatibility mode (patterns still apply; warning surfaced via
`/presence-doctor`).

## User-authored profiles

Drop JSON files at:

```
~/.claude/presence/presets/redaction/<your-name>.json
```

Then enable in settings:

```json
{
  "preset": "zerotrust",
  "overrides": {
    "redact": {
      "profiles": ["pii-eu", "your-custom"]
    }
  }
}
```

Verify the profile loaded:

```
python3 -m redact --list-profiles
python3 -m redact --show-profile your-custom
python3 -m redact --test-profile your-custom --input sample.txt
```

User-authored profiles in `~/.claude/presence/presets/redaction/` shadow
built-ins of the same name.

## Bar for shipping a built-in profile

To add a new profile to this directory (i.e., into the repo, where it ships to
all users):

1. **Positive + negative test coverage.** Each pattern: at least one realistic
   positive fixture, at least two negative look-alikes (timestamps, IDs, etc.).
   See `tests/test_redact_profiles.py` for the shape.
2. **Domain validation.** If the profile names a regulated framework (HIPAA,
   PCI, etc.), a contributor with relevant domain expertise must validate that
   the patterns match what their organization actually treats as sensitive.
3. **No certification framing.** The profile name describes the *jurisdiction
   or data class*, not the compliance framework. `pii-eu` is fine.
   `gdpr-compliant` is not. `pci-dss` is fine because it names the data class
   (cardholder data). `fedramp` is not, because it implies authorization we do
   not have.
4. **`_disclaimer` is mandatory.** It must say "Using this profile does not
   constitute compliance with X" plainly enough that a reader of the raw JSON
   cannot misinterpret it.

## Profiles shipped today

- `pii-eu.json`: EU IBAN, Dutch BSN, Italian codice fiscale, French INSEE/NIR.
- `pii-us.json`: US SSN, EIN, bank routing.
- `pci-dss.json`: PAN candidates with Luhn validator.

## Profiles deliberately deferred

- `phi-hipaa.json`: needs healthcare domain review.
- `cui-us-gov.json`: needs federal-contractor domain review.

PRs from contributors with relevant domain expertise are welcome.

## Why no compliance-framework presets

`presence` is a stdlib-only Claude Code plugin. It has no audit body, no ATO,
no formal compliance attestation. A preset named `fedramp` or `hipaa` would
imply otherwise. See `docs/compliance.md` for the long form.
