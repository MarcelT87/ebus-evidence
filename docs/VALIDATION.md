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
