# Parser and validation status

This document records the current public assurance boundary for the
`ebus-evidence` raw-log parser and the independent real-world validation that
supports it.

It is not a protocol-semantics document. A structurally valid transaction can
still contain an unknown value whose meaning is not established.

## Current parser acceptance boundary

Normal input is an ebusd **message-mode** raw log.

Before a record can become a normal `Frame` or contribute to Evidence, the
parser validates the parts that are observable in that representation:

1. request length and request/master CRC;
2. positive/negative command acknowledgement (ACK/NAK);
3. response presence when the target is a slave;
4. response length and response CRC;
5. final response acknowledgement where applicable;
6. direction changes and absence of unexplained transaction tails.

Broadcasts and master-target transactions use their corresponding shorter
transaction shapes.

CRC-invalid, NAK-bearing, truncated or otherwise incompletely proven records are
counted as `non_frames`. They do not create Evidence events.

Retry-shaped records are currently handled fail-closed rather than being
reconstructed into a second transaction.

## ebusd message-mode is a representation

The supported input is not assumed to be a lossless physical-wire capture.
ebusd formats the message-mode log after its own echo handling.

An independent dataset exposed a current upstream edge case: when an
ebusd-initiated request ends on-wire in `00`, a real slave ACK `00` can be
suppressed as an apparent echo by `ProtocolHandler::notifyDeviceData()`.

The upstream behaviour is tracked as
[john30/ebusd#1800](https://github.com/john30/ebusd/issues/1800).

The parser's compatibility handling is deliberately narrow. It is used only
when:

- the transaction was initiated by ebusd;
- the target is a slave and therefore expects a response;
- the outgoing request really ends on-wire in `00`;
- the incoming segment can be parsed from byte 0 as one complete CRC-valid
  response;
- ebusd's final outgoing response ACK is present and valid;
- no extra tail/direction segments remain.

This covers both a logical request CRC of `00` and a logical CRC of `a9`,
which is byte-stuffed on wire as `a9 00`. A logical CRC of `aa` is
byte-stuffed as `a9 01` and does not qualify.

The parser does not invent an omitted ACK for passive traffic and does not
reconstruct missing response bytes. If the remaining log representation is not
sufficient to validate one complete transaction, the record stays a non-frame.

## Independent full-dataset validation

Issue #22 provided an independent Vaillant aroTHERM plus HW5103 dataset
containing **4,818,571 message-mode raw-log lines**. The same static dataset was
re-imported repeatedly while the transport parser was hardened.

### CRC-only hardening (#25)

After request/response CRC validation:

```text
Frames observed ...... 4,767,302
Evidence events ......   209,980
Non-frames ...........    51,225
Skipped ..............         0
```

531 formerly accepted records became explicit non-frames. Two one-off B512
`/0613` values (`2` and `9`) disappeared and were confirmed from their raw
windows to have invalid request CRCs.

Established B512 states `0`, `3`, `5` and `6` remained.

### ACK/NAK and complete transaction framing (#26)

With full transaction framing enabled:

```text
Frames observed ...... 4,660,064
Evidence events ......   209,957
Non-frames ...........   158,463
Skipped ..............         0
```

Most newly excluded records were incomplete transactions. In particular,
100,841 of 103,091 `missing_command_ack` records were unanswered `07 04`
identification probes to unused addresses. Those remain non-frames because no
complete transaction exists.

The actual Evidence families remained stable.

### ebusd omitted-ACK compatibility (#28)

The identical dataset was imported again after the narrow logger compatibility
fix:

```text
Frames observed ...... 4,663,276
Evidence events ......   209,957
Non-frames ...........   155,251
Skipped ..............         0
invalid_command_ack ..        17
```

Compared with the #26 run:

- exactly **3,212** transactions moved from non-frame back to valid Frame;
- all 3,212 were ebusd-initiated transactions matching the logger artefact;
- `invalid_command_ack` fell from 3,229 to 17;
- all 17 remaining cases are passive traffic from other masters;
- all other non-frame reason counts were unchanged;
- the Evidence `checks` state was identical.

This is important: the compatibility path recovered exactly the affected
ebusd-initiated representation without changing the established Evidence.

The final independent Evidence checks included:

- B512 `/0613`: states `0=44097`, `3=31`, `5=6456`, `6=157985`;
- B512 response `0200ff=208569`, with no new variants;
- `/a80e`: 463 observations, all `0.0`;
- `/ba08`: 462 observations, all `0`;
- `/3538`: 463 observations with response
  `0aff020000000000030001`;
- export: `VALID`, `clean`, public submission `PASS`.

## Cross-hardware real-world check

Issue #38 added an independent Vaillant flexoTHERM exclusive installation with
a different hardware generation:

```text
08  HMU00  SW0308 / HW0403
15  VRC 700 (70000)  SW0614 / HW6903
76  VWZ00  SW0308 / HW0403
```

A static import over about 6 h 50 min produced:

```text
Frames observed ...... 15,987
Passive frames ....... 14,122
ebusd initiated ....... 1,865
Non-frames ........... 4,366
Skipped .............. 0
```

The normal `hw5103-open-evidence` v2 profile produced zero matches for its
four current HW5103 research discriminators. That is useful negative
cross-hardware evidence and supports keeping the bundled v2 profile scoped to
its current HW5103 research path.

A separate, unmerged experimental profile was then run against the identical
source window. It reproduced three structural families on the older hardware:

```text
B507 /0209XX ........ 387
B505 /025c00 ........ 396
B510 /020601 ........ 79
```

while B508 `/0209` and the tested B531/B510 LPC path had zero matches in that
window. These results are research discriminators, not new public protocol
semantics, and the experimental profile is not part of the rc2 release.

The returned experimental bundle verified as `VALID`, deterministic and
public-submission `PASS`, with the privacy-minimized system identity included.

## Additional HW5103 community capture (preliminary, #42)

On 2026-10-24, [issue #42](https://github.com/MarcelT87/ebus-evidence/issues/42)
received an independent live-`collect` submission from `rmalbrecht`, described by
the contributor as a Vaillant aroTHERM plus 55, HW5103, with native Linux/systemd
ebusd. The ZIP was reviewed as untrusted third-party input; it has **not yet**
been run through the official trusted
`./evidence verify --submission evidence.zip` gate. The following is a
read-only, preliminary inspection, **not** a recorded submission-policy PASS.

The submitted ZIP has four members (`checksums.json`,
`evidence/state.json`, `manifest.json`, `profile.yaml`). Independent checks
found matching member SHA-256 hashes, consistent profile/version metadata,
consistent event and frame subtotals, the expected deterministic ZIP member
ordering/compression/timestamps, and no extra members. The ZIP SHA-256 is:

```text
8083122bf91e537233d8d73d64b1444a46079e1336c524b0855928350008854c
```

The manifest reports `0.1.0rc2`, `hw5103-open-evidence` profile v2, and
source commit `4f6e60df7a4e19e1c8e27d28c38b65c6a3b4172c` (clean).
As with any third-party bundle, these provenance values are contributor-supplied
metadata, not an authentication of the originating installation.

The shared state summarizes approximately 10 h 49 min of observation on
2026-10-24 (raw log timestamps `07:41:49.472` to `18:30:32.707`, with
no timezone included in these raw fields):

```text
Accepted frames ........ 78,540
Passive frames ......... 73,969
ebusd-initiated ........  4,571
Non-frames ............. 20,553
Skipped records ........     27
Evidence events ........  4,420
Continuity resets ......      0
```

| Bundled profile check | Matches | Observation |
| --- | ---: | --- |
| HMU B509 `/a80e` | 252 | all decoded `0.0` |
| HMU B509 `/ba08` | 105 | all decoded `0` |
| VWZIO B51A `/3538` | 10 | response `0aff020000000000030001` |
| VWZIO B512 `/0613` | 4,053 | request state `0` throughout; response `0200ff` |

All four observed response/value sets are consistent with the earlier independent
HW5103 capture in #22. The lack of B512 states `3`, `5`, and `6` in this
shorter capture does **not** imply those states are unsupported: their appearance
is operating-condition/window dependent, and the earlier dataset observed them.
No new semantic interpretation is inferred.

Review limitations and follow-ups:

- `system.json` is absent. Hardware identity beyond the issue description,
  including exact device firmware, is not independently established by the ZIP.
  An existing, privacy-minimized `ebusctl scan` result would improve comparison.
- `skipped=27` is recorded, but per-record skip reasons are not available in
  the shared bundle. These should be requested if the collector's summary is
  already available. `non_frames` are a separate, deliberately excluded class.
- The bundled v2 checks **do not** test CompressorState `28` or the B507
  `/0209XX` semantic hypotheses; this submission is not evidence for either.
- Strict independent verification with the trusted release remains open before
  claiming `VALID / Public submission PASS` or treating #42 as completed.
  Do not commit the submitted ZIP or ingest it into other research stores
  before that gate passes.

## Bundle/verifier robustness

Separate from transport parsing, bundle verification is hardened against
pathological structured input.

Current structure protections include:

- maximum nesting depth: 64;
- maximum traversed structure size: 1,000,000 nodes;
- rejection of repeated/cyclic container references;
- controlled conversion of JSON/YAML recursion failures into bundle validation
  errors;
- iterative traversal for forbidden local resume fields.

These protections complement the existing ZIP/member/uncompressed-size and
submission-policy limits. See [Bundle format](BUNDLE_FORMAT.md).

## What this validation does not prove

The validation above does **not** prove:

- semantic meaning of every request/response field;
- that every possible eBUS device family uses the same traffic patterns;
- that ebusd message-mode logging can represent every physical-wire event
  losslessly;
- that a contributor's physical installation identity is authenticated by a
  bundle.

It does show that the current parser's CRC/framing decisions have been exercised
against one large independent real-world dataset and that the established
Evidence remained stable through the hardening sequence.

## Release-readiness implication

The transport-parser hardening from #25, #26 and #28 is considered independently
cross-validated for the current Vaillant/HW5103 research path.

Further parser changes should be evidence-driven rather than speculative.
Upstream changes to ebusd issue #1800 should be reviewed before removing or
broadening the current narrow compatibility path.
