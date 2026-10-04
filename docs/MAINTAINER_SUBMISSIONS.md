# Reviewing public evidence submissions

Public evidence attachments are **untrusted input** even when they were produced
by someone using this project.

This guide is for maintainers reviewing an `evidence.zip` attached to a public
Evidence submission issue.

## Safe review flow

1. Download the attachment into a dedicated local quarantine/staging directory.
2. Keep the original ZIP unchanged.
3. Do not double-click, execute or manually extract archive members.
4. Compute/retain the complete ZIP SHA-256 for provenance.
5. Run the strict submission verifier from a trusted checkout/install:

```bash
./evidence verify --submission /path/to/quarantine/evidence.zip
```

6. Continue to research/import review only when the command reports:

```text
Status: VALID
Submission policy: PASS
```

A rejected file should stay outside normal Analyzer/research data stores unless
you are deliberately investigating the rejection.

## What the strict gate adds

The ordinary verifier checks the public bundle-v1 structure.

The submission policy additionally rejects normal public contributions with:

- archives above the public size limits;
- excessive member count or uncompressed size;
- non-DEFLATE or encrypted ZIP members;
- raw context members;
- missing evidence state;
- legacy/missing provenance;
- non-deterministic repacking;
- no observed evidence;
- a profile that does not exactly match a trusted bundled profile.

The trusted-profile comparison happens during preflight, before the generic
bundle verifier parses the submitted profile YAML.

## What PASS does not prove

A passing submission is still contributor-supplied evidence.

It does **not** prove:

- who created it;
- that the observations came from the claimed physical installation;
- that values have the semantic interpretation proposed by the contributor;
- that the contributor used an official binary.

Keep structural acceptance and protocol interpretation separate.

## Never do this

Do not:

- run files from the ZIP;
- manually extract an unverified ZIP into a project/runtime directory;
- commit submitted ZIPs or raw logs to this repository;
- copy an unverified attachment directly into Analyzer data;
- treat a contributor-provided `VALID` screenshot/text as verification.

Always verify the actual downloaded ZIP with your own trusted tool.
