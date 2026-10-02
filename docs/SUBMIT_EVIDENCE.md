# Submit evidence

This page describes the normal way to send an `ebus-evidence` result for
cross-installation review.

The intended contribution is a **verified `evidence.zip` bundle**, not a full
raw log.

## 1. Create the bundle

After collecting or importing evidence, run:

```bash
./evidence export
```

This writes and immediately verifies:

```text
data/evidence.zip
```

A successful export ends with:

```text
Status .............. VALID
Deterministic ....... yes
Ready to share.
```

You can verify it again explicitly:

```bash
./evidence verify data/evidence.zip
```

Do not submit a bundle that reports `INVALID`.

## 2. What to submit

Submit exactly:

```text
data/evidence.zip
```

The normal bundle contains the evidence summary, profile and checksums, plus
optional privacy-minimized system identity and context metadata.

The default export does **not** include:

- the complete `ebusd.raw` file;
- local filesystem paths;
- resume checkpoint/device/inode details;
- credentials;
- host/network metadata;
- raw context payloads.

Absolute observation/evidence timestamps are retained intentionally because
timing is part of reproducible protocol evidence.

## 3. Open an Evidence submission issue

Open a new GitHub issue and choose the **Evidence submission** template.

Attach `data/evidence.zip` to the issue by dragging the ZIP into the issue
text area.

Also paste the output of:

```bash
./evidence verify data/evidence.zip
```

Useful optional context:

- system/product model if you know it;
- ebusd environment: Docker, native Linux, or Home Assistant App/Add-on;
- whether the bundle came from live `collect` or static `import`;
- anything unusual that happened during collection.

Do not include IP addresses, usernames, passwords, tokens, Wi-Fi details,
serial numbers or unrelated host configuration.

## 4. Public-sharing reminder

This repository is public.

A ZIP attached to a public GitHub issue should be treated as publicly shared
data. The normal bundle is designed to minimize host/private metadata, but it
still contains protocol observations and absolute timestamps.

If you are not comfortable sharing that information publicly, do not attach the
bundle to a public issue.

## 5. Raw context

For normal community submissions, use the default export:

```bash
./evidence export
```

Do **not** add `--include-context-raw` unless raw context was specifically
requested and you have reviewed it before sharing.

Never attach the complete long-running `ebusd.raw` file just because a normal
evidence bundle has too few matches. A maintainer can ask for a smaller,
reviewed follow-up sample if it is genuinely needed.

## 6. What happens after submission

A submitted bundle can be checked for:

- bundle/checksum validity;
- evidence/profile version;
- observation duration and frame counts;
- passive vs ebusd-initiated observations;
- per-check response/value variants;
- optional hardware/software topology;
- rare context-trigger metadata;
- differences against other installations.

A submission is evidence, not an automatic protocol conclusion.

Observed values are reviewed before they are used to change semantic research
findings or public protocol definitions.

## Minimal contribution flow

```text
install
  -> doctor
  -> collect or import
  -> export
  -> verify
  -> attach data/evidence.zip to an Evidence submission issue
```

Related:

- [Evidence bundle format v1](BUNDLE_FORMAT.md)
- [Community cross-installation test](COMMUNITY_TEST.md)
- [Privacy and troubleshooting](TROUBLESHOOTING.md)
- [System identity](SYSTEM_IDENTITY.md)
