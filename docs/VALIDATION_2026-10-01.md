# Validation snapshot — 2026-10-01

This document records the real-system validation state of `ebus-evidence` on the primary development installation as of 2026-10-01.

It is intentionally factual. It describes what was exercised and observed; it does not assign protocol semantics beyond the configured evidence profile.

## Repository state

Validated main:

```text
8885a5b062764916add11405e93756a5368974b0
test: reject context raw filename traversal
```

Test suite:

```text
74 passed
```

Python package version:

```text
0.1.0.dev0
```

## Real installation

Validated against a running ebusd Docker installation using automatic read-only discovery.

Observed discovery result:

```text
installation: Docker
container: ebusd
image: john30/ebusd:latest
raw mode: messages
container raw file: /var/log/ebusd/ebusd.raw
host raw file: /opt/docker/ebusd/rawlog/ebusd.raw
raw size limit: 102400 kB
```

The tool did not access the eBUS adapter directly and did not issue active eBUS commands.

## Offline analysis

Automatic discovery plus bundled profile analysis was validated against more than 1.4 million parsed raw-log frames.

Observed evidence included:

- HMU B509 `/a80e` zero-only values in the tested window.
- HMU B509 `/ba08` values `0` and one historical `0x20` occurrence.
- VWZIO B51A `/3538` stable typed responses.
- VWZIO B512 `/0613` observed raw state values `0, 3, 5, 6`.

The historical `/ba08 = 0x20` timestamp was preserved correctly through explicit UTC source-time normalization and Europe/Berlin display conversion.

## Live watch

Real live watch was validated repeatedly.

Representative clean run:

```text
frames=150
matches=9
non_frames=0
skipped=0
partial_tail=0
rotations=0
```

Short ebusd message-mode fragments such as `<00`, `<01` and `<20` were observed in other runs. They are classified as `non_frames`, not parser failures.

No real completed malformed raw record remained after this classification work.

## Persistent evidence state

Persistent state was validated across multiple watch restarts.

Observed behavior:

- event counts continue across runs;
- first/last timestamps remain consistent;
- response/value counts continue correctly;
- state files remain small;
- state writes are atomic;
- default state flush interval is 5 seconds;
- a clean shutdown forces a final flush.

The persisted aggregate and raw-log checkpoint are written together.

## Resume checkpoints

Resume from an earlier raw-log offset was validated on the real installation.

Validated properties:

- same active file resumes from the saved byte offset;
- records written while watch was stopped are replayed;
- the resumed stream then continues live;
- checkpoint state uses device, inode, byte offset and a SHA-256 content anchor;
- legacy pre-anchor checkpoints upgrade automatically after a successful resume;
- continuity resets remain explicit.

Representative persisted checkpoint shape:

```json
{
  "device": 64518,
  "inode": 393828,
  "offset": 101068449,
  "anchor_start": 101068193,
  "anchor_sha256": "<64 lowercase hex characters>"
}
```

The concrete numbers above are local validation examples only and are deliberately excluded from shareable evidence bundles.

### Rotation

Rename/create rotation handling is covered by synthetic tests.

A natural real-world `.old` rotation has not yet been observed during a running resume test. This remains an explicit validation item rather than an assumed success.

## Rare trigger context capture

The bundled HW5103 profile currently contains two explicit context triggers:

- HMU B509 `/a80e`: decoded value is non-zero.
- HMU B509 `/ba08`: decoded value is non-zero.

Configured window:

```text
120 seconds before
180 seconds after
```

The real installation currently returned zero for both values during live validation, so no real rare context bundle was generated.

A synthetic `/ba08 = 0x20` event was validated end to end.

Expected/resulting context:

```text
pre_window_complete = True
post_window_complete = True
record_count = 5
trigger_value = 32
```

The first record after the post-window closes the capture but is not included in the raw context itself.

## Shareable evidence bundles

Deterministic bundle creation was validated on the real installation using:

- the real persistent evidence state;
- one synthetic `/ba08 = 0x20` context bundle.

Two separately generated ZIP files were byte-identical:

```text
SHA256:
66b0f7a4d3df0563a11c770bf6fb30d44eace174d07b879ec20fc1e85af58b27
```

The validated full bundle contained:

```text
checksums.json
contexts/20261001T100000.000_hmu_ba08_variants_0001.json
contexts/20261001T100000.000_hmu_ba08_variants_0001.raw
evidence/state.json
manifest.json
profile.yaml
```

Privacy checks confirmed that the shared state did not contain:

- checkpoint;
- device;
- inode;
- offset;
- anchor_start;
- anchor_sha256;
- absolute local paths;
- host metadata;
- credentials.

A metadata-only bundle was also validated and contained no `.raw` member.

## Bundle verification

`ebus-evidence verify` was validated against three real generated variants.

### Original canonical bundle

Result:

```text
Status: VALID
Deterministic layout: yes
```

### Deliberately tampered bundle

The shared state was changed without updating `checksums.json`.

Result:

```text
INVALID: checksum mismatch for evidence/state.json
exit_code=2
```

### Content-preserving manual repack

All files remained unchanged but ZIP order/timestamps were changed.

Result:

```text
Status: VALID
Deterministic layout: no (content integrity still valid)
```

This distinction is intentional: content integrity and canonical archive layout are separate properties.

## Current trust boundary

The validated core is:

```text
existing ebusd message-mode raw log
        ->
read-only discovery / explicit file path
        ->
offline analysis or passive live watch
        ->
optional compact persistent state
        ->
rotation-aware resume checkpoint
        ->
explicit profile-triggered small context windows
        ->
deterministic shareable ZIP
        ->
independent ZIP verification
```

Not part of the validated core:

- direct adapter access;
- arbitrary `ebusctl read`;
- active writes;
- telegram injection;
- automatic semantic naming;
- confidence scoring;
- MQTT publishing;
- analyzer database dependency;
- cloud upload.

## Remaining real-world validation

The highest-value remaining validation item is a second independent ebusd installation.

Secondary items:

1. observe a natural raw-log rotation while a persisted checkpoint is in use;
2. validate native/systemd discovery on a real host;
3. collect the first naturally triggered context bundle for one of the rare profile conditions.

Do not treat these as already proven by the primary installation.
