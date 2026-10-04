# Evidence bundle format v1

This document describes the public interchange contract produced and verified by
the current `ebus-evidence` bundle implementation.

The format identifier is:

```text
ebus-evidence-bundle-v1
```

This document is intended for reviewers and independent consumers such as
research tooling. It does not require consumers to import or depend on the
`ebus-evidence` Python package.

## Scope

A normal bundle is a ZIP archive containing a small, allowlisted set of members:

```text
manifest.json
profile.yaml
checksums.json
evidence/state.json        optional
system.json                optional
contexts/*.json            optional
contexts/*.raw             optional, explicit opt-in only
```

No other member names are accepted by the v1 verifier.

The default `./evidence export` path excludes `contexts/*.raw`.

## Trust model

A bundle that verifies as `VALID` proves that:

- the ZIP structure is accepted by the v1 verifier;
- required members and the schema checks implemented by that verifier pass;
- every member covered by `checksums.json` matches its recorded SHA-256;
- the cross-member invariants checked by the verifier are consistent;
- the verifier's path-safety checks pass;
- the manifest contains the privacy declarations required by bundle v1.

`VALID` does **not** prove who created the bundle and is not a cryptographic
signature of the submitting person, installation or official repository build.

It also does **not** perform a generic secret/IP/path scan across every arbitrary
text value in the archive. The official exporter minimizes shareable data by
construction and several typed members use strict allowlists, but a manually
constructed conforming bundle must still be treated as untrusted submitted
content.

A technically capable third party can construct a conforming bundle. The
provenance fields described below do not change that trust model: they identify
the runtime/profile claimed by the bundle, but they do not authenticate the
submitter or attest an official build.

Consumers must therefore treat a valid bundle as **integrity-checked submitted
evidence**, not as automatically trusted protocol truth. Semantic conclusions
remain a separate review step.

## ZIP safety and limits

The v1 verifier rejects:

- an empty ZIP;
- more than 10,000 members;
- total uncompressed content above 512 MiB;
- duplicate member names;
- directory entries;
- absolute paths;
- backslash-based paths;
- any member path containing `..`;
- unknown members outside the allowlist above.

The verifier also checks that context raw-file references are safe filenames and
cannot traverse outside the `contexts/` namespace.

## Deterministic layout

Bundles created by the current exporter use:

- member names sorted lexicographically;
- a fixed ZIP timestamp of `1980-01-01 00:00:00`;
- DEFLATE compression;
- canonical JSON/YAML serialization for generated members.

The verifier reports whether this deterministic layout is present, including
that every member uses DEFLATE compression.

A repacked archive can still be structurally and cryptographically valid while
reporting:

```text
Deterministic layout: no
```

Deterministic layout is therefore a reproducibility property, not the member
integrity check itself.

## `manifest.json`

Current v1 manifest shape:

```json
{
  "format": "ebus-evidence-bundle-v1",
  "tool_version": "0.1.0.dev0",
  "profile": "hw5103-open-evidence",
  "profile_version": 2,
  "provenance": {
    "tool_runtime": {
      "algorithm": "ebus-evidence-runtime-sha256-v1",
      "sha256": "<64 lowercase hex characters>"
    },
    "profile_sha256": "<64 lowercase hex characters>",
    "git": {
      "commit": "<40 or 64 lowercase hex characters>",
      "dirty": false
    }
  },
  "evidence_state_included": true,
  "system_identity_included": false,
  "context_metadata_count": 0,
  "context_raw_count": 0,
  "context_raw_included": false,
  "privacy": {
    "absolute_paths_included": false,
    "resume_checkpoint_included": false,
    "host_metadata_included": false,
    "credentials_included": false,
    "full_raw_log_included": false,
    "absolute_timestamps_included": true,
    "context_raw_may_contain_device_specific_bus_data": false,
    "review_context_raw_before_public_sharing": false
  }
}
```

The verifier requires the manifest profile name/version to match
`profile.yaml`.

For backward compatibility, older bundle-v1 manifests may omit
`privacy.absolute_timestamps_included`. Current bundles explicitly set it to
`true`.

Older bundle-v1 manifests may also omit `provenance`. Current exporters include
it.

### Provenance

Current provenance records:

- `tool_runtime.sha256` — a deterministic SHA-256 fingerprint of the installed
  `ebus_evidence` runtime package;
- `profile_sha256` — SHA-256 of the exact canonical `profile.yaml` bytes
  embedded in the bundle;
- `git.commit` and `git.dirty` — optional source-checkout information only
  when the running package directory is exactly the checkout's
  `src/ebus_evidence` directory.

The runtime hash algorithm identifier is:

```text
ebus-evidence-runtime-sha256-v1
```

It hashes the algorithm identifier followed by all regular `.py`, `.yaml`
and `.yml` files below the installed `ebus_evidence` package directory in
lexicographic relative-path order. Each file contributes its relative path,
byte length and exact bytes using NUL separators.

This deliberately excludes host paths, timestamps, usernames and machine
identity, so provenance does not make otherwise deterministic bundles depend on
local environment details.

`git` is `null` when Git metadata cannot be determined safely, including
non-editable/wheel-style installs even when their virtual environment happens to
live inside a Git repository. This avoids attaching an unrelated or stale outer
checkout revision to installed runtime bytes.

A missing Git record does not make the bundle invalid because the runtime and
profile hashes remain available.

The verifier validates provenance syntax and requires
`provenance.profile_sha256` to equal the checksum of the embedded
`profile.yaml`.

The verifier cannot prove that a submitter did not manually forge provenance.
These fields are reproducibility/grouping metadata, not a signature or remote
attestation.

## `checksums.json`

Shape:

```json
{
  "sha256": {
    "manifest.json": "<64 lowercase hex characters>",
    "profile.yaml": "<64 lowercase hex characters>",
    "evidence/state.json": "<64 lowercase hex characters>"
  }
}
```

The exact keys depend on the members present.

Requirements:

- every ZIP member except `checksums.json` must appear exactly once in the
  SHA-256 mapping;
- no extra checksum entries are allowed;
- digests are lowercase 64-character SHA-256 hex strings;
- every recorded digest must match the member bytes.

`checksums.json` intentionally does not hash itself.

The SHA-256 printed by `./evidence verify` is a separate digest of the complete
ZIP file.

## `profile.yaml`

The complete profile used to create the evidence is embedded in the bundle.

At minimum, a valid profile contains:

```yaml
name: profile-name
version: 1
checks:
  - id: check-id
    match:
      source: "f1"
      target: "08"
      pbsb: "b509"
```

Check IDs must be unique.

Profiles may also contain decoding and context-trigger definitions supported by
the current profile loader.

Consumers should use the embedded profile as the definition of what was being
observed, rather than assuming that their locally installed current profile is
identical.

## `evidence/state.json`

When present, the format identifier is:

```text
ebus-evidence-shared-state-v1
```

Top-level shape:

```json
{
  "format": "ebus-evidence-shared-state-v1",
  "profile": "hw5103-open-evidence",
  "profile_version": 3,
  "profile_fingerprint": "<64 lowercase hex characters>",
  "created_at": "...",
  "updated_at": "...",
  "total_events": 0,
  "observation": {},
  "epochs": [],
  "continuity_reset_count": 0,
  "checks": {}
}
```

The shared state deliberately excludes local resume data.

The verifier rejects shared state containing these local-only fields anywhere in
the shared document:

```text
checkpoint
device
inode
offset
anchor_start
anchor_sha256
```

### Observation epochs and profile rollover

Current shared-state v1 may contain an `epochs` array.

Each entry is a completed historical observation from an older version of the
**same profile name**:

```json
{
  "profile": "hw5103-open-evidence",
  "profile_version": 2,
  "profile_fingerprint": "<64 lowercase hex characters or null for legacy state>",
  "created_at": "...",
  "updated_at": "...",
  "ended_at": "...",
  "total_events": 123,
  "observation": {},
  "checks": {}
}
```

Epoch versions are strictly increasing and must be lower than the active
top-level `profile_version`.

Coverage interpretation is deliberately epoch-scoped:

- the top-level `observation` applies only to checks in the active profile;
- a historical epoch's `observation` applies only to the checks stored in that
  epoch;
- a check introduced in profile v3 must **not** be treated as observed during a
  v2 epoch.

On a local profile-version rollover, the raw-log checkpoint remains local and is
preserved for resume, but it is never exported. The active epoch starts at zero
frames and continues from that checkpoint without replaying earlier traffic.

Bundle creation may also preview a forward rollover entirely in memory when the
local state still belongs to an older profile version. This read-only preview
produces the same historical/current epoch separation without modifying the
local state; a later collector/watch writer persists the rollover.

The rollover boundary timestamp is derived from the completed state's last
persisted `updated_at`, not from the wall clock at export time. This keeps
repeated read-only rollover previews deterministic. Coverage is determined by
the epoch's observation counters/timestamps, not merely by `created_at` or
`ended_at`.

`profile_fingerprint` hashes profile behavior while ignoring presentation-only
descriptions. Current local state uses it to reject silent semantic changes
without a profile-version bump. Historical legacy epochs may have a null
fingerprint when they were created before fingerprint tracking existed.

Older bundle-v1 shared states may omit both `profile_fingerprint` and
`epochs`; the current verifier accepts them as legacy state.

### Observation object

Current shape:

```json
{
  "frames_seen": 35,
  "passive_frames": 32,
  "ebusd_initiated_frames": 3,
  "non_frames": 0,
  "skipped": 0,
  "first_frame_timestamp": {
    "raw": "2026-10-02 15:11:32.994",
    "utc": null,
    "display": null
  },
  "last_frame_timestamp": {
    "raw": "2026-10-02 15:11:40.984",
    "utc": null,
    "display": null
  }
}
```

Rules include:

- counters are non-negative integers;
- `passive_frames + ebusd_initiated_frames == frames_seen`;
- frame timestamps are required when frames were observed;
- timestamp objects contain exactly `raw`, `utc`, and `display`;
- `raw` is always a non-empty string;
- `utc` and `display` may be strings or null.

The distinction between passive and ebusd-initiated traffic is part of the
evidence scope. A zero match must not be interpreted independently of the
observation window and initiator behavior.

### Checks object

The `checks` mapping must contain exactly the check IDs embedded in the
profile.

Each current check summary contains:

```text
description
matches
first_seen
last_seen
responses
values
value_status
```

`responses` and `values` retain counts plus first/last observation
timestamps. `value_status` distinguishes decoded values, no-response cases,
decode errors and checks without a configured decoder.

Consumers should not infer protocol semantics merely from these counts.

## `system.json`

When present, the format identifier is:

```text
ebus-evidence-system-v1
```

The allowed top-level fields are:

```text
format
topology_signature_sha256
devices
source
declared_product       optional
```

Each device contains only:

```text
address
manufacturer
id
sw
hw
```

Additional device fields such as serial numbers are rejected.

The topology signature is a deterministic SHA-256 over the normalized retained
device identity fields.

The required source declaration records that the document came from an existing
`ebusctl scan result` and that only the approved fields were retained.

`declared_product`, when present, may contain only `manufacturer` and
`model`.

## Context metadata

Context metadata files live under:

```text
contexts/*.json
```

Their format identifier is:

```text
ebus-evidence-context-v1
```

Current metadata contains:

```text
format
profile
profile_version
check_id
description
before_seconds
after_seconds
pre_window_complete
post_window_complete
trigger_count
triggers
record_count
raw_file
```

Newly captured contexts also carry these additive fields; older context-v1
metadata without them remains valid:

| Field | Meaning |
|---|---|
| `segment_started_at` | Raw source timestamp at the start of this segment. |
| `capture_end_timestamp` | Raw source timestamp at the boundary that closed it. |
| `capture_end_reason` | `post_window_complete`, `collection_stopped`, `duration_limit`, `byte_limit`, `record_limit`, `trigger_limit`, or `clock_regression`. |
| `continuation_of` | Previous segment's safe `.raw` basename, or `null`. This is a reference, not an exported host path. |
| `capture_limits` | Positive integer `max_seconds`, `max_bytes`, `max_records`, and `max_triggers` used for capture. |

The default limits are 900 seconds from segment start, 4 MiB of raw records,
10,000 records and 256 triggers per segment. The pre-trigger ring is separately
limited to 2 MiB and 10,000 records as well as the profile's time window.
The first segment may additionally contain its retained pre-trigger window.

Repeated triggers extend the requested post-window, but never these segment
limits. When a limit is reached, the current segment closes with
`post_window_complete=false` and a linked continuation receives subsequent
records. No pre-window is copied into a continuation. Its
`pre_window_complete` is therefore false; its trigger list may be empty when
it only completes the previous segment's post-window. At a trigger-count
boundary, the triggering record can be in the preceding segment while the
trigger metadata is in the continuation; consumers should follow the link.

Only reaching the requested post-window sets `post_window_complete=true`.
Stopping collection or a backward source-clock jump closes active windows as
incomplete. Source-clock regressions reset the pre-trigger ring and do not join
observations across the discontinuity. Eviction from the ring by its byte or
record budget also prevents claiming a complete affected pre-window.

These are per-ring/per-active-check memory bounds, not a total disk quota.
Completed local context files accumulate and are not automatically deleted.
Raw context remains excluded from normal exports; segmentation metadata is
included. The normal submission size/member limits still apply.

The verifier validates these fields when present, including safe continuation
filenames, count limits and completion flags. It does not authenticate capture
claims or prove that all referenced segments were supplied.

Context metadata included in a bundle must match the embedded active
profile name/version.

After a local profile rollover, older context metadata for the same profile name
is kept on disk but excluded from the current-profile bundle rather than being
silently relabeled. Historical state summaries remain available through
`evidence/state.json` epochs.

`raw_file` is a filename reference used for the corresponding optional
`contexts/*.raw` member. Even when raw context is excluded from a normal
public bundle, the metadata retains that safe local filename reference.

If any context raw members are present:

- every raw member must be referenced by metadata;
- every metadata raw reference must have a corresponding raw member;
- the manifest counts and raw/privacy flags must agree with the ZIP contents.

## Privacy contract

The current official exporter creates a manifest asserting:

```text
absolute host paths          excluded
resume checkpoint metadata  excluded
host metadata               excluded
credentials                 excluded
full raw log                excluded
raw context                  excluded by default
absolute timestamps          included
```

The verifier requires the relevant v1 manifest flags to have the expected
values and applies strict allowlists to members such as `system.json`.
Those checks are not a universal content scanner for every free-form string in
a manually constructed bundle.

Raw context is included only after an explicit request such as:

```bash
./evidence export --include-context-raw
```

Raw context can contain device-specific bus data and must be reviewed before
public sharing.

Absolute timestamps remain part of v1 evidence because timing is useful for
reproducibility and correlation. Their presence is explicitly disclosed by
current manifests and verifier output.

## Public submission policy

Structural bundle validity and public submission acceptance are deliberately
separate decisions.

The normal verifier remains format-focused:

```bash
./evidence verify evidence.zip
```

Maintainers reviewing untrusted public uploads should use:

```bash
./evidence verify --submission evidence.zip
```

The stricter submission policy currently requires:

- compressed ZIP size at or below 25 MB (25,000,000 bytes), matching the public GitHub upload limit;
- at most 1000 archive members;
- at most 64 MiB total uncompressed content;
- DEFLATE compression for every ZIP member;
- no encrypted ZIP members;
- no raw `contexts/*.raw` members;
- an included evidence state;
- current runtime/profile provenance;
- explicit absolute-timestamp disclosure;
- deterministic exporter layout;
- at least some observed evidence;
- an embedded profile that exactly matches the currently bundled trusted
  profile name/version/content.

The policy performs its tighter archive preflight before the full bundle
verification so obviously oversized or raw-context submissions can be rejected
without first processing their complete contents.

These rules are an acceptance policy for normal public contributions, not a new
bundle-format version. A bundle may remain structurally valid under bundle v1
while being unsuitable for normal public submission.

A successful submission-policy result is still **not** an authenticity proof.
A contributor can fabricate observations that satisfy the public data contract.
Human research review and cross-installation comparison remain necessary.

## Consumer guidance

An independent consumer should:

1. treat the input ZIP as untrusted;
2. validate ZIP/member safety before extracting anything;
3. verify `checksums.json`;
4. validate `manifest.json`, the embedded profile and all present typed
   members according to the consumer's supported contract;
5. apply any additional local submission/privacy policy needed for untrusted
   third-party content;
6. compute and retain the complete bundle SHA-256 as provenance;
7. never execute content from a submitted bundle;
8. preserve the original ZIP unchanged;
9. keep semantic interpretation separate from structural validation.

Consumers do not need to extract the ZIP to disk. Reading validated members
directly from the archive is preferable when practical.

## Compatibility

The current public interchange format is bundle v1.

A future incompatible archive contract must use a new format identifier rather
than silently changing the meaning of `ebus-evidence-bundle-v1`.

Profile version changes are separate from bundle-format changes.

Observation epochs are a backward-compatible extension of shared-state v1.
Older verifiers may ignore the additional epoch fields; consumers that need
profile-version coverage semantics should use a verifier that understands
epochs.

Current exporters add optional-compatible provenance inside bundle v1:
a deterministic runtime-package SHA-256, the exact embedded profile SHA-256,
and source-checkout Git commit/dirty status when available.

Older bundle-v1 archives without `provenance` remain valid and are reported as
legacy provenance.

No current provenance field is a build signature, publisher identity,
cryptographic attestation or proof that a bundle was created by an official
binary.

## Reference implementation

The current reference format verifier lives in:

```text
src/ebus_evidence/bundle.py
```

The additional public-submission acceptance policy lives in:

```text
src/ebus_evidence/submission.py
```

The format verifier remains authoritative for bundle-v1 structural acceptance;
the submission module intentionally layers stricter public-contribution policy
on top.

Related documentation:

- [Installation and first run](INSTALL.md)
- [Submit evidence](SUBMIT_EVIDENCE.md)
- [Review public submissions](MAINTAINER_SUBMISSIONS.md)
- [System identity](SYSTEM_IDENTITY.md)
- [Project boundaries](PROJECT_BOUNDARIES.md)
