# Security policy

`ebus-evidence` processes local raw-log data and may receive evidence bundles
from untrusted contributors. Security and privacy reports are welcome.

## Supported version

Until the first tagged release, security fixes target the current `main`
branch. After releases begin, this policy will be updated with an explicit
supported-version table.

## Reporting a vulnerability

Do **not** publish sensitive vulnerability details, credentials, private raw
logs or host information in a normal GitHub issue.

Prefer GitHub's private vulnerability reporting for this repository when it is
available from the repository **Security** tab.

If private vulnerability reporting is not available, open a minimal public
issue stating only that you need a private security contact. Do not include
exploit details, evidence bundles, raw logs, credentials or private system
information in that issue.

## Evidence attachments are untrusted input

A submitted `evidence.zip` is data supplied by another person. Maintainers
must treat it as untrusted even when it passes structural verification.

The verifier is designed to:

- inspect ZIP members without extracting them to arbitrary filesystem paths;
- reject unsafe or unexpected member paths;
- reject duplicate/unexpected members;
- bound archive member count and uncompressed size;
- validate checksums, schemas, profile alignment and privacy-related structure.

A `VALID` result means that the bundle is structurally consistent with the
supported evidence format. It is **not** proof of contributor identity,
authenticity, hardware ownership or semantic correctness.

Do not manually execute files from an evidence submission.

## Project safety boundary

Security fixes must preserve the project's passive/read-only boundary:

- no direct eBUS adapter access;
- no bus writes or telegram injection;
- no active probing solely to create evidence;
- no automatic control of a heating system.
