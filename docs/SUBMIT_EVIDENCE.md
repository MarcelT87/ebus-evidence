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

This writes the ZIP and immediately verifies both its bundle structure and the
normal public-submission policy:

```text
data/evidence.zip
```

A successful export ends with:

```text
Status .............. VALID
Deterministic ....... yes
Public submission ... PASS

Ready to share.
```

You can run the same strict public-submission check again explicitly if you
want:

```bash
./evidence verify --submission data/evidence.zip
```

For normal public sharing, this is the relevant manual re-check. The generic
`./evidence verify data/evidence.zip` command checks the bundle-v1 structure
without applying the additional public-submission policy.

Do not submit a bundle that reports `INVALID` or
`Public submission ... NOT READY (...)`.

You do **not** need to copy verifier output into the GitHub issue. `export`
already verifies the generated ZIP and checks whether it is ready for the normal
public submission path. Maintainers must still independently verify every public
submission rather than trusting pasted text. Current bundles report
runtime/profile provenance so maintainers can group evidence created by the
same tool/profile bytes.

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

## 3. Get the ZIP onto the device with your browser

`export` prints the absolute local path of the completed ZIP. The path is shown
in your terminal; it is not added to the bundle.

If collection and your browser run on the same computer, select that file in
the upload dialog. If collection runs on a server or inside a container, first
copy **only the generated ZIP** to the computer or phone with your browser.

Use an existing SFTP/file-transfer client: connect to the machine where the
file is stored, navigate to the path printed by `export`, and download
`evidence.zip`. A container path may require accessing that container or its
existing shared directory; the same path need not exist on the host.

If you already use SSH/SCP, run this on your **browser computer**, replacing
the example user, host and path with your own values:

```bash
scp user@server:/path/to/ebus-evidence/data/evidence.zip ./evidence.zip
```

Then select the downloaded `evidence.zip` in GitHub. Do not paste your private
connection details into the issue. No Git commit, repository write access or
GitHub token is needed to attach the file through the issue form.

The tool does not upload automatically or start a file server. If you cannot
reach the file from your browser device, resolve that transfer step before
submitting the issue.

## 4. Open an Evidence submission issue

Open a new GitHub issue and choose the **Evidence submission** form.

The form asks you to:

1. upload `data/evidence.zip` in the required ZIP field;
2. select the ebusd environment;
3. select whether the evidence came from live `collect` or static `import`;
4. optionally add the product/model and unusual collection details;
5. confirm the short privacy checklist.

No verifier-output copy/paste is required.

The upload field accepts ZIP files only. Attach the generated
`data/evidence.zip`, not a renamed full raw log or another archive.

Do not include IP addresses, usernames, passwords, tokens, Wi-Fi details,
serial numbers or unrelated host configuration.

## 5. Public-sharing reminder

This repository is public.

A ZIP attached to a public GitHub issue should be treated as publicly shared
data. The normal bundle is designed to minimize host/private metadata, but it
still contains protocol observations and absolute timestamps.

If you are not comfortable sharing that information publicly, do not attach the
bundle to a public issue.

## 6. Raw context

For normal community submissions, use the default export:

```bash
./evidence export
```

Do **not** add `--include-context-raw` unless raw context was specifically
requested and you have reviewed it before sharing.

Never attach the complete long-running `ebusd.raw` file just because a normal
evidence bundle has too few matches. A maintainer can ask for a smaller,
reviewed follow-up sample if it is genuinely needed.

## 7. What happens after submission

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
  -> export verifies locally
  -> Public submission ... PASS
  -> upload data/evidence.zip in the Evidence submission form
```

Related:

- [Evidence bundle format v1](BUNDLE_FORMAT.md)
- [Community cross-installation test](COMMUNITY_TEST.md)
- [Privacy and troubleshooting](TROUBLESHOOTING.md)
- [System identity](SYSTEM_IDENTITY.md)
